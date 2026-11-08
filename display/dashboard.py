"""
dashboard.py — Real-time terminal dashboard for F1 Manager 2024 Strategy AI.

Uses the Rich library for beautiful terminal rendering.
Displays race positions, tyre states, strategy recommendations, and intel.
"""
from __future__ import annotations

import sys
import time
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.live import Live
from rich.columns import Columns
from rich.align import Align

from core.models import RaceSnapshot, CarRaceState, TyreCompound, SectorState
from core.db_accessor import format_lap_time, format_gap
from strategy.engine import EngineState, StrategyRecommendation
from strategy.fastf1_calibrator import FastF1Calibrator


console = Console()


# ── Colour helpers ───────────────────────────────────────────────────────────

def tyre_color(condition: float) -> str:
    """Colour for tyre condition."""
    if condition > 0.70:
        return "green"
    elif condition > 0.40:
        return "yellow"
    else:
        return "red"


def ers_color(charge: float) -> str:
    if charge > 0.70:
        return "green"
    elif charge > 0.30:
        return "yellow"
    else:
        return "red"


def pos_change_emoji(current: int, previous: int) -> str:
    if current < previous:
        return "▲"
    elif current > previous:
        return "▼"
    return "="


def priority_color(p: int) -> str:
    if p >= 8:
        return "bold red"
    elif p >= 6:
        return "bold yellow"
    elif p >= 4:
        return "cyan"
    return "dim"


def format_seconds_to_lap_time(sec: float) -> str:
    """Format seconds into M:SS.mmm format."""
    if sec <= 0.0 or sec >= 9000.0:
        return "--:--.---"
    m = int(sec // 60)
    s = sec % 60
    return f"{m}:{s:06.3f}"


def format_sector(sec: float, state: SectorState) -> Text:
    """Return a color-coded Rich Text object for an F1 sector."""
    if sec <= 0.0:
        return Text(" --.---", style="dim")
    return Text(f"{sec:6.3f}", style=state.color)


def format_live_gap(gap_sec: float, is_leader: bool) -> str:
    """Format gap to race leader."""
    if is_leader or gap_sec <= 0.0:
        return "LEADER"
    if gap_sec < 60.0:
        return f"+{gap_sec:6.3f}"
    m = int(gap_sec // 60)
    s = gap_sec % 60
    return f"+{m}:{s:05.2f}"


def format_live_interval(interval_sec: float, is_leader: bool) -> str:
    """Format interval to car ahead."""
    if is_leader:
        return "   -   "
    if interval_sec <= 0.0:
        return "   -   "
    if interval_sec < 60.0:
        return f"+{interval_sec:6.3f}"
    m = int(interval_sec // 60)
    s = interval_sec % 60
    return f"+{m}:{s:05.2f}"


# ── Dashboard builder ───────────────────────────────────────────────────────

class Dashboard:
    """
    Builds and renders the strategy dashboard.
    
    Usage:
        dashboard = Dashboard()
        dashboard.render(snapshot, engine_state)
    """
    
    def __init__(self, my_team_id: int = 0, console: Optional[Console] = None):
        self.my_team_id = my_team_id
        self.console = console or Console()
        self._prev_positions: dict[int, int] = {}
        self._last_update: float = 0
        self._calibrator = FastF1Calibrator()
    
    def render(self, snapshot: RaceSnapshot, state: EngineState,
               live: Optional[Live] = None):
        """Render the full dashboard."""
        layout = Layout()
        
        if snapshot.is_live_timing:
            # Full-width stacked broadcast layout for F1 Live Timing Tower
            layout.split_column(
                Layout(name="header", size=3),
                Layout(name="standings", ratio=3),
                Layout(name="sub", ratio=1),
                Layout(name="footer", size=1),
            )
            layout["sub"].split_row(
                Layout(name="my_status", ratio=1),
                Layout(name="recommendations", ratio=2),
                Layout(name="weather", ratio=1),
                Layout(name="intel", ratio=1),
            )
        else:
            # Classic side-by-side layout for savefile mode (8 columns)
            layout.split_column(
                Layout(name="header", size=3),
                Layout(name="body"),
                Layout(name="footer", size=1),
            )
            layout["body"].split_row(
                Layout(name="left", ratio=2),
                Layout(name="right", ratio=1),
            )
            layout["left"].split_column(
                Layout(name="standings", ratio=2),
                Layout(name="recommendations", ratio=1),
            )
            layout["right"].split_column(
                Layout(name="my_status"),
                Layout(name="weather"),
                Layout(name="intel"),
            )
        
        # Header
        layout["header"].update(self._build_header(snapshot, state))
        
        # Standings table
        layout["standings"].update(self._build_standings(snapshot, state))
        
        # Recommendations
        layout["recommendations"].update(self._build_recommendations(state))
        
        # My car status
        layout["my_status"].update(self._build_my_status(snapshot, state))
        
        # Weather
        layout["weather"].update(self._build_weather(snapshot))
        
        # Intel
        layout["intel"].update(self._build_intel(state))
        
        # Footer
        layout["footer"].update(
            Panel(
                f"  [dim]Last update: {time.strftime('%H:%M:%S')} | "
                f"Team {self.my_team_id} | "
                f"Press Ctrl+C to exit[/dim]",
                style="dim",
            )
        )
        
        if live:
            live.update(layout)
        else:
            self.console.print(layout)
    
    def _build_header(self, snapshot: RaceSnapshot, state: EngineState) -> Panel:
        """Build the header panel."""
        if snapshot.is_live_timing:
            if getattr(snapshot, "is_live_paused", False):
                mode_badge = "[bold yellow]⏸️ LIVE (PAUSED)[/bold yellow]"
            else:
                mode_badge = "[bold green]🟢 LIVE[/bold green]"
        else:
            mode_badge = "[dim cyan]💾 SAVE[/dim cyan]"

        progress = f"Lap {state.current_lap}/{state.total_laps}"
        pct = (state.current_lap / max(1, state.total_laps)) * 100
        
        fl_badge = ""
        if snapshot.fastest_lap_time > 0 and snapshot.fastest_lap_time < 9000:
            fl_time_str = format_seconds_to_lap_time(snapshot.fastest_lap_time)
            driver = snapshot.fastest_lap_driver or "CAR"
            fl_badge = f"  [bold magenta]💜 FL: {driver} {fl_time_str}[/bold magenta]"

        sc_text = ""
        if snapshot.is_safety_car:
            sc_text = "  [bold red]🚨 SAFETY CAR[/bold red]"
        elif snapshot.is_vsc:
            sc_text = "  [bold yellow]⚠️ VSC[/bold yellow]"

        track_badge = ""
        if snapshot.track:
            t_name = snapshot.track.name
            if self._calibrator.find_track(t_name):
                track_badge = f"  [bold green]🏁 {t_name} [FastF1][/bold green]"
            else:
                track_badge = f"  [cyan]🏁 {t_name}[/cyan]"
        
        top_rec = state.top_recommendation
        alert = ""
        if top_rec and top_rec.priority >= 7:
            alert = f"  [{priority_color(top_rec.priority)}]{top_rec.title}[/{priority_color(top_rec.priority)}]"
        
        return Panel(
            f"  🏎️  F1 MANAGER 2024 — AI STRATEGY ENGINE  |  {mode_badge}  |  "
            f"{progress} ({pct:.0f}%){track_badge}{fl_badge}{sc_text}{alert}",
            style="bold white on dark_blue",
        )
    
    def _build_standings(self, snapshot: RaceSnapshot, state: EngineState) -> Panel:
        """Build the race standings table (supports F1 broadcast Live Timing tower)."""
        if snapshot.is_live_timing:
            table = Table(
                title="🏁 F1 Live Timing Tower",
                show_header=True,
                header_style="bold cyan",
                expand=False,
                padding=(0, 1),
            )
            table.add_column("Pos", width=4, justify="center")
            table.add_column("No", width=3, justify="center")
            table.add_column("Driver", width=7)
            table.add_column("Tyre", width=8, justify="center")
            table.add_column("Int", width=8, justify="right")
            table.add_column("Gap", width=8, justify="right")
            table.add_column("S1", width=7, justify="center")
            table.add_column("S2", width=7, justify="center")
            table.add_column("S3", width=7, justify="center")
            table.add_column("Current", width=8, justify="right")
            table.add_column("Last Lap", width=9, justify="right")
            table.add_column("Best Lap", width=9, justify="right")
            table.add_column("Pit", width=4, justify="center")

            cars = sorted(snapshot.cars, key=lambda c: c.race_position)
            for car in cars:
                is_my_car = car.team_id == self.my_team_id
                style = "bold green" if is_my_car else ""

                prev_pos = self._prev_positions.get(car.car_index, car.race_position)
                change = pos_change_emoji(car.race_position, prev_pos)
                pos_text = f"{car.race_position}{change}"

                num_text = str(car.driver_number) if car.driver_number > 0 else f"{car.car_index}"
                driver_text = car.driver_code or car.driver_name or f"#{car.car_index}"

                # Tyre badge with compound color & condition (life remaining)
                t_comp = car.tyre_compound
                t_color = t_comp.color if hasattr(t_comp, "color") else "white"
                t_short = t_comp.short if hasattr(t_comp, "short") else "S"
                tyre_pct = int(round(car.avg_tyre_condition * 100)) if car.avg_tyre_condition > 0 else (100 - car.tyre_wear_pct if car.tyre_wear_pct > 0 else 0)
                tyre_render = Text.assemble(
                    (f"[{t_short}]", f"bold {t_color}"),
                    (f" {tyre_pct}%", tyre_color(car.avg_tyre_condition))
                )

                # Int & Gap
                is_leader = (car.race_position == 1)
                int_text = format_live_interval(car.gap_to_ahead, is_leader)
                gap_text = format_live_gap(car.gap_to_leader, is_leader)

                # Sectors
                s1_text = format_sector(car.s1_time, car.s1_state)
                s2_text = format_sector(car.s2_time, car.s2_state)
                s3_text = format_sector(car.s3_time, car.s3_state)

                # Running current lap
                if car.current_lap_time > 0:
                    if car.current_lap_time >= 60.0:
                        m_c = int(car.current_lap_time // 60)
                        s_c = car.current_lap_time % 60
                        cur_text = Text(f"{m_c}:{s_c:04.1f}", style="cyan")
                    else:
                        cur_text = Text(f"{car.current_lap_time:4.1f}s", style="cyan")
                else:
                    cur_text = Text("  -  ", style="dim")

                # Last lap
                if car.last_lap_time > 0:
                    last_str = format_seconds_to_lap_time(car.last_lap_time)
                    if snapshot.fastest_lap_time > 0 and abs(car.last_lap_time - snapshot.fastest_lap_time) < 0.005:
                        last_text = Text(last_str, style="bold magenta")
                    elif car.best_lap_time > 0 and abs(car.last_lap_time - car.best_lap_time) < 0.005:
                        last_text = Text(last_str, style="bold green")
                    else:
                        last_text = Text(last_str, style="yellow")
                else:
                    last_text = Text("--:--.---", style="dim")

                # Best lap
                if car.best_lap_time > 0 and car.best_lap_time < 9000:
                    best_str = format_seconds_to_lap_time(car.best_lap_time)
                    if snapshot.fastest_lap_time > 0 and abs(car.best_lap_time - snapshot.fastest_lap_time) < 0.005:
                        best_text = Text(best_str, style="bold magenta")
                    else:
                        best_text = Text(best_str, style="green")
                else:
                    best_text = Text("--:--.---", style="dim")

                # Pit
                if car.is_in_pit_lane or car.is_in_pit:
                    pit_text = Text("PIT", style="bold red")
                else:
                    pit_text = Text(str(car.pit_stops_had), style="dim")

                table.add_row(
                    pos_text, num_text, driver_text, tyre_render,
                    int_text, gap_text, s1_text, s2_text, s3_text,
                    cur_text, last_text, best_text, pit_text,
                    style=style,
                )

            self._prev_positions = {c.car_index: c.race_position for c in cars}
            return Panel(table, title="[bold]🏎️ F1 Live Timing Tower[/bold]")

        # Fallback for savefile mode
        table = Table(
            title="🏁 Race Standings",
            show_header=True,
            header_style="bold cyan",
            expand=True,
            padding=(0, 1),
        )
        
        table.add_column("Pos", width=4, justify="center")
        table.add_column("Driver", min_width=12)
        table.add_column("Team", width=3)
        table.add_column("Gap", width=10, justify="right")
        table.add_column("Tyres", width=6, justify="center")
        table.add_column("Stops", width=5, justify="center")
        table.add_column("ERS", width=6, justify="right")
        table.add_column("Damage", width=6, justify="center")
        
        # Sort by position
        cars = sorted(snapshot.cars, key=lambda c: c.race_position)
        
        for car in cars:
            is_my_car = car.team_id == self.my_team_id
            style = "bold green" if is_my_car else ""
            
            # Position with change indicator
            prev_pos = self._prev_positions.get(car.car_index, car.race_position)
            change = pos_change_emoji(car.race_position, prev_pos)
            pos_text = f"{car.race_position}{change}"
            
            # Driver name (simplified)
            driver = f"#{car.car_index}"
            
            # Gap
            if car.race_position == 1:
                gap = "LEADER"
            else:
                # Find leader
                leader = next((c for c in cars if c.race_position == 1), None)
                if leader:
                    gap_ms = int((car.total_race_time - leader.total_race_time) * 1000)
                    gap = format_gap(gap_ms)
                else:
                    gap = "---"
            
            # Tyre condition
            cond = car.avg_tyre_condition
            tyre_text = Text(f"{cond:.0%}", style=tyre_color(cond))
            
            # ERS
            ers_text = Text(f"{car.ers_battery_charge:.0%}", style=ers_color(car.ers_battery_charge))
            
            # Damage
            if car.has_damage:
                dmg = f"{'█' * min(car.damage_severity // 3, 6)}"
                dmg_text = Text(dmg, style="red")
            else:
                dmg_text = Text("OK", style="dim")
            
            table.add_row(
                pos_text, driver, str(car.team_id),
                gap, tyre_text, str(car.pit_stops_had),
                ers_text, dmg_text,
                style=style,
            )
        
        # Update previous positions
        self._prev_positions = {c.car_index: c.race_position for c in cars}
        
        return Panel(table, title="[bold]Race Standings[/bold]")
    
    def _build_recommendations(self, state: EngineState) -> Panel:
        """Build the recommendations panel."""
        if not state.recommendations:
            return Panel(
                "[dim]No active recommendations[/dim]",
                title="[bold]📋 Strategy[/bold]",
            )
        
        # Sort by priority (highest first)
        recs = sorted(state.recommendations, key=lambda r: r.priority, reverse=True)
        
        lines = []
        for rec in recs[:4]:  # top 4
            color = priority_color(rec.priority)
            lines.append(
                f"[{color}][P{rec.priority}] {rec.title}[/{color}]"
            )
            lines.append(f"  [dim]{rec.detail}[/dim]")
            lines.append(f"  [bold]{rec.action}[/bold]")
            lines.append("")

        # Monte Carlo Simulation details if available
        if state.pit_strategy and getattr(state.pit_strategy, "mc_report", None):
            mc_rep = state.pit_strategy.mc_report
            if mc_rep and mc_rep.all_results:
                lines.append("[bold cyan]🎲 Monte Carlo Simulations (1,000 runs):[/bold cyan]")
                for cand in mc_rep.all_results[:3]:
                    is_best = (cand == mc_rep.best_result)
                    star = "[bold green]★[/bold green]" if is_best else " •"
                    cand_name = cand.strategy_name[:20]
                    lines.append(
                        f" {star} {cand_name:<20} "
                        f"ExpPts: [bold yellow]{cand.expected_points:>4.1f}[/bold yellow] | "
                        f"Pod: {cand.podium_probability:>4.0%} | "
                        f"Win: {cand.win_probability:>4.0%} | "
                        f"Traffic: {cand.traffic_risk:>3.0%} | "
                        f"CI: P{cand.p90_position}-P{cand.p10_position}"
                    )
                lines.append("")
        
        return Panel(
            "\n".join(lines),
            title="[bold]📋 Strategy Recommendations[/bold]",
        )
    
    def _build_my_status(self, snapshot: RaceSnapshot, state: EngineState) -> Panel:
        """Build my car status panel."""
        my_cars = snapshot.get_my_cars(self.my_team_id)
        if not my_cars:
            return Panel("[dim]No car data[/dim]", title="[bold]🏎️ My Car[/bold]")
        
        lines = []
        for car in my_cars:
            lines.append(f"[bold]Position: P{car.race_position}[/bold]")
            lines.append(f"Fuel: {car.fuel:.1f} kg")
            lines.append(f"Tyres: {car.avg_tyre_condition:.0%} ({tyre_color(car.avg_tyre_condition)})")
            lines.append(f"ERS: {car.ers_battery_charge:.0%} ({car.ers_battery_charge:.0%})")
            lines.append(f"Pit stops: {car.pit_stops_had}")
            
            if car.has_damage:
                lines.append(f"[red]Damage: {car.damage_severity}/18[/red]")
            else:
                lines.append("[dim]No damage[/dim]")
            lines.append("")
        
        return Panel(
            "\n".join(lines),
            title="[bold]🏎️ My Car[/bold]",
        )
    
    def _build_weather(self, snapshot: RaceSnapshot) -> Panel:
        """Build weather panel."""
        if not snapshot.weather:
            return Panel("[dim]No weather data[/dim]", title="[bold]🌦️ Weather[/bold]")
        
        w = snapshot.weather
        lines = [
            f"State: {w.weather_state.name}",
            f"Rain: {w.rain:.1%}",
            f"Track water: {w.water_on_track:.1%}",
            f"Ambient: {w.ambient_temp:.0f}°C",
            f"Track: {w.track_temp:.0f}°C",
            f"Rubber: {w.rubber_on_track:.1%}",
        ]
        
        if w.is_raining:
            lines.insert(0, "[bold blue]🌧️ RAINING[/bold blue]")
        
        return Panel(
            "\n".join(lines),
            title="[bold]🌦️ Weather[/bold]",
        )
    
    def _build_intel(self, state: EngineState) -> Panel:
        """Build intelligence panel."""
        if not state.intel_report:
            return Panel("[dim]No intel[/dim]", title="[bold]🔍 Intel[/bold]")
        
        intel = state.intel_report
        lines = [
            f"[bold]P{intel.my_position}[/bold]",
            f"Gap ahead: {format_gap(intel.gap_to_car_ahead_ms)}",
            f"Gap behind: {format_gap(intel.gap_to_car_behind_ms)}",
        ]
        
        if intel.immediate_threats:
            lines.append(f"\n[red]⚠️ Threats:[/red]")
            for t in intel.immediate_threats[:3]:
                lines.append(f"  {t.driver_name} ({t.gap_to_my_car_ms/1000:+.1f}s)")
        
        if intel.vulnerable_cars:
            lines.append(f"\n[green]🎯 Targets:[/green]")
            for v in intel.vulnerable_cars[:3]:
                lines.append(f"  {v.driver_name} ({v.gap_to_my_car_ms/1000:+.1f}s)")
        
        return Panel(
            "\n".join(lines),
            title="[bold]🔍 Race Intel[/bold]",
        )
    
    def print_compact(self, snapshot: RaceSnapshot, state: EngineState):
        """Print a compact one-line status (for non-live mode)."""
        my_cars = snapshot.get_my_cars(self.my_team_id)
        if not my_cars:
            return
        
        car = min(my_cars, key=lambda c: c.race_position)
        top = state.top_recommendation
        
        line = (
            f"L{state.current_lap}/{state.total_laps} | "
            f"P{car.race_position} | "
            f"Tyres {car.avg_tyre_condition:.0%} | "
            f"ERS {car.ers_battery_charge:.0%}"
        )
        
        if top:
            line += f" | [{top.priority}] {top.title}"
        
        console.print(line)
