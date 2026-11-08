"""
demo.py — Simulation demo for F1 Manager 2024 Strategy AI.

Simulates a 57-lap Bahrain race with realistic events:
- Tyre degradation
- Weather changes (rain at lap 35-45)
- Safety car (lap 22)
- Undercut/overcut situations
- Damage incidents

Shows exactly what the player would see in their terminal during a race.

Usage:
    python demo.py              # full demo
    python demo.py --fast       # 2x speed
    python demo.py --events     # only show event laps
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from typing import Optional

from rich.console import Console

from core.models import (
    RaceSnapshot, RaceSimManager, CarRaceState, WeatherState_Data,
    Track, TrackType, WeatherState, SafetyCarState, DamageLevel,
    ErsStrategy, OvertakeStrategy,
)
from display.compact import CompactDisplay, print_full_standings
from display.notifications import (
    NotificationManager, Notification, Priority,
    make_tyre_warning, make_weather_alert, make_safety_car_alert,
    make_pit_window, make_undercut_alert, make_ers_alert, make_damage_alert,
)

console = Console()


# ── Simulation data ──────────────────────────────────────────────────────────

BAHRAIN = Track(
    track_id=2, name="Bahrain", country_id=12, laps=57,
    track_length=5.412, type_of_track=TrackType.BALANCED,
    fastest_lap=91.447, safety_car_chance=0.75,
    pit_lane_time_loss=22, green_flag_time_loss=20,
    safety_car_time_loss=16, sprint_laps=19,
)

# Driver names for display
DRIVER_NAMES = [
    "HAM", "LEC", "NOR", "PIA", "VER", "PER",
    "RUS", "SAI", "ALO", "STR", "GAS", "OCO",
    "ALB", "SAR", "TSU", "RIC", "BOT", "ZHO",
    "MAG", "HUL"
]

# Team IDs (2 drivers per team)
TEAM_MAP = {
    0: 3, 1: 2, 2: 4, 3: 4, 4: 1, 5: 1,
    6: 3, 7: 2, 8: 5, 9: 5, 10: 6, 11: 6,
    12: 7, 13: 7, 14: 8, 15: 8, 16: 9, 17: 9,
    18: 10, 19: 10,
}

MY_TEAM = 3  # McLaren (NOR=2, PIA=3)
MY_CARS = [2, 3]  # car indices


def build_simulated_snapshot(lap: int, total_laps: int,
                              safety_car_lap: int = -1,
                              rain_start_lap: int = -1,
                              rain_end_lap: int = -1) -> RaceSnapshot:
    """Build a realistic simulated race snapshot."""
    
    random.seed(42 + lap)  # reproducible but varied
    
    # Weather
    if rain_start_lap <= lap <= rain_end_lap:
        progress = (lap - rain_start_lap) / max(1, rain_end_lap - rain_start_lap)
        if progress < 0.3:
            rain = 0.1 + progress * 0.8
            water = progress * 0.4
            w_state = WeatherState.LIGHT_RAIN
        elif progress < 0.7:
            rain = 0.4 + random.uniform(-0.1, 0.2)
            water = 0.3 + random.uniform(0, 0.2)
            w_state = WeatherState.HEAVY_RAIN
        else:
            rain = max(0, 0.5 - (progress - 0.7) * 1.5)
            water = max(0.05, 0.5 - (progress - 0.7) * 1.0)
            w_state = WeatherState.LIGHT_RAIN
        ambient = 22.0
        track_temp = 28.0
    else:
        rain = 0.0
        water = 0.0
        w_state = WeatherState.CLEAR
        ambient = 32.0 + random.uniform(-2, 2)
        track_temp = 42.0 + random.uniform(-3, 3)
    
    weather = WeatherState_Data(
        time=lap * 90, rain=rain, water_on_track=water,
        ambient_temp=ambient, track_temp=track_temp,
        weather_state=w_state, time_until_track_dry=0,
        rubber_on_track=min(1.0, lap * 0.015),
    )
    
    # Safety car
    sc_active = safety_car_lap <= lap <= safety_car_lap + 3
    sc_state = SafetyCarState.DEPLOYED if sc_active else SafetyCarState.NONE
    
    manager = RaceSimManager(
        sim_time=lap * 90.0,
        safety_car_state=sc_state,
        race_event_flags=0,
    )
    
    # Build cars
    cars = []
    for i in range(20):
        team_id = TEAM_MAP[i]
        is_my = i in MY_CARS
        
        # Base position (with some variation)
        base_pos = i + 1
        if lap > 5:
            # Positions shift over time
            shift = int(random.gauss(0, 1.5))
            base_pos = max(1, min(20, base_pos + shift))
        
        # Tyre condition (degrades over laps)
        stint_lap = lap % 25  # approximate stint position
        base_tyre = max(0.15, 1.0 - stint_lap * 0.025 + random.uniform(-0.05, 0.05))
        
        # ERS
        ers = 0.3 + random.uniform(0, 0.6)
        
        # Total time (position-based)
        base_time = 1800.0 + (base_pos - 1) * 2.2 + random.uniform(-0.5, 0.5)
        
        # Pit stops
        stops = 0 if lap < 15 else (1 if lap < 35 else 2)
        if i == 4 or i == 5:  # VER/PER — aggressive strategy
            stops = min(stops + 1, 2)
        
        car = CarRaceState(
            car_index=i, driver_id=i+1, team_id=team_id,
            race_position=base_pos,
            total_race_time=base_time,
            fuel=100.0 - lap * 1.5 + random.uniform(-2, 2),
            current_tyre_id=1,
            tyre1_condition=base_tyre + random.uniform(-0.03, 0.03),
            tyre2_condition=base_tyre + random.uniform(-0.03, 0.03),
            tyre3_condition=base_tyre + random.uniform(-0.03, 0.03),
            tyre4_condition=base_tyre + random.uniform(-0.03, 0.03),
            tyre1_surface_temp=85.0 + random.uniform(-5, 15),
            tyre2_surface_temp=85.0 + random.uniform(-5, 15),
            tyre3_surface_temp=85.0 + random.uniform(-5, 15),
            tyre4_surface_temp=85.0 + random.uniform(-5, 15),
            ers_battery_charge=ers,
            pit_stops_had=stops,
            lap_count=lap,
        )
        
        # Damage for some cars
        if i == 12 and lap > 20:  # ALB has damage
            car.front_wing_damage = DamageLevel.MEDIUM
            car.floor_damage = DamageLevel.LIGHT
        
        cars.append(car)
    
    # Fix positions to be unique
    cars.sort(key=lambda c: c.total_race_time)
    for idx, car in enumerate(cars):
        car.race_position = idx + 1
    
    return RaceSnapshot(
        track=BAHRAIN, current_lap=lap, total_laps=total_laps,
        race_manager=manager, weather=weather, cars=cars,
    )


# ── Strategy analysis (simplified for demo) ─────────────────────────────────

def analyze_and_notify(snapshot: RaceSnapshot, nm: NotificationManager,
                       prev_tyre: dict[int, float]):
    """Analyze snapshot and push notifications."""
    my_cars = snapshot.get_my_cars(MY_TEAM)
    if not my_cars:
        return
    
    car = min(my_cars, key=lambda c: c.race_position)
    lap = snapshot.current_lap
    cond = car.avg_tyre_condition
    prev_cond = prev_tyre.get(car.car_index, cond)
    prev_tyre[car.car_index] = cond
    
    # ── Tyre warnings ────────────────────────────────────────────────────
    # Only notify on significant drops or thresholds
    if cond < 0.20 and prev_cond >= 0.20:
        n = make_tyre_warning(lap, cond, 2)
        if n: nm.push(n)
    elif cond < 0.35 and prev_cond >= 0.35:
        n = make_tyre_warning(lap, cond, 8)
        if n: nm.push(n)
    elif cond < 0.50 and prev_cond >= 0.50:
        n = make_tyre_warning(lap, cond, 15)
        if n: nm.push(n)
    
    # ── Weather ──────────────────────────────────────────────────────────
    if snapshot.weather:
        w = snapshot.weather
        if w.rain > 0.50 and prev_cond > 0.5:  # only alert once
            n = make_weather_alert(lap, w.rain, w.water_on_track, "WET")
            if n: nm.push(n)
        elif w.rain > 0.15:
            n = make_weather_alert(lap, w.rain, w.water_on_track, "INTER")
            if n: nm.push(n)
    
    # ── Safety car ───────────────────────────────────────────────────────
    if snapshot.is_safety_car:
        n = make_safety_car_alert(lap, 8.5, should_pit=True)
        if n: nm.push(n)
    
    # ── Pit window ───────────────────────────────────────────────────────
    if lap in (28, 29, 30) and cond > 0.30:
        n = make_pit_window(lap, 30, "M", 2500)
        if n: nm.push(n)
    
    # ── Undercut ─────────────────────────────────────────────────────────
    if lap == 26:
        ahead = [c for c in snapshot.cars if c.race_position == car.race_position - 1]
        if ahead:
            gap = (car.total_race_time - ahead[0].total_race_time)
            n = make_undercut_alert(lap, ahead[0].race_position, gap, 28)
            if n: nm.push(n)
    
    # ── ERS ──────────────────────────────────────────────────────────────
    n = make_ers_alert(lap, car.ers_battery_charge)
    if n: nm.push(n)
    
    # ── Damage ───────────────────────────────────────────────────────────
    if car.has_damage and car.damage_severity > 5:
        n = make_damage_alert(lap, car.damage_severity, "Front wing, Floor")
        if n: nm.push(n)


def get_extra_info(snapshot: RaceSnapshot) -> str:
    """Get short extra info for compact display."""
    my_cars = snapshot.get_my_cars(MY_TEAM)
    if not my_cars:
        return ""
    car = min(my_cars, key=lambda c: c.race_position)
    
    hints = []
    if car.avg_tyre_condition < 0.40:
        hints.append("⚠️ Pit soon")
    if snapshot.is_safety_car:
        hints.append("🟡 SC → BOX?")
    if car.ers_battery_charge > 0.90:
        hints.append("⚡ERS full")
    return " | ".join(hints) if hints else ""


# ── Main demo ────────────────────────────────────────────────────────────────

def run_demo(fast: bool = False, events_only: bool = False):
    """
    Run the full race simulation demo.
    """
    console.print()
    console.print("[bold cyan]╔══════════════════════════════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║    🏎️  F1 Manager 2024 — AI Strategy Engine  DEMO  🏎️        ║[/bold cyan]")
    console.print("[bold cyan]║    Bahrain GP | 57 laps | Team: McLaren (Papaya)           ║[/bold cyan]")
    console.print("[bold cyan]╚══════════════════════════════════════════════════════════════╝[/bold cyan]")
    console.print()
    console.print("[dim]Simulating race... Watch the strategy AI in action.[/dim]")
    console.print("[dim]Key events: Safety Car @ L22 | Rain @ L35-45 | Pit window @ L28-30[/dim]")
    console.print()
    
    delay = 0.15 if fast else 0.4
    
    # Initialize
    compact = CompactDisplay(my_team_id=MY_TEAM, console=console)
    nm = NotificationManager(console=console, suppress_below=Priority.WARNING, 
                             enable_sound=False)
    prev_tyre: dict[int, float] = {}
    
    # Print header
    compact.print_header("Bahrain International Circuit", 57, MY_TEAM)
    
    # Run simulation
    for lap in range(1, 58):
        snapshot = build_simulated_snapshot(
            lap, 57,
            safety_car_lap=22,
            rain_start_lap=35,
            rain_end_lap=45,
        )
        
        # Analyze and push notifications
        analyze_and_notify(snapshot, nm, prev_tyre)
        
        # Get extra info for compact line
        extra = get_extra_info(snapshot)
        
        # Decide whether to show this lap
        has_notifications = len(nm._pending) > 0
        show_lap = not events_only or has_notifications or lap in (1, 22, 23, 35, 36, 45, 57)
        
        if show_lap:
            # Print compact status
            compact.update(snapshot, extra_info=extra)
            
            # Flush notifications (if any)
            nm.flush()
            
            time.sleep(delay)
        else:
            # Still update internal state
            nm.flush()  # clear any pending (they were below threshold)
            time.sleep(delay * 0.3)
    
    # ── End of race ──────────────────────────────────────────────────────
    console.print()
    console.print("[bold]🏁 RACE COMPLETE[/bold]")
    console.print()
    
    # Show final standings
    final_snapshot = build_simulated_snapshot(57, 57)
    print_full_standings(final_snapshot, MY_TEAM, console)
    
    # Show notification stats
    stats = nm.get_stats()
    console.print()
    console.print(f"[dim]Notifications sent: {stats['total']} total[/dim]")
    for prio, count in stats.get('by_priority', {}).items():
        console.print(f"[dim]  {prio}: {count}[/dim]")
    
    console.print()
    console.print("[dim cyan]─" * 60 + "[/dim cyan]")
    console.print("[bold]💡 What you just saw:[/bold]")
    console.print("  • [green]Compact one-line status[/green] — glance at any time")
    console.print("  • [yellow]Smart notifications[/yellow] — only shown when action needed")
    console.print("  • [red]Priority system[/red] — CRITICAL > URGENT > WARNING > NOTICE")
    console.print("  • [cyan]Deduplication[/cyan] — same alert won't repeat for 30 seconds")
    console.print()
    console.print("[bold]In real gameplay, you'd also hear:[/bold]")
    console.print("  • 🔔 Beep for WARNING (tyres/weather)")
    console.print("  • 🔔🔔 Double beep for URGENT (pit window)")
    console.print("  • 🔔🔔🔔 Triple beep for CRITICAL (safety car / rain)")
    console.print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="F1 Strategy AI Demo")
    parser.add_argument("--fast", action="store_true", help="2x speed")
    parser.add_argument("--events", action="store_true", help="Only show event laps")
    args = parser.parse_args()
    run_demo(fast=args.fast, events_only=args.events)
