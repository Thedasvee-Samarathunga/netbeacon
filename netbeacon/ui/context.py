"""AppContext: the shared hub every page talks to (store, history, engine, signals, helpers)."""
from __future__ import annotations

import time
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal

from .. import config_writer
from ..engine import EngineCore, LoopInfo
from ..store import History, MonitorDef, Store


class AppContext(QObject):
    snapshot_changed = Signal(list)
    event_added = Signal(dict)
    status_changed = Signal(object)
    problems_changed = Signal(list)
    notification = Signal(str, str, str)
    settings_changed = Signal()
    checks_changed = Signal()
    navigate = Signal(str)
    toast_requested = Signal(str, str)
    theme_changed = Signal(str)
    devices_changed = Signal()          # a scan finished or a device was renamed / marked known

    def __init__(self, store: Store, history: History, core: EngineCore) -> None:
        super().__init__()
        self.store = store
        self.history = history
        self.core = core
        self.snapshot: list[dict] = []
        self.problems: list[str] = []
        self.main_window: Optional[Any] = None
        # engine thread -> Qt thread (signals queue automatically across threads)
        core.on_snapshot.append(self._on_snapshot)
        core.on_event.append(self._on_event)
        core.on_status.append(self._on_status)
        core.on_problems.append(self._on_problems)
        core.on_notify.append(self._on_notify)
        self._avail_cache: dict[str, tuple[float, dict]] = {}

    # ---- engine callbacks (called on the engine thread)
    def _on_snapshot(self, rows: list[dict]) -> None:
        self.snapshot_changed.emit(self.enrich(rows))

    def _on_event(self, ev: dict) -> None:
        self.event_added.emit(ev)

    def _on_status(self, info: LoopInfo) -> None:
        self.status_changed.emit(info)

    def _on_problems(self, problems: list[str]) -> None:
        self.problems_changed.emit(list(problems))

    def _on_notify(self, title: str, text: str, level: str) -> None:
        self.notification.emit(title, text, level)

    # ---- helpers
    def enrich(self, rows: list[dict], window_s: int = 86400) -> list[dict]:
        """Add 24h availability and the recent-results bars to each snapshot row."""
        since = time.time() - window_s
        for r in rows:
            try:
                av = self.history.availability(r["name"], since)
                r["avail"] = av["pct"]
                r["bars"] = self.history.recent_statuses(r["name"], 40)
            except Exception:
                r["avail"], r["bars"] = None, []
        return rows

    def apply_changes(self) -> None:
        """Call after any change to checks or settings: rewrites the INI files and reloads the engine."""
        self.core.reload()
        self.checks_changed.emit()

    def toast(self, text: str, level: str = "info") -> None:
        self.toast_requested.emit(text, level)

    def goto(self, page: str) -> None:
        self.navigate.emit(page)

    def monitor_names(self) -> list[str]:
        return [m.name for m in self.store.monitors]

    def preview(self, m: MonitorDef) -> str:
        return config_writer.preview_section(m, self.store)

    @property
    def teaching(self) -> bool:
        return bool(self.store.get("teaching_mode", True))
