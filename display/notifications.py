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
            f"🛞 轮胎即将报废！({condition:.0%})",
            f"剩余约 {remaining} 圈",
            "立刻进站！",
            sound="alarm",
            lap=lap,
        )
    elif condition < 0.35:
        return Notification(
            Priority.URGENT, "TYRE",
            f"🛞 轮胎严重衰退 ({condition:.0%})",
            f"剩余约 {remaining} 圈",
            "建议 2 圈内进站",
            sound="alert",
            lap=lap,
        )
    elif condition < 0.50:
        return Notification(
            Priority.WARNING, "TYRE",
            f"🛞 轮胎中度磨损 ({condition:.0%})",
            f"剩余约 {remaining} 圈",
            "开始考虑进站窗口",
            lap=lap,
        )
    return None


def make_weather_alert(lap: int, rain: float, water: float, 
                       compound: str) -> Optional[Notification]:
    if rain > 0.50:
        return Notification(
            Priority.CRITICAL, "WEATHER",
            "🌧️ 大雨来袭！",
            f"雨量 {rain:.0%}，赛道积水 {water:.0%}",
            f"立刻换 {compound} 胎！",
            sound="alarm",
            lap=lap,
        )
    elif rain > 0.15:
        return Notification(
            Priority.URGENT, "WEATHER",
            "🌦️ 开始下雨",
            f"雨量 {rain:.0%}，积水 {water:.0%}",
            f"准备换 {compound} 胎",
            sound="alert",
            lap=lap,
        )
    elif rain > 0.05:
        return Notification(
            Priority.NOTICE, "WEATHER",
            "☁️ 零星小雨",
            f"雨量 {rain:.0%}",
            "监控天气变化",
            lap=lap,
        )
    return None


def make_safety_car_alert(lap: int, time_saved: float, 
                          should_pit: bool) -> Notification:
    if should_pit:
        return Notification(
            Priority.CRITICAL, "SAFETY_CAR",
            "🚨 安全车 — 免费进站机会！",
            f"可节省 {time_saved:.1f} 秒",
            "立刻进站换胎！",
            sound="alarm",
            lap=lap,
        )
    else:
        return Notification(
            Priority.URGENT, "SAFETY_CAR",
            "🟡 安全车出动",
            f"维修区损失仅 {time_saved:.1f}s",
            "评估是否进站",
            sound="alert",
            lap=lap,
        )


def make_pit_window(lap: int, target_lap: int, compound: str, 
                    gain_ms: int) -> Notification:
    if gain_ms > 3000:
        return Notification(
            Priority.URGENT, "PIT",
            f"📦 最佳进站窗口：第 {target_lap} 圈",
            f"换 {compound} 胎，预计收益 +{gain_ms/1000:.1f}s",
            f"第 {target_lap} 圈进站",
            sound="alert",
            lap=lap,
        )
    elif gain_ms > 1000:
        return Notification(
            Priority.WARNING, "PIT",
            f"📦 进站窗口打开：第 {target_lap} 圈",
            f"换 {compound} 胎，收益 +{gain_ms/1000:.1f}s",
            "可选择进站",
            lap=lap,
        )
    return None


def make_undercut_alert(lap: int, target_pos: int, gap: float, 
                        target_lap: int) -> Notification:
    return Notification(
        Priority.WARNING, "INTEL",
        f"⚡ Undercut 机会：P{target_pos}",
        f"差距 {gap:.1f}s，对手轮胎更好",
        f"第 {target_lap} 圈进站可反超",
        sound="beep",
        lap=lap,
    )


def make_ers_alert(lap: int, charge: float) -> Optional[Notification]:
    if charge > 0.90:
        return Notification(
            Priority.NOTICE, "ERS",
            "⚡ ERS 满电",
            f"电量 {charge:.0%}",
            "可以全功率超车",
            lap=lap,
        )
    elif charge < 0.15:
        return Notification(
            Priority.WARNING, "ERS",
            "🔋 ERS 电量低",
            f"电量 {charge:.0%}",
            "切换回收模式",
            lap=lap,
        )
    return None


def make_damage_alert(lap: int, severity: int, parts: str) -> Notification:
    if severity > 10:
        return Notification(
            Priority.URGENT, "DAMAGE",
            f"🔧 严重损伤 ({severity}/18)",
            parts,
            "考虑进站维修",
            sound="alert",
            lap=lap,
        )
    elif severity > 5:
        return Notification(
            Priority.WARNING, "DAMAGE",
            f"🔧 中度损伤 ({severity}/18)",
            parts,
            "监控性能影响",
            lap=lap,
        )
    return None
