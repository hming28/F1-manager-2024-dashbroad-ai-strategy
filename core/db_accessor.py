"""
db_accessor.py — Database access layer for F1 Manager 2024.

Provides typed query functions for all game data. Every function takes a
sqlite3.Connection and returns domain model instances from models.py.

This is the ONLY module that touches raw SQL — all other modules use these APIs.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Optional

from core.models import (
    CarRaceState, CarStats, DamageLevel, DriverData, ErsStrategy,
    LapRecord, OvertakeStrategy, PitStopRecord, RaceSnapshot,
    RaceSimManager, SafetyCarState, StrategyStint, TeamPerformance,
    Track, TrackType, TyreCompound, TyreSetState, WeatherState,
    WeatherState_Data,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER
# ═══════════════════════════════════════════════════════════════════════════════

def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def _safe_int(val, default=0) -> int:
    return int(val) if val is not None else default


def _safe_float(val, default=0.0) -> float:
    return float(val) if val is not None else default


def _safe_enum(enum_cls, val, default=None):
    if val is None:
        return default if default is not None else list(enum_cls)[0]
    try:
        return enum_cls(int(val))
    except (ValueError, KeyError):
        return default if default is not None else list(enum_cls)[0]


# ═══════════════════════════════════════════════════════════════════════════════
# TABLE EXISTENCE CHECK
# ═══════════════════════════════════════════════════════════════════════════════

def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Check if a table exists and has rows."""
    try:
        result = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        ).fetchone()
        return result is not None
    except Exception:
        return False


def table_has_rows(conn: sqlite3.Connection, table: str) -> bool:
    """Check if a table exists and contains data."""
    if not table_exists(conn, table):
        return False
    try:
        count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        return count > 0
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# STATIC REFERENCE DATA (always populated)
# ═══════════════════════════════════════════════════════════════════════════════

def get_tracks(conn: sqlite3.Connection) -> list[Track]:
    """Get all tracks from Races_Tracks."""
    rows = conn.execute("SELECT * FROM Races_Tracks").fetchall()
    tracks = []
    for r in rows:
        tracks.append(Track(
            track_id=r["TrackID"],
            name=r["Name"],
            country_id=r["CountryID"],
            laps=r["Laps"],
            track_length=_safe_float(r["TrackLength"]),
            type_of_track=_safe_enum(TrackType, r["TypeOfTrack"]),
            fastest_lap=_safe_float(r["FastestLap"]),
            safety_car_chance=_safe_float(r["SafetyCarChance"]),
            pit_lane_time_loss=_safe_int(r["PitLaneTimeLoss"]),
            green_flag_time_loss=_safe_int(r["GreenFlagTimeLoss"]),
            safety_car_time_loss=_safe_int(r["SafetyCarTimeLoss"]),
            sprint_laps=_safe_int(r["SprintLaps"], 20),
        ))
    return tracks


def get_track_by_id(conn: sqlite3.Connection, track_id: int) -> Optional[Track]:
    """Get a specific track by ID."""
    for t in get_tracks(conn):
        if t.track_id == track_id:
            return t
    return None


def get_team_performance(conn: sqlite3.Connection, season_id: int) -> list[TeamPerformance]:
    """Get all team performance data for a season."""
    rows = conn.execute(
        "SELECT * FROM Races_TeamPerformance WHERE SeasonID=?",
        (season_id,)
    ).fetchall()
    results = []
    for r in rows:
        results.append(TeamPerformance(
            season_id=r["SeasonID"],
            team_id=r["TeamID"],
            track_id=r["TrackID"],
            straights=_safe_float(r["Straights"]),
            slow_corners=_safe_float(r["SlowCorners"]),
            medium_corners=_safe_float(r["MediumCorners"]),
            fast_corners=_safe_float(r["FastCorners"]),
        ))
    return results


def get_driver_data(conn: sqlite3.Connection) -> list[DriverData]:
    """
    Get all driver data. Joins Staff_DriverData with staff base info.
    """
    # Try to get driver names from Staff_BasicData or similar
    try:
        rows = conn.execute("""
            SELECT d.StaffID, d.Aggression, d.Improvability, d.Marketability,
                   d.AssignedCarNumber, d.DriverCode
            FROM Staff_DriverData d
            ORDER BY d.StaffID
        """).fetchall()
    except Exception as e:
        logger.warning(f"Cannot read driver data: {e}")
        return []

    drivers = []
    for r in rows:
        staff_id = r["StaffID"]
        
        # Try to get name from Staff_BasicData
        first_name = ""
        last_name = ""
        abbreviation = r["DriverCode"] or ""
        team_id = 0
        overall = 50
        
        try:
            basic = conn.execute(
                "SELECT FirstName, LastName, TeamID FROM Staff_BasicData WHERE StaffID=?",
                (staff_id,)
            ).fetchone()
            if basic:
                first_name = basic["FirstName"] or ""
                last_name = basic["LastName"] or ""
                team_id = _safe_int(basic["TeamID"])
        except Exception:
            pass
        
        # Try performance stats
        try:
            perf = conn.execute(
                "SELECT OverallRating FROM Staff_PerformanceStats WHERE StaffID=?",
                (staff_id,)
            ).fetchone()
            if perf:
                overall = _safe_int(perf["OverallRating"], 50)
        except Exception:
            pass

        drivers.append(DriverData(
            staff_id=staff_id,
            first_name=first_name,
            last_name=last_name,
            abbreviation=abbreviation.replace("[DriverCode_", "").replace("]", ""),
            aggression=_safe_int(r["Aggression"], 50),
            improvability=_safe_int(r["Improvability"], 50),
            marketability=_safe_int(r["Marketability"], 50),
            team_id=team_id,
            car_number=_safe_int(r["AssignedCarNumber"]),
            overall_rating=overall,
        ))
    return drivers


def get_car_stats(conn: sqlite3.Connection, team_id: int) -> Optional[CarStats]:
    """
    Get aggregated car performance stats for a team.
    Reads from Parts_Designs_StatValues + Parts_Designs_TeamData.
    """
    try:
        # Get current car design IDs for this team
        rows = conn.execute("""
            SELECT pd.DesignID, pd.PartStat, pd.UnitValue
            FROM Parts_Designs_StatValues pd
            JOIN Parts_Designs_TeamData ptd ON pd.DesignID = ptd.DesignID
            WHERE ptd.TeamID = ?
        """, (team_id,)).fetchall()
    except Exception:
        return None

    stat_map = {}
    for r in rows:
        stat_map[r["PartStat"]] = _safe_float(r["UnitValue"])

    return CarStats(
        team_id=team_id,
        top_speed=stat_map.get(0, 50.0),       # Parts_Enum_CarStats: 0=TopSpeed
        acceleration=stat_map.get(1, 50.0),     # 1=Acceleration
        braking=stat_map.get(2, 50.0),          # 2=Braking
        cornering=stat_map.get(3, 50.0),        # 3=Cornering
        air_flow_front=stat_map.get(4, 50.0),   # 4=AirFlowFront (approx)
        air_flow_tolerance=stat_map.get(5, 50.0),
        tyre_preservation=stat_map.get(6, 50.0),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# REAL-TIME RACE DATA (populated during races)
# ═══════════════════════════════════════════════════════════════════════════════

def get_race_sim_manager(conn: sqlite3.Connection) -> Optional[RaceSimManager]:
    """Get current race simulation manager state."""
    if not table_has_rows(conn, "Save_RaceSimManager"):
        return None
    r = conn.execute("SELECT * FROM Save_RaceSimManager LIMIT 1").fetchone()
    if r is None:
        return None
    return RaceSimManager(
        sim_time=_safe_float(r["SimTime"]),
        safety_car_state=_safe_enum(SafetyCarState, r["SafetyCarState"], SafetyCarState.NONE),
        race_event_flags=_safe_int(r["RaceEventFlags"]),
    )


def get_weather(conn: sqlite3.Connection) -> Optional[WeatherState_Data]:
    """Get current/latest weather state."""
    if not table_has_rows(conn, "Save_WeatherHistory"):
        return None
    # Get the most recent weather entry
    r = conn.execute(
        "SELECT * FROM Save_WeatherHistory ORDER BY Time DESC LIMIT 1"
    ).fetchone()
    if r is None:
        return None
    return WeatherState_Data(
        time=_safe_int(r["Time"]),
        rain=_safe_float(r["Rain"]),
        water_on_track=_safe_float(r["WaterOnTrack"]),
        ambient_temp=_safe_float(r["AmbientTemperature"]),
        track_temp=_safe_float(r["TrackTemperature"]),
        weather_state=_safe_enum(WeatherState, r["WeatherState"]),
        time_until_track_dry=_safe_float(r["TimeUntilTrackDry"]),
        rubber_on_track=_safe_float(r["RubberOnTrack"]),
    )


def get_weather_forecast(conn: sqlite3.Connection, limit: int = 10) -> list[WeatherState_Data]:
    """Get recent weather history for trend analysis."""
    if not table_has_rows(conn, "Save_WeatherHistory"):
        return []
    rows = conn.execute(
        "SELECT * FROM Save_WeatherHistory ORDER BY Time DESC LIMIT ?",
        (limit,)
    ).fetchall()
    return [WeatherState_Data(
        time=_safe_int(r["Time"]),
        rain=_safe_float(r["Rain"]),
        water_on_track=_safe_float(r["WaterOnTrack"]),
        ambient_temp=_safe_float(r["AmbientTemperature"]),
        track_temp=_safe_float(r["TrackTemperature"]),
        weather_state=_safe_enum(WeatherState, r["WeatherState"]),
        time_until_track_dry=_safe_float(r["TimeUntilTrackDry"]),
        rubber_on_track=_safe_float(r["RubberOnTrack"]),
    ) for r in rows]


def get_car_race_states(conn: sqlite3.Connection) -> list[CarRaceState]:
    """
    Get the race state for ALL 20 cars.
    Joins Save_RaceSimCars + Save_RaceSimCars_Parts + Save_RaceSimCars_Misc + Save_RaceSimCars_Strategy.
    """
    if not table_has_rows(conn, "Save_RaceSimCars"):
        return []

    cars = []
    rows = conn.execute("SELECT * FROM Save_RaceSimCars").fetchall()

    for r in rows:
        car_idx = r["CarIndex"]

        # Determine driver_id and team_id from CarIndex
        # CarIndex maps to Cars table or similar
        driver_id = 0
        team_id = 0
        try:
            car_info = conn.execute(
                "SELECT DriverID, TeamID FROM Cars WHERE CarIndex=?",
                (car_idx,)
            ).fetchone()
            if car_info:
                driver_id = _safe_int(car_info["DriverID"])
                team_id = _safe_int(car_info["TeamID"])
        except Exception:
            # Fallback: try to derive from driver assignment tables
            try:
                car_info = conn.execute(
                    "SELECT StaffID FROM Staff_DriverData WHERE AssignedCarNumber=?",
                    (car_idx + 1,)
                ).fetchone()
                if car_info:
                    driver_id = _safe_int(car_info["StaffID"])
            except Exception:
                pass

        # Base car state
        car = CarRaceState(
            car_index=car_idx,
            driver_id=driver_id,
            team_id=team_id,
            race_position=_safe_int(r["RacePosition"]),
            total_race_time=_safe_float(r["TotalRaceTime"]),
            fuel=_safe_float(r["Fuel"]),
            engine_temp=_safe_float(r["EngineTemperature"]),
            brake_temp=_safe_float(r["BrakeTemperature"]),
            current_tyre_id=_safe_int(r["CurrentActiveTyreID"]),
            drs_active=_safe_int(r["DRSState"]) > 0,
            waiting_for_sc=_safe_bool(r["WaitingForSafetyCarToPit"]),
            sc_restart_lap=_safe_int(r["SafetyCarRestartLap"]),
            lap_count=_safe_int(r["LapCountAtRaceEnd"]),
        )

        # Parts data (tyre + damage)
        if table_has_rows(conn, "Save_RaceSimCars_Parts"):
            try:
                parts = conn.execute(
                    "SELECT * FROM Save_RaceSimCars_Parts WHERE CarIndex=?",
                    (car_idx,)
                ).fetchone()
                if parts:
                    car.tyre1_condition = _safe_float(parts["Tyre1Condition"])
                    car.tyre2_condition = _safe_float(parts["Tyre2Condition"])
                    car.tyre3_condition = _safe_float(parts["Tyre3Condition"])
                    car.tyre4_condition = _safe_float(parts["Tyre4Condition"])
                    car.tyre1_surface_temp = _safe_float(parts["Tyre1SurfaceTemperature"])
                    car.tyre2_surface_temp = _safe_float(parts["Tyre2SurfaceTemperature"])
                    car.tyre3_surface_temp = _safe_float(parts["Tyre3SurfaceTemperature"])
                    car.tyre4_surface_temp = _safe_float(parts["Tyre4SurfaceTemperature"])
                    car.body_damage = _safe_enum(DamageLevel, parts["BodyDamageLevel"])
                    car.front_wing_damage = _safe_enum(DamageLevel, parts["FrontWingDamageLevel"])
                    car.rear_wing_damage = _safe_enum(DamageLevel, parts["RearWingDamageLevel"])
                    car.sidepods_damage = _safe_enum(DamageLevel, parts["SidePodsDamageLevel"])
                    car.floor_damage = _safe_enum(DamageLevel, parts["FloorDamageLevel"])
                    car.suspension_damage = _safe_enum(DamageLevel, parts["SuspensionDamageLevel"])
            except Exception as e:
                logger.debug(f"Parts data not available for car {car_idx}: {e}")

        # Misc data (ERS)
        if table_has_rows(conn, "Save_RaceSimCars_Misc"):
            try:
                misc = conn.execute(
                    "SELECT * FROM Save_RaceSimCars_Misc WHERE CarIndex=?",
                    (car_idx,)
                ).fetchone()
                if misc:
                    car.ers_battery_charge = _safe_float(misc["ErsBatteryCharge"])
                    car.ers_deploy_amount = _safe_float(misc["ErsDeployAmountCurrentLap"])
                    car.ers_charge_amount = _safe_float(misc["ErsChargeAmountCurrentLap"])
            except Exception as e:
                logger.debug(f"Misc data not available for car {car_idx}: {e}")

        # Strategy data
        if table_has_rows(conn, "Save_RaceSimCars_Strategy"):
            try:
                strat = conn.execute(
                    "SELECT * FROM Save_RaceSimCars_Strategy WHERE CarIndex=?",
                    (car_idx,)
                ).fetchone()
                if strat:
                    car.tyre_wear_strategy = _safe_int(strat["TyreWearStrategy"])
                    car.ers_strategy = _safe_enum(ErsStrategy, strat["ErsStrategy"], ErsStrategy.NEUTRAL)
                    car.overtake_strategy = _safe_enum(OvertakeStrategy, strat["OvertakeStrategy"], OvertakeStrategy.BALANCED)
                    car.defence_strategy = _safe_int(strat["DefenceStrategy"])
                    car.avoid_dirty_air = _safe_bool(strat["AvoidDirtyAir"])
                    car.avoid_kerbs = _safe_bool(strat["AvoidKerbs"])
            except Exception as e:
                logger.debug(f"Strategy data not available for car {car_idx}: {e}")

        # Pit stop data
        if table_has_rows(conn, "Save_RaceSimCars_PitStop"):
            try:
                pit = conn.execute(
                    "SELECT * FROM Save_RaceSimCars_PitStop WHERE CarIndex=?",
                    (car_idx,)
                ).fetchone()
                if pit:
                    car.pit_stop_state = _safe_int(pit["PitStopState"])
                    car.pit_stops_had = _safe_int(pit["PitStopsHadNum"])
                    car.new_tyre_set_id = _safe_int(pit["NewTyreSetID"])
            except Exception as e:
                logger.debug(f"PitStop data not available for car {car_idx}: {e}")

        # Overtake data
        if table_has_rows(conn, "Save_RaceSimCars_Overtake"):
            try:
                ot = conn.execute(
                    "SELECT * FROM Save_RaceSimCars_Overtake WHERE CarIndex=?",
                    (car_idx,)
                ).fetchone()
                if ot:
                    car.overtake_active = _safe_bool(ot["OvertakeActive"])
                    car.defender_car = _safe_int(ot["DefenderCar"], -1)
            except Exception as e:
                logger.debug(f"Overtake data not available for car {car_idx}: {e}")

        cars.append(car)

    return cars


def get_lap_times(conn: sqlite3.Connection, limit: int = 100) -> list[LapRecord]:
    """Get recent lap times for all cars."""
    if not table_has_rows(conn, "Save_TimingManager_Laps"):
        return []
    rows = conn.execute(
        "SELECT * FROM Save_TimingManager_Laps ORDER BY Lap DESC, CarIndex LIMIT ?",
        (limit,)
    ).fetchall()
    return [LapRecord(
        car_index=r["CarIndex"],
        lap=r["Lap"],
        lap_time_ms=r["LapTimeMS"],
        race_time=_safe_float(r["RaceTime"]),
    ) for r in rows]


def get_lap_times_for_car(conn: sqlite3.Connection, car_index: int) -> list[LapRecord]:
    """Get all lap times for a specific car."""
    if not table_has_rows(conn, "Save_TimingManager_Laps"):
        return []
    rows = conn.execute(
        "SELECT * FROM Save_TimingManager_Laps WHERE CarIndex=? ORDER BY Lap",
        (car_index,)
    ).fetchall()
    return [LapRecord(
        car_index=r["CarIndex"],
        lap=r["Lap"],
        lap_time_ms=r["LapTimeMS"],
        race_time=_safe_float(r["RaceTime"]),
    ) for r in rows]


def get_tyre_allocations(conn: sqlite3.Connection) -> list[TyreSetState]:
    """Get tyre set allocations for all cars."""
    if not table_has_rows(conn, "Save_CarTyreAllocation"):
        return []
    rows = conn.execute("SELECT * FROM Save_CarTyreAllocation").fetchall()
    return [TyreSetState(
        car_id=r["CarID"],
        tyre_set_id=r["TyreSetID"],
        weekend_tyre_type=_safe_enum(TyreCompound, r["WeekendTyreType"]),
        front_left_wear=_safe_float(r["FrontLeftWear"]),
        front_right_wear=_safe_float(r["FrontRightWear"]),
        back_left_wear=_safe_float(r["BackLeftWear"]),
        back_right_wear=_safe_float(r["BackRightWear"]),
        estimated_lap_time=_safe_float(r["EstimatedLapTime"]),
        estimated_lap_life=_safe_int(r["EstimatedLapLifeRemaining"]),
        laps_completed=_safe_int(r["LapsCompleted"]),
    ) for r in rows]


def get_tyre_allocations_for_car(conn: sqlite3.Connection, car_id: int) -> list[TyreSetState]:
    """Get all tyre sets for a specific car."""
    if not table_has_rows(conn, "Save_CarTyreAllocation"):
        return []
    rows = conn.execute(
        "SELECT * FROM Save_CarTyreAllocation WHERE CarID=?",
        (car_id,)
    ).fetchall()
    return [TyreSetState(
        car_id=r["CarID"],
        tyre_set_id=r["TyreSetID"],
        weekend_tyre_type=_safe_enum(TyreCompound, r["WeekendTyreType"]),
        front_left_wear=_safe_float(r["FrontLeftWear"]),
        front_right_wear=_safe_float(r["FrontRightWear"]),
        back_left_wear=_safe_float(r["BackLeftWear"]),
        back_right_wear=_safe_float(r["BackRightWear"]),
        estimated_lap_time=_safe_float(r["EstimatedLapTime"]),
        estimated_lap_life=_safe_int(r["EstimatedLapLifeRemaining"]),
        laps_completed=_safe_int(r["LapsCompleted"]),
    ) for r in rows]


def get_player_strategy(conn: sqlite3.Connection) -> list[StrategyStint]:
    """Get the player's current race strategy."""
    if not table_has_rows(conn, "Save_PlayerStrategyStints"):
        return []
    rows = conn.execute("SELECT * FROM Save_PlayerStrategyStints").fetchall()
    return [StrategyStint(
        loadout_id=r["LoadoutID"],
        strategy_id=r["StrategyID"],
        stint_id=r["StintID"],
        tyre_durability=_safe_float(r["TyreDurability"]),
        tyre_type=_safe_enum(TyreCompound, r["TyreType"]),
        tyre_set_id=_safe_int(r["TyreSetID"]),
        pit_window_start=_safe_int(r["PitWindowStart"]),
        optimal_pit_lap=_safe_int(r["OptimalPitLap"]),
        pit_window_end=_safe_int(r["PitWindowEnd"]),
        stint_tyre_strategy=_safe_int(r["StintTyreStrategy"]),
        stint_start_tyre_wear=_safe_float(r["StintStartTyreWear"]),
        is_current=_safe_bool(r["CurrentStint"]),
    ) for r in rows]


def get_pit_stop_records(conn: sqlite3.Connection) -> list[PitStopRecord]:
    """Get pit stop records for all cars."""
    if not table_has_rows(conn, "Save_RaceSimCars_PitStop"):
        return []
    rows = conn.execute("SELECT * FROM Save_RaceSimCars_PitStop").fetchall()
    return [PitStopRecord(
        car_index=r["CarIndex"],
        pit_stop_state=_safe_int(r["PitStopState"]),
        pit_stop_start_time=_safe_float(r["PitStopStartTime"]),
        pit_stop_end_time=_safe_float(r["PitStopReleaseEndTime"]),
        new_tyre_set_id=_safe_int(r["NewTyreSetID"]),
        pit_stops_had=_safe_int(r["PitStopsHadNum"]),
        previous_pit_stop_lap=_safe_int(r["PreviousPitStopLap"]),
        mistake_stage=_safe_int(r["MistakeStage"]),
        mistake_severity=_safe_int(r["MistakeSeverity"]),
    ) for r in rows]


def get_safety_car_summary(conn: sqlite3.Connection) -> dict:
    """Get safety car deployment summary."""
    if not table_has_rows(conn, "Save_SafetyCarDeploymentsSummary"):
        return {"safety_cars": 0, "vscs": 0}
    r = conn.execute("SELECT * FROM Save_SafetyCarDeploymentsSummary LIMIT 1").fetchone()
    if r is None:
        return {"safety_cars": 0, "vscs": 0}
    return {
        "safety_cars": _safe_int(r["SafetyCarDeployments"]),
        "vscs": _safe_int(r["VirtualSafetyCarDeployments"]),
    }


def get_driver_commands(conn: sqlite3.Connection) -> dict:
    """Get current driver command settings."""
    if not table_has_rows(conn, "Save_DriverCommands"):
        return {}
    rows = conn.execute("SELECT * FROM Save_DriverCommands").fetchall()
    commands = {}
    for r in rows:
        commands[r["LoadoutID"]] = {
            "lift_and_coast": _safe_int(r["LiftAndCoastStrategy"], -1),
            "race_pace": _safe_int(r["RacePaceStrategy"], -1),
            "ers": _safe_int(r["ERSStrategy"], -1),
            "fast_lap_count": _safe_int(r["FastLapCount"], -1),
        }
    return commands


# ═══════════════════════════════════════════════════════════════════════════════
# AI STRATEGY DATA (pre-race planning)
# ═══════════════════════════════════════════════════════════════════════════════

def get_ai_strategies(conn: sqlite3.Connection, track_id: int, season_id: int) -> list[dict]:
    """Get AI strategy templates for a specific track and season."""
    if not table_has_rows(conn, "Races_Strategies"):
        return []
    rows = conn.execute(
        "SELECT * FROM Races_Strategies WHERE TrackID=? AND SeasonID=?",
        (track_id, season_id)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_driver_standings(conn: sqlite3.Connection, season_id: int) -> list[dict]:
    """Get driver championship standings."""
    if not table_has_rows(conn, "Races_DriverStandings"):
        return []
    rows = conn.execute(
        "SELECT * FROM Races_DriverStandings WHERE SeasonID=? ORDER BY Position",
        (season_id,)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_team_standings(conn: sqlite3.Connection, season_id: int) -> list[dict]:
    """Get constructor championship standings."""
    if not table_has_rows(conn, "Races_TeamStandings"):
        return []
    rows = conn.execute(
        "SELECT * FROM Races_TeamStandings WHERE SeasonID=? ORDER BY Position",
        (season_id,)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_race_results_history(conn: sqlite3.Connection, driver_id: int) -> list[dict]:
    """Get historical race results for a driver."""
    if not table_has_rows(conn, "Races_Results"):
        return []
    rows = conn.execute(
        "SELECT * FROM Races_Results WHERE DriverID=? ORDER BY Season, RaceID",
        (driver_id,)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# SNAPSHOT BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def build_race_snapshot(conn: sqlite3.Connection) -> RaceSnapshot:
    """
    Build a complete RaceSnapshot from the current database state.
    This is the main entry point for getting all race data at once.
    """
    snapshot = RaceSnapshot()

    # Race manager
    snapshot.race_manager = get_race_sim_manager(conn)

    # Weather
    snapshot.weather = get_weather(conn)

    # Cars
    snapshot.cars = get_car_race_states(conn)

    # Determine current lap from cars
    if snapshot.cars:
        snapshot.current_lap = max(c.lap_count for c in snapshot.cars)

    # Lap times (recent)
    snapshot.recent_laps = get_lap_times(conn, limit=60)

    # Player strategy
    snapshot.player_strategy = get_player_strategy(conn)

    # Pit stops
    snapshot.pit_stops = get_pit_stop_records(conn)

    return snapshot


# ── Utility ──────────────────────────────────────────────────────────────────

def _safe_bool(val) -> bool:
    if val is None:
        return False
    return bool(int(val))


def format_lap_time(ms: int) -> str:
    """Format milliseconds as M:SS.mmm"""
    if ms <= 0:
        return "--:--.---"
    total_seconds = ms / 1000.0
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:06.3f}"


def format_gap(gap_ms: int) -> str:
    """Format gap in milliseconds as +S.mmm or +M:SS.mmm"""
    if gap_ms <= 0:
        return "LEADER"
    if gap_ms < 60000:
        return f"+{gap_ms / 1000:.3f}s"
    minutes = gap_ms // 60000
    seconds = (gap_ms % 60000) / 1000.0
    return f"+{minutes}:{seconds:06.3f}"
