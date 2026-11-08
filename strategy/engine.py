"""
engine.py — Main strategy engine for F1 Manager 2024.

Orchestrates all strategy modules and produces a unified recommendation.
This is the brain of the system.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from core.models import (
    CarRaceState, RaceSnapshot, Track, TyreCompound, DriverData,
)
from strategy.tyre_model import TyreModel, TyreWearPrediction
from strategy.pit_optimizer import PitOptimizer, StrategyPlan
from strategy.weather_strategy import WeatherStrategy, WeatherAlert
from strategy.safety_car import SafetyCarStrategy, SafetyCarDecision
from strategy.race_intel import RaceIntel, RaceIntelReport

logger = logging.getLogger(__name__)


# ── Unified Recommendation ───────────────────────────────────────────────────

@dataclass
class StrategyRecommendation:
    """
    The final, unified strategy recommendation.
    This is what the player sees.
    """
    # Priority: higher = more urgent
    priority: int                # 1-10
    category: str                # "PIT" / "WEATHER" / "SAFETY_CAR" / "ERS" / "PACE"
    title: str                   # Short headline
    detail: str                  # Detailed explanation
    action: str                  # Specific action to take
    
    # Supporting data
    pit_plan: Optional[StrategyPlan] = None
    weather_alert: Optional[WeatherAlert] = None
    sc_decision: Optional[SafetyCarDecision] = None
    intel: Optional[RaceIntelReport] = None
    tyre_predictions: list[TyreWearPrediction] = field(default_factory=list)


@dataclass
class EngineState:
    """Complete state of the strategy engine at a point in time."""
    recommendations: list[StrategyRecommendation]
    pit_strategy: Optional[StrategyPlan]
    weather_alert: Optional[WeatherAlert]
    sc_decision: Optional[SafetyCarDecision]
    intel_report: Optional[RaceIntelReport]
    
    # Quick stats
    my_position: int = 0
    current_lap: int = 0
    total_laps: int = 0
    tyre_condition: float = 0.0
    fuel_level: float = 0.0
    ers_charge: float = 0.0
    
    @property
    def top_recommendation(self) -> Optional[StrategyRecommendation]:
        if self.recommendations:
            return max(self.recommendations, key=lambda r: r.priority)
        return None
    
    @property
    def has_urgent_action(self) -> bool:
        return any(r.priority >= 7 for r in self.recommendations)


class StrategyEngine:
    """
    Main strategy engine. Analyzes race state and produces recommendations.
    
    Usage:
        engine = StrategyEngine(my_team_id=3, track=track, drivers=drivers)
        state = engine.update(snapshot)
        for rec in state.recommendations:
            print(f"[P{rec.priority}] {rec.title}: {rec.action}")
    """
    
    def __init__(self, my_team_id: int, track: Track,
                 drivers: Optional[list[DriverData]] = None,
                 risk_level: float = 0.5):
        """
        Args:
            my_team_id: Your team ID (1-10)
            track: Current track data
            drivers: All driver data (for intel)
            risk_level: 0.0 = conservative, 1.0 = aggressive
        """
        self.my_team_id = my_team_id
        self.track = track
        self.risk_level = risk_level
        
        # Initialize sub-engines
        self.tyre_model = TyreModel()
        self.pit_optimizer = PitOptimizer(self.tyre_model)
        self.weather_strategy = WeatherStrategy()
        self.safety_car_strategy = SafetyCarStrategy()
        self.race_intel = RaceIntel(drivers)
        
        # State tracking
        self._last_snapshot: Optional[RaceSnapshot] = None
        self._last_state: Optional[EngineState] = None
    
    def update(self, snapshot: RaceSnapshot) -> EngineState:
        """
        Process a new race snapshot and return updated strategy state.
        
        This is the main method — call it every time the save file changes.
        """
        self._last_snapshot = snapshot
        my_cars = snapshot.get_my_cars(self.my_team_id)
        
        if not my_cars:
            logger.warning("No cars found for team %d", self.my_team_id)
            return self._empty_state()
        
        # Use the higher-placed car as primary
        primary_car = min(my_cars, key=lambda c: c.race_position)
        
        recommendations = []
        
        # ── 1. Safety Car (highest priority) ─────────────────────────────────
        sc_decision = self.safety_car_strategy.evaluate(
            snapshot, primary_car, self.track
        )
        if sc_decision and sc_decision.should_pit:
            recommendations.append(StrategyRecommendation(
                priority=10 if sc_decision.priority == "MUST_DO" else 8,
                category="SAFETY_CAR",
                title="🚨 SAFETY CAR — PIT NOW!",
                detail=sc_decision.reason,
                action=f"Pit for fresh tyres. Position change: {sc_decision.position_change:+d}",
                sc_decision=sc_decision,
            ))
        
        # ── 2. Weather alerts ────────────────────────────────────────────────
        weather_alert = self.weather_strategy.analyze(snapshot)
        if weather_alert:
            priority = {"CRITICAL": 9, "WARNING": 7, "INFO": 4}.get(weather_alert.severity, 3)
            recommendations.append(StrategyRecommendation(
                priority=priority,
                category="WEATHER",
                title=weather_alert.message,
                detail=f"Confidence: {weather_alert.confidence:.0%}",
                action=f"Switch to {weather_alert.recommended_compound.name} tyres",
                weather_alert=weather_alert,
            ))
        
        # ── 3. Pit strategy ──────────────────────────────────────────────────
        pit_plan = self.pit_optimizer.optimize(snapshot, primary_car, self.track)
        if pit_plan and pit_plan.stops:
            top_stop = max(pit_plan.stops, key=lambda s: s.expected_time_gain_ms)
            has_mc = pit_plan.mc_report is not None and pit_plan.mc_report.best_result is not None
            if top_stop.expected_time_gain_ms > 1000 or (has_mc and pit_plan.mc_report.best_result.expected_points > 0):
                priority = 6 if top_stop.priority == "RECOMMENDED" else 4
                mc_title_extra = ""
                mc_detail_extra = ""
                if has_mc:
                    mc_b = pit_plan.mc_report.best_result
                    mc_title_extra = f" [Exp Pts: {mc_b.expected_points:.1f} | Pod: {mc_b.podium_probability:.0%}]"
                    mc_detail_extra = f" | Traffic Risk: {mc_b.traffic_risk:.0%} | Est: P{mc_b.p90_position}-P{mc_b.p10_position}"

                recommendations.append(StrategyRecommendation(
                    priority=priority,
                    category="PIT",
                    title=f"📦 Pit window: lap {top_stop.lap} for {top_stop.compound.short}{mc_title_extra}",
                    detail=f"{top_stop.reason}{mc_detail_extra}",
                    action=f"Pit on lap {top_stop.lap} for {top_stop.compound.name} compound",
                    pit_plan=pit_plan,
                ))
        
        # ── 4. Tyre condition warnings ───────────────────────────────────────
        tyre_pred = self.tyre_model.predict_wear(
            primary_car,
            self._guess_compound(primary_car),
            snapshot.current_lap,
            snapshot.current_lap + 5,
            self.track,
            snapshot.weather,
            aggression=self.risk_level,
        )
        if tyre_pred.recommendation in ("BOX_NOW", "BOX_SOON"):
            recommendations.append(StrategyRecommendation(
                priority=7 if tyre_pred.recommendation == "BOX_NOW" else 5,
                category="TYRE",
                title=f"🛞 Tyres critical: {primary_car.avg_tyre_condition:.0%}",
                detail=f"Estimated {tyre_pred.estimated_laps_remaining} laps remaining",
                action="Box this lap!" if tyre_pred.recommendation == "BOX_NOW" 
                       else "Box within 3 laps",
                tyre_predictions=[tyre_pred],
            ))
        
        # ── 5. Race intelligence ─────────────────────────────────────────────
        intel = self.race_intel.analyze(snapshot, self.my_team_id, self.track)
        if intel.undercut_opportunities:
            recommendations.append(StrategyRecommendation(
                priority=5,
                category="INTEL",
                title=f"⚡ {len(intel.undercut_opportunities)} undercut opportunity(ies)",
                detail="\n".join(intel.undercut_opportunities[:3]),
                action="Consider early pit for undercut",
                intel=intel,
            ))
        
        # ── 6. ERS recommendations ───────────────────────────────────────────
        if primary_car.ers_battery_charge > 0.80:
            recommendations.append(StrategyRecommendation(
                priority=3,
                category="ERS",
                title="⚡ ERS fully charged",
                detail=f"Battery: {primary_car.ers_battery_charge:.0%}",
                action="Deploy ERS for overtaking or lap time",
            ))
        elif primary_car.ers_battery_charge < 0.20:
            recommendations.append(StrategyRecommendation(
                priority=4,
                category="ERS",
                title="🔋 ERS low",
                detail=f"Battery: {primary_car.ers_battery_charge:.0%}",
                action="Switch to harvest mode to recharge",
            ))
        
        # ── 7. Damage warnings ───────────────────────────────────────────────
        if primary_car.has_damage and primary_car.damage_severity > 6:
            recommendations.append(StrategyRecommendation(
                priority=6,
                category="DAMAGE",
                title=f"🔧 Significant damage (severity: {primary_car.damage_severity}/18)",
                detail=self._describe_damage(primary_car),
                action="Consider pit stop for repairs",
            ))
        
        # ── Build engine state ───────────────────────────────────────────────
        state = EngineState(
            recommendations=recommendations,
            pit_strategy=pit_plan,
            weather_alert=weather_alert,
            sc_decision=sc_decision,
            intel_report=intel,
            my_position=primary_car.race_position,
            current_lap=snapshot.current_lap,
            total_laps=self.track.laps,
            tyre_condition=primary_car.avg_tyre_condition,
            fuel_level=primary_car.fuel,
            ers_charge=primary_car.ers_battery_charge,
        )
        
        self._last_state = state
        return state
    
    def _guess_compound(self, car: CarRaceState) -> TyreCompound:
        """Guess current tyre compound from condition."""
        condition = car.avg_tyre_condition
        if condition > 0.85:
            return TyreCompound.HARD
        elif condition > 0.60:
            return TyreCompound.MEDIUM
        else:
            return TyreCompound.SOFT
    
    def _describe_damage(self, car: CarRaceState) -> str:
        """Describe which parts are damaged."""
        parts = []
        if car.front_wing_damage.value > 0:
            parts.append(f"Front wing: {car.front_wing_damage.name}")
        if car.rear_wing_damage.value > 0:
            parts.append(f"Rear wing: {car.rear_wing_damage.name}")
        if car.sidepods_damage.value > 0:
            parts.append(f"Sidepods: {car.sidepods_damage.name}")
        if car.floor_damage.value > 0:
            parts.append(f"Floor: {car.floor_damage.name}")
        if car.suspension_damage.value > 0:
            parts.append(f"Suspension: {car.suspension_damage.name}")
        return ", ".join(parts) if parts else "Unknown damage"
    
    def _empty_state(self) -> EngineState:
        return EngineState(
            recommendations=[], pit_strategy=None, weather_alert=None,
            sc_decision=None, intel_report=None,
        )
