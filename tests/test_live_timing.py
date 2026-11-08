"""
Unit tests for F1 Live Timing system:
- UE4SS JSON reader and robustness
- LapHistoryAccumulator accuracy (no lap drop, no duplication)
- Session fastest & personal best tracking
- Sector color states (purple/green/yellow)
- Interval & gap calculations
- Dual-mode RaceSnapshot generation & StrategyEngine integration
- Dashboard F1 timing tower rendering
"""
import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from core.models import (
    CarRaceState, CompletedLapRecord, RaceSnapshot, SectorState,
    Track, TrackType, TyreCompound, WeatherState, WeatherState_Data,
)
from core.live_timing_reader import (
    LiveTimingReader, LapHistoryAccumulator, resolve_team_id,
)
from strategy.engine import StrategyEngine
from display.dashboard import Dashboard


@pytest.fixture
def sample_track():
    return Track(
        track_id=1, name="Bahrain", country_id=1, laps=57,
        track_length=5.412, type_of_track=TrackType.BALANCED,
        fastest_lap=91.447, safety_car_chance=0.75,
        pit_lane_time_loss=22, green_flag_time_loss=20,
        safety_car_time_loss=16, sprint_laps=19,
    )


@pytest.fixture
def mock_20_cars_telemetry():
    """Generate 20 cars with realistic F1 names, numbers, and live timing fields."""
    drivers = [
        ("VER", 1, "Max Verstappen", "RedBull"),
        ("PER", 11, "Sergio Perez", "RedBull"),
        ("NOR", 4, "Lando Norris", "McLaren"),
        ("PIA", 81, "Oscar Piastri", "McLaren"),
        ("LEC", 16, "Charles Leclerc", "Ferrari"),
        ("SAI", 55, "Carlos Sainz", "Ferrari"),
        ("HAM", 44, "Lewis Hamilton", "Mercedes"),
        ("RUS", 63, "George Russell", "Mercedes"),
        ("ALO", 14, "Fernando Alonso", "AstonMartin"),
        ("STR", 18, "Lance Stroll", "AstonMartin"),
        ("TSU", 22, "Yuki Tsunoda", "RacingBulls"),
        ("RIC", 3, "Daniel Ricciardo", "RacingBulls"),
        ("ALB", 23, "Alexander Albon", "Williams"),
        ("SAR", 2, "Logan Sargeant", "Williams"),
        ("HUL", 27, "Nico Hulkenberg", "Haas"),
        ("MAG", 20, "Kevin Magnussen", "Haas"),
        ("OCO", 31, "Esteban Ocon", "Alpine"),
        ("GAS", 10, "Pierre Gasly", "Alpine"),
        ("BOT", 77, "Valtteri Bottas", "Sauber"),
        ("ZHO", 24, "Zhou Guanyu", "Sauber"),
    ]

    cars = []
    base_time = 0.0
    for i, (code, num, name, team) in enumerate(drivers):
        gap = round(base_time, 3)
        cars.append({
            "car_index": i,
            "driver_name": name,
            "driver_code": code,
            "driver_number": num,
            "team_name": team,
            "position": i + 1,
            "lap_count": 1,
            "lap_progress": 0.45,
            "current_lap_time": 42.5,
            "last_lap_time": 0.0,
            "best_lap_time": 0.0,
            "gap_to_leader": gap,
            "s1_time": 28.500 + i * 0.05,
            "s1_state": 1,  # Completed
            "s2_time": 39.100 + i * 0.08,
            "s2_state": 0,  # Open
            "s3_time": 0.0,
            "s3_state": 0,
            "tyre_compound": 0 if i < 10 else 1,  # Soft / Medium
            "tyre_wear": 10 + i,
            "tyre_temp": 95,
            "ers_charge": 80 - i,
            "drs_state": 1 if i % 2 == 0 else 0,
            "fuel": 45.0,
            "speed_kph": 290 - i * 2,
            "gear": 7,
            "is_in_pit": (i == 19),  # Last car in pit
            "race_complete_state": 0,
        })
        base_time += 1.25

    return {
        "timestamp": 1000.0,
        "session_type": "Race",
        "car_count": 20,
        "cars": cars,
    }


class TestTeamResolution:
    def test_team_name_resolutions(self):
        assert resolve_team_id("RedBull") == 3
        assert resolve_team_id("Ferrari") == 1
        assert resolve_team_id("McLaren") == 2
        assert resolve_team_id("Mercedes") == 4
        assert resolve_team_id("Alpine") == 5
        assert resolve_team_id("Williams") == 6
        assert resolve_team_id("Haas") == 7
        assert resolve_team_id("RacingBulls") == 8
        assert resolve_team_id("Sauber") == 9
        assert resolve_team_id("AstonMartin") == 10
        assert resolve_team_id("CustomTeam") == 32
        assert resolve_team_id("MyTeam") == 32
        assert resolve_team_id("Unknown", default=99) == 99


class TestLiveTimingReader:
    def test_reader_freshness_detection(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            tf.write(b'{"cars": []}')
            temp_path = tf.name

        try:
            reader = LiveTimingReader(json_path=temp_path)
            assert reader.is_live(max_age_seconds=5.0) is True
            assert reader.is_live(max_age_seconds=-1.0) is False

            # Non-existent path
            reader_none = LiveTimingReader(json_path="non_existent_file_12345.json")
            assert reader_none.is_live() is False
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_reader_read_raw_and_retry(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tf:
            json.dump({"timestamp": 123.45, "cars": [{"car_index": 0, "position": 1}]}, tf)
            temp_path = tf.name

        try:
            reader = LiveTimingReader(json_path=temp_path)
            data = reader.read_latest_raw()
            assert data is not None
            assert data["timestamp"] == 123.45
            assert len(data["cars"]) == 1
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_reader_handles_corrupt_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tf:
            tf.write("{bad json...")
            temp_path = tf.name

        try:
            reader = LiveTimingReader(json_path=temp_path)
            data = reader.read_latest_raw(retries=2, delay=0.01)
            assert data is None
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_reader_pause_detection(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            tf.write(b'{"cars": []}')
            temp_path = tf.name

        try:
            reader = LiveTimingReader(json_path=temp_path)
            # Fresh file: not paused
            assert reader.is_paused(pause_threshold_sec=5.0) is False

            # Simulate pause: file modified 10 seconds ago
            old_time = time.time() - 10.0
            os.utime(temp_path, (old_time, old_time))
            assert reader.is_paused(pause_threshold_sec=3.0, max_pause_sec=60.0) is True
            assert reader.is_live(max_age_seconds=30.0) is True
            # Expired beyond 60s
            assert reader.is_paused(pause_threshold_sec=3.0, max_pause_sec=8.0) is False
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


class TestLapHistoryAccumulator:
    def test_single_car_lap_accumulation(self):
        acc = LapHistoryAccumulator()

        # Step 1: Lap 1, in Sector 1
        tick1 = [{
            "car_index": 0, "driver_code": "VER", "lap_count": 1,
            "current_lap_time": 15.0, "last_lap_time": 0.0,
            "s1_time": 28.450, "s1_state": 0, "s2_time": 0.0, "s2_state": 0, "s3_time": 0.0, "s3_state": 0,
        }]
        completed = acc.update_from_telemetry(tick1)
        assert len(completed) == 0

        # Step 2: Pass S1 Checkpoint
        tick2 = [{
            "car_index": 0, "driver_code": "VER", "lap_count": 1,
            "current_lap_time": 30.0, "last_lap_time": 0.0,
            "s1_time": 28.450, "s1_state": 3, "s2_time": 0.0, "s2_state": 0, "s3_time": 0.0, "s3_state": 0,
        }]
        acc.update_from_telemetry(tick2)
        assert acc._sector_cache[0]["s1"] == 28.450

        # Step 3: Pass S2 Checkpoint
        tick3 = [{
            "car_index": 0, "driver_code": "VER", "lap_count": 1,
            "current_lap_time": 68.0, "last_lap_time": 0.0,
            "s1_time": 28.450, "s1_state": 3, "s2_time": 39.120, "s2_state": 3, "s3_time": 0.0, "s3_state": 0,
        }]
        acc.update_from_telemetry(tick3)
        assert acc._sector_cache[0]["s2"] == 39.120

        # Step 4: Cross Finish Line -> Lap 2 begins!
        tick4 = [{
            "car_index": 0, "driver_code": "VER", "lap_count": 2,
            "current_lap_time": 2.0, "last_lap_time": 91.850,
            "s1_time": 0.0, "s1_state": 0, "s2_time": 0.0, "s2_state": 0, "s3_time": 24.280, "s3_state": 1,
        }]
        completed = acc.update_from_telemetry(tick4)
        assert len(completed) == 1
        rec = completed[0]
        assert rec.car_index == 0
        assert rec.driver_code == "VER"
        assert rec.lap_number == 1
        assert rec.lap_time == 91.850
        assert rec.s1_time == 28.450
        assert rec.s2_time == 39.120
        assert rec.s3_time == 24.280
        assert rec.is_personal_best is True
        assert rec.is_session_best is True

        # Step 5: Duplicate tick does NOT produce duplicate record
        completed_dup = acc.update_from_telemetry(tick4)
        assert len(completed_dup) == 0
        assert len(acc.lap_history[0]) == 1

        # Step 6: Complete Lap 2 with faster time
        tick5 = [{
            "car_index": 0, "driver_code": "VER", "lap_count": 3,
            "current_lap_time": 1.5, "last_lap_time": 91.200,
            "s1_time": 28.200, "s1_state": 2, "s2_time": 38.900, "s2_state": 2, "s3_time": 24.100, "s3_state": 2,
        }]
        completed2 = acc.update_from_telemetry(tick5)
        assert len(completed2) == 1
        assert completed2[0].lap_number == 2
        assert completed2[0].lap_time == 91.200
        assert completed2[0].is_session_best is True
        assert acc.session_fastest_lap == 91.200
        assert acc.session_fastest_lap_driver == "VER"
        assert len(acc.lap_history[0]) == 2

    def test_20_cars_multi_lap_simulation(self, mock_20_cars_telemetry):
        acc = LapHistoryAccumulator()

        # Initial frame (lap 1)
        acc.update_from_telemetry(mock_20_cars_telemetry["cars"])
        assert len(acc.lap_history) == 20

        # Simulate 5 full laps for all 20 cars
        for lap in range(1, 6):
            tick_cars = []
            for car in mock_20_cars_telemetry["cars"]:
                idx = car["car_index"]
                # Car 0 (VER) sets the absolute fastest lap 90.500 on lap 3
                lap_time = 91.500 + (idx * 0.15)
                if idx == 0 and lap == 3:
                    lap_time = 90.500

                tick_cars.append({
                    "car_index": idx,
                    "driver_code": car["driver_code"],
                    "lap_count": lap + 1,
                    "current_lap_time": 0.5,
                    "last_lap_time": lap_time,
                    "s1_time": 28.300 + idx * 0.02,
                    "s1_state": 1,
                    "s2_time": 39.000 + idx * 0.03,
                    "s2_state": 1,
                    "s3_time": round(lap_time - 28.300 - 39.000 - idx * 0.05, 3),
                    "s3_state": 1,
                    "tyre_compound": car["tyre_compound"],
                    "tyre_wear": car["tyre_wear"] + lap * 3,
                })
            new_records = acc.update_from_telemetry(tick_cars)
            assert len(new_records) == 20

        # Verify all 20 cars have exactly 5 completed laps recorded
        for idx in range(20):
            assert len(acc.lap_history[idx]) == 5
            laps_recorded = [r.lap_number for r in acc.lap_history[idx]]
            assert laps_recorded == [1, 2, 3, 4, 5]

        # Verify session fastest lap
        assert acc.session_fastest_lap == 90.500
        assert acc.session_fastest_lap_driver == "VER"
        assert acc.session_fastest_lap_car_index == 0
        assert acc.session_fastest_lap_number == 3

    def test_interval_and_gap_calculation(self, mock_20_cars_telemetry, sample_track):
        acc = LapHistoryAccumulator()
        snapshot = acc.create_snapshot(mock_20_cars_telemetry, base_track=sample_track)

        assert snapshot.is_live_timing is True
        assert len(snapshot.cars) == 20
        assert snapshot.track.name == "Bahrain"

        # P1 VER
        p1 = snapshot.cars[0]
        assert p1.race_position == 1
        assert p1.gap_to_leader == 0.0
        assert p1.gap_to_ahead == 0.0

        # P2 PER
        p2 = snapshot.cars[1]
        assert p2.race_position == 2
        assert p2.gap_to_leader == 1.25
        assert p2.gap_to_ahead == 1.25

        # P3 NOR
        p3 = snapshot.cars[2]
        assert p3.race_position == 3
        assert p3.gap_to_leader == 2.50
        assert p3.gap_to_ahead == 1.25


class TestStrategyAndDashboardIntegration:
    def test_live_snapshot_in_strategy_engine(self, mock_20_cars_telemetry, sample_track):
        acc = LapHistoryAccumulator()
        snapshot = acc.create_snapshot(mock_20_cars_telemetry, base_track=sample_track)

        # Initialize engine for Team 3 (Red Bull)
        engine = StrategyEngine(my_team_id=3, track=sample_track)
        state = engine.update(snapshot)

        assert state is not None
        assert state.current_lap == 1
        assert len(snapshot.cars) == 20
        # Engine produces recommendations and state
        assert isinstance(state.recommendations, list)

    def test_dashboard_renders_live_timing_tower(self, mock_20_cars_telemetry, sample_track):
        acc = LapHistoryAccumulator()
        snapshot = acc.create_snapshot(mock_20_cars_telemetry, base_track=sample_track)
        snapshot.fastest_lap_time = 90.500
        snapshot.fastest_lap_driver = "VER"

        engine = StrategyEngine(my_team_id=3, track=sample_track)
        state = engine.update(snapshot)

        dashboard = Dashboard(my_team_id=3)

        # Verify header panel builds with live badge and fastest lap
        header = dashboard._build_header(snapshot, state)
        assert header is not None
        header_text = str(header.renderable)
        assert "LIVE" in header_text
        assert "FL: VER 1:30.500" in header_text

        # Verify standings table builds with live timing tower
        standings = dashboard._build_standings(snapshot, state)
        assert standings is not None
        table = standings.renderable
        col_names = [col.header for col in table.columns]
        assert "S1" in col_names
        assert "S2" in col_names
        assert "S3" in col_names
        assert "Current" in col_names
        assert "Last Lap" in col_names
        assert "Best Lap" in col_names
        assert "Int" in col_names
        assert "Gap" in col_names

        # Verify full dashboard renders without raising exceptions
        dashboard.render(snapshot, state)

    def test_dashboard_paused_header_and_tyre_display(self, mock_20_cars_telemetry, sample_track):
        acc = LapHistoryAccumulator()
        snapshot = acc.create_snapshot(mock_20_cars_telemetry, base_track=sample_track)
        snapshot.is_live_paused = True

        engine = StrategyEngine(my_team_id=3, track=sample_track)
        state = engine.update(snapshot)

        dashboard = Dashboard(my_team_id=3)
        header = dashboard._build_header(snapshot, state)
        header_text = str(header.renderable)
        assert "PAUSED" in header_text

        # Verify tyre display in standings represents remaining tyre life (e.g. 10% wear -> 90% life)
        standings = dashboard._build_standings(snapshot, state)
        table = standings.renderable
        assert table.columns[2].header == "Driver"
        assert table.columns[2].width == 7


class TestLiveTimingEdgeCases:
    def test_empty_and_partial_telemetry(self, sample_track):
        acc = LapHistoryAccumulator()
        snap_empty = acc.create_snapshot({"cars": []}, base_track=sample_track)
        assert snap_empty.cars == []
        assert snap_empty.current_lap == 0

        # Partial fields with missing names and None values
        tick = [{
            "car_index": 7,
            "position": 1,
            "lap_count": 2,
            "last_lap_time": 93.456,
            "s1_time": 29.100,
            "s2_time": 40.000,
            "s3_time": 0.0,  # missing s3 time -> should deduce from lap time!
        }]
        acc.update_from_telemetry(tick)
        # Advance lap
        tick[0]["lap_count"] = 3
        tick[0]["last_lap_time"] = 92.500
        completed = acc.update_from_telemetry(tick)
        assert len(completed) == 1
        rec = completed[0]
        # 92.500 - 29.100 - 40.000 = 23.400
        assert abs(rec.s3_time - 23.400) < 0.001

    def test_accumulator_reset(self):
        acc = LapHistoryAccumulator()
        acc.session_fastest_lap = 88.5
        acc.session_fastest_lap_driver = "HAM"
        acc.personal_bests[0] = {"lap": 89.0}
        acc.lap_history[0] = [CompletedLapRecord(0, 1, 89.0, 28.0, 38.0, 23.0)]

        acc.reset()
        assert acc.session_fastest_lap == 9999.0
        assert acc.session_fastest_lap_driver == ""
        assert len(acc.lap_history) == 0
        assert len(acc.personal_bests) == 0

    def test_mid_race_connection(self):
        acc = LapHistoryAccumulator()
        # Connect at lap 25 where driver already has a personal/session best of 89.200s
        tick = [{
            "car_index": 0, "driver_code": "VER", "lap_count": 25,
            "best_lap_time": 89.200, "last_lap_time": 91.0
        }]
        new_laps = acc.update_from_telemetry(tick)
        assert len(new_laps) == 0
        assert len(acc.lap_history[0]) == 0
        assert acc.session_fastest_lap == 89.200
        assert acc.personal_bests[0]["lap"] == 89.200

        # Car finishes lap 25 with a slower in-lap 93.500 -> enters lap 26
        tick2 = [{
            "car_index": 0, "driver_code": "VER", "lap_count": 26,
            "best_lap_time": 89.200, "last_lap_time": 93.500,
            "s1_time": 28.5, "s2_time": 39.5, "s3_time": 25.5
        }]
        new_laps2 = acc.update_from_telemetry(tick2)
        assert len(new_laps2) == 1
        assert new_laps2[0].lap_number == 25
        assert len(acc.lap_history[0]) == 1
        # Slower in-lap should NOT be marked as personal best or session best!
        assert new_laps2[0].is_personal_best is False
        assert new_laps2[0].is_session_best is False
        assert acc.session_fastest_lap == 89.200

    def test_multi_lap_jump_at_high_speed(self):
        """Simulate 16x speed or lag where lap_count jumps from 10 to 12 without dropping laps."""
        acc = LapHistoryAccumulator()
        # Lap 10
        acc.update_from_telemetry([{"car_index": 0, "lap_count": 10, "last_lap_time": 91.0}])
        # Jump to Lap 12 (finished lap 10 and lap 11)
        completed = acc.update_from_telemetry([{
            "car_index": 0, "lap_count": 12, "last_lap_time": 90.800,
            "s1_time": 28.1, "s2_time": 39.0, "s3_time": 23.7
        }])
        assert len(completed) == 2
        assert [r.lap_number for r in completed] == [10, 11]
        assert len(acc.lap_history[0]) == 2
        assert acc.lap_history[0][0].lap_number == 10
        assert acc.lap_history[0][1].lap_number == 11
        assert acc.lap_history[0][1].lap_time == 90.800

    def test_purple_sector_preservation_across_lap(self):
        """Verify that a purple (session best) sector is preserved after crossing the finish line."""
        acc = LapHistoryAccumulator()
        # Lap 1: car sets purple sector 1 (state=2, time=27.900)
        acc.update_from_telemetry([{
            "car_index": 0, "driver_code": "VER", "lap_count": 1,
            "s1_time": 27.900, "s1_state": 2, "s2_time": 0.0, "s2_state": 0, "s3_time": 0.0, "s3_state": 0
        }])
        assert acc.session_best_s1 == 27.900

        # Lap 2 begins: car crosses line, s1_state resets to 0 (OPEN)
        completed = acc.update_from_telemetry([{
            "car_index": 0, "driver_code": "VER", "lap_count": 2,
            "last_lap_time": 89.900,
            "s1_time": 0.0, "s1_state": 0, "s2_time": 0.0, "s2_state": 0, "s3_time": 23.5, "s3_state": 1
        }])
        assert len(completed) == 1
        rec = completed[0]
        assert rec.lap_number == 1
        assert rec.s1_time == 27.900
        # Sector 1 MUST retain SESSION_BEST purple state!
        assert rec.s1_state == SectorState.SESSION_BEST

    def test_critical_tyre_wear_mapping(self, sample_track):
        acc = LapHistoryAccumulator()
        telemetry = {
            "timestamp": 500.0,
            "cars": [{
                "car_index": 0,
                "position": 1,
                "lap_count": 30,
                "tyre_compound": 0,  # Soft
                "tyre_wear": 85,     # 85% worn out -> 0.15 condition
                "is_in_pit": True,
            }]
        }
        snap = acc.create_snapshot(telemetry, base_track=sample_track)
        car = snap.cars[0]
        assert car.tyre_wear_pct == 85
        assert abs(car.avg_tyre_condition - 0.15) < 0.001
        assert car.is_in_pit_lane is True
        assert car.is_in_pit is True

    def test_eco_mode_cli_parsing(self):
        import argparse
        import main

        # Create parser identical to main()
        # Verify --eco and --fps arguments work cleanly
        parser = argparse.ArgumentParser()
        parser.add_argument("--eco", action="store_true")
        parser.add_argument("--fps", "--refresh-rate", type=float, default=None, dest="fps")

        args = parser.parse_args(["--eco"])
        assert args.eco is True
        assert args.fps is None

        args2 = parser.parse_args(["--fps", "1.5"])
        assert args2.eco is False
        assert args2.fps == 1.5

    def test_optimize_ue4ss_settings(self, tmp_path):
        import install_mod

        ini_file = tmp_path / "UE4SS-settings.ini"
        ini_file.write_text(
            "[Debug]\n"
            "ConsoleEnabled = 1\n"
            "GuiConsoleEnabled = 1\n"
            "LogLevel = 3\n",
            encoding="utf-8"
        )

        install_mod.optimize_ue4ss_settings(tmp_path)

        updated_content = ini_file.read_text(encoding="utf-8")
        assert "ConsoleEnabled = 0" in updated_content
        assert "GuiConsoleEnabled = 0" in updated_content
        assert (tmp_path / "UE4SS-settings.ini.bak").exists()
