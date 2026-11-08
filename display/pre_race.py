"""
pre_race.py — Pre-race data display and strategy planning.

Shows all available data before the race starts:
- Track characteristics and history
- Weather forecast
- Competitor analysis (car performance, driver stats)
- Strategy options to evaluate
- Tyre compound analysis
- Safety car probability

User can choose what to display and what strategy to plan.
"""
from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich.prompt import Prompt, Confirm

from core.models import (
    Track, TrackType, TyreCompound, DriverData, CarStats, TeamPerformance,
    WeatherState_Data, WeatherState,
)
from strategy.tyre_model import TyreModel
from strategy.pace_control import PaceController, PACE_MODES, ERS_MODES


console = Console()


class PreRaceDisplay:
    """
    Pre-race data display and strategy planner.
    
    Usage:
        display = PreRaceDisplay(track, drivers, my_team_id)
        display.show_menu()           # interactive menu
        display.show_all()            # show everything
        display.show_track_info()     # track characteristics
        display.show_tyre_analysis()  # compound comparison
        display.show_competitors()    # competitor analysis
        display.show_weather()        # weather forecast
        display.show_strategy_plan()  # strategy options
    """
    
    def __init__(self, track: Track, my_team_id: int,
                 drivers: Optional[list[DriverData]] = None,
                 team_performance: Optional[list[TeamPerformance]] = None,
                 weather_forecast: Optional[list[WeatherState_Data]] = None,
                 car_stats: Optional[dict[int, CarStats]] = None):
        self.track = track
        self.my_team_id = my_team_id
        self.drivers = drivers or []
        self.team_performance = team_performance or []
        self.weather_forecast = weather_forecast or []
        self.car_stats = car_stats or {}
        
        self.tyre_model = TyreModel()
        self.pace_controller = PaceController(track)
    
    def show_menu(self):
        """Interactive pre-race menu."""
        console.print()
        console.print("[bold cyan]═══════════════════════════════════════════════════[/bold cyan]")
        console.print("[bold]  📋 PRE-RACE BRIEFING — Select data to view:[/bold]")
        console.print("[bold cyan]═══════════════════════════════════════════════════[/bold cyan]")
        console.print()
        console.print("  [bold]1.[/bold] 🏁 Track Information")
        console.print("  [bold]2.[/bold] 🛞 Tyre Compound Analysis")
        console.print("  [bold]3.[/bold] 🌦️ Weather Forecast")
        console.print("  [bold]4.[/bold] 🏎️ Competitor Analysis")
        console.print("  [bold]5.[/bold] 📊 Car Performance Comparison")
        console.print("  [bold]6.[/bold] 📋 Strategy Options")
        console.print("  [bold]7.[/bold] 🏆 Championship Context")
        console.print("  [bold]8.[/bold] 📖 Show ALL Data")
        console.print("  [bold]0.[/bold] Exit & Start Race")
        console.print()
        
        while True:
            choice = Prompt.ask("[bold]Select option[/bold]", default="8")
            
            if choice == "0":
                break
            elif choice == "1":
                self.show_track_info()
            elif choice == "2":
                self.show_tyre_analysis()
            elif choice == "3":
                self.show_weather()
            elif choice == "4":
                self.show_competitors()
            elif choice == "5":
                self.show_car_performance()
            elif choice == "6":
                self.show_strategy_plan()
            elif choice == "7":
                self.show_championship_context()
            elif choice == "8":
                self.show_all()
            else:
                console.print("[red]Invalid option[/red]")
            
            console.print()
    
    def show_all(self):
        """Show all pre-race data."""
        self.show_track_info()
        console.print()
        self.show_tyre_analysis()
        console.print()
        self.show_weather()
        console.print()
        self.show_competitors()
        console.print()
        self.show_car_performance()
        console.print()
        self.show_strategy_plan()
    
    def show_track_info(self):
        """Display track characteristics."""
        t = self.track
        
        table = Table(
            title=f"🏁 {t.name}",
            show_header=False,
            expand=True,
            padding=(0, 2),
        )
        table.add_column("Attribute", style="cyan", width=25)
        table.add_column("Value", style="white")
        
        table.add_row("Track Length", f"{t.track_length:.3f} km")
        table.add_row("Race Laps", str(t.laps))
        table.add_row("Total Distance", f"{t.track_length * t.laps:.1f} km")
        table.add_row("Track Type", t.type_of_track.name)
        table.add_row("Fastest Lap", f"{t.fastest_lap:.3f}s")
        table.add_row("Safety Car Chance", f"{t.safety_car_chance:.0%}")
        table.add_row("Pit Lane Time Loss", f"{t.pit_lane_time_loss}s")
        table.add_row("Green Flag Time Loss", f"{t.green_flag_time_loss}s")
        table.add_row("SC Pit Time Loss", f"{t.safety_car_time_loss}s")
        table.add_row("Time Saved Under SC", f"{t.pit_lane_time_loss - t.safety_car_time_loss}s")
        table.add_row("Sprint Laps", str(t.sprint_laps))
        
        # Strategy implications
        sc_note = ""
        if t.safety_car_chance > 0.7:
            sc_note = "[bold red]⚠️ HIGH SC probability — flexible strategy recommended[/bold red]"
        elif t.safety_car_chance > 0.4:
            sc_note = "[yellow]⚠️ Moderate SC probability[/yellow]"
        else:
            sc_note = "[green]Low SC probability — commit to planned strategy[/green]"
        
        table.add_row("Strategy Note", sc_note)
        
        console.print(table)
    
    def show_tyre_analysis(self):
        """Compare tyre compounds for this track."""
        table = Table(
            title="🛞 Tyre Compound Analysis",
            show_header=True,
            header_style="bold cyan",
            expand=True,
        )
        
        table.add_column("Compound", width=10)
        table.add_column("Expected Life", width=12, justify="center")
        table.add_column("Deg/Lap", width=10, justify="center")
        table.add_column("Cliff At", width=10, justify="center")
        table.add_column("Pace Delta", width=12, justify="center")
        table.add_column("Best For", width=20)
        
        for compound in [TyreCompound.SOFT, TyreCompound.MEDIUM, TyreCompound.HARD]:
            analysis = self.tyre_model.analyze_compound(compound, self.track)
            
            pace_delta = f"{analysis.pace_delta_vs_medium_ms/1000:+.1f}s"
            if compound == TyreCompound.MEDIUM:
                pace_delta = "baseline"
            
            if compound == TyreCompound.SOFT:
                best_for = "Quali, short stints, SC restarts"
            elif compound == TyreCompound.MEDIUM:
                best_for = "Balanced, most versatile"
            else:
                best_for = "Long stints, hot conditions"
            
            color = {"SOFT": "red", "MEDIUM": "yellow", "HARD": "white"}[compound.name]
            
            table.add_row(
                f"[{color}]{compound.name}[/{color}]",
                f"{analysis.expected_life_laps} laps",
                f"{analysis.degradation_per_lap:.4f}",
                f"{analysis.cliff_at_wear:.0%}",
                pace_delta,
                best_for,
            )
        
        # Inter/Wet
        if self.weather_forecast and any(w.is_raining for w in self.weather_forecast):
            for compound in [TyreCompound.INTER, TyreCompound.WET]:
                analysis = self.tyre_model.analyze_compound(compound, self.track)
                color = "green" if compound == TyreCompound.INTER else "blue"
                table.add_row(
                    f"[{color}]{compound.name}[/{color}]",
                    f"{analysis.expected_life_laps} laps",
                    f"{analysis.degradation_per_lap:.4f}",
                    f"{analysis.cliff_at_wear:.0%}",
                    "N/A",
                    "Wet conditions",
                )
        
        console.print(table)
        
        # Strategy implication
        optimal_s = self.tyre_model.get_optimal_stint_length(TyreCompound.SOFT, self.track)
        optimal_m = self.tyre_model.get_optimal_stint_length(TyreCompound.MEDIUM, self.track)
        optimal_h = self.tyre_model.get_optimal_stint_length(TyreCompound.HARD, self.track)
        
        console.print()
        console.print(f"  [dim]Optimal stint lengths: S={optimal_s} laps | M={optimal_m} laps | H={optimal_h} laps[/dim]")
        
        # Number of stops recommendation
        total = self.track.laps
        for name, stint in [("S→M", optimal_s + optimal_m), ("M→H", optimal_m + optimal_h),
                            ("S→M→H", optimal_s + optimal_m + optimal_h)]:
            if stint >= total:
                console.print(f"  [green]✓ {name} strategy viable ({stint} laps)[/green]")
            else:
                console.print(f"  [red]✗ {name} strategy too short ({stint} laps)[/red]")
    
    def show_weather(self):
        """Display weather forecast."""
        if not self.weather_forecast:
            console.print("[dim]No weather forecast data available[/dim]")
            return
        
        table = Table(
            title="🌦️ Weather Forecast",
            show_header=True,
            header_style="bold cyan",
            expand=True,
        )
        
        table.add_column("Period", width=10)
        table.add_column("Condition", width=15)
        table.add_column("Rain", width=8, justify="center")
        table.add_column("Ambient", width=10, justify="center")
        table.add_column("Track", width=10, justify="center")
        table.add_column("Implication", width=25)
        
        for w in self.weather_forecast:
            rain_pct = f"{w.rain:.0%}"
            if w.is_raining:
                condition = "[blue]🌧️ RAIN[/blue]"
                impl = f"Need {'WET' if w.rain > 0.5 else 'INTER'} tyres"
            else:
                condition = f"[yellow]☀️ {w.weather_state.name}[/yellow]"
                impl = "Dry tyres OK"
            
            table.add_row(
                f"L{w.time}",
                condition,
                rain_pct,
                f"{w.ambient_temp:.0f}°C",
                f"{w.track_temp:.0f}°C",
                impl,
            )
        
        console.print(table)
    
    def show_competitors(self):
        """Display competitor analysis."""
        if not self.drivers:
            console.print("[dim]No driver data available[/dim]")
            return
        
        table = Table(
            title="🏎️ Competitor Analysis",
            show_header=True,
            header_style="bold cyan",
            expand=True,
        )
        
        table.add_column("Team", width=12)
        table.add_column("Driver", width=8)
        table.add_column("Rating", width=8, justify="center")
        table.add_column("Aggr", width=6, justify="center")
        table.add_column("Car Perf", width=10)
        table.add_column("Threat", width=8)
        
        my_drivers = [d for d in self.drivers if d.team_id == self.my_team_id]
        other_drivers = [d for d in self.drivers if d.team_id != self.my_team_id]
        
        # Sort by rating
        all_drivers = sorted(self.drivers, key=lambda d: d.overall_rating, reverse=True)
        
        for d in all_drivers:
            is_mine = d.team_id == self.my_team_id
            style = "bold green" if is_mine else ""
            
            # Car performance
            stats = self.car_stats.get(d.team_id)
            if stats:
                car_perf = f"TS:{stats.top_speed:.0f} Acc:{stats.acceleration:.0f}"
            else:
                car_perf = "N/A"
            
            # Threat level
            if is_mine:
                threat = "[green]YOU[/green]"
            elif d.overall_rating > 85:
                threat = "[red]HIGH[/red]"
            elif d.overall_rating > 70:
                threat = "[yellow]MED[/yellow]"
            else:
                threat = "[dim]LOW[/dim]"
            
            table.add_row(
                f"Team {d.team_id}",
                d.abbreviation or f"#{d.staff_id}",
                str(d.overall_rating),
                str(d.aggression),
                car_perf,
                threat,
                style=style,
            )
        
        console.print(table)
    
    def show_car_performance(self):
        """Display car performance comparison."""
        if not self.car_stats:
            console.print("[dim]No car performance data available[/dim]")
            return
        
        table = Table(
            title="📊 Car Performance Comparison",
            show_header=True,
            header_style="bold cyan",
            expand=True,
        )
        
        table.add_column("Team", width=10)
        table.add_column("Top Speed", width=10, justify="center")
        table.add_column("Accel", width=8, justify="center")
        table.add_column("Braking", width=8, justify="center")
        table.add_column("Cornering", width=10, justify="center")
        table.add_column("Tyre Pres", width=10, justify="center")
        
        for team_id, stats in sorted(self.car_stats.items()):
            is_mine = team_id == self.my_team_id
            style = "bold green" if is_mine else ""
            
            def color_bar(val, max_val=100):
                pct = val / max_val
                if pct > 0.7:
                    return f"[green]{val:.0f}[/green]"
                elif pct > 0.4:
                    return f"[yellow]{val:.0f}[/yellow]"
                else:
                    return f"[red]{val:.0f}[/red]"
            
            table.add_row(
                f"Team {team_id}{' (YOU)' if is_mine else ''}",
                color_bar(stats.top_speed),
                color_bar(stats.acceleration),
                color_bar(stats.braking),
                color_bar(stats.cornering),
                color_bar(stats.tyre_preservation),
                style=style,
            )
        
        console.print(table)
    
    def show_strategy_plan(self):
        """Display strategy options and recommendations."""
        console.print("[bold]📋 STRATEGY OPTIONS[/bold]")
        console.print()
        
        # 1-stop strategies
        console.print("[bold cyan]1-Stop Strategies:[/bold cyan]")
        for name, stint1, stint2 in [
            ("S → M", 18, 39),
            ("M → H", 25, 32),
            ("H → M", 30, 27),
        ]:
            if stint1 + stint2 >= self.track.laps:
                console.print(f"  [green]✓[/green] {name}: Stint 1={stint1} laps, Stint 2={stint2} laps")
            else:
                console.print(f"  [red]✗[/red] {name}: Too short ({stint1+stint2} laps)")
        
        # 2-stop strategies
        console.print()
        console.print("[bold cyan]2-Stop Strategies:[/bold cyan]")
        for name, s1, s2, s3 in [
            ("S → S → M", 15, 15, 27),
            ("S → M → M", 15, 20, 22),
            ("M → M → H", 20, 18, 19),
        ]:
            if s1 + s2 + s3 >= self.track.laps:
                console.print(f"  [green]✓[/green] {name}: {s1}+{s2}+{s3} laps")
            else:
                console.print(f"  [red]✗[/red] {name}: Too short ({s1+s2+s3} laps)")
        
        # Safety car impact
        console.print()
        console.print(f"[bold]Safety Car Impact:[/bold]")
        time_saved = self.track.pit_lane_time_loss - self.track.safety_car_time_loss
        console.print(f"  Time saved pitting under SC: [bold green]{time_saved}s[/bold green]")
        if self.track.safety_car_chance > 0.5:
            console.print(f"  [yellow]⚠️ High SC chance ({self.track.safety_car_chance:.0%}) — keep strategy flexible[/yellow]")
        
        # Pace controller preview
        console.print()
        console.print("[bold]Available Pace Modes:[/bold]")
        for name, mode in PACE_MODES.items():
            console.print(f"  [cyan]{name:10s}[/cyan] — {mode.description}")
        
        console.print()
        console.print("[bold]Available ERS Modes:[/bold]")
        for name, mode in ERS_MODES.items():
            console.print(f"  [cyan]{name:10s}[/cyan] — {mode.description}")
    
    def show_championship_context(self):
        """Display championship standings context."""
        console.print("[dim]Championship context — requires save file data[/dim]")
