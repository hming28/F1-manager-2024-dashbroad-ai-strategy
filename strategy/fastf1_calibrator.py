"""
fastf1_calibrator.py — Real-world F1 telemetry calibration using FastF1.

Extracts official FIA timing and telemetry data to calibrate:
- Circuit baseline lap times
- Tyre degradation slopes per compound (Soft, Medium, Hard)
- Theoretical compound pace deltas
- Overtaking and safety car characteristics
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Default path to the calibrated tracks database
DEFAULT_CALIBRATION_FILE = Path(__file__).resolve().parent.parent / "data" / "calibrated_tracks.json"
DEFAULT_CACHE_DIR = Path.home() / ".fastf1_cache"


def is_fastf1_available() -> bool:
    """Check if the fastf1 package is installed and importable."""
    try:
        import fastf1  # noqa: F401
        return True
    except ImportError:
        return False


@dataclass
class TrackCalibrationProfile:
    """Calibrated parameters for a circuit."""
    track_id: int
    name: str
    country: str
    laps: int
    track_length_km: float
    base_lap_time_ms: int
    compound_deg_rate: Dict[str, float]
    compound_pace_delta_ms: Dict[str, int]
    deg_lap_time_penalty_ms_per_lap: Dict[str, int]
    pit_lane_loss_sec: float
    sc_probability: float
    overtaking_difficulty: float
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class FastF1Calibrator:
    """
    Manages loading, querying, and updating calibrated track parameters
    derived from FastF1 telemetry.
    """

    def __init__(self, calibration_path: Optional[Union[str, Path]] = None,
                 cache_dir: Optional[Union[str, Path]] = None):
        self.calibration_path = Path(calibration_path or DEFAULT_CALIBRATION_FILE)
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
        self._database: Optional[Dict[str, Any]] = None

    def get_database(self) -> Dict[str, Any]:
        """Load and return the calibrated tracks database."""
        if self._database is None:
            if not self.calibration_path.exists():
                logger.warning("Calibration file not found at %s, initializing empty.", self.calibration_path)
                self._database = {"version": "1.0.0", "season": 2024, "tracks": {}}
            else:
                with open(self.calibration_path, "r", encoding="utf-8") as f:
                    self._database = json.load(f)
        return self._database

    def find_track(self, query: Union[str, int]) -> Optional[Dict[str, Any]]:
        """
        Lookup track calibration by track name, alias, or track_id.
        """
        db = self.get_database()
        tracks = db.get("tracks", {})

        if isinstance(query, int):
            for key, data in tracks.items():
                if data.get("track_id") == query:
                    return data
            return None

        # String search: exact key, then lowercase name or country substring
        q = str(query).strip().lower()
        if q in tracks:
            return tracks[q]

        for key, data in tracks.items():
            name = data.get("name", "").lower()
            country = data.get("country", "").lower()
            if q == name or q == country or q in key or q in name:
                return data

        return None

    def list_tracks(self) -> List[Tuple[str, str, int, float]]:
        """Return list of (key, name, base_lap_time_ms, sc_prob)."""
        db = self.get_database()
        tracks = db.get("tracks", {})
        results = []
        for key, data in sorted(tracks.items(), key=lambda x: x[1].get("track_id", 999)):
            results.append((
                key,
                data.get("name", key),
                data.get("base_lap_time_ms", 0),
                data.get("sc_probability", 0.0),
            ))
        return results

    def save_database(self) -> None:
        """Write current database back to JSON file."""
        if self._database is None:
            return
        self.calibration_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.calibration_path, "w", encoding="utf-8") as f:
            json.dump(self._database, f, indent=2, ensure_ascii=False)
        logger.info("Saved calibration database to %s", self.calibration_path)

    def calibrate_session(self, year: int, grand_prix: str,
                          session_type: str = "R") -> TrackCalibrationProfile:
        """
        Calibrate track parameters using official FastF1 session data.
        Requires fastf1 package to be installed.
        """
        if not is_fastf1_available():
            raise RuntimeError(
                "FastF1 is not installed. Run 'pip install fastf1' to enable dynamic calibration."
            )

        import fastf1
        import numpy as np
        import pandas as pd

        # Enable local file caching for FastF1
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        fastf1.Cache.enable_cache(str(self.cache_dir))

        logger.info("Loading FastF1 session: %d %s [%s]", year, grand_prix, session_type)
        session = fastf1.get_session(year, grand_prix, session_type)
        session.load(telemetry=False, weather=True)

        laps = session.laps
        if laps.empty:
            raise ValueError(f"No lap data found for {year} {grand_prix} [{session_type}]")

        # 1. Filter clean, dry racing laps
        # Exclude in/out laps, unverified laps, safety car laps (TrackStatus != '1')
        clean_laps = laps[
            (laps["IsAccurate"] == True) &
            (laps["TrackStatus"] == "1") &
            (laps["PitInTime"].isna()) &
            (laps["PitOutTime"].isna()) &
            (laps["LapNumber"] > 1) &
            (laps["LapTime"].notna())
        ].copy()

        if clean_laps.empty:
            logger.warning("No clean green flag laps found; relaxing TrackStatus requirement.")
            clean_laps = laps[
                (laps["PitInTime"].isna()) &
                (laps["PitOutTime"].isna()) &
                (laps["LapNumber"] > 1) &
                (laps["LapTime"].notna())
            ].copy()

        clean_laps["LapTimeSec"] = clean_laps["LapTime"].dt.total_seconds()

        # Remove extreme lap time outliers (> 108% of median)
        median_lap = clean_laps["LapTimeSec"].median()
        clean_laps = clean_laps[clean_laps["LapTimeSec"] < median_lap * 1.08]

        # 2. Compute compound statistics
        compound_deg: Dict[str, float] = {}
        compound_penalty: Dict[str, int] = {}
        compound_median_pace: Dict[str, float] = {}

        # Fuel burn correction factor: roughly -0.035 sec / lap as fuel burns off
        fuel_correction_per_lap = 0.035

        for compound in ["SOFT", "MEDIUM", "HARD"]:
            cLaps = clean_laps[clean_laps["Compound"].str.upper() == compound]
            if len(cLaps) < 8:
                # Fallback to default proportions if compound was rarely used
                continue

            compound_median_pace[compound] = float(cLaps["LapTimeSec"].median())

            # Stint-level degradation slope: LapTimeSec vs TyreLife
            stint_slopes = []
            for (driver, stint_num), stint_df in cLaps.groupby(["Driver", "Stint"]):
                if len(stint_df) >= 6:
                    x = stint_df["TyreLife"].values
                    # Correct for fuel consumption to get true tyre degradation
                    y = stint_df["LapTimeSec"].values + (stint_df["LapNumber"].values * fuel_correction_per_lap)
                    if len(x) > 1 and np.std(x) > 0.5:
                        slope, _ = np.polyfit(x, y, 1)
                        if 0.01 <= slope <= 0.40:  # reasonable degradation bound
                            stint_slopes.append(slope)

            if stint_slopes:
                avg_slope = float(np.median(stint_slopes))
            else:
                avg_slope = 0.08  # Default reasonable slope

            penalty_ms = int(round(avg_slope * 1000))
            compound_penalty[compound] = penalty_ms

            # Normalize to wear fraction (assuming cliff around 1.5s pace drop)
            # Higher slope = faster wear rate
            wear_rate = round(avg_slope / 3.2, 4)
            compound_deg[compound] = max(0.010, min(wear_rate, 0.055))

        # Fill in defaults if any compound wasn't run
        if "MEDIUM" not in compound_deg:
            compound_deg["MEDIUM"] = 0.022
            compound_penalty["MEDIUM"] = 75
        if "SOFT" not in compound_deg:
            compound_deg["SOFT"] = round(compound_deg["MEDIUM"] * 1.55, 3)
            compound_penalty["SOFT"] = int(compound_penalty["MEDIUM"] * 1.5)
        if "HARD" not in compound_deg:
            compound_deg["HARD"] = round(compound_deg["MEDIUM"] * 0.65, 3)
            compound_penalty["HARD"] = int(compound_penalty["MEDIUM"] * 0.6)

        # Baseline pace delta vs Medium
        med_pace = compound_median_pace.get("MEDIUM", median_lap)
        compound_deltas: Dict[str, int] = {}
        for c in ["SOFT", "MEDIUM", "HARD"]:
            if c in compound_median_pace:
                compound_deltas[c] = int(round((compound_median_pace[c] - med_pace) * 1000))
            else:
                defaults = {"SOFT": -750, "MEDIUM": 0, "HARD": 620}
                compound_deltas[c] = defaults[c]

        # Base race lap time in ms
        base_lap_time_ms = int(round(med_pace * 1000))

        # Check existing metadata if track exists in db
        existing = self.find_track(grand_prix) or {}

        profile = TrackCalibrationProfile(
            track_id=existing.get("track_id", 1),
            name=existing.get("name", grand_prix),
            country=existing.get("country", grand_prix),
            laps=existing.get("laps", int(session.total_laps or 55)),
            track_length_km=existing.get("track_length_km", 5.2),
            base_lap_time_ms=base_lap_time_ms,
            compound_deg_rate=compound_deg,
            compound_pace_delta_ms=compound_deltas,
            deg_lap_time_penalty_ms_per_lap=compound_penalty,
            pit_lane_loss_sec=existing.get("pit_lane_loss_sec", 21.0),
            sc_probability=existing.get("sc_probability", 0.60),
            overtaking_difficulty=existing.get("overtaking_difficulty", 0.50),
            source=f"FastF1 {year} {grand_prix} GP Telemetry",
        )
        return profile

    def update_track(self, key: str, profile: TrackCalibrationProfile) -> None:
        """Update or insert calibrated profile into database and save."""
        db = self.get_database()
        db.setdefault("tracks", {})[key] = profile.to_dict()
        self.save_database()


def main():
    parser = argparse.ArgumentParser(description="FastF1 Track Calibration Tool")
    parser.add_argument("--list", action="store_true", help="List all calibrated tracks")
    parser.add_argument("--status", action="store_true", help="Check FastF1 installation and cache")
    parser.add_argument("--track", type=str, help="Look up a track in the calibration database")
    parser.add_argument("--gp", type=str, help="Grand Prix name to calibrate (e.g. 'Bahrain')")
    parser.add_argument("--year", type=int, default=2024, help="Season year (default: 2024)")
    parser.add_argument("--session", type=str, default="R", help="Session type ('R' or 'FP2')")
    parser.add_argument("--save", action="store_true", help="Save calibrated results to data/calibrated_tracks.json")

    args = parser.parse_args()
    calibrator = FastF1Calibrator()

    if args.status:
        avail = is_fastf1_available()
        print(f"FastF1 Installed: {'YES' if avail else 'NO'}")
        print(f"Calibration File: {calibrator.calibration_path} (Exists: {calibrator.calibration_path.exists()})")
        print(f"Cache Directory:  {calibrator.cache_dir}")
        return

    if args.list:
        tracks = calibrator.list_tracks()
        print(f"Calibrated Tracks ({len(tracks)} entries):")
        print(f"{'Key':<15} {'Name':<22} {'Base Lap (s)':<14} {'SC Chance':<10}")
        print("-" * 65)
        for key, name, base_ms, sc_chance in tracks:
            print(f"{key:<15} {name:<22} {base_ms/1000:<14.3f} {sc_chance:<10.0%}")
        return

    if args.track:
        data = calibrator.find_track(args.track)
        if data:
            print(json.dumps(data, indent=2))
        else:
            print(f"Track '{args.track}' not found in calibration database.")
        return

    if args.gp:
        print(f"Running FastF1 calibration for {args.year} {args.gp} [{args.session}]...")
        try:
            profile = calibrator.calibrate_session(args.year, args.gp, args.session)
            print(json.dumps(profile.to_dict(), indent=2))
            if args.save:
                key = args.gp.lower().replace(" ", "_")
                calibrator.update_track(key, profile)
                print(f"Successfully saved calibration to {calibrator.calibration_path}")
        except Exception as e:
            print(f"Calibration failed: {e}", file=sys.stderr)
            sys.exit(1)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
