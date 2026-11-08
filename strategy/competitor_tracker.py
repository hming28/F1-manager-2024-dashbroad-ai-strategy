"""
competitor_tracker.py — Real-time competitor strategy tracking.

Tracks every competitor's:
- Pit stop history (when, what compound, how long)
- Gap trend (closing or opening)
- Undercut/overcut threat detection
- Strategy pattern recognition

When a competitor pits, immediately evaluates the impact on your strategy.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from core.models import CarRaceState, RaceSnapshot, TyreCompound


@dataclass
class PitStopEvent:
    """Record of a single pit stop."""
    car_index: int
    lap: int
    timestamp: float
    duration_sec: float       # time spent in pits
    new_compound: str         # estimated compound (S/M/H/I/W)
    position_before: int
    position_after: int


@dataclass
class GapTrend:
    """Gap trend to a specific car over recent laps."""
    car_index: int
    driver_name: str
    current_gap_ms: int
    gap_3_laps_ago_ms: int
    gap_delta_ms: int         # negative = closing in
    trend: str                # "CLOSING" / "STABLE" / "OPENING"
    closing_rate_ms_per_lap: float


@dataclass
class UndercutThreat:
    """Detected undercut/overcut threat or opportunity."""
    threat_type: str          # "THEY_UNDERCUT_US" / "WE_CAN_UNDERCUT" / "THEY_OVERCUT" / "WE_CAN_OVERCUT"
    target_car_index: int
    target_driver: str
    target_position: int
    gap_ms: int
    their_action: str         # what they did
    our_response: str         # what we should do
    urgency: str              # "NOW" / "SOON" / "WATCH"
    estimated_gain_ms: int


@dataclass
class CompetitorState:
    """Full state tracking for one competitor."""
    car_index: int
    driver_name: str
    team_id: int
    
    # Current state
    position: int = 0
    gap_to_us_ms: int = 0
    tyre_condition: float = 0.0
    ers_charge: float = 0.0
    pit_stops: int = 0
    has_damage: bool = False
    
    # History
    pit_history: list[PitStopEvent] = field(default_factory=list)
    gap_history: list[int] = field(default_factory=list)  # last N gaps
    position_history: list[int] = field(default_factory=list)
    
    # Alerts
    last_pit_lap: int = 0
    last_alert_lap: int = 0


class CompetitorTracker:
    """
    Tracks all competitors and detects strategic events.
    
    Usage:
        tracker = CompetitorTracker(my_team_id=3)
        events = tracker.update(snapshot)
        for event in events:
            print(event)
    """
    
    # Driver name mapping (car_index -> name)
    DRIVER_NAMES = {
        0: "HAM", 1: "LEC", 2: "NOR", 3: "PIA", 4: "VER", 5: "PER",
        6: "RUS", 7: "SAI", 8: "ALO", 9: "STR", 10: "GAS", 11: "OCO",
        12: "ALB", 13: "SAR", 14: "TSU", 15: "RIC", 16: "BOT", 17: "ZHO",
        18: "MAG", 19: "HUL",
    }
    
    def __init__(self, my_team_id: int, history_depth: int = 10):
        self.my_team_id = my_team_id
        self.history_depth = history_depth
        
        # State tracking
        self._competitors: dict[int, CompetitorState] = {}
        self._my_cars: dict[int, CompetitorState] = {}
        self._last_snapshot: Optional[RaceSnapshot] = None
        self._events: list[str] = []
    
    def update(self, snapshot: RaceSnapshot) -> list[str]:
        """
        Update tracking with new snapshot. Returns list of event messages.
        """
        self._events = []
        current_lap = snapshot.current_lap
        
        # Get my cars
        my_cars = snapshot.get_my_cars(self.my_team_id)
        my_car = min(my_cars, key=lambda c: c.race_position) if my_cars else None
        if not my_car:
            return self._events
        
        # Update all cars
        for car in snapshot.cars:
            name = self.DRIVER_NAMES.get(car.car_index, f"#{car.car_index}")
            is_mine = car.team_id == self.my_team_id
            
            # Get or create state
            if is_mine:
                state = self._my_cars.setdefault(car.car_index, CompetitorState(
                    car_index=car.car_index, driver_name=name, team_id=car.team_id,
                ))
            else:
                state = self._competitors.setdefault(car.car_index, CompetitorState(
                    car_index=car.car_index, driver_name=name, team_id=car.team_id,
                ))
            
            # Calculate gap to my car
            gap_ms = int((car.total_race_time - my_car.total_race_time) * 1000)
            
            # ── Detect pit stops ────────────────────────────────────────
            if car.pit_stops_had > state.pit_stops and state.pit_stops > 0:
                # This car just pitted!
                self._on_competitor_pit(car, state, snapshot, my_car)
            
            # ── Track gap trend ─────────────────────────────────────────
            state.gap_history.append(gap_ms)
            if len(state.gap_history) > self.history_depth:
                state.gap_history = state.gap_history[-self.history_depth:]
            
            # ── Detect gap changes ──────────────────────────────────────
            if len(state.gap_history) >= 3:
                old_gap = state.gap_history[-3]
                new_gap = state.gap_history[-1]
                delta = new_gap - old_gap  # negative = closing
                
                if not is_mine and abs(delta) > 500:  # >0.5s change in 3 laps
                    if delta < -1000:
                        self._events.append(
                            f"⚡ {name} closing in FAST! Gap: {gap_ms/1000:+.1f}s "
                            f"(was {old_gap/1000:+.1f}s 3 laps ago, delta {delta/1000:+.1f}s)"
                        )
                    elif delta > 1000:
                        self._events.append(
                            f"📈 {name} falling back. Gap: {gap_ms/1000:+.1f}s "
                            f"(delta {delta/1000:+.1f}s)"
                        )
            
            # ── Update state ────────────────────────────────────────────
            state.position = car.race_position
            state.gap_to_us_ms = gap_ms
            state.tyre_condition = car.avg_tyre_condition
            state.ers_charge = car.ers_battery_charge
            state.pit_stops = car.pit_stops_had
            state.has_damage = car.has_damage
            state.position_history.append(car.race_position)
            if len(state.position_history) > self.history_depth:
                state.position_history = state.position_history[-self.history_depth:]
        
        # ── Detect undercut/overcut threats ─────────────────────────────
        self._detect_undercut_threats(snapshot, my_car)
        
        self._last_snapshot = snapshot
        return self._events
    
    def _on_competitor_pit(self, car: CarRaceState, state: CompetitorState,
                           snapshot: RaceSnapshot, my_car: CarRaceState):
        """Handle a competitor's pit stop."""
        name = state.driver_name
        lap = snapshot.current_lap
        
        # Estimate pit duration (from game data or default)
        duration = 2.5  # default estimate
        
        # Estimate compound (from tyre condition after pit)
        compound = "M"  # default
        if car.avg_tyre_condition > 0.95:
            compound = "S"  # fresh softs likely
        
        # Record the pit stop
        event = PitStopEvent(
            car_index=car.car_index,
            lap=lap,
            timestamp=time.time(),
            duration_sec=duration,
            new_compound=compound,
            position_before=state.position,
            position_after=car.race_position,
        )
        state.pit_history.append(event)
        state.last_pit_lap = lap
        
        # Evaluate impact on us
        gap_before = state.gap_to_us_ms
        gap_after = int((car.total_race_time - my_car.total_race_time) * 1000)
        
        position_change = car.race_position - state.position
        
        # Alert based on proximity
        if abs(gap_before) < 5000:  # within 5 seconds
            if car.race_position > my_car.race_position:
                # They were behind us — they're trying to undercut!
                self._events.append(
                    f"🚨 [{lap}] {name} PITTED for {compound}s! "
                    f"They were {abs(gap_before)/1000:.1f}s behind — UNDERCUT THREAT! "
                    f"Consider pitting next lap to cover."
                )
            elif car.race_position < my_car.race_position:
                # They were ahead — overcut opportunity
                self._events.append(
                    f"💡 [{lap}] {name} pitted for {compound}s from P{state.position}. "
                    f"Gap was {gap_before/1000:+.1f}s. "
                    f"Stay out to overcut if tyres allow."
                )
        elif abs(gap_before) < 15000:  # within 15 seconds
            self._events.append(
                f"ℹ️ [{lap}] {name} pitted for {compound}s (gap {gap_before/1000:+.1f}s)"
            )
        
        # Check if they jumped us
        if position_change < 0 and car.race_position < my_car.race_position:
            self._events.append(
                f"⚠️ {name} jumped us! Now P{car.race_position} (was P{state.position})"
            )
    
    def _detect_undercut_threats(self, snapshot: RaceSnapshot, my_car: CarRaceState):
        """Detect undercut/overcut situations."""
        my_pos = my_car.race_position
        lap = snapshot.current_lap
        
        # Check car directly ahead
        ahead = [c for c in snapshot.cars if c.race_position == my_pos - 1]
        behind = [c for c in snapshot.cars if c.race_position == my_pos + 1]
        
        if ahead:
            car_ahead = ahead[0]
            state = self._competitors.get(car_ahead.car_index)
            if state:
                gap = state.gap_to_us_ms
                
                # They just pitted and we didn't — undercut threat
                if (state.last_pit_lap == lap - 1 or state.last_pit_lap == lap):
                    if gap < 3000 and state.tyre_condition > 0.90:
                        self._events.append(
                            f"🚨 [{lap}] {state.driver_name} just pitted (undercut!). "
                            f"Gap: {gap/1000:.1f}s. New tyres will be fast. "
                            f"Consider pitting NOW to respond."
                        )
                
                # Their tyres are much worse — we can undercut
                if (state.tyre_condition < my_car.avg_tyre_condition - 0.15 
                    and gap < 5000 and gap > 0):
                    self._events.append(
                        f"⚡ [{lap}] {state.driver_name}'s tyres worn ({state.tyre_condition:.0%} vs your {my_car.avg_tyre_condition:.0%}). "
                        f"Gap: {gap/1000:.1f}s. Pit 1-2 laps before them for undercut!"
                    )
        
        if behind:
            car_behind = behind[0]
            state = self._competitors.get(car_behind.car_index)
            if state:
                gap = state.gap_to_us_ms
                
                # They're closing in with better tyres — undercut threat
                if (len(state.gap_history) >= 3 
                    and state.gap_history[-1] < state.gap_history[-3] - 500
                    and state.tyre_condition > my_car.avg_tyre_condition + 0.10):
                    self._events.append(
                        f"⚠️ [{lap}] {state.driver_name} closing in ({gap/1000:.1f}s) "
                        f"with better tyres ({state.tyre_condition:.0%}). "
                        f"Undercut threat! Consider pitting before them."
                    )
    
    def get_competitors_by_gap(self) -> list[CompetitorState]:
        """Get competitors sorted by gap (closest first)."""
        return sorted(
            self._competitors.values(),
            key=lambda c: abs(c.gap_to_us_ms)
        )
    
    def get_recent_pits(self, last_n_laps: int = 5, 
                        current_lap: int = 0) -> list[tuple[CompetitorState, PitStopEvent]]:
        """Get competitors who pitted in the last N laps."""
        results = []
        for state in self._competitors.values():
            for event in state.pit_history:
                if current_lap - event.lap <= last_n_laps:
                    results.append((state, event))
        return results
    
    def get_strategy_summary(self) -> str:
        """Get a summary of competitor strategies."""
        lines = []
        for state in sorted(self._competitors.values(), key=lambda c: c.position):
            pit_info = f"{state.pit_stops} stops"
            if state.pit_history:
                last_pit = state.pit_history[-1]
                pit_info += f" (last: L{last_pit.lap} {last_pit.new_compound})"
            
            tyre_info = f"{state.tyre_condition:.0%}"
            
            lines.append(
                f"P{state.position:2d} {state.driver_name:4s} | "
                f"Tyres {tyre_info} | {pit_info} | "
                f"Gap {state.gap_to_us_ms/1000:+.1f}s"
            )
        
        return "\n".join(lines)
