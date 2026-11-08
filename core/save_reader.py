"""
save_reader.py — F1 Manager 2024 .sav file unpacker.

Wraps savefile_codec.py to extract the SQLite database from game saves.
Handles auto-detection of the save directory and latest save file.
"""
from __future__ import annotations

import glob
import logging
import os
import pathlib
import platform
import sqlite3
import tempfile
import time
from typing import Optional

from core.savefile_codec import unpack_bytes, Unpacked

logger = logging.getLogger(__name__)

# ── Save directory auto-detection ────────────────────────────────────────────

def _default_save_dir() -> pathlib.Path:
    """
    Auto-detect the F1 Manager 2024 save directory.
    Works on Windows and WSL.
    """
    system = platform.system()
    
    if system == "Windows":
        base = pathlib.Path(os.environ.get("LOCALAPPDATA", ""))
    elif system == "Linux":
        # WSL: check if we can access Windows filesystem
        wsl_base = pathlib.Path("/mnt/c/Users")
        if wsl_base.exists():
            # Find the Windows user
            users = [d for d in wsl_base.iterdir() if d.is_dir() 
                     and d.name not in ("Public", "Default", "Default User")]
            if users:
                # Try common user (first non-system user)
                for user in users:
                    candidate = user / "AppData" / "Local"
                    if candidate.exists():
                        base = candidate
                        break
                else:
                    base = users[0] / "AppData" / "Local"
            else:
                raise FileNotFoundError("Cannot find Windows user directory in WSL")
        else:
            # Native Linux - check for Proton/Wine prefix
            home = pathlib.Path.home()
            candidate = home / ".local" / "share" / "Steam" / "steamapps" / "compatdata"
            if candidate.exists():
                # Look for F1 Manager 2024 Proton prefix
                for prefix in candidate.iterdir():
                    pfx_save = prefix / "pfx" / "drive_c" / "users" / "steamuser" / "AppData" / "Local"
                    if pfx_save.exists() and any(pfx_save.glob("F1Manager*")):
                        base = pfx_save
                        break
                else:
                    raise FileNotFoundError("Cannot find F1 Manager 2024 save directory (Proton)")
            else:
                raise FileNotFoundError("Cannot find F1 Manager 2024 save directory")
    else:
        raise FileNotFoundError(f"Unsupported OS: {system}")
    
    # F1 Manager 2024 save location patterns
    patterns = [
        "F1Manager24/Saved/SaveGames",
        "F1Manager2024/Saved/SaveGames",
        "F1 Manager 24/Saved/SaveGames",
    ]
    
    for pattern in patterns:
        candidate = base / pattern
        if candidate.exists():
            logger.info(f"Found save directory: {candidate}")
            return candidate
    
    # Fallback: search
    for candidate in base.glob("*F1*Manager*/Saved/SaveGames"):
        if candidate.is_dir():
            logger.info(f"Found save directory (glob): {candidate}")
            return candidate
    
    raise FileNotFoundError(
        f"Cannot find F1 Manager 2024 save directory under {base}. "
        f"Set save_dir manually in config.yaml"
    )


# ── Save file operations ────────────────────────────────────────────────────

class SaveReader:
    """
    Reads F1 Manager 2024 .sav files and returns SQLite database connections.
    
    Usage:
        reader = SaveReader()
        conn = reader.get_latest_db()
        # ... query with conn ...
        conn.close()
    """
    
    def __init__(self, save_dir: Optional[str] = None):
        if save_dir:
            self.save_dir = pathlib.Path(save_dir)
        else:
            self.save_dir = _default_save_dir()
        
        if not self.save_dir.exists():
            raise FileNotFoundError(f"Save directory not found: {self.save_dir}")
        
        self._temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="f1m24_"))
        self._last_db_path: Optional[pathlib.Path] = None
        self._last_db_time: float = 0
        
        logger.info(f"SaveReader initialized: {self.save_dir}")
    
    def list_saves(self) -> list[pathlib.Path]:
        """List all .sav files sorted by modification time (newest first)."""
        saves = list(self.save_dir.glob("*.sav"))
        saves.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return saves
    
    def get_latest_save(self) -> Optional[pathlib.Path]:
        """Get the most recently modified .sav file."""
        saves = self.list_saves()
        return saves[0] if saves else None
    
    def has_newer_save(self) -> bool:
        """Check if the latest save is newer than our last read."""
        latest = self.get_latest_save()
        if latest is None:
            return False
        return latest.stat().st_mtime > self._last_db_time
    
    def unpack_save(self, save_path: pathlib.Path) -> pathlib.Path:
        """
        Unpack a .sav file and return the path to the extracted main.db.
        
        The .sav format: GVAS header + zlib-compressed SQLite databases.
        """
        logger.info(f"Unpacking: {save_path.name} ({save_path.stat().st_size / 1024:.1f} KB)")
        
        data = save_path.read_bytes()
        result = unpack_bytes(data)
        
        # Write main.db to temp directory
        db_path = self._temp_dir / f"{save_path.stem}_main.db"
        db_path.write_bytes(result.main_db)
        
        logger.info(f"Extracted DB: {db_path} ({len(result.main_db) / 1024:.1f} KB)")
        return db_path
    
    def get_db(self, save_path: Optional[pathlib.Path] = None) -> sqlite3.Connection:
        """
        Get a read-only SQLite connection to a save file's database.
        
        Args:
            save_path: Specific .sav file. If None, uses the latest save.
            
        Returns:
            sqlite3.Connection (read-only, row_factory=Row)
        """
        if save_path is None:
            save_path = self.get_latest_save()
            if save_path is None:
                raise FileNotFoundError("No .sav files found in save directory")
        
        db_path = self.unpack_save(save_path)
        
        # Open read-only connection
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        
        self._last_db_path = db_path
        self._last_db_time = save_path.stat().st_mtime
        
        return conn
    
    def get_latest_db(self) -> sqlite3.Connection:
        """Convenience: get DB connection for the most recent save."""
        return self.get_db(None)
    
    def get_latest_db_if_changed(self) -> Optional[sqlite3.Connection]:
        """
        Get DB connection only if the save file has changed since last read.
        Returns None if no change detected.
        """
        if not self.has_newer_save():
            return None
        
        latest = self.get_latest_save()
        if latest is None:
            return None
        
        return self.get_db(latest)
    
    def cleanup(self):
        """Remove temporary extracted databases."""
        import shutil
        if self._temp_dir.exists():
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            logger.debug(f"Cleaned up temp dir: {self._temp_dir}")
    
    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass


# ── Utility functions ────────────────────────────────────────────────────────

def quick_read_latest(save_dir: Optional[str] = None) -> sqlite3.Connection:
    """One-liner to get a DB connection for the latest save."""
    reader = SaveReader(save_dir)
    return reader.get_latest_db()


def discover_schema(conn: sqlite3.Connection) -> dict[str, int]:
    """
    Discover all tables and their row counts.
    Useful for debugging and understanding save state.
    """
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    
    schema = {}
    for (table_name,) in tables:
        try:
            count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
            schema[table_name] = count
        except Exception:
            schema[table_name] = -1
    
    return schema
