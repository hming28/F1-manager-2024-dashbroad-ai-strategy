"""
main.py — Entry point for F1 Manager 2024 AI Strategy System.

Usage:
    # Auto-detect save directory and start monitoring
    python main.py
    
    # Specify save directory
    python main.py --save-dir "C:/Users/You/AppData/Local/F1Manager24/Saved/SaveGames"
    
    # Specify team ID
    python main.py --team 3
    
    # One-shot analysis (no monitoring)
    python main.py --once
    
    # Discover schema (debug)
    python main.py --schema
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.live import Live

from core.save_reader import SaveReader, discover_schema
from core.db_accessor import (
    build_race_snapshot, get_tracks, get_driver_data, get_team_standings,
)
from core.file_watcher import SaveWatcher, SavePoller
from core.live_timing_reader import LiveTimingReader
from strategy.engine import StrategyEngine
from display.dashboard import Dashboard

console = Console()


# ── Logging setup ────────────────────────────────────────────────────────────

def setup_logging(level: str = "INFO", log_file: Optional[str] = None):
    handlers = [logging.StreamHandler(sys.stderr)]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


# ── Core logic ───────────────────────────────────────────────────────────────

def discover_save_dir() -> Optional[str]:
    """Try to auto-detect save directory."""
    try:
        reader = SaveReader()
        console.print(f"[green]✓[/green] Save directory: {reader.save_dir}")
        
        saves = reader.list_saves()
        if saves:
            console.print(f"[green]✓[/green] Found {len(saves)} save file(s)")
            for s in saves[:3]:
                size_kb = s.stat().st_size / 1024
                mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s.stat().st_mtime))
                console.print(f"  📄 {s.name} ({size_kb:.0f} KB, {mtime})")
        else:
            console.print("[yellow]⚠[/yellow] No .sav files found yet")
        
        return str(reader.save_dir)
    except FileNotFoundError as e:
        console.print(f"[red]✗[/red] {e}")
        return None


def run_schema_discovery(save_dir: Optional[str]):
    """Discover and display the database schema."""
    console.print("\n[bold cyan]═══ Schema Discovery ═══[/bold cyan]\n")
    
    reader = SaveReader(save_dir)
    conn = reader.get_latest_db()
    
    try:
        schema = discover_schema(conn)
        
        # Group by prefix
        groups: dict[str, list[tuple[str, int]]] = {}
        for name, count in schema.items():
            prefix = name.split("_")[0] if "_" in name else "Other"
            groups.setdefault(prefix, []).append((name, count))
        
        for group, tables in sorted(groups.items()):
            console.print(f"\n[bold]{group}[/bold] ({len(tables)} tables)")
            for name, count in sorted(tables):
                marker = "●" if count > 0 else "○"
                style = "green" if count > 0 else "dim"
                console.print(f"  [{style}]{marker}[/{style}] {name}: {count} rows")
        
        # Show tracks
        tracks = get_tracks(conn)
        if tracks:
            console.print(f"\n[bold cyan]Tracks ({len(tracks)}):[/bold cyan]")
            for t in tracks:
                console.print(
                    f"  {t.name}: {t.laps} laps, {t.track_length}km, "
                    f"SC chance: {t.safety_car_chance:.0%}, "
                    f"Pit loss: {t.pit_lane_time_loss}s"
                )
        
    finally:
        conn.close()
        reader.cleanup()


def run_once(save_dir: Optional[str], team_id: int):
    """Run a single analysis on the latest save."""
    console.print("\n[bold cyan]═══ One-Shot Analysis ═══[/bold cyan]\n")
    
    reader = SaveReader(save_dir)
    conn = reader.get_latest_db()
    
    try:
        # Get tracks
        tracks = get_tracks(conn)
        track = tracks[0] if tracks else None
        
        # Get drivers
        drivers = get_driver_data(conn)
        
        # Build snapshot
        snapshot = build_race_snapshot(conn)
        
        console.print(f"[green]✓[/green] Snapshot: {len(snapshot.cars)} cars")
        console.print(f"  Current lap: {snapshot.current_lap}")
        console.print(f"  Weather: {snapshot.weather.weather_state.name if snapshot.weather else 'N/A'}")
        console.print(f"  Safety car: {snapshot.is_safety_car}")
        
        if snapshot.cars:
            console.print("\n[bold]Position board:[/bold]")
            for car in sorted(snapshot.cars, key=lambda c: c.race_position):
                style = "bold green" if car.team_id == team_id else ""
                console.print(
                    f"  [{style}]P{car.race_position:2d} | Car#{car.car_index:2d} | "
                    f"Tyres {car.avg_tyre_condition:.0%} | "
                    f"ERS {car.ers_battery_charge:.0%} | "
                    f"Stops {car.pit_stops_had}[/{style}]"
                )
        
        # Run strategy engine
        if track:
            console.print(f"\n[bold cyan]Track: {track.name} ({track.laps} laps)[/bold cyan]")
            
            engine = StrategyEngine(
                my_team_id=team_id,
                track=track,
                drivers=drivers,
            )
            state = engine.update(snapshot)
            
            if state.recommendations:
                console.print("\n[bold]Strategy Recommendations:[/bold]")
                for rec in sorted(state.recommendations, key=lambda r: r.priority, reverse=True):
                    console.print(f"  [P{rec.priority}] {rec.title}")
                    console.print(f"    {rec.detail}")
                    console.print(f"    → {rec.action}")
            else:
                console.print("\n[dim]No recommendations at this time[/dim]")
        
    finally:
        conn.close()
        reader.cleanup()


def run_monitor(
    save_dir: Optional[str],
    team_id: int,
    use_watchdog: bool = True,
    live_path: Optional[str] = None,
    force_live: bool = False,
    force_save: bool = False,
):
    """Start the real-time monitoring mode with dual-mode auto-detection."""
    console.print("\n[bold cyan]═══ Real-Time Strategy Monitor (Dual Mode) ═══[/bold cyan]\n")
    console.print("[dim]Auto-detecting Live Timing in-race telemetry & save file updates...[/dim]\n")
    
    live_reader = LiveTimingReader(json_path=live_path)
    console.print(f"[green]✓[/green] Live Timing stream target: {live_reader.json_path}")

    reader = SaveReader(save_dir) if save_dir else None
    
    # Load initial data for track/driver info
    tracks = []
    drivers = []
    track = None
    
    if reader:
        try:
            conn = reader.get_latest_db()
            tracks = get_tracks(conn)
            drivers = get_driver_data(conn)
            conn.close()
        except Exception as e:
            console.print(f"[yellow]Warning: Could not load initial data: {e}[/yellow]")
    
    if tracks:
        # For now, use the first track (would need to detect from save)
        track = tracks[0]
        console.print(f"[green]✓[/green] Track: {track.name} ({track.laps} laps)")
    
    # Initialize engine
    engine = StrategyEngine(
        my_team_id=team_id,
        track=track or _default_track(),
        drivers=drivers,
    )
    dashboard = Dashboard(my_team_id=team_id, console=console)
    
    # State for updates
    latest_save_snapshot = None
    latest_save_state = None
    last_live_snapshot = None
    last_live_state = None
    running = True
    
    def on_save_update(snapshot, save_path):
        nonlocal latest_save_snapshot, latest_save_state
        latest_save_snapshot = snapshot
        latest_save_state = engine.update(snapshot)
    
    # Signal handler for clean exit
    def signal_handler(sig, frame):
        nonlocal running
        running = False
        console.print("\n[yellow]Shutting down...[/yellow]")
    
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start save watcher if not in force-live mode and save_dir is configured
    watcher = None
    if not force_live and save_dir:
        if use_watchdog:
            watcher = SaveWatcher(save_dir=save_dir, callback=on_save_update)
            watcher.start()
        else:
            watcher = SavePoller(save_dir=save_dir, callback=on_save_update, poll_interval_sec=1.0)
            watcher.start()
    
    # Live display loop (higher refresh rate to smoothly show sector and running times)
    try:
        with Live(console=console, refresh_per_second=5) as live:
            while running:
                is_live_active = (not force_save) and (force_live or live_reader.is_live())

                if is_live_active:
                    live_snapshot = live_reader.read_snapshot(base_track=track)
                    if live_snapshot and live_snapshot.cars:
                        live_state = engine.update(live_snapshot)
                        last_live_snapshot = live_snapshot
                        last_live_state = live_state
                        dashboard.render(live_snapshot, live_state, live=live)
                        time.sleep(0.20)
                        continue
                    elif last_live_snapshot and last_live_state and (force_live or live_reader.is_paused()):
                        # Keep displaying paused live snapshot without jarring fallback
                        dashboard.render(last_live_snapshot, last_live_state, live=live)
                        time.sleep(0.20)
                        continue

                # Fallback to savefile data when outside live 3D race
                if latest_save_snapshot and latest_save_state:
                    dashboard.render(latest_save_snapshot, latest_save_state, live=live)
                else:
                    from rich.panel import Panel
                    status_msg = (
                        "[dim]Waiting for data stream...\n"
                        f"• Live Timing: searching [cyan]{live_reader.json_path}[/cyan]\n"
                        f"• Save Watcher: monitoring [cyan]{save_dir or 'Not specified'}[/cyan]\n"
                        "Start or load a race in F1 Manager 2024 to begin.[/dim]"
                    )
                    live.update(Panel(status_msg, title="🏎️ F1 Strategy AI"))

                time.sleep(0.40)
    except KeyboardInterrupt:
        pass
    finally:
        if watcher:
            watcher.stop()
        console.print("[green]✓[/green] Stopped")


def _default_track():
    """Fallback track if none detected."""
    from core.models import Track, TrackType
    return Track(
        track_id=0, name="Unknown", country_id=0, laps=56,
        track_length=5.0, type_of_track=TrackType.BALANCED,
        fastest_lap=90.0, safety_car_chance=0.5,
        pit_lane_time_loss=22, green_flag_time_loss=20,
        safety_car_time_loss=12, sprint_laps=20,
    )


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="F1 Manager 2024 AI Strategy System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                    # Auto-detect and monitor
  python main.py --team 3           # Monitor for team 3
  python main.py --once             # One-shot analysis
  python main.py --schema           # Discover database schema
  python main.py --no-watchdog      # Use polling instead of watchdog
        """,
    )
    
    parser.add_argument(
        "--save-dir", "-d",
        help="Path to F1 Manager 2024 save directory",
    )
    parser.add_argument(
        "--team", "-t",
        type=int, default=0,
        help="Your team ID (1-10). 0 = auto-detect",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run single analysis and exit",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Discover database schema and exit",
    )
    parser.add_argument(
        "--no-watchdog",
        action="store_true",
        help="Use polling instead of watchdog for file monitoring",
    )
    parser.add_argument(
        "--live-path",
        help="Path to live_timing.json from UE4SS LiveTimingMod",
    )
    parser.add_argument(
        "--force-live",
        action="store_true",
        help="Force live timing mode without savefile fallback",
    )
    parser.add_argument(
        "--force-save",
        action="store_true",
        help="Disable live timing and force savefile monitoring only",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    parser.add_argument(
        "--log-file",
        help="Log to file",
    )
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.log_level, args.log_file)
    
    # Banner
    console.print("""
[bold cyan]╔══════════════════════════════════════════════════════════════╗
║           🏎️  F1 Manager 2024 — AI Strategy Engine  🏎️          ║
║                                                              ║
║   Real-time strategy analysis powered by save file parsing   ║
╚══════════════════════════════════════════════════════════════╝[/bold cyan]
    """)
    
    # Auto-detect save dir
    save_dir = args.save_dir
    if not save_dir:
        save_dir = discover_save_dir()
        if not save_dir and not args.force_live:
            console.print("[red]Cannot find save directory. Use --save-dir to specify.[/red]")
            sys.exit(1)
    
    # Run mode
    if args.schema:
        run_schema_discovery(save_dir)
    elif args.once:
        run_once(save_dir, args.team)
    else:
        run_monitor(
            save_dir,
            args.team,
            use_watchdog=not args.no_watchdog,
            live_path=args.live_path,
            force_live=args.force_live,
            force_save=args.force_save,
        )


if __name__ == "__main__":
    main()
