"""
models.py — Domain models for F1 Manager 2024 data.

Every dataclass maps to one or more SQLite tables in the game's save file.
Field names match the database columns for zero-ambiguity mapping.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


# ── Enums ────────────────────────────────────────────────────────────────────

class TyreCompound(IntEnum):
    """
    Standardized domain enum for F1 Tyre Compounds.
    
    0 = SOFT   (Red, 'S')
    1 = MEDIUM (Yellow, 'M')
    2 = HARD   (White, 'H')
    3 = INTER  (Green, 'I')
    4 = WET    (Blue, 'W')
    """
    SOFT = 0
    MEDIUM = 1
    HARD = 2
    INTER = 3
    WET = 4

    @property
    def color(self) -> str:
        return {
            self.SOFT: "red",
            self.MEDIUM: "yellow",
            self.HARD: "white",
            self.INTER: "green",
            self.WET: "blue",
        }.get(self, "white")

    @property
    def short(self) -> str:
        return {
            self.SOFT: "S",
            self.MEDIUM: "M",
            self.HARD: "H",
            self.INTER: "I",
            self.WET: "W",
        }.get(self, "?")


class WeatherState(IntEnum):
    """Maps to Save_WeatherHistory.WeatherState"""
    CLEAR = 0
    OVERCAST = 1
    LIGHT_RAIN = 2
    HEAVY_RAIN = 3


class SafetyCarState(IntEnum):
    """Maps to Save_RaceSimManager.SafetyCarState"""
    NONE = 0
    DEPLOYED = 1
    VSC = 2


class TrackType(IntEnum):
    """Maps to Races_Enum_TrackType"""
    STREET = 0
    HIGH_SPEED = 1
    BALANCED = 2


class ErsStrategy(IntEnum):
    """Maps to Save_RaceSimCars_Strategy.ErsStrategy"""
    NONE = 0
    HARVEST = 1
    NEUTRAL = 2
    DEPLOY = 3
    HOTLAP = 4


class OvertakeStrategy(IntEnum):
    """Maps to Save_RaceSimCars_Strategy.OvertakeStrategy"""
    DEFEND = 0
    BALANCED = 1
    ATTACK = 2


class DamageLevel(IntEnum):
    """Maps to Parts_Enum_DamageStates"""
    NONE = 0
    LIGHT = 1
    MEDIUM = 2
    HEAVY = 3


class SectorState(IntEnum):
    """Maps to ESectorState enum in F1 Manager 2024."""
    OPEN = 0                      # In progress
    COMPLETE = 1                  # Yellow / standard completed
    SESSION_BEST = 2              # Purple / overall fastest
    PERSONAL_BEST = 3             # Green / personal fastest
    OUT_FROM_PIT = 4
    RACE_START = 5
    STOPPED_ON_TRACK = 6
    INTO_PIT = 7
    SAME_AS_PERSONAL_BEST = 8

    @property
    def color(self) -> str:
        """Rich style color string for F1 broadcast timing tower."""
        if self == SectorState.SESSION_BEST:
            return "bold magenta"
        elif self in (SectorState.PERSONAL_BEST, SectorState.SAME_AS_PERSONAL_BEST):
            return "bold green"
        elif self == SectorState.COMPLETE:
            return "yellow"
        elif self in (SectorState.STOPPED_ON_TRACK, SectorState.INTO_PIT):
            return "bold red"
        return "dim white"


# ── Static Reference Data ───────────────────────────────────────────────────

@dataclass(frozen=True)
class Track:
    """Maps to Races_Tracks"""
    track_id: int
    name: str
    country_id: int
    laps: int
    track_length: float          # km
    type_of_track: TrackType
    fastest_lap: float           # seconds
    safety_car_chance: float     # 0.0-1.0
    pit_lane_time_loss: int      # seconds
    green_flag_time_loss: int    # seconds
    safety_car_time_loss: int    # seconds
    sprint_laps: int


@dataclass(frozen=True)
class TeamPerformance:
    """Maps to Races_TeamPerformance — per-track performance ratings"""
    season_id: int
    team_id: int
    track_id: int
    straights: float
    slow_corners: float
    medium_corners: float
    fast_corners: float


@dataclass(frozen=True)
class DriverData:
    """Maps to Staff_DriverData + Staff base tables"""
    staff_id: int
    first_name: str
    last_name: str
    abbreviation: str
    aggression: int              # 0-100
    improvability: int           # 0-100
    marketability: int           # 0-100
    team_id: int
    car_number: int
    overall_rating: int          # 0-100


@dataclass(frozen=True)
class CarStats:
    """Maps to Parts_Designs_StatValues — aggregated car performance"""
    team_id: int
    top_speed: float
    acceleration: float
    braking: float
    cornering: float
    air_flow_front: float
    air_flow_tolerance: float
    tyre_preservation: float


# ── Race Weekend State ───────────────────────────────────────────────────────

@dataclass
class TyreSetState:
    """Maps to Save_CarTyreAllocation — one tyre set for one car"""
    car_id: int
    tyre_set_id: int
    weekend_tyre_type: TyreCompound
    front_left_wear: float       # 0.0 (new) to 1.0 (destroyed)
    front_right_wear: float
    back_left_wear: float
    back_right_wear: float
    estimated_lap_time: float
    estimated_lap_life: int      # remaining laps
    laps_completed: int

    @property
    def avg_wear(self) -> float:
        return (self.front_left_wear + self.front_right_wear +
                self.back_left_wear + self.back_right_wear) / 4.0

    @property
    def max_wear(self) -> float:
        return max(self.front_left_wear, self.front_right_wear,
                   self.back_left_wear, self.back_right_wear)

    @property
    def is_critical(self) -> bool:
        return self.max_wear > 0.80


@dataclass
class CarRaceState:
    """Maps to Save_RaceSimCars + Save_RaceSimCars_Parts + Save_RaceSimCars_Misc"""
    car_index: int
    driver_id: int
    team_id: int

    # Position & timing
    race_position: int
    total_race_time: float
    last_lap_time_ms: int = 0
    best_lap_time_ms: int = 0
    gap_to_leader_ms: int = 0

    # Fuel & engine
    fuel: float = 0.0            # kg remaining
    engine_temp: float = 0.0
    brake_temp: float = 0.0

    # Tyre state (current set)
    current_tyre_id: int = 0
    tyre1_condition: float = 0.0
    tyre2_condition: float = 0.0
    tyre3_condition: float = 0.0
    tyre4_condition: float = 0.0
    tyre1_surface_temp: float = 0.0
    tyre2_surface_temp: float = 0.0
    tyre3_surface_temp: float = 0.0
    tyre4_surface_temp: float = 0.0

    # Damage
    body_damage: DamageLevel = DamageLevel.NONE
    front_wing_damage: DamageLevel = DamageLevel.NONE
    rear_wing_damage: DamageLevel = DamageLevel.NONE
    sidepods_damage: DamageLevel = DamageLevel.NONE
    floor_damage: DamageLevel = DamageLevel.NONE
    suspension_damage: DamageLevel = DamageLevel.NONE

    # ERS
    ers_battery_charge: float = 0.0    # 0.0-1.0
    ers_deploy_amount: float = 0.0
    ers_charge_amount: float = 0.0

    # DRS
    drs_active: bool = False

    # Safety car
    waiting_for_sc: bool = False
    sc_restart_lap: int = 0

    # Strategy settings
    tyre_wear_strategy: int = 1
    ers_strategy: ErsStrategy = ErsStrategy.NEUTRAL
    overtake_strategy: OvertakeStrategy = OvertakeStrategy.BALANCED
    defence_strategy: int = 1
    avoid_dirty_air: bool = False
    avoid_kerbs: bool = False

    # Pit stop
    pit_stop_state: int = 0      # 0 = on track, >0 = in pit
    pit_stops_had: int = 0
    new_tyre_set_id: int = 0

    # Overtake
    overtake_active: bool = False
    defender_car: int = -1

    # Laps
    lap_count: int = 0

    # Live timing tower fields (from UE4SS or LapHistoryAccumulator)
    driver_name: str = ""
    driver_code: str = ""
    driver_number: int = 0
    team_name: str = ""

    current_lap_time: float = 0.0      # Current lap running time in seconds
    last_lap_time: float = 0.0         # Last completed lap time in seconds
    best_lap_time: float = 0.0         # Personal best lap time in seconds
    lap_progress: float = 0.0          # 0.0 to 1.0
    gap_to_leader: float = 0.0         # Seconds to leader
    gap_to_ahead: float = 0.0          # Seconds to car ahead (Interval)

    # Sector tracking
    s1_time: float = 0.0               # Sector 1 time (seconds)
    s1_state: SectorState = SectorState.OPEN
    s2_time: float = 0.0               # Sector 2 time (seconds)
    s2_state: SectorState = SectorState.OPEN
    s3_time: float = 0.0               # Sector 3 time (seconds)
    s3_state: SectorState = SectorState.OPEN

    # Live telemetry
    speed_kph: int = 0
    gear: int = 0
    tyre_compound: TyreCompound = TyreCompound.SOFT
    tyre_wear_pct: int = 0
    is_in_pit_lane: bool = False

    @property
    def avg_tyre_condition(self) -> float:
        return (self.tyre1_condition + self.tyre2_condition +
                self.tyre3_condition + self.tyre4_condition) / 4.0

    @property
    def avg_tyre_temp(self) -> float:
        return (self.tyre1_surface_temp + self.tyre2_surface_temp +
                self.tyre3_surface_temp + self.tyre4_surface_temp) / 4.0

    @property
    def has_damage(self) -> bool:
        return any(d > DamageLevel.NONE for d in [
            self.body_damage, self.front_wing_damage, self.rear_wing_damage,
            self.sidepods_damage, self.floor_damage, self.suspension_damage
        ])

    @property
    def damage_severity(self) -> int:
        """Sum of all damage levels (0-18 scale)"""
        return sum(d.value for d in [
            self.body_damage, self.front_wing_damage, self.rear_wing_damage,
            self.sidepods_damage, self.floor_damage, self.suspension_damage
        ])

    @property
    def is_in_pit(self) -> bool:
        return self.pit_stop_state > 0


@dataclass
class WeatherState_Data:
    """Maps to Save_WeatherHistory"""
    time: int
    rain: float                  # 0.0-1.0
    water_on_track: float        # 0.0-1.0
    ambient_temp: float          # celsius
    track_temp: float            # celsius
    weather_state: WeatherState
    time_until_track_dry: float
    rubber_on_track: float       # 0.0-1.0 (grip evolution)

    @property
    def is_raining(self) -> bool:
        return self.rain > 0.1

    @property
    def needs_wets(self) -> bool:
        return self.water_on_track > 0.5

    @property
    def needs_inters(self) -> bool:
        return 0.15 < self.water_on_track <= 0.5


@dataclass
class RaceSimManager:
    """Maps to Save_RaceSimManager"""
    sim_time: float
    safety_car_state: SafetyCarState
    race_event_flags: int


@dataclass
class LapRecord:
    """Maps to Save_TimingManager_Laps"""
    car_index: int
    lap: int
    lap_time_ms: int
    race_time: float


@dataclass
class CompletedLapRecord:
    """Historical record for one completed lap of one car from live timing."""
    car_index: int
    lap_number: int
    lap_time: float               # Seconds
    s1_time: float                # Seconds
    s2_time: float                # Seconds
    s3_time: float                # Seconds
    driver_code: str = ""
    s1_state: SectorState = SectorState.COMPLETE
    s2_state: SectorState = SectorState.COMPLETE
    s3_state: SectorState = SectorState.COMPLETE
    tyre_compound: TyreCompound = TyreCompound.SOFT
    tyre_wear_pct: int = 0
    is_personal_best: bool = False
    is_session_best: bool = False


@dataclass
class StrategyStint:
    """Maps to Save_PlayerStrategyStints"""
    loadout_id: int
    strategy_id: int
    stint_id: int
    tyre_durability: float
    tyre_type: TyreCompound
    tyre_set_id: int
    pit_window_start: int
    optimal_pit_lap: int
    pit_window_end: int
    stint_tyre_strategy: int
    stint_start_tyre_wear: float
    is_current: bool


@dataclass
class PitStopRecord:
    """Maps to Save_RaceSimCars_PitStop"""
    car_index: int
    pit_stop_state: int
    pit_stop_start_time: float
    pit_stop_end_time: float
    new_tyre_set_id: int
    pit_stops_had: int
    previous_pit_stop_lap: int
    mistake_stage: int
    mistake_severity: int


# ── Aggregated Race Snapshot ─────────────────────────────────────────────────

@dataclass
class RaceSnapshot:
    """
    Complete snapshot of a race at a point in time.
    Assembled from multiple Save_* tables by db_accessor.
    """
    # Metadata
    track: Optional[Track] = None
    current_lap: int = 0
    total_laps: int = 0

    # Race manager
    race_manager: Optional[RaceSimManager] = None

    # Weather
    weather: Optional[WeatherState_Data] = None

    # All cars on track (index 0-19)
    cars: list[CarRaceState] = field(default_factory=list)

    # Lap history (recent)
    recent_laps: list[LapRecord] = field(default_factory=list)

    # Strategy stints (player)
    player_strategy: list[StrategyStint] = field(default_factory=list)

    # Pit stop records
    pit_stops: list[PitStopRecord] = field(default_factory=list)

    # Computed fields
    safety_car_laps_remaining: int = 0

    # Live timing fields
    live_lap_history: dict[int, list[CompletedLapRecord]] = field(default_factory=dict)
    fastest_lap_time: float = 0.0
    fastest_lap_driver: str = ""
    fastest_lap_car_index: int = -1
    session_best_s1: float = 0.0
    session_best_s2: float = 0.0
    session_best_s3: float = 0.0
    is_live_timing: bool = False
    is_live_paused: bool = False

    def get_car(self, car_index: int) -> Optional[CarRaceState]:
        for car in self.cars:
            if car.car_index == car_index:
                return car
        return None

    def get_my_cars(self, team_id: int) -> list[CarRaceState]:
        return [c for c in self.cars if c.team_id == team_id]

    def get_position_board(self) -> list[CarRaceState]:
        return sorted(self.cars, key=lambda c: c.race_position)

    def get_cars_on_tyres(self, compound: TyreCompound) -> list[CarRaceState]:
        """Cars likely on a given compound (heuristic from tyre condition patterns)"""
        # This is approximate — exact compound tracking needs tyre set lookup
        return [c for c in self.cars if c.avg_tyre_condition > 0]  # placeholder

    @property
    def is_safety_car(self) -> bool:
        return (self.race_manager is not None and
                self.race_manager.safety_car_state != SafetyCarState.NONE)

    @property
    def is_vsc(self) -> bool:
        return (self.race_manager is not None and
                self.race_manager.safety_car_state == SafetyCarState.VSC)

    @property
    def race_progress(self) -> float:
        """0.0 to 1.0"""
        if self.total_laps == 0:
            return 0.0
        return min(1.0, self.current_lap / self.total_laps)
