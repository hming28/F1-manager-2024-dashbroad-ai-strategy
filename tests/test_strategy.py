"""
Tests for F1 Manager 2024 AI Strategy System.

Run with: python -m pytest tests/ -v
"""
import pytest
import sqlite3
from pathlib import Path

from core.models import (
    Track, TrackType, TyreCompound, CarRaceState, WeatherState_Data,
    WeatherState, SafetyCarState, RaceSnapshot, RaceSimManager, DamageLevel,
    ErsStrategy, OvertakeStrategy,
)
from strategy.tyre_model import TyreModel, BASE_DEGRADATION
from strategy.pit_optimizer import PitOptimizer
from strategy.weather_strategy import WeatherStrategy
from strategy.safety_car import SafetyCarStrategy
from strategy.race_intel import RaceIntel
from strategy.engine import StrategyEngine


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def bahrain_track():
    return Track(
        track_id=2, name="Bahrain", country_id=12, laps=57,
        track_length=5.412, type_of_track=TrackType.BALANCED,
        fastest_lap=91.447, safety_car_chance=0.75,
        pit_lane_time_loss=22, green_flag_time_loss=20,
        safety_car_time_loss=16, sprint_laps=19,
    )


@pytest.fixture
def tyre_model():
    return TyreModel()


@pytest.fixture
def pit_optimizer(tyre_model):
    return PitOptimizer(tyre_model)


@pytest.fixture
def weather_strategy():
    return WeatherStrategy()


@pytest.fixture
def safety_car_strategy():
    return SafetyCarStrategy()


@pytest.fixture
def race_intel():
    return RaceIntel()


@pytest.fixture
def sample_car():
    return CarRaceState(
        car_index=0, driver_id=1, team_id=3,
        race_position=5, total_race_time=3600.0,
        fuel=45.0, engine_temp=90.0, brake_temp=350.0,
        current_tyre_id=1,
        tyre1_condition=0.65, tyre2_condition=0.62,
        tyre3_condition=0.68, tyre4_condition=0.63,
        tyre1_surface_temp=95.0, tyre2_surface_temp=97.0,
        tyre3_surface_temp=93.0, tyre4_surface_temp=96.0,
        ers_battery_charge=0.75,
        pit_stops_had=0, lap_count=30,
    )


@pytest.fixture
def sample_snapshot(sample_car, bahrain_track):
    weather = WeatherState_Data(
        time=1000, rain=0.0, water_on_track=0.0,
        ambient_temp=32.0, track_temp=45.0,
        weather_state=WeatherState.CLEAR,
        time_until_track_dry=0.0, rubber_on_track=0.5,
    )
    manager = RaceSimManager(
        sim_time=1000.0,
        safety_car_state=SafetyCarState.NONE,
        race_event_flags=0,
    )
    
    # Create 20 cars
    cars = []
    for i in range(20):
        car = CarRaceState(
            car_index=i, driver_id=i+1, team_id=(i // 2) + 1,
            race_position=i+1, total_race_time=3600.0 + i * 2.5,
            fuel=45.0, current_tyre_id=1,
            tyre1_condition=0.65, tyre2_condition=0.62,
            tyre3_condition=0.68, tyre4_condition=0.63,
            tyre1_surface_temp=95.0, tyre2_surface_temp=97.0,
            tyre3_surface_temp=93.0, tyre4_surface_temp=96.0,
            ers_battery_charge=0.75,
            pit_stops_had=0, lap_count=30,
        )
        cars.append(car)
    
    # Override car 0 with our sample
    cars[0] = sample_car
    
    return RaceSnapshot(
        track=bahrain_track, current_lap=30, total_laps=57,
        race_manager=manager, weather=weather, cars=cars,
    )


# ── Model Tests ──────────────────────────────────────────────────────────────

class TestTyreModel:
    def test_degradation_rates(self):
        """Soft degrades faster than medium, medium faster than hard."""
        assert BASE_DEGRADATION[TyreCompound.SOFT] > BASE_DEGRADATION[TyreCompound.MEDIUM]
        assert BASE_DEGRADATION[TyreCompound.MEDIUM] > BASE_DEGRADATION[TyreCompound.HARD]
    
    def test_analyze_compound(self, tyre_model, bahrain_track):
        """Analysis returns valid data for all compounds."""
        for compound in [TyreCompound.SOFT, TyreCompound.MEDIUM, TyreCompound.HARD]:
            analysis = tyre_model.analyze_compound(compound, bahrain_track)
            assert analysis.expected_life_laps > 0
            assert 0 < analysis.degradation_per_lap < 0.1
            assert analysis.cliff_at_wear > 0
    
    def test_compound_life_ordering(self, tyre_model, bahrain_track):
        """Hard lasts longer than medium, medium longer than soft."""
        soft = tyre_model.analyze_compound(TyreCompound.SOFT, bahrain_track)
        medium = tyre_model.analyze_compound(TyreCompound.MEDIUM, bahrain_track)
        hard = tyre_model.analyze_compound(TyreCompound.HARD, bahrain_track)
        assert hard.expected_life_laps > medium.expected_life_laps > soft.expected_life_laps
    
    def test_predict_wear(self, tyre_model, sample_car, bahrain_track):
        """Wear prediction is reasonable."""
        pred = tyre_model.predict_wear(
            sample_car, TyreCompound.MEDIUM,
            current_lap=30, target_lap=40,
            track=bahrain_track,
        )
        assert pred.avg_condition > 0
        assert pred.avg_condition < 1.0
        assert pred.estimated_laps_remaining > 0
    
    def test_optimal_stint_length(self, tyre_model, bahrain_track):
        """Optimal stint is reasonable for each compound."""
        for compound in [TyreCompound.SOFT, TyreCompound.MEDIUM, TyreCompound.HARD]:
            stint = tyre_model.get_optimal_stint_length(compound, bahrain_track)
            assert 5 <= stint <= bahrain_track.laps
    
    def test_weather_affects_degradation(self, tyre_model, bahrain_track):
        """Rain increases dry tyre degradation."""
        dry_weather = WeatherState_Data(
            time=0, rain=0.0, water_on_track=0.0,
            ambient_temp=30.0, track_temp=40.0,
            weather_state=WeatherState.CLEAR,
            time_until_track_dry=0.0, rubber_on_track=0.5,
        )
        wet_weather = WeatherState_Data(
            time=0, rain=0.5, water_on_track=0.3,
            ambient_temp=25.0, track_temp=30.0,
            weather_state=WeatherState.LIGHT_RAIN,
            time_until_track_dry=5.0, rubber_on_track=0.2,
        )
        
        dry_analysis = tyre_model.analyze_compound(TyreCompound.SOFT, bahrain_track, dry_weather)
        wet_analysis = tyre_model.analyze_compound(TyreCompound.SOFT, bahrain_track, wet_weather)
        
        assert wet_analysis.degradation_per_lap > dry_analysis.degradation_per_lap


class TestPitOptimizer:
    def test_optimize_returns_plan(self, pit_optimizer, sample_snapshot, sample_car, bahrain_track):
        """Optimizer returns a valid strategy plan."""
        plan = pit_optimizer.optimize(sample_snapshot, sample_car, bahrain_track)
        assert plan is not None
        assert isinstance(plan.risk_level, str)
    
    def test_safety_car_detection(self, pit_optimizer, sample_snapshot, sample_car, bahrain_track):
        """Safety car is detected and evaluated."""
        sample_snapshot.race_manager.safety_car_state = SafetyCarState.DEPLOYED
        
        plan = pit_optimizer.optimize(sample_snapshot, sample_car, bahrain_track)
        # Should have at least one option
        assert plan is not None


class TestWeatherStrategy:
    def test_no_alert_in_clear(self, weather_strategy, sample_snapshot):
        """No alert in clear weather."""
        alert = weather_strategy.analyze(sample_snapshot)
        assert alert is None  # clear weather, no alert needed
    
    def test_rain_alert(self, weather_strategy, sample_snapshot):
        """Alert when rain starts."""
        sample_snapshot.weather = WeatherState_Data(
            time=0, rain=0.6, water_on_track=0.4,
            ambient_temp=20.0, track_temp=25.0,
            weather_state=WeatherState.HEAVY_RAIN,
            time_until_track_dry=0.0, rubber_on_track=0.1,
        )
        alert = weather_strategy.analyze(sample_snapshot)
        assert alert is not None
        assert alert.severity == "CRITICAL"
        assert alert.recommended_compound == TyreCompound.WET


class TestSafetyCar:
    def test_no_action_without_sc(self, safety_car_strategy, sample_car, bahrain_track, sample_snapshot):
        """No recommendation when no safety car."""
        decision = safety_car_strategy.evaluate(sample_snapshot, sample_car, bahrain_track)
        assert decision is None
    
    def test_pit_under_sc(self, safety_car_strategy, sample_car, bahrain_track, sample_snapshot):
        """Should recommend pitting under safety car."""
        sample_snapshot.race_manager.safety_car_state = SafetyCarState.DEPLOYED
        
        decision = safety_car_strategy.evaluate(sample_snapshot, sample_car, bahrain_track)
        assert decision is not None
        # With decent tyres, should recommend pitting for free
        assert decision.time_saved_ms > 0


class TestRaceIntel:
    def test_analyze_returns_report(self, race_intel, sample_snapshot, bahrain_track):
        """Intel analysis returns a valid report."""
        report = race_intel.analyze(sample_snapshot, my_team_id=3, track=bahrain_track)
        assert report is not None
        assert report.my_position > 0


class TestStrategyEngine:
    def test_engine_update(self, sample_snapshot, bahrain_track):
        """Engine processes snapshot and returns state."""
        engine = StrategyEngine(my_team_id=3, track=bahrain_track)
        state = engine.update(sample_snapshot)
        
        assert state is not None
        assert state.my_position > 0
        assert state.current_lap == 30
        assert state.total_laps == 57
    
    def test_engine_with_safety_car(self, sample_snapshot, bahrain_track):
        """Engine handles safety car correctly."""
        sample_snapshot.race_manager.safety_car_state = SafetyCarState.DEPLOYED
        
        engine = StrategyEngine(my_team_id=3, track=bahrain_track)
        state = engine.update(sample_snapshot)
        
        assert state.sc_decision is not None


# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
