"""Events, the engine's own log, and the generated config files."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLineEdit, QPlainTextEdit, QTableWidget,
                               QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from ... import knowledge, paths
from .. import theme
from ..widgets import InfoBanner, PageHeader, label, make_button
from .base import Page

LEVEL_COLORS = {"error": "#dc2626", "warn": "#f59e0b", "ok": "#16a34a", "info": "#64748b", "alert": "#2563eb"}
LEVEL_NAMES = {"error": "Down", "warn": "Warning", "ok": "Recovered", "info": "Info", "alert": "Alert sent"}


class ActivityPage(Page):
    key = "activity"
    title = "Activity & logs"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        head = PageHeader("Activity & under the hood", "What happened, and how the SimpleMonitor engine works.")
        self.root.addWidget(head)
        self.root.addWidget(InfoBanner("activity"))
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)

        # ---- events
        ev = QWidget()
        el = QVBoxLayout(ev)
        bar = QHBoxLayout()
        self.level = QComboBox()
        for t, v in (("Everything", ""), ("Problems (down + warnings)", "error,warn"), ("Recoveries", "ok"), ("Alerts sent", "alert"), ("Info", "info")):
            self.level.addItem(t, v)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search events...")
        self.search.setClearButtonEnabled(True)
        bar.addWidget(self.level)
        bar.addWidget(self.search, 1)
        el.addLayout(bar)
        self.events = QTableWidget(0, 4)
        self.events.setHorizontalHeaderLabels(["When", "What", "Check", "Details"])
        self.events.setAlternatingRowColors(True)
        self.events.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.events.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.events.verticalHeader().setVisible(False)
        self.events.setShowGrid(False)
        self.events.horizontalHeader().setStretchLastSection(True)
        self.events.setColumnWidth(0, 140)
        self.events.setColumnWidth(1, 110)
        self.events.setColumnWidth(2, 190)
        el.addWidget(self.events, 1)
        self.tabs.addTab(ev, "Events")

        # ---- engine log
        lg = QWidget()
        ll = QVBoxLayout(lg)
        ll.addWidget(label("This is SimpleMonitor itself talking: one line per check, per round. 'sm:' marks messages from its alerters and loggers.", "muted", wrap=True))
        lbar = QHBoxLayout()
        self.log_level = QComboBox()
        for t, v in (("Everything", "INFO"), ("Warnings and errors", "WARNING"), ("Errors only", "ERROR")):
            self.log_level.addItem(t, v)
        self.log_clear = make_button("Clear view")
        lbar.addWidget(self.log_level)
        lbar.addStretch(1)
        lbar.addWidget(self.log_clear)
        ll.addLayout(lbar)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.log_view.setFont(QFont("Consolas", 9))
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        ll.addWidget(self.log_view, 1)
        self.tabs.addTab(lg, "Engine log")

        # ---- config
        cf = QWidget()
        cl = QVBoxLayout(cf)
        self.how = QTextBrowser()
        self.how.setMaximumHeight(210)
        self.how.document().setDefaultStyleSheet(theme.html_css(theme._current))
        self.how.setHtml(knowledge.HOW_IT_WORKS)
        cl.addWidget(self.how)
        cbar = QHBoxLayout()
        self.file_combo = QComboBox()
        self.file_combo.addItem("monitors.ini  (the checks)", "monitors.ini")
        self.file_combo.addItem("monitor.ini  (engine, alerts, loggers)", "monitor.ini")
        self.copy_btn = make_button("Copy")
        self.open_btn = make_button("Open folder")
        cbar.addWidget(self.file_combo)
        cbar.addStretch(1)
        cbar.addWidget(self.copy_btn)
        cbar.addWidget(self.open_btn)
        cl.addLayout(cbar)
        self.cfg_view = QPlainTextEdit()
        self.cfg_view.setReadOnly(True)
        self.cfg_view.setFont(QFont("Consolas", 9))
        cl.addWidget(self.cfg_view, 1)
        self.tabs.addTab(cf, "Config files")

        self.level.currentIndexChanged.connect(self.reload_events)
        self.search.textChanged.connect(self.reload_events)
        self.log_level.currentIndexChanged.connect(self._reload_log)
        self.log_clear.clicked.connect(self.log_view.clear)
        self.file_combo.currentIndexChanged.connect(self._load_cfg)
        self.copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.cfg_view.toPlainText()))
        self.open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.config_dir()))))
        ctx.event_added.connect(self._on_event)
        ctx.core.logbuf.listeners.append(self._log_line_threadsafe)
        self._log_signal_bridge()
        self.reload_events()
        self._reload_log()
        self._load_cfg()

    # --- log lines arrive on the engine thread: hop to the GUI thread through a signal
    def _log_signal_bridge(self) -> None:
        from PySide6.QtCore import QObject, Signal

        class _B(QObject):
            line = Signal(tuple)

        self._bridge = _B()
        self._bridge.line.connect(self._append_log)

    def _log_line_threadsafe(self, item: tuple) -> None:
        self._bridge.line.emit(item)

    ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}

    def _append_log(self, item: tuple) -> None:
        ts, lvl, name, msg = item
        if self.ORDER.get(lvl, 1) < self.ORDER[self.log_level.currentData()]:
            return
        self.log_view.appendPlainText(f"{time.strftime('%H:%M:%S', time.localtime(ts))} {lvl:<7} {name}: {msg}")

    def _reload_log(self) -> None:
        self.log_view.clear()
        for item in list(self.ctx.core.logbuf.lines)[-1500:]:
            self._append_log(item)

    # --- events
    def reload_events(self) -> None:
        levels = [x for x in (self.level.currentData() or "").split(",") if x]
        rows = self.ctx.history.events(limit=600, levels=levels or None, search=self.search.text().strip())
        self.events.setRowCount(len(rows))
        for r, e in enumerate(rows):
            vals = [time.strftime("%d %b %H:%M:%S", time.localtime(e["ts"])), LEVEL_NAMES.get(e["level"], e["level"]), e["monitor"] or "", e["text"]]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 1:
                    it.setForeground(QColor(LEVEL_COLORS.get(e["level"], "#64748b")))
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                self.events.setItem(r, c, it)

    def _on_event(self, _e: dict) -> None:
        if self.isVisible():
            self.reload_events()

    def _load_cfg(self) -> None:
        p = paths.config_dir() / (self.file_combo.currentData() or "monitors.ini")
        try:
            text = p.read_text(encoding="utf-8")
            import re
            text = re.sub(r"(?im)^(password|token)=.*$", r"\1=********", text)
            text = re.sub(r"(?im)^(url=https://hooks\.slack\.com/).*$", r"\1********", text).strip()
        except OSError:
            text = "(not written yet)"
        self.cfg_view.setPlainText(text)

    def on_show(self) -> None:
        self.reload_events()
        self._load_cfg()
