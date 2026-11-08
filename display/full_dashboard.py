"""
full_dashboard.py — Complete Rich terminal dashboard showing ALL race data.

This dashboard shows everything Python can read from the game:
- Full 20-car standings (position, gap, tyres, ERS, damage, pits, last lap)
- Competitor strategy tracker (recent pits, gap trends, undercut threats)
- Your car's detailed status
- Strategy recommendations
- Pace/fuel/ERS control
- Weather panel
- Safety car status

Layout:
┌─────────────────────────────────────────────────────────────────────┐
│ HEADER: Track | Lap/Total | Weather | SC Status                    │
├──────────────────────────────────────┬──────────────────────────────┤
│ LEFT (65%)                           │ RIGHT (35%)                  │
│ ┌──────────────────────────────────┐ │ ┌──────────────────────────┐│
│ │ FULL STANDINGS TABLE (20 cars)   │ │ │ MY CAR DETAIL            ││
│ │ Pos|Car|Gap|Tyre|ERS|Dmg|Pits   │ │ │ All stats + pace mode    ││
│ └──────────────────────────────────┘ │ └──────────────────────────┘│
│ ┌──────────────────────────────────┐ │ ┌──────────────────────────┐│
│ │ COMPETITOR TRACKER               │ │ │ STRATEGY RECOMMENDATIONS ││
│ │ Recent pits, undercut alerts     │ │ │ Pit, Weather, SC, Intel  ││
│ └──────────────────────────────────┘ │ └──────────────────────────┘│
│                                      │ ┌──────────────────────────┐│
│                                      │ │ PACE & FUEL              ││
│                                      │ │ ERS, Fuel/lap, Pace mode ││
│                                      │ └──────────────────────────┘│
└──────────────────────────────────────┴──────────────────────────────┘
"""
from __future__ import annotations

import time
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.columns import Columns
from rich.align import Align
from rich.rule import Rule

from core.models import RaceSnapshot, CarRaceState, TyreCompound
from core.db_accessor import format_lap_time, format_gap
from strategy.engine import EngineState, StrategyRecommendation
from strategy.competitor_tracker import CompetitorTracker
from strategy.pace_control import PaceRecommendation


console = Console()


# ── Helpers ──────────────────────────────────────────────────────────────────

def tyre_emoji(c: float) -> str:
    if c > 0.70: return "🟢"
    elif c > 0.50: return "🟡"
    elif c > 0.30: return "🟠"
    else: return "🔴"

def tyre_style(c: float) -> str:
    if c > 0.70: return "green"
    elif c > 0.50: return "yellow"
    elif c > 0.30: return "dark_orange"
    return "bold red"

def ers_style(c: float) -> str:
    if c > 0.70: return "green"
    elif c > 0.30: return "yellow"
    return "red"

def fuel_style(fuel: float, needed: float) -> str:
    ratio = fuel / max(1, needed)
    if ratio > 1.1: return "green"
    elif ratio > 0.95: return "yellow"
    return "red"


class FullDashboard:
    """
    Complete race dashboard showing all data.
    
    Usage:
        dashboard = FullDashboard(my_team_id=3)
        dashboard.render(snapshot, engine_state, competitor_tracker, pace_rec)
    """
    
    def __init__(self, my_team_id: int):
        self.my_team_id = my_team_id
        self._prev_positions: dict[int, int] = {}
    
    def render(self, snapshot: RaceSnapshot, 
               engine_state: EngineState,
               competitor_tracker: Optional[CompetitorTracker] = None,
               pace_rec: Optional[PaceRecommendation] = None,
               live=None):
        """Render the full dashboard."""
        
        # ── Build layout ────────────────────────────────────────────────
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=5),
            Layout(name="body"),
            Layout(name="footer", size=1),
        )
        layout["body"].split_row(
            Layout(name="left", ratio=3),
            Layout(name="right", ratio=2),
        )
        layout["left"].split_column(
            Layout(name="standings"),
            Layout(name="competitor_tracker", size=10),
        )
        layout["right"].split_column(
            Layout(name="my_car"),
            Layout(name="strategy"),
            Layout(name="pace"),
            Layout(name="weather"),
        )
        
        # ── Header ──────────────────────────────────────────────────────
        layout["header"].update(self._build_header(snapshot, engine_state))
        
        # ── Standings ───────────────────────────────────────────────────
        layout["standings"].update(self._build_standings(snapshot))
        
        # ── Competitor tracker ──────────────────────────────────────────
        layout["competitor_tracker"].update(
            self._build_competitor_tracker(snapshot, competitor_tracker)
        )
        
        # ── My car detail ───────────────────────────────────────────────
        layout["my_car"].update(self._build_my_car(snapshot, pace_rec))
        
        # ── Strategy recommendations ────────────────────────────────────
        layout["strategy"].update(self._build_strategy(engine_state))
        
        # ── Pace & fuel ─────────────────────────────────────────────────
        layout["pace"].update(self._build_pace(pace_rec))
        
        # ── Weather ─────────────────────────────────────────────────────
        layout["weather"].update(self._build_weather(snapshot))
        
        # ── Footer ──────────────────────────────────────────────────────
        layout["footer"].update(Panel(
            f"  [dim]{time.strftime('%H:%M:%S')} | "
            f"F1 Manager 2024 AI Strategy | "
            f"Tab=expand | Ctrl+C=exit[/dim]",
            style="dim",
        ))
        
        if live:
            live.update(layout)
        else:
            console.print(layout)
    
    def _build_header(self, snapshot: RaceSnapshot, state: EngineState) -> Panel:
        """Header with track, lap, weather, SC."""
        track_name = snapshot.track.name if snapshot.track else "Unknown"
        progress = f"L{state.current_lap}/{state.total_laps}"
        pct = (state.current_lap / max(1, state.total_laps)) * 100
        
        # Progress bar
        bar_len = 30
        filled = int(pct / 100 * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        
        # SC status
        sc = ""
        if snapshot.is_safety_car:
            sc = "  [bold red on yellow] 🟡 SAFETY CAR [/bold red on yellow]"
        elif snapshot.is_vsc:
            sc = "  [bold yellow] ⚠️ VSC [/bold yellow]"
        
        # Weather
        weather_str = ""
        if snapshot.weather:
            w = snapshot.weather
            if w.is_raining:
                weather_str = f"  [blue]🌧️ Rain {w.rain:.0%} | Track {w.track_temp:.0f}°C[/blue]"
            else:
                weather_str = f"  [yellow]☀️ {w.weather_state.name} | Air {w.ambient_temp:.0f}°C | Track {w.track_temp:.0f}°C[/yellow]"
        
        text = Text()
        text.append(f"  🏎️  ", style="bold")
        text.append(f"{track_name}", style="bold cyan")
        text.append(f"  │  ", style="dim")
        text.append(f"{progress}", style="bold white")
        text.append(f"  ({pct:.0f}%)  ", style="dim")
        text.append(f"{bar}", style="green" if pct < 80 else "yellow")
        text.append(f"{sc}", style="")
        text.append(f"\n{weather_str}", style="")
        
        return Panel(text, style="bold white on dark_blue", padding=(0, 1))
    
    def _build_standings(self, snapshot: RaceSnapshot) -> Panel:
        """Full 20-car standings table."""
        table = Table(
            show_header=True,
            header_style="bold cyan",
            expand=True,
            padding=(0, 1),
            box=None,
        )
        
        table.add_column("Pos", width=4, justify="center")
        table.add_column("Car", width=4, justify="center")
        table.add_column("Driver", width=6)
        table.add_column("Gap", width=10, justify="right")
        table.add_column("LastLap", width=10, justify="right")
        table.add_column("Tyres", width=8, justify="center")
        table.add_column("ERS", width=6, justify="right")
        table.add_column("Fuel", width=6, justify="right")
        table.add_column("Dmg", width=5, justify="center")
        table.add_column("Pits", width=4, justify="center")
        table.add_column("SC", width=3, justify="center")
        
        cars = sorted(snapshot.cars, key=lambda c: c.race_position)
        leader_time = cars[0].total_race_time if cars else 0
        
        for car in cars:
            is_my = car.team_id == self.my_team_id
            style = "bold green" if is_my else ""
            
            # Position with change
            prev = self._prev_positions.get(car.car_index, car.race_position)
            diff = prev - car.race_position
            if diff > 0:
                pos_txt = f"{car.race_position}▲"
                pos_style = "green"
            elif diff < 0:
                pos_txt = f"{car.race_position}▼"
                pos_style = "red"
            else:
                pos_txt = f"{car.race_position}"
                pos_style = "white"
            
            # Gap
            if car.race_position == 1:
                gap = "LEADER"
            else:
                gap_ms = int((car.total_race_time - leader_time) * 1000)
                gap = format_gap(gap_ms)
            
            # Tyres
            cond = car.avg_tyre_condition
            tyre_txt = f"{tyre_emoji(cond)}{cond:.0%}"
            
            # ERS
            ers_txt = f"{car.ers_battery_charge:.0%}"
            
            # Fuel
            fuel_txt = f"{car.fuel:.1f}"
            
            # Damage
            if car.has_damage:
                dmg = f"{'█' * min(car.damage_severity // 4, 5)}"
                dmg_style = "red"
            else:
                dmg = "—"
                dmg_style = "dim"
            
            # SC waiting
            sc_txt = "🟡" if car.waiting_for_sc else ""
            
            # Driver name
            driver = f"#{car.car_index}"
            
            table.add_row(
                Text(pos_txt, style=pos_style),
                str(car.car_index),
                driver,
                gap,
                "—",
                Text(tyre_txt, style=tyre_style(cond)),
                Text(ers_txt, style=ers_style(car.ers_battery_charge)),
                fuel_txt,
                Text(dmg, style=dmg_style),
                str(car.pit_stops_had),
                sc_txt,
                style=style,
            )
        
        # Update prev positions
        self._prev_positions = {c.car_index: c.race_position for c in cars}
        
        return Panel(table, title="[bold]🏁 Race Standings[/bold]", border_style="cyan")
    
    def _build_competitor_tracker(self, snapshot: RaceSnapshot,
                                   tracker: Optional[CompetitorTracker]) -> Panel:
        """Competitor strategy tracker."""
        if not tracker:
            return Panel("[dim]No competitor data[/dim]", 
                        title="[bold]🔍 Competitor Tracker[/bold]")
        
        lines = []
        
        # Recent pit stops
        recent_pits = tracker.get_recent_pits(5, snapshot.current_lap)
        if recent_pits:
            lines.append("[bold]Recent Pit Stops:[/bold]")
            for state, event in recent_pits[-4:]:
                lines.append(
                    f"  L{event.lap} {state.driver_name:4s} → {event.new_compound}s "
                    f"(P{event.position_before}→P{event.position_after})"
                )
        
        # Closest competitors
        closest = tracker.get_competitors_by_gap()[:5]
        if closest:
            lines.append("[bold]Closest:[/bold]")
            for c in closest:
                gap = c.gap_to_us_ms / 1000
                trend = ""
                if len(c.gap_history) >= 3:
                    delta = c.gap_history[-1] - c.gap_history[-3]
                    if delta < -500:
                        trend = "[red]⚡closing[/red]"
                    elif delta > 500:
                        trend = "[green]↑opening[/green]"
                    else:
                        trend = "[dim]=stable[/dim]"
                
                lines.append(
                    f"  {c.driver_name:4s} {gap:+.1f}s {trend} "
                    f"Tyres:{c.tyre_condition:.0%} Pits:{c.pit_stops}"
                )
        
        if not lines:
            lines.append("[dim]No competitor events yet[/dim]")
        
        return Panel(
            "\n".join(lines),
            title="[bold]🔍 Competitor Tracker[/bold]",
            border_style="yellow",
        )
    
    def _build_my_car(self, snapshot: RaceSnapshot,
                       pace_rec: Optional[PaceRecommendation]) -> Panel:
        """Your car's detailed status."""
        my_cars = snapshot.get_my_cars(self.my_team_id)
        if not my_cars:
            return Panel("[dim]No data[/dim]", title="[bold]🏎️ My Car[/bold]")
        
        lines = []
        for car in my_cars:
            lines.append(f"[bold]Car #{car.car_index} — P{car.race_position}[/bold]")
            lines.append(f"")
            lines.append(f"  Fuel:    {car.fuel:.1f} kg")
            lines.append(f"  ERS:     {car.ers_battery_charge:.0%} {'⚡' * int(car.ers_battery_charge * 5)}")
            lines.append(f"  Tyres:   {tyre_emoji(car.avg_tyre_condition)} {car.avg_tyre_condition:.0%}")
            lines.append(f"  Temp:    {car.avg_tyre_temp:.0f}°C")
            lines.append(f"  Stops:   {car.pit_stops_had}")
            
            if car.has_damage:
                parts = []
                if car.front_wing_damage.value > 0: parts.append(f"FW:{car.front_wing_damage.name}")
                if car.rear_wing_damage.value > 0: parts.append(f"RW:{car.rear_wing_damage.name}")
                if car.floor_damage.value > 0: parts.append(f"FL:{car.floor_damage.name}")
                if car.suspension_damage.value > 0: parts.append(f"SUS:{car.suspension_damage.name}")
                lines.append(f"  Damage:  [red]{', '.join(parts)}[/red]")
            else:
                lines.append(f"  Damage:  [dim]None[/dim]")
            
            # Pace mode (if available)
            if pace_rec:
                lines.append(f"")
                lines.append(f"  Pace:    [cyan]{pace_rec.recommended_pace.name}[/cyan]")
                lines.append(f"  ERS:     [cyan]{pace_rec.recommended_ers.name}[/cyan]")
                lines.append(f"  Fuel:    {pace_rec.fuel_target_per_lap:.2f} kg/lap")
        
        return Panel(
            "\n".join(lines),
            title="[bold]🏎️ My Car Detail[/bold]",
            border_style="green",
        )
    
    def _build_strategy(self, state: EngineState) -> Panel:
        """Strategy recommendations."""
        if not state.recommendations:
            return Panel(
                "[dim green]✓ No action needed[/dim green]",
                title="[bold]📋 Strategy[/bold]",
            )
        
        lines = []
        recs = sorted(state.recommendations, key=lambda r: r.priority, reverse=True)
        
        for rec in recs[:4]:
            color = {5: "bold white on red", 4: "bold red", 3: "yellow", 2: "cyan"}.get(rec.priority, "white")
            icon = {5: "🚨", 4: "🔔", 3: "⚠️", 2: "💡", 1: "ℹ️"}.get(rec.priority, "")
            
            lines.append(f"[{color}]{icon} {rec.title}[/{color}]")
            lines.append(f"  [dim]{rec.detail}[/dim]")
            lines.append(f"  [bold]{rec.action}[/bold]")
            lines.append("")
        
        return Panel(
            "\n".join(lines),
            title="[bold]📋 Strategy Recommendations[/bold]",
            border_style="red" if state.has_urgent_action else "cyan",
        )
    
    def _build_pace(self, pace_rec: Optional[PaceRecommendation]) -> Panel:
        """Pace and fuel management."""
        if not pace_rec:
            return Panel("[dim]No pace data[/dim]", title="[bold]🏎️ Pace Control[/bold]")
        
        lines = [
            f"Pace:  [bold cyan]{pace_rec.recommended_pace.name}[/bold cyan]",
            f"  [dim]{pace_rec.recommended_pace.description}[/dim]",
            f"",
            f"ERS:   [bold cyan]{pace_rec.recommended_ers.name}[/bold cyan]",
            f"  [dim]{pace_rec.recommended_ers.description}[/dim]",
            f"",
            f"Fuel:  [bold]{pace_rec.fuel_target_per_lap:.2f} kg/lap[/bold]",
            f"  [dim]{pace_rec.reason_fuel}[/dim]",
        ]
        
        if pace_rec.urgency != "NORMAL":
            lines.append(f"")
            lines.append(f"[bold red]⚡ {pace_rec.urgency}[/bold red]")
        
        return Panel(
            "\n".join(lines),
            title="[bold]🏎️ Pace & Fuel[/bold]",
            border_style="cyan",
        )
    
    def _build_weather(self, snapshot: RaceSnapshot) -> Panel:
        """Weather panel."""
        if not snapshot.weather:
            return Panel("[dim]No data[/dim]", title="[bold]🌦️ Weather[/bold]")
        
        w = snapshot.weather
        lines = [
            f"State:    {w.weather_state.name}",
            f"Rain:     {w.rain:.1%} {'🌧️' if w.is_raining else '☀️'}",
            f"Water:    {w.water_on_track:.1%}",
            f"Air:      {w.ambient_temp:.0f}°C",
            f"Track:    {w.track_temp:.0f}°C",
            f"Rubber:   {w.rubber_on_track:.1%}",
        ]
        
        return Panel(
            "\n".join(lines),
            title="[bold]🌦️ Weather[/bold]",
            border_style="blue" if w.is_raining else "yellow",
        )
    
    def print_compact(self, snapshot: RaceSnapshot, state: EngineState,
                      extra: str = ""):
        """Compact one-line output."""
        my_cars = snapshot.get_my_cars(self.my_team_id)
        if not my_cars:
            return
        car = min(my_cars, key=lambda c: c.race_position)
        
        line = (
            f"L{state.current_lap}/{state.total_laps} │ "
            f"P{car.race_position} │ "
            f"Tyres {tyre_emoji(car.avg_tyre_condition)}{car.avg_tyre_condition:.0%} │ "
            f"ERS {car.ers_battery_charge:.0%} │ "
            f"Fuel {car.fuel:.1f}"
        )
        if extra:
            line += f" │ {extra}"
        
        console.print(line)
