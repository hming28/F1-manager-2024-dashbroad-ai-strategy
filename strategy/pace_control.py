"""
pace_control.py — Driver pace, ERS deployment, and fuel management.

Manages the trade-off between:
- Lap time (push vs conserve)
- Tyre life (aggressive = more wear)
- ERS battery (deploy vs harvest)
- Fuel consumption (push = more fuel)

Provides clear recommendations for each mode.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.models import CarRaceState, RaceSnapshot, Track, WeatherState_Data


# ── Pace modes ───────────────────────────────────────────────────────────────

class PaceMode:
    """
    Defines a pace mode with its effects on performance and resources.
    """
    def __init__(self, name: str, pace_pct: float, tyre_mult: float,
                 fuel_mult: float, ers_mode: str, description: str):
        self.name = name
        self.pace_pct = pace_pct        # 0.0-1.0 (1.0 = maximum attack)
        self.tyre_mult = tyre_mult      # tyre wear multiplier
        self.fuel_mult = fuel_mult      # fuel consumption multiplier
        self.ers_mode = ers_mode        # "DEPLOY" / "BALANCED" / "HARVEST"
        self.description = description


PACE_MODES = {
    "PUSH": PaceMode(
        name="PUSH", pace_pct=1.0, tyre_mult=1.3, fuel_mult=1.2,
        ers_mode="DEPLOY",
        description="Maximum attack. Fast laps but heavy tyre/fuel cost."
    ),
    "ATTACK": PaceMode(
        name="ATTACK", pace_pct=0.85, tyre_mult=1.15, fuel_mult=1.1,
        ers_mode="DEPLOY",
        description="Aggressive pace. Good for overtaking or building gap."
    ),
    "BALANCED": PaceMode(
        name="BALANCED", pace_pct=0.7, tyre_mult=1.0, fuel_mult=1.0,
        ers_mode="BALANCED",
        description="Standard race pace. Optimal balance of speed and conservation."
    ),
    "CONSERVE": PaceMode(
        name="CONSERVE", pace_pct=0.55, tyre_mult=0.85, fuel_mult=0.9,
        ers_mode="HARVEST",
        description="Conservation mode. Extends tyre life and saves fuel."
    ),
    "NURSE": PaceMode(
        name="NURSE", pace_pct=0.4, tyre_mult=0.7, fuel_mult=0.8,
        ers_mode="HARVEST",
        description="Minimal push. Maximum tyre/fuel conservation. Last resort."
    ),
}


# ── ERS strategies ──────────────────────────────────────────────────────────

class ErsMode:
    """ERS deployment strategy."""
    def __init__(self, name: str, deploy_pct: float, harvest_pct: float,
                 description: str):
        self.name = name
        self.deploy_pct = deploy_pct    # % of available ERS to deploy
        self.harvest_pct = harvest_pct  # harvesting intensity
        self.description = description


ERS_MODES = {
    "HOTLAP": ErsMode("HOTLAP", deploy_pct=1.0, harvest_pct=0.2,
                      description="Full ERS deploy every lap. For qualifying or critical overtakes."),
    "DEPLOY": ErsMode("DEPLOY", deploy_pct=0.8, harvest_pct=0.3,
                      description="Aggressive deploy. Good for attacking."),
    "BALANCED": ErsMode("BALANCED", deploy_pct=0.5, harvest_pct=0.5,
                        description="Equal deploy/harvest. Standard racing."),
    "HARVEST": ErsMode("HARVEST", deploy_pct=0.2, harvest_pct=0.8,
                       description="Focus on recharging. For recovery or preparation."),
    "NONE": ErsMode("NONE", deploy_pct=0.0, harvest_pct=1.0,
                    description="No deploy, maximum harvest. Full recharge."),
}


# ── Recommendation ───────────────────────────────────────────────────────────

@dataclass
class PaceRecommendation:
    """Recommended pace mode and reasoning."""
    recommended_pace: PaceMode
    recommended_ers: ErsMode
    fuel_target_per_lap: float       # kg per lap
    
    reason_pace: str
    reason_ers: str
    reason_fuel: str
    
    urgency: str   # "NORMAL" / "IMPORTANT" / "CRITICAL"


class PaceController:
    """
    Recommends pace mode, ERS strategy, and fuel management
    based on race situation.
    
    Usage:
        controller = PaceController(track)
        rec = controller.recommend(snapshot, my_car)
        print(f"Pace: {rec.recommended_pace.name}")
        print(f"ERS: {rec.recommended_ers.name}")
        print(f"Fuel target: {rec.fuel_target_per_lap:.2f} kg/lap")
    """
    
    def __init__(self, track: Track):
        self.track = track
        self.base_fuel_per_lap = self._estimate_base_fuel(track)
    
    def recommend(self, snapshot: RaceSnapshot, 
                  my_car: CarRaceState) -> PaceRecommendation:
        """
        Analyze situation and recommend pace/ERS/fuel settings.
        """
        remaining_laps = self.track.laps - snapshot.current_lap
        race_progress = snapshot.current_lap / max(1, self.track.laps)
        
        # Analyze each factor
        pace_factors = self._analyze_pace_factors(snapshot, my_car, remaining_laps)
        ers_factors = self._analyze_ers_factors(snapshot, my_car, remaining_laps)
        fuel_factors = self._analyze_fuel_factors(my_car, remaining_laps)
        
        # Determine pace mode
        pace_score = sum(f[1] for f in pace_factors) / max(1, len(pace_factors))
        pace_mode = self._score_to_pace_mode(pace_score)
        pace_reasons = "; ".join(f[0] for f in pace_factors if f[0])
        
        # Determine ERS mode
        ers_score = sum(f[1] for f in ers_factors) / max(1, len(ers_factors))
        ers_mode = self._score_to_ers_mode(ers_score)
        ers_reasons = "; ".join(f[0] for f in ers_factors if f[0])
        
        # Calculate fuel target
        fuel_target = self._calculate_fuel_target(my_car, remaining_laps)
        fuel_reason = self._fuel_reasoning(my_car, remaining_laps)
        
        # Overall urgency
        urgency = "NORMAL"
        if my_car.avg_tyre_condition < 0.30 or my_car.fuel < remaining_laps * 1.0:
            urgency = "CRITICAL"
        elif my_car.avg_tyre_condition < 0.50 or snapshot.is_safety_car:
            urgency = "IMPORTANT"
        
        return PaceRecommendation(
            recommended_pace=pace_mode,
            recommended_ers=ers_mode,
            fuel_target_per_lap=fuel_target,
            reason_pace=pace_reasons or "Standard race pace",
            reason_ers=ers_reasons or "Balanced ERS",
            reason_fuel=fuel_reason,
            urgency=urgency,
        )
    
    def _analyze_pace_factors(self, snapshot: RaceSnapshot, 
                               car: CarRaceState, remaining: int) -> list[tuple[str, float]]:
        """
        Analyze factors that affect pace decision.
        Returns list of (reason, score) where score: -1.0=conserve to 1.0=push.
        """
        factors = []
        
        # Tyre condition
        cond = car.avg_tyre_condition
        if cond > 0.70:
            factors.append(("Tyres good, can push", 0.3))
        elif cond > 0.50:
            factors.append(("Tyres moderate", 0.0))
        elif cond > 0.30:
            factors.append(("Tyres wearing, conserve", -0.4))
        else:
            factors.append(("Tyres critical, nurse", -0.8))
        
        # Position relative to competitors
        my_gap_to_ahead = self._gap_to_position(snapshot, car, car.race_position - 1)
        my_gap_to_behind = self._gap_to_position(snapshot, car, car.race_position + 1)
        
        if my_gap_to_ahead is not None and 0 < my_gap_to_ahead < 3000:
            factors.append((f"Close to P{car.race_position-1} ({my_gap_to_ahead/1000:.1f}s), push to attack", 0.5))
        elif my_gap_to_behind is not None and 0 < my_gap_to_behind < 3000:
            factors.append((f"P{car.race_position+1} closing ({my_gap_to_behind/1000:.1f}s), defend", -0.2))
        
        # Safety car
        if snapshot.is_safety_car:
            factors.append(("Safety car — conserve tyres/fuel", -0.5))
        
        # Race phase
        progress = snapshot.current_lap / max(1, self.track.laps)
        if progress < 0.15:
            factors.append(("Early race — manage tyres", -0.2))
        elif progress > 0.85:
            factors.append(("End of race — push to finish", 0.4))
        
        # Weather
        if snapshot.weather and snapshot.weather.is_raining:
            factors.append(("Wet conditions — smooth inputs", -0.3))
        
        return factors
    
    def _analyze_ers_factors(self, snapshot: RaceSnapshot,
                              car: CarRaceState, remaining: int) -> list[tuple[str, float]]:
        """Analyze ERS deployment factors. Score: -1.0=harvest to 1.0=deploy."""
        factors = []
        
        # Battery level
        if car.ers_battery_charge > 0.80:
            factors.append(("ERS full, can deploy", 0.5))
        elif car.ers_battery_charge < 0.20:
            factors.append(("ERS low, must harvest", -0.7))
        elif car.ers_battery_charge < 0.40:
            factors.append(("ERS moderate, balance", -0.2))
        
        # Position situation
        my_gap_ahead = self._gap_to_position(snapshot, car, car.race_position - 1)
        if my_gap_ahead and 0 < my_gap_ahead < 2000:
            factors.append(("Within DRS range, deploy for overtake", 0.7))
        
        # Safety car
        if snapshot.is_safety_car:
            factors.append(("Safety car — harvest to recharge", -0.5))
        
        # Race phase
        progress = snapshot.current_lap / max(1, self.track.laps)
        if progress > 0.90:
            factors.append(("Final laps — deploy everything", 0.8))
        
        return factors
    
    def _analyze_fuel_factors(self, car: CarRaceState, remaining: int) -> str:
        """Analyze fuel situation."""
        if remaining <= 0:
            return "Race ending"
        
        current_fuel_per_lap = car.fuel / max(1, remaining)
        target = self.base_fuel_per_lap
        
        if car.fuel < remaining * target * 0.9:
            return f"⚠️ Fuel critical! Need {remaining * target:.1f}kg but have {car.fuel:.1f}kg. Save fuel!"
        elif car.fuel < remaining * target * 1.0:
            return f"Fuel tight. Target {target:.2f}kg/lap, have {car.fuel:.1f}kg for {remaining} laps."
        elif car.fuel > remaining * target * 1.15:
            return f"Fuel surplus (+{(car.fuel - remaining * target):.1f}kg). Can push harder."
        else:
            return f"Fuel on target. {target:.2f}kg/lap for {remaining} laps."
    
    def _calculate_fuel_target(self, car: CarRaceState, remaining: int) -> float:
        """Calculate target fuel consumption per lap."""
        if remaining <= 0:
            return 0
        return car.fuel / remaining
    
    def _fuel_reasoning(self, car: CarRaceState, remaining: int) -> str:
        if remaining <= 0:
            return "Race ending"
        target = car.fuel / remaining
        base = self.base_fuel_per_lap
        diff_pct = ((target - base) / base) * 100 if base > 0 else 0
        
        if diff_pct < -10:
            return f"Must save fuel: target {target:.2f}kg/lap ({abs(diff_pct):.0f}% below normal)"
        elif diff_pct > 10:
            return f"Fuel surplus: can use {diff_pct:.0f}% more fuel per lap"
        else:
            return f"On target: {target:.2f}kg/lap"
    
    def _gap_to_position(self, snapshot: RaceSnapshot, 
                          my_car: CarRaceState, target_pos: int) -> Optional[int]:
        """Get gap in ms to a specific position."""
        for car in snapshot.cars:
            if car.race_position == target_pos:
                return int((car.total_race_time - my_car.total_race_time) * 1000)
        return None
    
    def _score_to_pace_mode(self, score: float) -> PaceMode:
        if score > 0.6:
            return PACE_MODES["PUSH"]
        elif score > 0.2:
            return PACE_MODES["ATTACK"]
        elif score > -0.2:
            return PACE_MODES["BALANCED"]
        elif score > -0.5:
            return PACE_MODES["CONSERVE"]
        else:
            return PACE_MODES["NURSE"]
    
    def _score_to_ers_mode(self, score: float) -> ErsMode:
        if score > 0.6:
            return ERS_MODES["HOTLAP"]
        elif score > 0.2:
            return ERS_MODES["DEPLOY"]
        elif score > -0.2:
            return ERS_MODES["BALANCED"]
        elif score > -0.5:
            return ERS_MODES["HARVEST"]
        else:
            return ERS_MODES["NONE"]
    
    def _estimate_base_fuel(self, track: Track) -> float:
        """Estimate base fuel consumption per lap."""
        # Rough estimate based on track length
        # ~1.5 kg/km average for F1
        return track.track_length * 1.5
    
    def format_recommendation(self, rec: PaceRecommendation) -> str:
        """Format recommendation as readable text."""
        lines = [
            f"🏎️ PACE: {rec.recommended_pace.name} — {rec.recommended_pace.description}",
            f"⚡ ERS:  {rec.recommended_ers.name} — {rec.recommended_ers.description}",
            f"⛽ FUEL: Target {rec.fuel_target_per_lap:.2f} kg/lap",
            "",
            f"  Pace reason: {rec.reason_pace}",
            f"  ERS reason:  {rec.reason_ers}",
            f"  Fuel reason: {rec.reason_fuel}",
        ]
        return "\n".join(lines)
