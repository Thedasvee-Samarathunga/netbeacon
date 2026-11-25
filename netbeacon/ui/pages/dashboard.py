"""The home page: how is everything right now?"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QSplitter, QVBoxLayout, QWidget

from ... import netutil
from .. import theme
from ..check_table import make_table
from ..widgets import InfoBanner, PageHeader, StatCard, label, make_button
from .base import Page

LEVEL_COLORS = {"error": "#dc2626", "warn": "#f59e0b", "ok": "#16a34a", "info": "#64748b", "alert": "#2563eb"}


class DashboardPage(Page):
    key = "dashboard"
    title = "Dashboard"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        head = PageHeader("Dashboard", "Everything NetBeacon is watching, right now.")
        self.diag_btn = head.add_action(make_button("What's wrong?", tooltip="Test the connection step by step and find where it breaks."))
        self.diag_btn.clicked.connect(lambda: ctx.main_window.diagnose())
        self.add_btn = head.add_action(make_button("+ Add a check", "primary"))
        self.add_btn.clicked.connect(lambda: ctx.main_window.open_check_dialog())
        self.root.addWidget(head)
        self.root.addWidget(InfoBanner("dashboard"))

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.c_up = StatCard("Checks OK", "How many checks are currently passing.")
        self.c_down = StatCard("Problems", "Checks that are DOWN (failed more often than their tolerance allows).")
        self.c_avail = StatCard("Availability (24 h)", "Share of checks that succeeded over the last 24 hours. Brief retries count as OK.")
        self.c_lat = StatCard("Avg response (24 h)", "Average round-trip time of checks that measure it (ping, ports, web, DNS).")
        self.c_inc = StatCard("Incidents (24 h)", "Separate outages recorded in the last 24 hours. Open the Uptime page for details.")
        for c in (self.c_up, self.c_down, self.c_avail, self.c_lat, self.c_inc):
            cards.addWidget(c, 1)
        self.root.addLayout(cards)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search checks...")
        self.search.setClearButtonEnabled(True)
        self.group = QComboBox()
        self.group.setMinimumWidth(130)
        self.status = QComboBox()
        self.status.setMinimumWidth(140)
        for text, val in (("All statuses", ""), ("Problems only", "problem"), ("Up", "up"), ("Paused", "paused")):
            self.status.addItem(text, val)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.group)
        bar.addWidget(self.status)
        ll.addLayout(bar)
        self.view, self.model, self.proxy = make_table(["status", "name", "result", "response", "avail", "bars"])
        ll.addWidget(self.view, 1)
        self.empty = QFrame()
        self.empty.setObjectName("card")
        el = QVBoxLayout(self.empty)
        el.setContentsMargins(30, 30, 30, 30)
        el.addWidget(label("Nothing is being watched yet", "h2"))
        el.addWidget(label("Add your first check - a ping to your router is a perfect start - or run the Quick Start wizard from Settings.", "muted", wrap=True))
        b = make_button("Add a check", "primary")
        b.clicked.connect(lambda: ctx.main_window.open_check_dialog())
        el.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        ll.addWidget(self.empty)
        split.addWidget(left)

        right = QFrame()
        right.setObjectName("card")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(14, 12, 14, 12)
        rl.addWidget(label("Latest events", "h2"))
        self.events_box = QVBoxLayout()
        self.events_box.setSpacing(8)
        rl.addLayout(self.events_box)
        rl.addStretch(1)
        more = make_button("See all activity", "link")
        more.clicked.connect(lambda: ctx.goto("activity"))
        rl.addWidget(more)
        right.setMinimumWidth(250)
        right.setMaximumWidth(330)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        self.root.addWidget(split, 1)

        self.search.textChanged.connect(self._filters)
        self.group.currentIndexChanged.connect(self._filters)
        self.status.currentIndexChanged.connect(self._filters)
        self.view.customContextMenuRequested.connect(self._menu)
        self.view.doubleClicked.connect(self._open_uptime)
        ctx.snapshot_changed.connect(self.on_snapshot)
        ctx.event_added.connect(self._on_event)
        self._rows: list[dict] = []
        self._refresh_events()

    def _on_event(self, _e: dict) -> None:
        self._refresh_events()

    # ----------------------------------------------------------- data
    def on_snapshot(self, rows: list[dict]) -> None:
        self._rows = rows
        sel = self._selected_name()
        self.model.set_rows(rows)
        self.view.sortByColumn(self.proxy.sortColumn() if self.proxy.sortColumn() >= 0 else 0, self.proxy.sortOrder())
        if sel:
            self._select_name(sel)
        groups = sorted({r["group"] for r in rows}, key=str.lower)
        cur = self.group.currentData()
        self.group.blockSignals(True)
        self.group.clear()
        self.group.addItem("All groups", "")
        for g in groups:
            self.group.addItem(g, g)
        i = self.group.findData(cur)
        self.group.setCurrentIndex(max(0, i))
        self.group.blockSignals(False)
        self.empty.setVisible(not rows)
        self.view.setVisible(bool(rows))
        self._cards(rows)

    def _cards(self, rows: list[dict]) -> None:
        active = [r for r in rows if r["enabled"]]
        up = sum(1 for r in active if r["status"] == "up")
        down = [r for r in active if r["status"] in ("down", "error")]
        retry = sum(1 for r in active if r["status"] == "retry")
        self.c_up.set(f"{up} / {len(active)}", f"{retry} retrying" if retry else "all other checks are fine" if up == len(active) else "", "#16a34a" if up == len(active) and active else None)
        self.c_down.set(str(len(down)), ", ".join(r["name"] for r in down[:3]) + ("..." if len(down) > 3 else "") if down else "nothing is down", "#dc2626" if down else "#16a34a")
        since = time.time() - 86400
        av = self.ctx.history.availability(None, since)
        if av["pct"] is None:
            self.c_avail.set("-", "collecting data...")
        else:
            col = "#16a34a" if av["pct"] >= 99.5 else "#f59e0b" if av["pct"] >= 95 else "#dc2626"
            self.c_avail.set(f"{av['pct']:.2f}%", f"{av['total']:,} checks".replace(",", " "), col)
        lat = self.ctx.history.latency_stats(None, since)
        if lat["avg"] is None:
            self.c_lat.set("-", "no timed checks yet")
        else:
            self.c_lat.set(f"{lat['avg']:.0f} ms", f"max {lat['max']:.0f} ms")
        inc = self.ctx.history.incidents(None, since)
        open_n = sum(1 for i in inc if i["ended"] is None)
        self.c_inc.set(str(len(inc)), f"{open_n} still open" if open_n else "none ongoing", "#dc2626" if open_n else None)

    def _refresh_events(self) -> None:
        while self.events_box.count():
            it = self.events_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        events = self.ctx.history.events(limit=7, levels=["error", "warn", "ok", "info", "alert"])
        if not events:
            self.events_box.addWidget(label("Nothing has happened yet. Quiet is good!", "muted", wrap=True))
        for e in events:
            row = QHBoxLayout()
            dot = QLabel("\u25CF")
            dot.setStyleSheet(f"color:{LEVEL_COLORS.get(e['level'], '#64748b')};")
            dot.setFixedWidth(14)
            txt = QLabel(f"<span style='color:{theme.palette()['muted']}'>{time.strftime('%H:%M', time.localtime(e['ts']))}</span> {e['text']}")
            txt.setWordWrap(True)
            txt.setTextFormat(Qt.TextFormat.RichText)
            row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(txt, 1)
            w = QWidget()
            w.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            self.events_box.addWidget(w)

    # ----------------------------------------------------------- interaction
    def _filters(self) -> None:
        self.proxy.set_filters(self.search.text(), self.group.currentData() or "", self.status.currentData() or "")

    def _selected_name(self) -> str:
        idx = self.view.currentIndex()
        if not idx.isValid():
            return ""
        return self.model.row_at(self.proxy.mapToSource(idx).row())["name"]

    def _select_name(self, name: str) -> None:
        for r in range(self.proxy.rowCount()):
            if self.model.row_at(self.proxy.mapToSource(self.proxy.index(r, 0)).row())["name"] == name:
                self.view.selectRow(r)
                return

    def _current_row(self):
        idx = self.view.currentIndex()
        return self.model.row_at(self.proxy.mapToSource(idx).row()) if idx.isValid() else None

    def _open_uptime(self, _idx=None) -> None:
        r = self._current_row()
        if r:
            self.ctx.main_window.show_uptime_for(r["name"])

    def _menu(self, pos) -> None:
        idx = self.view.indexAt(pos)
        if not idx.isValid():
            return
        self.view.selectRow(idx.row())
        r = self._current_row()
        m = QMenu(self)
        m.addAction("View uptime and history", self._open_uptime)
        m.addAction("What's wrong with this?", lambda: self.ctx.main_window.diagnose(r["id"]))
        m.addAction("Edit...", lambda: self.ctx.main_window.edit_check(r["id"]))
        m.addAction("Check everything now", self.ctx.core.check_now)
        m.exec(self.view.viewport().mapToGlobal(pos))
