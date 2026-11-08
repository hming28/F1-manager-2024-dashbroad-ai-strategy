"""
weather_strategy.py — Weather response strategy for F1 Manager 2024.

Monitors weather trends and recommends tyre compound changes
before conditions deteriorate or improve.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.models import (
    CarRaceState, RaceSnapshot, TyreCompound, WeatherState_Data, WeatherState,
)


@dataclass
class WeatherAlert:
    """A weather-related strategy recommendation."""
    severity: str           # "INFO" / "WARNING" / "CRITICAL"
    message: str
    recommended_compound: TyreCompound
    laps_until_change: int  # estimated laps until weather changes enough to act
    confidence: float       # 0.0-1.0


class WeatherStrategy:
    """
    Analyzes weather trends and recommends compound changes.
    """
    
    # Thresholds for compound switching
    RAIN_START_THRESHOLD = 0.15       # rain intensity to consider inters
    HEAVY_RAIN_THRESHOLD = 0.50       # rain intensity for full wets
    DRY_THRESHOLD = 0.05              # rain intensity below which slicks work
    WATER_TRACK_DRY_THRESHOLD = 0.10  # water on track for slicks
    
    def analyze(self, snapshot: RaceSnapshot) -> Optional[WeatherAlert]:
        """
        Analyze current weather and return an alert if action is needed.
        """
        if snapshot.weather is None:
            return None
        
        weather = snapshot.weather
        
        # Check current conditions vs current tyres
        return self._check_conditions(weather, snapshot)
    
    def get_weather_trend(self, weather_history: list[WeatherState_Data]) -> str:
        """
        Determine weather trend from history.
        Returns: "IMPROVING" / "STABLE" / "DETERIORATING"
        """
        if len(weather_history) < 2:
            return "STABLE"
        
        recent = weather_history[:3]  # most recent 3 readings
        
        rain_values = [w.rain for w in recent]
        water_values = [w.water_on_track for w in recent]
        
        rain_trend = rain_values[0] - rain_values[-1]  # positive = increasing
        water_trend = water_values[0] - water_values[-1]
        
        if rain_trend > 0.1 or water_trend > 0.1:
            return "DETERIORATING"
        elif rain_trend < -0.1 or water_trend < -0.1:
            return "IMPROVING"
        else:
            return "STABLE"
    
    def _check_conditions(self, weather: WeatherState_Data,
                          snapshot: RaceSnapshot) -> Optional[WeatherAlert]:
        """Check if current conditions warrant a tyre change."""
        
        # Is it raining?
        if weather.rain > self.HEAVY_RAIN_THRESHOLD:
            # Heavy rain — need full wets
            return WeatherAlert(
                severity="CRITICAL",
                message="🌧️ HEAVY RAIN! Switch to WET tyres immediately!",
                recommended_compound=TyreCompound.WET,
                laps_until_change=0,
                confidence=0.95,
            )
        
        if weather.rain > self.RAIN_START_THRESHOLD:
            # Light rain — intermediates
            if weather.water_on_track > 0.3:
                return WeatherAlert(
                    severity="WARNING",
                    message="🌦️ Rain increasing. Switch to INTERMEDIATES.",
                    recommended_compound=TyreCompound.INTER,
                    laps_until_change=2,
                    confidence=0.85,
                )
            else:
                return WeatherAlert(
                    severity="INFO",
                    message="🌦️ Light rain detected. Monitor conditions.",
                    recommended_compound=TyreCompound.INTER,
                    laps_until_change=5,
                    confidence=0.60,
                )
        
        # Track is drying (only if there was recent water)
        if (0.01 < weather.water_on_track < self.WATER_TRACK_DRY_THRESHOLD 
            and weather.rain < 0.05):
            # Check if cars are on wet/inter tyres
            # This would need tyre compound tracking
            return WeatherAlert(
                severity="INFO",
                message="☀️ Track is drying. Consider switching to slicks.",
                recommended_compound=TyreCompound.MEDIUM,
                laps_until_change=3,
                confidence=0.70,
            )
        
        # Temperature warnings
        if weather.track_temp > 50:
            return WeatherAlert(
                severity="INFO",
                message=f"🌡️ High track temp ({weather.track_temp:.0f}°C). Hard compound recommended.",
                recommended_compound=TyreCompound.HARD,
                laps_until_change=0,
                confidence=0.75,
            )
        
        if weather.track_temp < 20:
            return WeatherAlert(
                severity="INFO",
                message=f"❄️ Low track temp ({weather.track_temp:.0f}°C). Soft compound may struggle to warm up.",
                recommended_compound=TyreCompound.MEDIUM,
                laps_until_change=0,
                confidence=0.65,
            )
        
        return None
