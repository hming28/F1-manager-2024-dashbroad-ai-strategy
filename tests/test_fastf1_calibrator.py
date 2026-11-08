"""
Tests for FastF1 real data calibration module.
"""
import pytest
from pathlib import Path

from core.models import Track, TrackType, TyreCompound
from strategy.fastf1_calibrator import FastF1Calibrator, is_fastf1_available
from strategy.tyre_model import TyreModel


@pytest.fixture
def calibrator():
    return FastF1Calibrator()


@pytest.fixture
def tyre_model(calibrator):
    return TyreModel(calibrator=calibrator)


class TestFastF1Calibrator:
    def test_database_loads_all_24_tracks(self, calibrator):
        """Database contains all 24 championship circuits."""
        db = calibrator.get_database()
        assert "tracks" in db
        tracks = db["tracks"]
        assert len(tracks) == 24

        required_keys = [
            "track_id", "name", "country", "laps", "track_length_km",
            "base_lap_time_ms", "compound_deg_rate", "compound_pace_delta_ms",
            "deg_lap_time_penalty_ms_per_lap", "pit_lane_loss_sec",
            "sc_probability", "overtaking_difficulty", "source"
        ]
        for key, data in tracks.items():
            for rk in required_keys:
                assert rk in data, f"Missing key {rk} in track {key}"
            assert data["base_lap_time_ms"] > 50000
            assert 0.0 <= data["sc_probability"] <= 1.0
            assert 0.0 <= data["overtaking_difficulty"] <= 1.0

    def test_track_lookup_by_name_and_id(self, calibrator):
        """Tracks can be looked up by string name or integer track_id."""
        bahrain = calibrator.find_track("Bahrain")
        assert bahrain is not None
        assert bahrain["name"] == "Bahrain"

        monza = calibrator.find_track("monza")
        assert monza is not None
        assert monza["country"] == "Italy"

        track_8 = calibrator.find_track(8)
        assert track_8 is not None
        assert "Monaco" in track_8["name"]

    def test_list_tracks(self, calibrator):
        """list_tracks returns complete sorted track summaries."""
        track_list = calibrator.list_tracks()
        assert len(track_list) == 24
        assert track_list[0][0] == "bahrain"

    def test_tyre_model_uses_calibrated_rates(self, tyre_model):
        """TyreModel incorporates circuit-specific degradation and pace deltas."""
        bahrain_track = Track(
            track_id=1, name="Bahrain", country_id=1, laps=57,
            track_length=5.412, type_of_track=TrackType.BALANCED,
            fastest_lap=91.4, safety_car_chance=0.65,
            pit_lane_time_loss=22, green_flag_time_loss=20,
            safety_car_time_loss=16, sprint_laps=19,
        )
        assert tyre_model.is_track_calibrated(bahrain_track) is True

        soft_analysis = tyre_model.analyze_compound(TyreCompound.SOFT, bahrain_track)
        medium_analysis = tyre_model.analyze_compound(TyreCompound.MEDIUM, bahrain_track)
        hard_analysis = tyre_model.analyze_compound(TyreCompound.HARD, bahrain_track)

        # In Bahrain, calibrated SOFT pace delta is -750ms, HARD is +650ms vs Medium
        assert soft_analysis.pace_delta_vs_medium_ms == -750
        assert medium_analysis.pace_delta_vs_medium_ms == 0
        assert hard_analysis.pace_delta_vs_medium_ms == 650

        # Hard tyre expected life is strictly longer than medium, which is longer than soft
        assert hard_analysis.expected_life_laps > medium_analysis.expected_life_laps > soft_analysis.expected_life_laps

    def test_uncalibrated_track_fallback(self, tyre_model):
        """Unknown or fictional tracks gracefully fall back to base defaults."""
        custom_track = Track(
            track_id=999, name="Fictional Ring", country_id=99, laps=50,
            track_length=5.0, type_of_track=TrackType.HIGH_SPEED,
            fastest_lap=85.0, safety_car_chance=0.3, pit_lane_time_loss=20,
            green_flag_time_loss=18, safety_car_time_loss=14, sprint_laps=15,
        )
        assert tyre_model.is_track_calibrated(custom_track) is False

        analysis = tyre_model.analyze_compound(TyreCompound.SOFT, custom_track)
        assert analysis.expected_life_laps > 0
        assert analysis.pace_delta_vs_medium_ms == -800  # Default fallback

    def test_fastf1_availability_flag(self):
        """is_fastf1_available returns a boolean without throwing an unhandled exception."""
        status = is_fastf1_available()
        assert isinstance(status, bool)
