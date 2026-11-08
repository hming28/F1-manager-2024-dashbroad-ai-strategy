"""
notifications.py — Smart notification system for F1 Manager 2024 Strategy AI.

Core principle: "Silent when things are fine, loud when action is needed."

Priority levels:
  0 = SILENT    — never shown (normal laps)
  1 = INFO      — shown once, then suppressed (track evolution)
  2 = NOTICE    — shown briefly (tyre warming up, ERS full)
  3 = WARNING   — highlighted (tyre < 40%, weather changing)
  4 = URGENT    — red alert + sound (tyre cliff approaching, pit window)
  5 = CRITICAL  — flashing + loud sound (safety car, tyre destroyed, rain start)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.table import Table


class Priority(IntEnum):
    SILENT = 0
    INFO = 1
    NOTICE = 2
    WARNING = 3
    URGENT = 4
    CRITICAL = 5


@dataclass
class Notification:
    """A single notification event."""
    priority: Priority
    category: str       # "TYRE" / "WEATHER" / "SAFETY_CAR" / "PIT" / "ERS" / "INTEL" / "DAMAGE"
    title: str          # Short headline (max ~50 chars)
    detail: str         # One line of detail
    action: str         # What to do
    timestamp: float = field(default_factory=time.time)
    lap: int = 0
    sound: str = ""     # "beep" / "alert" / "alarm" / ""


# ── Sound patterns (ASCII bell codes) ────────────────────────────────────────

SOUND_MAP = {
    "beep":  "\a",           # single terminal bell
    "alert": "\a\a",         # double beep
    "alarm": "\a\a\a",       # triple beep (urgent)
    "": "",
}

# ── Style map ────────────────────────────────────────────────────────────────

PRIORITY_STYLE = {
    Priority.SILENT:  "dim",
    Priority.INFO:    "dim white",
    Priority.NOTICE:  "cyan",
    Priority.WARNING: "yellow",
    Priority.URGENT:  "bold red",
    Priority.CRITICAL:"bold white on red",
}

PRIORITY_ICON = {
    Priority.SILENT:  "",
    Priority.INFO:    "ℹ️ ",
    Priority.NOTICE:  "💡",
    Priority.WARNING: "⚠️ ",
    Priority.URGENT:  "🔔",
    Priority.CRITICAL:"🚨",
}


class NotificationManager:
    """
    Manages notification display with deduplication and throttling.
    
    Usage:
        nm = NotificationManager()
        nm.push(Notification(Priority.URGENT, "TYRE", "Tyres critical", ...))
        nm.flush()  # prints all pending notifications
    """
    
    def __init__(self, console: Optional[Console] = None,
                 suppress_below: Priority = Priority.INFO,
                 dedup_window_sec: float = 30.0,
                 enable_sound: bool = True):
        self.console = console or Console()
        self.suppress_below = suppress_below
        self.dedup_window = dedup_window_sec
        self.enable_sound = enable_sound
        
        self._pending: list[Notification] = []
        self._history: list[Notification] = []
        self._last_shown: dict[str, float] = {}  # category -> timestamp
        self._last_shown_detail: dict[str, str] = {}  # category -> detail hash
    
    def push(self, notif: Notification):
        """Queue a notification for display."""
        # Deduplication: skip if same category+detail shown recently
        key = f"{notif.category}:{notif.title}"
        now = time.time()
        
        if key in self._last_shown:
            elapsed = now - self._last_shown[key]
            if elapsed < self.dedup_window and self._last_shown_detail.get(key) == notif.detail:
                return  # suppress duplicate
        
        # Priority filter
        if notif.priority < self.suppress_below:
            return
        
        self._pending.append(notif)
        self._history.append(notif)
        self._last_shown[key] = now
        self._last_shown_detail[key] = notif.detail
    
    def flush(self) -> list[Notification]:
        """
        Display all pending notifications and clear the queue.
        Returns the list of displayed notifications.
        """
        if not self._pending:
            return []
        
        # Sort by priority (highest first)
        self._pending.sort(key=lambda n: n.priority, reverse=True)
        
        displayed = []
        for notif in self._pending:
            self._display_single(notif)
            displayed.append(notif)
            
            # Play sound
            if self.enable_sound and notif.sound:
                sound_char = SOUND_MAP.get(notif.sound, "")
                if sound_char:
                    self.console.file.write(sound_char)
                    self.console.file.flush()
        
        self._pending.clear()
        return displayed
    
    def _display_single(self, notif: Notification):
        """Display a single notification."""
        style = PRIORITY_STYLE.get(notif.priority, "white")
        icon = PRIORITY_ICON.get(notif.priority, "")
        
        lap_str = f"L{notif.lap}" if notif.lap > 0 else ""
        
        # Format: [STYLE] ICON LAP | TITLE — DETAIL → ACTION
        line = Text()
        line.append(f" {icon} ", style=style)
        if lap_str:
            line.append(f"{lap_str} ", style="dim")
        line.append(f"{notif.title}", style=style)
        if notif.detail:
            line.append(f" — {notif.detail}", style="dim")
        if notif.action:
            line.append(f" → ", style="dim")
            line.append(f"{notif.action}", style="bold " + style.split()[-1])
        
        self.console.print(line)
    
    def get_stats(self) -> dict:
        """Get notification statistics."""
        by_priority = {}
        for n in self._history:
            by_priority[n.priority.name] = by_priority.get(n.priority.name, 0) + 1
        return {
            "total": len(self._history),
            "by_priority": by_priority,
        }
    
    def clear_history(self):
        self._history.clear()
        self._last_shown.clear()
        self._last_shown_detail.clear()


# ── Convenience factory ──────────────────────────────────────────────────────

def make_tyre_warning(lap: int, condition: float, remaining: int) -> Notification:
    if condition < 0.20:
        return Notification(
            Priority.CRITICAL, "TYRE",
            f"🛞 Tyre Puncture Risk! ({condition:.0%})",
            f"Est. {remaining} laps remaining",
            "BOX NOW!",
            sound="alarm",
            lap=lap,
        )
    elif condition < 0.35:
        return Notification(
            Priority.URGENT, "TYRE",
            f"🛞 Severe Tyre Degradation ({condition:.0%})",
            f"Est. {remaining} laps remaining",
            "Box within 2 laps",
            sound="alert",
            lap=lap,
        )
    elif condition < 0.50:
        return Notification(
            Priority.WARNING, "TYRE",
            f"🛞 Moderate Tyre Wear ({condition:.0%})",
            f"Est. {remaining} laps remaining",
            "Prepare pit window",
            lap=lap,
        )
    return None


def make_weather_alert(lap: int, rain: float, water: float, 
                       compound: str) -> Optional[Notification]:
    if rain > 0.50:
        return Notification(
            Priority.CRITICAL, "WEATHER",
            "🌧️ Heavy Rain Incoming!",
            f"Rain {rain:.0%}, Track wetness {water:.0%}",
            f"Box for {compound} tyres now!",
            sound="alarm",
            lap=lap,
        )
    elif rain > 0.15:
        return Notification(
            Priority.URGENT, "WEATHER",
            "🌦️ Rain Starting",
            f"Rain {rain:.0%}, Track wetness {water:.0%}",
            f"Prepare for {compound} tyres",
            sound="alert",
            lap=lap,
        )
    elif rain > 0.05:
        return Notification(
            Priority.NOTICE, "WEATHER",
            "☁️ Light Drizzle",
            f"Rain intensity {rain:.0%}",
            "Monitor weather radar",
            lap=lap,
        )
    return None


def make_safety_car_alert(lap: int, time_saved: float, 
                          should_pit: bool) -> Notification:
    if should_pit:
        return Notification(
            Priority.CRITICAL, "SAFETY_CAR",
            "🚨 Safety Car — Free Pit Window!",
            f"Saves ~{time_saved:.1f}s pit delta",
            "Box this lap for cheap stop!",
            sound="alarm",
            lap=lap,
        )
    else:
        return Notification(
            Priority.URGENT, "SAFETY_CAR",
            "🟡 Safety Car Deployed",
            f"Pit loss reduced to {time_saved:.1f}s",
            "Evaluate pit stop opportunity",
            sound="alert",
            lap=lap,
        )


def make_pit_window(lap: int, target_lap: int, compound: str, 
                    gain_ms: int) -> Notification:
    if gain_ms > 3000:
        return Notification(
            Priority.URGENT, "PIT",
            f"📦 Optimal Pit Window: Lap {target_lap}",
            f"Fit {compound}, estimated gain +{gain_ms/1000:.1f}s",
            f"Box lap {target_lap}",
            sound="alert",
            lap=lap,
        )
    elif gain_ms > 1000:
        return Notification(
            Priority.WARNING, "PIT",
            f"📦 Pit Window Open: Lap {target_lap}",
            f"Fit {compound}, estimated gain +{gain_ms/1000:.1f}s",
            "Pit stop available",
            lap=lap,
        )
    return None


def make_undercut_alert(lap: int, target_pos: int, gap: float, 
                        target_lap: int) -> Notification:
    return Notification(
        Priority.WARNING, "INTEL",
        f"⚡ Undercut Opportunity: P{target_pos}",
        f"Gap {gap:.1f}s, rival tyre delta advantage",
        f"Box lap {target_lap} to undercut",
        sound="beep",
        lap=lap,
    )


def make_ers_alert(lap: int, charge: float) -> Optional[Notification]:
    if charge > 0.90:
        return Notification(
            Priority.NOTICE, "ERS",
            "⚡ ERS Battery Full",
            f"Charge {charge:.0%}",
            "Deploy overtake mode",
            lap=lap,
        )
    elif charge < 0.15:
        return Notification(
            Priority.WARNING, "ERS",
            "🔋 ERS Battery Low",
            f"Charge {charge:.0%}",
            "Switch to harvest mode",
            lap=lap,
        )
    return None


def make_damage_alert(lap: int, severity: int, parts: str) -> Notification:
    if severity > 10:
        return Notification(
            Priority.URGENT, "DAMAGE",
            f"🔧 Critical Damage ({severity}/18)",
            parts,
            "Consider pitting for repairs",
            sound="alert",
            lap=lap,
        )
    elif severity > 5:
        return Notification(
            Priority.WARNING, "DAMAGE",
            f"🔧 Moderate Damage ({severity}/18)",
            parts,
            "Monitor pace impact",
            lap=lap,
        )
    return None
