"""
compact.py — Compact one-line status display for F1 Manager 2024.

Shows a single line per lap update — always visible, never distracting.
Designed to be glanced at during gameplay, not stared at.

Format:
  L32/57 | P5 (-1) | Tyres 🟢62% | ERS ⚡85% | Gap +2.3s | [OK]
  L33/57 | P5 (=)  | Tyres 🟡48% | ERS ⚡72% | Gap +1.8s | ⚠️ Pit window L36
"""
from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.text import Text
from rich.table import Table
from rich.panel import Panel

from core.models import RaceSnapshot, CarRaceState
from core.db_accessor import format_gap


# ── Colour thresholds ────────────────────────────────────────────────────────

def tyre_emoji(condition: float) -> str:
    if condition > 0.70:
        return "🟢"
    elif condition > 0.50:
        return "🟡"
    elif condition > 0.30:
        return "🟠"
    else:
        return "🔴"


def tyre_style(condition: float) -> str:
    if condition > 0.70:
        return "green"
    elif condition > 0.50:
        return "yellow"
    elif condition > 0.30:
        return "dark_orange"
    else:
        return "bold red"


def ers_style(charge: float) -> str:
    if charge > 0.70:
        return "green"
    elif charge > 0.30:
        return "yellow"
    else:
        return "red"


def pos_change_str(current: int, previous: int) -> str:
    diff = previous - current  # positive = gained positions
    if diff > 0:
        return f" (+{diff})"
    elif diff < 0:
        return f" ({diff})"
    return " (=)"


class CompactDisplay:
    """
    One-line compact status display.
    
    Usage:
        display = CompactDisplay(my_team_id=3)
        display.update(snapshot)  # prints one line
    """
    
    def __init__(self, my_team_id: int, console: Optional[Console] = None):
        self.my_team_id = my_team_id
        self.console = console or Console()
        self._prev_position: dict[int, int] = {}  # car_index -> position
        self._lap_count: int = 0
    
    def update(self, snapshot: RaceSnapshot, extra_info: str = ""):
        """
        Print one compact status line for the current state.
        """
        my_cars = snapshot.get_my_cars(self.my_team_id)
        if not my_cars:
            return
        
        # Use primary car (higher position)
        car = min(my_cars, key=lambda c: c.race_position)
        
        # Position change
        prev = self._prev_position.get(car.car_index, car.race_position)
        change = pos_change_str(car.race_position, prev)
        self._prev_position[car.car_index] = car.race_position
        
        # Build the line
        line = Text()
        
        # Lap counter
        line.append(f"L{snapshot.current_lap}/{snapshot.total_laps}", style="bold white")
        line.append(" │ ", style="dim")
        
        # Position
        pos_style = "bold green" if car.race_position <= 3 else "white"
        line.append(f"P{car.race_position}", style=pos_style)
        line.append(change, style="dim cyan" if "+" in change else ("dim red" if "-" in change else "dim"))
        line.append(" │ ", style="dim")
        
        # Tyres
        cond = car.avg_tyre_condition
        emoji = tyre_emoji(cond)
        style = tyre_style(cond)
        line.append(f"Tyres {emoji}", style=style)
        line.append(f"{cond:.0%}", style=style)
        line.append(" │ ", style="dim")
        
        # ERS
        ers = car.ers_battery_charge
        line.append(f"ERS ⚡", style=ers_style(ers))
        line.append(f"{ers:.0%}", style=ers_style(ers))
        
        # Gap to car ahead
        ahead = [c for c in snapshot.cars if c.race_position == car.race_position - 1]
        if ahead:
            gap_ms = int((car.total_race_time - ahead[0].total_race_time) * 1000)
            if gap_ms > 0:
                line.append(" │ ", style="dim")
                line.append(f"Gap {format_gap(gap_ms)}", style="dim")
        
        # Pit stops
        if car.pit_stops_had > 0:
            line.append(" │ ", style="dim")
            line.append(f"Pits:{car.pit_stops_had}", style="dim")
        
        # Damage indicator
        if car.has_damage:
            line.append(" │ ", style="dim")
            line.append(f"🔧DMG", style="red")
        
        # Extra info (strategy hint)
        if extra_info:
            line.append(" │ ", style="dim")
            line.append(extra_info, style="bold yellow")
        
        # Safety car indicator
        if snapshot.is_safety_car:
            line.append(" │ ", style="dim")
            line.append("🟡 SC", style="bold yellow")
        elif snapshot.is_vsc:
            line.append(" │ ", style="dim")
            line.append("⚠️ VSC", style="yellow")
        
        # Weather indicator
        if snapshot.weather and snapshot.weather.is_raining:
            line.append(" │ ", style="dim")
            line.append("🌧️", style="blue")
        
        self.console.print(line)
        self._lap_count = snapshot.current_lap
    
    def print_header(self, track_name: str, total_laps: int, team_id: int):
        """Print a header line before the race starts."""
        self.console.print()
        self.console.print(
            f"  🏎️  [bold cyan]{track_name}[/bold cyan] | "
            f"{total_laps} laps | Team {team_id}",
            highlight=False,
        )
        self.console.print("  " + "─" * 70, style="dim")
        self.console.print()


# ── Expanded detail view (shown on pause or keypress) ────────────────────────

def print_full_standings(snapshot: RaceSnapshot, my_team_id: int, 
                         console: Optional[Console] = None):
    """
    Print full standings table — use when player pauses or asks for detail.
    """
    console = console or Console()
    
    table = Table(
        show_header=True,
        header_style="bold cyan",
        expand=True,
        padding=(0, 1),
        title="🏁 Full Standings",
    )
    
    table.add_column("Pos", width=4, justify="center")
    table.add_column("Car", width=4, justify="center")
    table.add_column("Gap", width=10, justify="right")
    table.add_column("Tyres", width=8, justify="center")
    table.add_column("ERS", width=6, justify="right")
    table.add_column("Stops", width=5, justify="center")
    table.add_column("Damage", width=6, justify="center")
    
    cars = sorted(snapshot.cars, key=lambda c: c.race_position)
    leader_time = cars[0].total_race_time if cars else 0
    
    for car in cars:
        is_my = car.team_id == my_team_id
        style = "bold green" if is_my else ""
        
        # Gap
        if car.race_position == 1:
            gap = "LEADER"
        else:
            gap_ms = int((car.total_race_time - leader_time) * 1000)
            gap = format_gap(gap_ms)
        
        # Tyres
        cond = car.avg_tyre_condition
        tyre_txt = f"{tyre_emoji(cond)} {cond:.0%}"
        
        # ERS
        ers_txt = f"{car.ers_battery_charge:.0%}"
        
        # Damage
        if car.has_damage:
            dmg = f"{'█' * min(car.damage_severity // 3, 6)}"
            dmg_style = "red"
        else:
            dmg = "—"
            dmg_style = "dim"
        
        table.add_row(
            f"P{car.race_position}",
            f"#{car.car_index}",
            gap,
            tyre_txt,
            ers_txt,
            str(car.pit_stops_had),
            dmg,
            style=style,
        )
    
    console.print(table)
