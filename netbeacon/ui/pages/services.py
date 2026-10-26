"""What's running on this computer: services, programs, listening ports."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLineEdit, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from ... import knowledge, netutil
from ..widgets import HelpText, InfoBanner, PageHeader, Task, label, make_button
from .base import Page


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.setShowGrid(False)
    t.setSortingEnabled(True)
    t.horizontalHeader().setStretchLastSection(True)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    return t


class ServicesPage(Page):
    key = "services"
    title = "Services & programs"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._tasks: list[Task] = []
        head = PageHeader("Services & programs", "What is running on this computer - and turn any of it into a check.")
        self.refresh_btn = head.add_action(make_button("Refresh"))
        self.root.addWidget(head)
        self.root.addWidget(InfoBanner("services"))
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)

        # --- services
        self.svc_table = _table(["Name", "Display name", "Status", "Starts"])
        self.svc_search = QLineEdit()
        self.svc_search.setPlaceholderText("Filter services...")
        self.svc_state = QComboBox()
        for t, v in (("All", ""), ("Running", "running"), ("Stopped", "stopped")):
            self.svc_state.addItem(t, v)
        self.svc_note = label("", "muted", wrap=True)
        self.svc_btn = make_button("Monitor the selected service...", "primary")
        self.tabs.addTab(self._tab(self.svc_search, self.svc_state, self.svc_table, self.svc_btn, self.svc_note), "Windows services")

        # --- programs
        self.proc_table = _table(["Program", "Copies", "Memory (MB)"])
        self.proc_search = QLineEdit()
        self.proc_search.setPlaceholderText("Filter programs...")
        self.proc_btn = make_button("Monitor the selected program...", "primary")
        self.tabs.addTab(self._tab(self.proc_search, None, self.proc_table, self.proc_btn, label("Programs are grouped by name; 'copies' is how many are running.", "muted")), "Running programs")

        # --- listening ports
        self.listen_table = _table(["Port", "Address", "Reachable from", "Program", "PID", "Known as"])
        self.listen_search = QLineEdit()
        self.listen_search.setPlaceholderText("Filter ports...")
        self.listen_btn = make_button("Monitor the selected port...", "primary")
        self.tabs.addTab(self._tab(self.listen_search, None, self.listen_table, self.listen_btn,
                                   label("These are the ports this PC is <b>listening</b> on. 'network' means other computers can try to connect; 'this PC only' means only programs on this computer can.", "muted", wrap=True)), "Listening ports")

        self.refresh_btn.clicked.connect(self.refresh)
        self.svc_search.textChanged.connect(lambda: self._filter(self.svc_table, self.svc_search.text(), self.svc_state.currentData() or "", 2))
        self.svc_state.currentIndexChanged.connect(lambda: self._filter(self.svc_table, self.svc_search.text(), self.svc_state.currentData() or "", 2))
        self.proc_search.textChanged.connect(lambda: self._filter(self.proc_table, self.proc_search.text()))
        self.listen_search.textChanged.connect(lambda: self._filter(self.listen_table, self.listen_search.text()))
        self.svc_btn.clicked.connect(self._monitor_service)
        self.proc_btn.clicked.connect(self._monitor_process)
        self.listen_btn.clicked.connect(self._monitor_port)
        self._loaded = False

    @staticmethod
    def _tab(search, combo, table, button, note) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        bar.addWidget(search, 1)
        if combo is not None:
            bar.addWidget(combo)
        bar.addWidget(button)
        lay.addLayout(bar)
        lay.addWidget(table, 1)
        lay.addWidget(note)
        return w

    @staticmethod
    def _filter(table: QTableWidget, text: str, status: str = "", status_col: int = -1) -> None:
        t = text.lower()
        for r in range(table.rowCount()):
            hay = " ".join((table.item(r, c).text() if table.item(r, c) else "") for c in range(table.columnCount())).lower()
            hide = bool(t) and t not in hay
            if status and status_col >= 0 and table.item(r, status_col) and table.item(r, status_col).text().lower() != status:
                hide = True
            table.setRowHidden(r, hide)

    def on_show(self) -> None:
        if not self._loaded:
            self.refresh()

    def refresh(self) -> None:
        self._loaded = True
        self.refresh_btn.setEnabled(False)

        def work(_t):
            return netutil.list_windows_services(), netutil.list_processes(), netutil.list_listening_ports()

        t = Task(work, self)
        t.result.connect(self._loaded_data)
        t.failed.connect(self._load_failed)
        self._tasks.append(t)
        t.start()

    def _load_failed(self, msg: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.ctx.toast(f"Could not read the list: {msg}", "error")

    def _loaded_data(self, res) -> None:
        self.refresh_btn.setEnabled(True)
        services, procs, ports = res
        self.svc_table.setSortingEnabled(False)
        self.svc_table.setRowCount(len(services))
        for r, s in enumerate(sorted(services, key=lambda s: s["display_name"].lower())):
            for c, v in enumerate((s["name"], s["display_name"], s["status"], s["start_type"])):
                it = QTableWidgetItem(v)
                if c == 2:
                    it.setForeground(QColor("#16a34a" if v == "running" else "#94a3b8"))
                self.svc_table.setItem(r, c, it)
        self.svc_table.setSortingEnabled(True)
        if not services:
            self.svc_note.setText("Windows services are only available when NetBeacon runs on Windows." if sys.platform != "win32"
                                  else "Could not read the list of services.")
        else:
            self.svc_note.setText(f"{len(services)} services. Tip: monitor the ones your business software depends on (database, accounting, backup agent), "
                                  "not every Windows component.")
        self.proc_table.setSortingEnabled(False)
        self.proc_table.setRowCount(len(procs))
        for r, p in enumerate(procs):
            for c, v in enumerate((p["name"], p["count"], round(p["memory"] / 1024 ** 2))):
                it = QTableWidgetItem()
                it.setData(Qt.ItemDataRole.DisplayRole, v)
                self.proc_table.setItem(r, c, it)
        self.proc_table.setSortingEnabled(True)
        self.listen_table.setSortingEnabled(False)
        self.listen_table.setRowCount(len(ports))
        for r, p in enumerate(ports):
            vals = (p["port"], p["address"], p["exposure"], p["process"], p["pid"], knowledge.port_name(p["port"]))
            for c, v in enumerate(vals):
                it = QTableWidgetItem()
                it.setData(Qt.ItemDataRole.DisplayRole, v)
                if c == 2 and v == "network":
                    it.setForeground(QColor("#f59e0b"))
                self.listen_table.setItem(r, c, it)
        self.listen_table.setSortingEnabled(True)

    @staticmethod
    def _cell(table: QTableWidget, col: int) -> str:
        r = table.currentRow()
        it = table.item(r, col) if r >= 0 else None
        return it.text() if it else ""

    def _monitor_service(self) -> None:
        name = self._cell(self.svc_table, 0)
        if name:
            disp = self._cell(self.svc_table, 1)
            self.ctx.main_window.open_check_dialog(kind="service", params={"service": name}, name=f"Service {disp or name}")
        else:
            self.ctx.toast("Select a service first.", "info")

    def _monitor_process(self) -> None:
        name = self._cell(self.proc_table, 0)
        if name:
            self.ctx.main_window.open_check_dialog(kind="process", params={"process_name": name}, name=f"Program {name}")
        else:
            self.ctx.toast("Select a program first.", "info")

    def _monitor_port(self) -> None:
        port = self._cell(self.listen_table, 0)
        if port:
            prog = self._cell(self.listen_table, 3)
            self.ctx.main_window.open_check_dialog(kind="tcp", params={"host": "127.0.0.1", "port": int(port)},
                                                   name=f"Port {port}" + (f" ({prog})" if prog else ""))
        else:
            self.ctx.toast("Select a port first.", "info")
