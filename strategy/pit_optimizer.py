"""
pit_optimizer.py — Pit stop window optimizer for F1 Manager 2024.

Finds the optimal lap to pit by comparing:
- Staying out on current tyres (degradation cost)
- Pitting now (pit lane time loss + new tyre advantage)
- Safety car opportunity (free pit stop)
- Undercut/overcut vs competitors

Uses a dynamic programming approach to find the global optimum
across the remaining race distance.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from core.models import (
    CarRaceState, RaceSnapshot, TyreCompound, Track, WeatherState_Data,
    SafetyCarState,
)
from strategy.tyre_model import TyreModel, TyreWearPrediction


@dataclass
class PitWindow:
    """A recommended pit stop."""
    lap: int                        # Lap to pit on
    compound: TyreCompound          # Tyre to fit
    stint_length: int              # Laps on new tyres
    expected_time_gain_ms: int     # vs staying out (+ = beneficial)
    confidence: float              # 0.0-1.0
    reason: str                    # Human-readable explanation
    priority: str                  # "CRITICAL" / "RECOMMENDED" / "OPTIONAL"
    undercut_vs: Optional[int]     # Car index we're undercutting (if any)


@dataclass
class StrategyPlan:
    """Complete pit strategy for the remaining race."""
    stops: list[PitWindow]
    total_expected_gain_ms: int
    risk_level: str                # "LOW" / "MEDIUM" / "HIGH"
    notes: list[str]


class PitOptimizer:
    """
    Computes optimal pit stop windows considering all factors.
    """
    
    def __init__(self, tyre_model: TyreModel):
        self.tyre_model = tyre_model
    
    def optimize(self, snapshot: RaceSnapshot, my_car: CarRaceState,
                 track: Track) -> StrategyPlan:
        """
        Find the optimal pit strategy for the remaining race.
        
        Args:
            snapshot: Current race state
            my_car: Your car's current state
            track: Track information
            
        Returns:
            StrategyPlan with recommended pit stops
        """
        remaining_laps = track.laps - snapshot.current_lap
        if remaining_laps <= 0:
            return StrategyPlan(stops=[], total_expected_gain_ms=0,
                              risk_level="LOW", notes=["Race ending"])
        
        weather = snapshot.weather
        
        # Get available tyre compounds
        compounds = self._get_available_compounds(weather)
        
        # Generate all possible strategies
        strategies = []
        
        # Strategy 0: No more stops (if current tyres can last)
        no_stop = self._evaluate_no_stop(snapshot, my_car, track, remaining_laps)
        if no_stop:
            strategies.append(("no_stop", no_stop))
        
        # Strategy 1: One stop at various laps
        for pit_lap in range(snapshot.current_lap + 1,
                           min(snapshot.current_lap + remaining_laps, track.laps)):
            for compound in compounds:
                strategy = self._evaluate_one_stop(
                    snapshot, my_car, track, pit_lap, compound, remaining_laps
                )
                if strategy:
                    strategies.append((f"pit_l{pit_lap}_{compound.short}", strategy))
        
        # Strategy 2: Two stops (if enough laps remaining)
        if remaining_laps >= 20:
            for first_pit in range(snapshot.current_lap + 5,
                                  snapshot.current_lap + remaining_laps - 10, 3):
                for second_pit in range(first_pit + 8,
                                       min(first_pit + remaining_laps - 5, track.laps), 3):
                    for c1 in compounds:
                        for c2 in compounds:
                            strategy = self._evaluate_two_stop(
                                snapshot, my_car, track,
                                first_pit, c1, second_pit, c2,
                                remaining_laps
                            )
                            if strategy:
                                strategies.append(
                                    (f"2stop_l{first_pit}{c1.short}_l{second_pit}{c2.short}",
                                     strategy)
                                )
        
        # Evaluate safety car opportunity
        sc_strategy = self._evaluate_safety_car(snapshot, my_car, track, compounds)
        if sc_strategy:
            strategies.append(("safety_car", sc_strategy))
        
        # Evaluate undercut opportunity
        undercut = self._evaluate_undercut(snapshot, my_car, track, compounds)
        if undercut:
            strategies.append(("undercut", undercut))
        
        # Pick the best strategy
        if not strategies:
            return StrategyPlan(
                stops=[], total_expected_gain_ms=0,
                risk_level="LOW", notes=["No viable strategies found"]
            )
        
        # Sort by total expected gain
        strategies.sort(key=lambda s: s[1].total_expected_gain_ms, reverse=True)
        best_name, best_plan = strategies[0]
        
        # Add notes about alternatives
        notes = []
        if len(strategies) > 1:
            alt_name = strategies[1][0]
            alt_gain = strategies[1][1].total_expected_gain_ms
            notes.append(f"Alternative: {alt_name} (gain: {alt_gain}ms)")
        
        return best_plan
    
    def _evaluate_no_stop(self, snapshot: RaceSnapshot, car: CarRaceState,
                          track: Track, remaining: int) -> Optional[StrategyPlan]:
        """Evaluate staying out until the end."""
        if car.avg_tyre_condition < 0.20:
            return None  # tyres are too worn
        
        # Predict tyre condition at end
        current_compound = self._guess_current_compound(car)
        prediction = self.tyre_model.predict_wear(
            car, current_compound, snapshot.current_lap,
            track.laps, track, snapshot.weather
        )
        
        if prediction.is_past_cliff:
            return None  # tyres won't last
        
        # Cost: time lost from degradation vs fresh tyres
        time_cost = prediction.lap_time_delta_ms * remaining
        
        return StrategyPlan(
            stops=[],
            total_expected_gain_ms=-time_cost,  # negative = time lost
            risk_level="HIGH" if prediction.estimated_laps_remaining < 5 else "MEDIUM",
            notes=[f"Tyres will last ~{prediction.estimated_laps_remaining} more laps"]
        )
    
    def _evaluate_one_stop(self, snapshot: RaceSnapshot, car: CarRaceState,
                           track: Track, pit_lap: int, compound: TyreCompound,
                           remaining: int) -> Optional[StrategyPlan]:
        """Evaluate a single pit stop at pit_lap."""
        laps_before_pit = pit_lap - snapshot.current_lap
        laps_after_pit = track.laps - pit_lap
        
        if laps_before_pit <= 0 or laps_after_pit <= 0:
            return None
        
        # Time cost: pit lane time loss
        pit_loss_ms = track.pit_lane_time_loss * 1000
        
        # Time cost: degradation on current tyres until pit
        current_compound = self._guess_current_compound(car)
        pre_pit_prediction = self.tyre_model.predict_wear(
            car, current_compound, snapshot.current_lap,
            pit_lap, track, snapshot.weather
        )
        pre_pit_cost = pre_pit_prediction.lap_time_delta_ms * laps_before_pit
        
        # Time benefit: fresh tyres after pit
        post_pit_analysis = self.tyre_model.analyze_compound(
            compound, track, snapshot.weather
        )
        # Fresh tyres give optimal pace for first ~10 laps, then degrade
        fresh_benefit_ms = 0
        deg_rate = post_pit_analysis.degradation_per_lap
        for lap in range(laps_after_pit):
            wear = deg_rate * lap * 1.1  # approximate
            if wear < post_pit_analysis.cliff_at_wear:
                lap_delta = int(wear * 2000) if wear > 0.3 else 0
            else:
                cliff_excess = wear - post_pit_analysis.cliff_at_wear
                lap_delta = int(1500 + cliff_excess * 8000)
            fresh_benefit_ms -= lap_delta
        
        # Net gain
        net_gain = fresh_benefit_ms - pit_loss_ms - pre_pit_cost
        
        # Confidence based on prediction accuracy
        confidence = 0.7 if pre_pit_prediction.estimated_laps_remaining > 3 else 0.4
        
        # Reason
        if net_gain > 0:
            reason = f"Pit lap {pit_lap} for {compound.short}s: save {net_gain}ms"
            priority = "RECOMMENDED" if net_gain > 2000 else "OPTIONAL"
        else:
            reason = f"Pit lap {pit_lap} for {compound.short}s: lose {abs(net_gain)}ms"
            priority = "OPTIONAL"
        
        return StrategyPlan(
            stops=[PitWindow(
                lap=pit_lap,
                compound=compound,
                stint_length=laps_after_pit,
                expected_time_gain_ms=net_gain,
                confidence=confidence,
                reason=reason,
                priority=priority,
                undercut_vs=None,
            )],
            total_expected_gain_ms=net_gain,
            risk_level="LOW" if confidence > 0.6 else "MEDIUM",
            notes=[reason],
        )
    
    def _evaluate_two_stop(self, snapshot: RaceSnapshot, car: CarRaceState,
                           track: Track, pit1_lap: int, c1: TyreCompound,
                           pit2_lap: int, c2: TyreCompound,
                           remaining: int) -> Optional[StrategyPlan]:
        """Evaluate a two-stop strategy."""
        if pit2_lap <= pit1_lap + 5:
            return None
        
        pit_loss_ms = track.pit_lane_time_loss * 1000 * 2  # two stops
        
        # Stint 1: current -> pit1
        stint1_laps = pit1_lap - snapshot.current_lap
        current_compound = self._guess_current_compound(car)
        s1_pred = self.tyre_model.predict_wear(
            car, current_compound, snapshot.current_lap,
            pit1_lap, track, snapshot.weather
        )
        s1_cost = s1_pred.lap_time_delta_ms * stint1_laps
        
        # Stint 2: pit1 -> pit2 on c1
        stint2_laps = pit2_lap - pit1_lap
        s2_analysis = self.tyre_model.analyze_compound(c1, track, snapshot.weather)
        s2_cost = self._estimate_stint_cost(s2_analysis, stint2_laps)
        
        # Stint 3: pit2 -> end on c2
        stint3_laps = track.laps - pit2_lap
        s3_analysis = self.tyre_model.analyze_compound(c2, track, snapshot.weather)
        s3_cost = self._estimate_stint_cost(s3_analysis, stint3_laps)
        
        total_degradation_cost = s1_cost + s2_cost + s3_cost
        net_gain = -(total_degradation_cost + pit_loss_ms)
        
        return StrategyPlan(
            stops=[
                PitWindow(
                    lap=pit1_lap, compound=c1, stint_length=stint2_laps,
                    expected_time_gain_ms=0, confidence=0.5,
                    reason=f"1st stop: lap {pit1_lap} for {c1.short}",
                    priority="RECOMMENDED", undercut_vs=None,
                ),
                PitWindow(
                    lap=pit2_lap, compound=c2, stint_length=stint3_laps,
                    expected_time_gain_ms=0, confidence=0.5,
                    reason=f"2nd stop: lap {pit2_lap} for {c2.short}",
                    priority="RECOMMENDED", undercut_vs=None,
                ),
            ],
            total_expected_gain_ms=net_gain,
            risk_level="MEDIUM",
            notes=[f"2-stop: {c1.short} -> {c2.short}"],
        )
    
    def _evaluate_safety_car(self, snapshot: RaceSnapshot, car: CarRaceState,
                             track: Track,
                             compounds: list[TyreCompound]) -> Optional[StrategyPlan]:
        """Evaluate pitting under safety car."""
        if not snapshot.is_safety_car:
            return None
        
        # Safety car = reduced pit lane time loss
        sc_pit_loss = track.safety_car_time_loss * 1000
        normal_pit_loss = track.pit_lane_time_loss * 1000
        saved_time = normal_pit_loss - sc_pit_loss
        
        if saved_time <= 0:
            return None
        
        # Best compound for remaining laps
        remaining = track.laps - snapshot.current_lap
        best_compound = self._pick_best_compound(remaining, compounds, track, snapshot.weather)
        
        return StrategyPlan(
            stops=[PitWindow(
                lap=snapshot.current_lap,
                compound=best_compound,
                stint_length=remaining,
                expected_time_gain_ms=saved_time,
                confidence=0.9,
                reason=f"🚨 FREE PIT! Save {saved_time}ms under safety car",
                priority="CRITICAL",
                undercut_vs=None,
            )],
            total_expected_gain_ms=saved_time,
            risk_level="LOW",
            notes=[f"Safety car pit saves {saved_time/1000:.1f}s"],
        )
    
    def _evaluate_undercut(self, snapshot: RaceSnapshot, car: CarRaceState,
                           track: Track,
                           compounds: list[TyreCompound]) -> Optional[StrategyPlan]:
        """Evaluate undercutting a nearby competitor."""
        # Find the car directly ahead
        ahead_car = None
        for c in snapshot.cars:
            if c.race_position == car.race_position - 1:
                ahead_car = c
                break
        
        if ahead_car is None:
            return None
        
        # Check if undercut is viable
        gap_ms = int((car.total_race_time - ahead_car.total_race_time) * 1000)
        if gap_ms > 10000 or gap_ms < 0:  # too far or already ahead
            return None
        
        # Undercut: pit 1-2 laps before opponent likely pits
        pit_lap = snapshot.current_lap + 1
        
        # New tyres should give ~1.5s advantage per lap
        expected_gain_per_lap = 1500
        new_tyre_advantage = expected_gain_per_lap * 2  # 2 laps on fresh tyres
        pit_loss = track.pit_lane_time_loss * 1000
        
        net_gain = new_tyre_advantage - pit_loss - gap_ms
        
        if net_gain <= 0:
            return None
        
        best_compound = self._pick_best_compound(
            track.laps - pit_lap, compounds, track, snapshot.weather
        )
        
        return StrategyPlan(
            stops=[PitWindow(
                lap=pit_lap,
                compound=best_compound,
                stint_length=track.laps - pit_lap,
                expected_time_gain_ms=net_gain,
                confidence=0.6,
                reason=f"⚡ Undercut P{ahead_car.race_position}! Gap: {gap_ms/1000:.1f}s",
                priority="RECOMMENDED",
                undercut_vs=ahead_car.car_index,
            )],
            total_expected_gain_ms=net_gain,
            risk_level="MEDIUM",
            notes=[f"Undercut target: car {ahead_car.car_index} (P{ahead_car.race_position})"],
        )
    
    # ── Helpers ──────────────────────────────────────────────────────────────
    
    def _get_available_compounds(self, weather: Optional[WeatherState_Data]) -> list[TyreCompound]:
        if weather and weather.is_raining:
            return [TyreCompound.INTER, TyreCompound.WET]
        return [TyreCompound.SOFT, TyreCompound.MEDIUM, TyreCompound.HARD]
    
    def _guess_current_compound(self, car: CarRaceState) -> TyreCompound:
        """Heuristic: guess current compound from condition and wear pattern."""
        condition = car.avg_tyre_condition
        if condition > 0.85:
            return TyreCompound.HARD  # probably fresh hards
        elif condition > 0.60:
            return TyreCompound.MEDIUM
        else:
            return TyreCompound.SOFT
    
    def _pick_best_compound(self, remaining_laps: int,
                            compounds: list[TyreCompound],
                            track: Track,
                            weather: Optional[WeatherState_Data]) -> TyreCompound:
        """Pick the best compound for the remaining laps."""
        best = None
        best_score = -999999
        
        for c in compounds:
            analysis = self.tyre_model.analyze_compound(c, track, weather)
            if analysis.expected_life_laps >= remaining_laps:
                # Can last the distance
                score = analysis.pace_delta_vs_medium_ms * -1  # prefer faster
                score += 1000  # bonus for lasting the distance
            else:
                # Won't last — penalize
                deficit = remaining_laps - analysis.expected_life_laps
                score = -deficit * 500
            
            if score > best_score:
                best_score = score
                best = c
        
        return best or TyreCompound.MEDIUM
    
    def _estimate_stint_cost(self, analysis, laps: int) -> int:
        """Estimate total time cost from tyre degradation over a stint."""
        total_cost = 0
        for lap in range(laps):
            wear = analysis.degradation_per_lap * lap * 1.1
            if wear < 0.3:
                delta = 0
            elif wear < analysis.cliff_at_wear:
                delta = int((wear - 0.3) * 3000)
            else:
                cliff_excess = wear - analysis.cliff_at_wear
                delta = int(1500 + cliff_excess * 8000)
            total_cost += delta
        return total_cost
