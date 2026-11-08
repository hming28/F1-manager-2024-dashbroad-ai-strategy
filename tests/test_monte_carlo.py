"""
Tests for Monte Carlo Race Simulator.
"""
import pytest
import time

from core.models import (
    Track, TrackType, TyreCompound, CarRaceState, RaceSnapshot,
    RaceSimManager, SafetyCarState, WeatherState_Data, WeatherState
)
from strategy.monte_carlo import MonteCarloSimulator, F1_POINTS
from strategy.tyre_model import TyreModel


@pytest.fixture
def track_bahrain():
    return Track(
        track_id=1, name="Bahrain", country_id=1, laps=57,
        track_length=5.412, type_of_track=TrackType.BALANCED,
        fastest_lap=91.4, safety_car_chance=0.65,
        pit_lane_time_loss=22, green_flag_time_loss=20,
        safety_car_time_loss=16, sprint_laps=19,
    )


@pytest.fixture
def track_monaco():
    return Track(
        track_id=8, name="Monaco", country_id=8, laps=78,
        track_length=3.337, type_of_track=TrackType.STREET,
        fastest_lap=74.5, safety_car_chance=0.85,
        pit_lane_time_loss=19, green_flag_time_loss=18,
        safety_car_time_loss=14, sprint_laps=20,
    )


@pytest.fixture
def snapshot(track_bahrain):
    weather = WeatherState_Data(
        time=0, rain=0.0, water_on_track=0.0, ambient_temp=28.0,
        track_temp=38.0, weather_state=WeatherState.CLEAR,
        time_until_track_dry=0.0, rubber_on_track=0.6,
    )
    manager = RaceSimManager(
        sim_time=2400.0, safety_car_state=SafetyCarState.NONE, race_event_flags=0
    )
    cars = []
    for i in range(20):
        cars.append(CarRaceState(
            car_index=i, driver_id=i + 1, team_id=(i // 2) + 1,
            race_position=i + 1, total_race_time=2400.0 + i * 2.2,
            tyre1_condition=0.55, tyre2_condition=0.55,
            tyre3_condition=0.55, tyre4_condition=0.55,
            pit_stops_had=1, lap_count=35,
        ))
    return RaceSnapshot(
        track=track_bahrain, current_lap=35, total_laps=57,
        race_manager=manager, weather=weather, cars=cars,
    )


class TestMonteCarloSimulator:
    def test_simulation_execution_speed(self, snapshot, track_bahrain):
        """1,000 simulations over 22 remaining laps must complete in under 1 second."""
        sim = MonteCarloSimulator(default_simulations=1000)
        car = snapshot.cars[2]  # P3 car
        candidates = [
            ("Box L38 Medium", 38, TyreCompound.MEDIUM),
            ("Box L40 Hard", 40, TyreCompound.HARD),
            ("Stay Out", 0, TyreCompound.MEDIUM),
        ]
        start = time.perf_counter()
        report = sim.simulate(snapshot, car, track_bahrain, candidates, num_simulations=1000)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"Monte Carlo took {elapsed:.2f}s, expected < 1.0s"
        assert report.simulations_run == 1000
        assert len(report.all_results) == 3

    def test_reproducibility_with_seed(self, snapshot, track_bahrain):
        """Fixed random seed must yield identical probability results."""
        sim = MonteCarloSimulator()
        car = snapshot.cars[0]  # Leader
        candidates = [("Box L38 Medium", 38, TyreCompound.MEDIUM)]

        r1 = sim.simulate(snapshot, car, track_bahrain, candidates, num_simulations=500, seed=123)
        r2 = sim.simulate(snapshot, car, track_bahrain, candidates, num_simulations=500, seed=123)

        assert r1.best_result.expected_points == r2.best_result.expected_points
        assert r1.best_result.win_probability == r2.best_result.win_probability
        assert r1.best_result.podium_probability == r2.best_result.podium_probability

    def test_expected_points_and_probabilities_bounds(self, snapshot, track_bahrain):
        """Statistical metrics must adhere to probability and F1 points bounds."""
        sim = MonteCarloSimulator()
        car = snapshot.cars[4]  # P5 car
        candidates = [("Box L38 Medium", 38, TyreCompound.MEDIUM)]

        report = sim.simulate(snapshot, car, track_bahrain, candidates, num_simulations=500, seed=42)
        res = report.best_result

        assert 0.0 <= res.expected_points <= 25.0
        assert 0.0 <= res.win_probability <= 1.0
        assert 0.0 <= res.podium_probability <= 1.0
        assert 0.0 <= res.points_probability <= 1.0
        assert 1 <= res.p90_position <= res.p10_position <= 20
        assert 0.0 <= res.traffic_risk <= 1.0

    def test_worn_tyre_forces_pit_recommendation(self, snapshot, track_bahrain):
        """When tyres are 85% worn, pitting beats staying out in expected points."""
        sim = MonteCarloSimulator()
        car = snapshot.cars[1]  # P2 car
        # Extremely worn tyres (15% condition remaining)
        car.tyre1_condition = 0.15
        car.tyre2_condition = 0.15
        car.tyre3_condition = 0.15
        car.tyre4_condition = 0.15

        candidates = [
            ("Box L36 Soft", 36, TyreCompound.SOFT),
            ("Stay Out Worn", 0, TyreCompound.MEDIUM),
        ]
        report = sim.simulate(snapshot, car, track_bahrain, candidates, num_simulations=800, seed=99)
        # Pitting for fresh rubber should easily beat staying out on cliffed tyres
        assert report.best_result.strategy_name == "Box L36 Soft"
        assert report.best_result.expected_points > report.all_results[1].expected_points

    def test_overtaking_difficulty_increases_traffic_risk(self, snapshot, track_bahrain, track_monaco):
        """Street tracks with high overtaking difficulty yield higher traffic risk than open tracks."""
        sim = MonteCarloSimulator()
        car = snapshot.cars[3]

        candidates = [("Box Next Lap", 36, TyreCompound.MEDIUM)]
        res_bahrain = sim.simulate(snapshot, car, track_bahrain, candidates, num_simulations=500, seed=10)
        res_monaco = sim.simulate(snapshot, car, track_monaco, candidates, num_simulations=500, seed=10)

        # Monaco overtaking difficulty is 0.98 vs Bahrain 0.45
        assert res_monaco.best_result.traffic_risk >= res_bahrain.best_result.traffic_risk

    def test_safety_car_in_progress_favors_immediate_box(self, snapshot, track_bahrain):
        """Pitting immediately under an active Safety Car yields higher benefit than green-flag pit."""
        snapshot.race_manager.safety_car_state = SafetyCarState.DEPLOYED
        sim = MonteCarloSimulator()
        car = snapshot.cars[2]

        candidates = [
            ("Box Under SC L36", 36, TyreCompound.MEDIUM),
            ("Box Green L42", 42, TyreCompound.MEDIUM),
        ]
        report = sim.simulate(snapshot, car, track_bahrain, candidates, num_simulations=800, seed=77)

        # Pitting under SC gets free pit stop delta and should score higher expected points
        assert report.best_result.strategy_name == "Box Under SC L36"
        assert report.best_result.sc_benefit_frequency > 0.5
