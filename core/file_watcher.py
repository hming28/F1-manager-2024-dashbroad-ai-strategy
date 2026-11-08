"""
file_watcher.py — Monitors F1 Manager 2024 save directory for changes.

When the game writes a new save, we detect it, unpack the database,
and trigger the strategy analysis pipeline.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent
from watchdog.observers import Observer

from core.save_reader import SaveReader
from core.db_accessor import build_race_snapshot, RaceSnapshot

logger = logging.getLogger(__name__)


# ── Callback type ────────────────────────────────────────────────────────────

# Called with (RaceSnapshot, save_path) when a new save is detected
OnSnapshotCallback = Callable[[RaceSnapshot, Path], None]


# ── Save file event handler ─────────────────────────────────────────────────

class SaveFileHandler(FileSystemEventHandler):
    """
    Watches for .sav file changes in the F1 Manager 2024 save directory.
    Debounces rapid writes (game may write multiple times quickly).
    """
    
    def __init__(self, callback: OnSnapshotCallback, reader: SaveReader,
                 debounce_ms: int = 500):
        super().__init__()
        self.callback = callback
        self.reader = reader
        self.debounce_sec = debounce_ms / 1000.0
        self._last_trigger: float = 0
        self._lock = threading.Lock()
        self._processing = False
    
    def on_modified(self, event):
        self._handle(event)
    
    def on_created(self, event):
        self._handle(event)
    
    def _handle(self, event):
        if event.is_directory:
            return
        
        path = Path(event.src_path)
        if path.suffix.lower() != ".sav":
            return
        
        # Debounce: skip if we just processed
        now = time.time()
        with self._lock:
            if now - self._last_trigger < self.debounce_sec:
                logger.debug(f"Debounced: {path.name}")
                return
            if self._processing:
                logger.debug(f"Already processing, skipping: {path.name}")
                return
            self._processing = True
            self._last_trigger = now
        
        try:
            logger.info(f"Save file changed: {path.name}")
            self._process_save(path)
        except Exception as e:
            logger.error(f"Error processing save {path.name}: {e}", exc_info=True)
        finally:
            with self._lock:
                self._processing = False
    
    def _process_save(self, save_path: Path):
        """Unpack save and build snapshot."""
        try:
            conn = self.reader.get_db(save_path)
            try:
                snapshot = build_race_snapshot(conn)
                logger.info(
                    f"Snapshot built: {len(snapshot.cars)} cars, "
                    f"lap {snapshot.current_lap}, "
                    f"weather={snapshot.weather.weather_state.name if snapshot.weather else 'N/A'}"
                )
                self.callback(snapshot, save_path)
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Failed to build snapshot: {e}", exc_info=True)


# ── Main watcher class ──────────────────────────────────────────────────────

class SaveWatcher:
    """
    High-level save file watcher.
    
    Usage:
        def on_update(snapshot, path):
            print(f"New snapshot from {path.name}")
            # ... run strategy analysis ...
        
        watcher = SaveWatcher(save_dir="C:/Users/...", callback=on_update)
        watcher.start()
        # ... program runs ...
        watcher.stop()
    """
    
    def __init__(self, save_dir: Optional[str] = None,
                 callback: Optional[OnSnapshotCallback] = None,
                 poll_interval_sec: float = 1.0):
        self.reader = SaveReader(save_dir)
        self.callback = callback or self._default_callback
        self.poll_interval = poll_interval_sec
        
        self._handler = SaveFileHandler(
            callback=self.callback,
            reader=self.reader,
            debounce_ms=500,
        )
        self._observer = Observer()
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
    
    @staticmethod
    def _default_callback(snapshot: RaceSnapshot, path: Path):
        logger.info(f"Default callback: {len(snapshot.cars)} cars at lap {snapshot.current_lap}")
    
    def start(self):
        """Start watching for save file changes."""
        if self._running:
            logger.warning("Watcher already running")
            return
        
        save_dir = str(self.reader.save_dir)
        logger.info(f"Starting save watcher on: {save_dir}")
        
        # Watchdog observer for file system events
        self._observer.schedule(
            self._handler,
            save_dir,
            recursive=False,
        )
        self._observer.start()
        
        # Also poll periodically as backup (some writes may not trigger FS events)
        self._running = True
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="save-poller",
        )
        self._poll_thread.start()
        
        logger.info("Save watcher started")
    
    def _poll_loop(self):
        """Backup polling loop in case FS events are missed."""
        while self._running:
            try:
                if self.reader.has_newer_save():
                    latest = self.reader.get_latest_save()
                    if latest:
                        logger.debug(f"Poll detected newer save: {latest.name}")
                        self._handler._process_save(latest)
            except Exception as e:
                logger.debug(f"Poll error: {e}")
            time.sleep(self.poll_interval)
    
    def stop(self):
        """Stop watching."""
        logger.info("Stopping save watcher...")
        self._running = False
        self._observer.stop()
        self._observer.join(timeout=5)
        if self._poll_thread:
            self._poll_thread.join(timeout=5)
        self.reader.cleanup()
        logger.info("Save watcher stopped")
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, *args):
        self.stop()


# ── Standalone polling mode (no watchdog dependency) ─────────────────────────

class SavePoller:
    """
    Simpler alternative to SaveWatcher — just polls the save directory.
    Use when watchdog is not available or not desired.
    """
    
    def __init__(self, save_dir: Optional[str] = None,
                 callback: Optional[OnSnapshotCallback] = None,
                 poll_interval_sec: float = 2.0):
        self.reader = SaveReader(save_dir)
        self.callback = callback or (lambda s, p: None)
        self.poll_interval = poll_interval_sec
        self._running = False
        self._thread: Optional[threading.Thread] = None
    
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="save-poller",
        )
        self._thread.start()
        logger.info(f"Polling every {self.poll_interval}s: {self.reader.save_dir}")
    
    def _loop(self):
        while self._running:
            try:
                if self.reader.has_newer_save():
                    latest = self.reader.get_latest_save()
                    if latest:
                        conn = self.reader.get_db(latest)
                        try:
                            snapshot = build_race_snapshot(conn)
                            self.callback(snapshot, latest)
                        finally:
                            conn.close()
            except Exception as e:
                logger.error(f"Poll error: {e}")
            time.sleep(self.poll_interval)
    
    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        self.reader.cleanup()
