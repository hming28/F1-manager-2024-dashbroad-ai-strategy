"""
tyre_model.py — Tyre degradation model for F1 Manager 2024.

Models tyre wear as a function of:
- Compound type (soft/medium/hard/inter/wet)
- Track characteristics (abrasiveness, corner severity)
- Tyre temperatures (overheating accelerates wear)
- Driving style (aggressive = more wear)
- Track evolution (rubber = less wear over time)

The game uses a 4-tyre system (FL, FR, BL, BR) with individual conditions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from core.models import (
    CarRaceState, TyreCompound, Track, WeatherState_Data, TrackType
)
from strategy.fastf1_calibrator import FastF1Calibrator


# ── Constants ────────────────────────────────────────────────────────────────

# Base degradation rates per compound (wear fraction per lap, 0.0-1.0 scale)
# These are calibrated against typical F1 Manager 2024 behaviour
BASE_DEGRADATION = {
    TyreCompound.SOFT:   0.028,   # ~36 laps max on a standard track
    TyreCompound.MEDIUM: 0.018,   # ~55 laps
    TyreCompound.HARD:   0.012,   # ~83 laps
    TyreCompound.INTER:  0.020,   # ~50 laps (on dry, much less on wet)
    TyreCompound.WET:    0.015,   # ~66 laps (on wet track)
}

# Temperature thresholds (surface temp in game units)
TYRE_OPTIMAL_TEMP = {
    TyreCompound.SOFT:   (85.0, 105.0),   # (min, max) optimal range
    TyreCompound.MEDIUM: (80.0, 100.0),
    TyreCompound.HARD:   (75.0, 95.0),
    TyreCompound.INTER:  (60.0, 80.0),
    TyreCompound.WET:    (40.0, 65.0),
}

# Cliff threshold — tyre performance drops sharply past this wear level
TYRE_CLIFF_THRESHOLD = {
    TyreCompound.SOFT:   0.70,
    TyreCompound.MEDIUM: 0.75,
    TyreCompound.HARD:   0.80,
    TyreCompound.INTER:  0.72,
    TyreCompound.WET:    0.68,
}


@dataclass
class TyreWearPrediction:
    """Predicted tyre state at a future lap."""
    lap: int
    avg_condition: float         # 0.0 (destroyed) to 1.0 (new)
    max_wear: float              # 0.0 (new) to 1.0 (destroyed)
    lap_time_delta_ms: int       # milliseconds slower than optimal
    is_past_cliff: bool
    estimated_laps_remaining: int
    recommendation: str          # "STAY" / "BOX_NOW" / "BOX_SOON"


@dataclass
class CompoundAnalysis:
    """Analysis of a tyre compound for a specific track."""
    compound: TyreCompound
    expected_life_laps: int
    degradation_per_lap: float
    optimal_temp_range: tuple[float, float]
    cliff_at_wear: float
    pace_delta_vs_medium_ms: int  # negative = faster


class TyreModel:
    """
    Predicts tyre degradation and optimal pit windows.
    Integrates FastF1 official telemetry calibrations with game physics.
    """
    
    def __init__(self, calibrator: Optional[FastF1Calibrator] = None):
        # Track-specific multipliers (loaded from historical data if available)
        self._track_multiplier: float = 1.0
        self._weather_multiplier: float = 1.0
        self.calibrator = calibrator if calibrator is not None else FastF1Calibrator()

    def get_calibrated_profile(self, track: Track) -> Optional[dict]:
        """Retrieve real-world FastF1 calibrated profile for this track if available."""
        if not track:
            return None
        return self.calibrator.find_track(track.name) or self.calibrator.find_track(track.track_id)

    def is_track_calibrated(self, track: Track) -> bool:
        """Return True if the track has FastF1 telemetry calibrations."""
        return self.get_calibrated_profile(track) is not None
    
    def analyze_compound(self, compound: TyreCompound, track: Track,
                         weather: Optional[WeatherState_Data] = None) -> CompoundAnalysis:
        """
        Analyze how a tyre compound will perform on a given track.
        Uses FastF1 calibrated baseline pace and degradation when available.
        """
        cal_profile = self.get_calibrated_profile(track)
        compound_name = compound.name  # "SOFT", "MEDIUM", "HARD", "INTER", "WET"
        
        pace_delta: Optional[int] = None
        if cal_profile and compound in (TyreCompound.SOFT, TyreCompound.MEDIUM, TyreCompound.HARD):
            cal_deg_map = cal_profile.get("compound_deg_rate", {})
            base_deg = cal_deg_map.get(compound_name, BASE_DEGRADATION.get(compound, 0.020))
            pace_delta = cal_profile.get("compound_pace_delta_ms", {}).get(compound_name)
            # Track length adjustment
            length_mult = 1.0 + (track.track_length - 5.0) * 0.02
        else:
            base_deg = BASE_DEGRADATION.get(compound, 0.020)
            track_mult = self._track_type_multiplier(track.type_of_track, compound)
            length_mult = 1.0 + (track.track_length - 5.0) * 0.03
            base_deg = base_deg * track_mult
        
        # Weather adjustment
        weather_mult = 1.0
        if weather:
            if compound in (TyreCompound.INTER, TyreCompound.WET):
                weather_mult = max(0.5, 1.0 - weather.water_on_track * 0.5)
            else:
                weather_mult = 1.0 + weather.water_on_track * 2.0
            if weather.track_temp > 45:
                weather_mult *= 1.15
            elif weather.track_temp < 25:
                weather_mult *= 0.90
        
        effective_deg = base_deg * length_mult * weather_mult
        
        # Expected life
        if effective_deg > 0:
            expected_life = int(1.0 / effective_deg)
        else:
            expected_life = 999
        
        # Pace delta vs medium
        if pace_delta is None:
            if compound == TyreCompound.SOFT:
                pace_delta = -800   # faster by 0.8s
            elif compound == TyreCompound.HARD:
                pace_delta = +600   # slower by 0.6s
            elif compound == TyreCompound.MEDIUM:
                pace_delta = 0
            else:
                pace_delta = +400   # inters/wets slower on dry
        
        return CompoundAnalysis(
            compound=compound,
            expected_life_laps=expected_life,
            degradation_per_lap=effective_deg,
            optimal_temp_range=TYRE_OPTIMAL_TEMP.get(compound, (80, 100)),
            cliff_at_wear=TYRE_CLIFF_THRESHOLD.get(compound, 0.75),
            pace_delta_vs_medium_ms=pace_delta,
        )
    
    def predict_wear(self, car: CarRaceState, compound: TyreCompound,
                     current_lap: int, target_lap: int,
                     track: Track,
                     weather: Optional[WeatherState_Data] = None,
                     aggression: float = 0.5) -> TyreWearPrediction:
        """
        Predict tyre condition at a future lap.
        
        Args:
            car: Current car state
            compound: Tyre compound being used
            current_lap: Current race lap
            target_lap: Lap to predict for
            track: Track data
            weather: Current weather
            aggression: 0.0 (nurse) to 1.0 (push hard)
        """
        analysis = self.analyze_compound(compound, track, weather)
        
        laps_to_simulate = target_lap - current_lap
        if laps_to_simulate <= 0:
            # Current state
            return TyreWearPrediction(
                lap=current_lap,
                avg_condition=car.avg_tyre_condition,
                max_wear=1.0 - car.avg_tyre_condition,
                lap_time_delta_ms=0,
                is_past_cliff=False,
                estimated_laps_remaining=0,
                recommendation="STAY",
            )
        
        # Current wear from car state (condition is 1.0=new, 0.0=destroyed)
        current_wear = 1.0 - car.avg_tyre_condition
        
        # Aggression multiplier (pushing = more wear)
        aggression_mult = 1.0 + (aggression - 0.5) * 0.4  # 0.8x to 1.2x
        
        # Overheating penalty
        temp_penalty = 1.0
        if car.avg_tyre_temp > analysis.optimal_temp_range[1]:
            overheat = (car.avg_tyre_temp - analysis.optimal_temp_range[1]) / 20.0
            temp_penalty = 1.0 + overheat * 0.3
        
        # Simulate lap by lap
        wear = current_wear
        for lap_offset in range(laps_to_simulate):
            effective_deg = (analysis.degradation_per_lap * 
                           aggression_mult * temp_penalty)
            
            # Wear accelerates as tyre degrades (non-linear)
            wear_acceleration = 1.0 + (wear ** 2) * 0.5
            wear += effective_deg * wear_acceleration
            
            if wear >= 1.0:
                wear = 1.0
                break
        
        predicted_condition = max(0.0, 1.0 - wear)
        is_cliff = wear >= analysis.cliff_at_wear
        
        # Lap time delta from wear
        if wear < 0.3:
            time_delta = 0
        elif wear < analysis.cliff_at_wear:
            # Gradual degradation
            time_delta = int((wear - 0.3) * 3000)  # up to ~1.5s
        else:
            # Past cliff — dramatic performance loss
            cliff_excess = wear - analysis.cliff_at_wear
            time_delta = int(1500 + cliff_excess * 8000)  # 1.5s to 5s+
        
        # Remaining laps
        remaining_degradation = analysis.degradation_per_lap * aggression_mult * temp_penalty
        if remaining_degradation > 0:
            remaining = int((1.0 - wear) / remaining_degradation)
        else:
            remaining = 999
        
        # Recommendation
        if wear >= 0.90:
            rec = "BOX_NOW"
        elif wear >= analysis.cliff_at_wear:
            rec = "BOX_NOW"
        elif remaining <= 3:
            rec = "BOX_SOON"
        elif remaining <= 8:
            rec = "CONSIDER_BOX"
        else:
            rec = "STAY"
        
        return TyreWearPrediction(
            lap=target_lap,
            avg_condition=predicted_condition,
            max_wear=wear,
            lap_time_delta_ms=time_delta,
            is_past_cliff=is_cliff,
            estimated_laps_remaining=remaining,
            recommendation=rec,
        )
    
    def get_optimal_stint_length(self, compound: TyreCompound,
                                  track: Track,
                                  weather: Optional[WeatherState_Data] = None,
                                  aggression: float = 0.5) -> int:
        """
        Get the optimal number of laps for a stint on this compound.
        """
        analysis = self.analyze_compound(compound, track, weather)
        
        # Stop stint just before cliff
        optimal_wear = analysis.cliff_at_wear - 0.05
        aggression_mult = 1.0 + (aggression - 0.5) * 0.4
        
        effective_deg = analysis.degradation_per_lap * aggression_mult
        if effective_deg > 0:
            # Account for non-linear wear acceleration
            # Approximate: average acceleration factor ~1.1
            optimal_laps = int(optimal_wear / (effective_deg * 1.1))
        else:
            optimal_laps = track.laps
        
        return max(1, min(optimal_laps, track.laps))
    
    def compare_compounds(self, track: Track,
                          weather: Optional[WeatherState_Data] = None) -> list[CompoundAnalysis]:
        """Compare all dry compounds for a track."""
        compounds = [TyreCompound.SOFT, TyreCompound.MEDIUM, TyreCompound.HARD]
        if weather and weather.is_raining:
            compounds = [TyreCompound.INTER, TyreCompound.WET]
        
        analyses = [self.analyze_compound(c, track, weather) for c in compounds]
        return sorted(analyses, key=lambda a: a.expected_life_laps, reverse=True)
    
    # ── Private helpers ──────────────────────────────────────────────────────
    
    @staticmethod
    def _track_type_multiplier(track_type: TrackType, compound: TyreCompound) -> float:
        """Adjust degradation based on track type and compound."""
        # High speed tracks = more energy = more wear
        # Street tracks = less abrasive but more stop-start
        multipliers = {
            TrackType.HIGH_SPEED: {
                TyreCompound.SOFT: 1.15, TyreCompound.MEDIUM: 1.10,
                TyreCompound.HARD: 1.05, TyreCompound.INTER: 1.0,
                TyreCompound.WET: 1.0,
            },
            TrackType.STREET: {
                TyreCompound.SOFT: 0.90, TyreCompound.MEDIUM: 0.95,
                TyreCompound.HARD: 1.00, TyreCompound.INTER: 1.0,
                TyreCompound.WET: 1.0,
            },
            TrackType.BALANCED: {
                TyreCompound.SOFT: 1.0, TyreCompound.MEDIUM: 1.0,
                TyreCompound.HARD: 1.0, TyreCompound.INTER: 1.0,
                TyreCompound.WET: 1.0,
            },
        }
        return multipliers.get(track_type, {}).get(compound, 1.0)
