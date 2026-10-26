"""TCP port scanner with explanations."""
from __future__ import annotations

import ipaddress
import socket

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar,
                               QTableWidget, QTableWidgetItem)

from ... import knowledge, netutil
from ..widgets import HelpText, InfoBanner, PageHeader, Task, label, make_button
from .base import Page

RISK = {"info": ("Normal", "#16a34a"), "caution": ("Be careful", "#f59e0b"), "danger": ("Risky", "#dc2626")}
HEADERS = ["Port", "Service", "Risk", "What it is", "What to do"]


class PortsPage(Page):
    key = "ports"
    title = "Port scanner"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.task: Task | None = None
        self.host_scanned = ""
        self.open_ports: list[int] = []
        head = PageHeader("Port scanner", "Which doors are open on a device? (TCP only.)")
        self.root.addWidget(head)
        self.root.addWidget(InfoBanner("ports"))

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Device:"))
        self.host = QLineEdit()
        self.host.setPlaceholderText("192.168.1.20 or server.local")
        self.host.setMinimumWidth(220)
        bar.addWidget(self.host)
        bar.addWidget(QLabel("Ports:"))
        self.preset = QComboBox()
        for name in knowledge.PORT_PRESETS:
            self.preset.addItem(name, name)
        self.preset.addItem("Custom list...", "custom")
        bar.addWidget(self.preset)
        self.custom = QLineEdit()
        self.custom.setPlaceholderText("e.g. 22,80,443,8000-8100")
        self.custom.setVisible(False)
        bar.addWidget(self.custom)
        self.scan_btn = make_button("Scan", "primary")
        self.cancel_btn = make_button("Cancel")
        self.cancel_btn.setVisible(False)
        bar.addWidget(self.scan_btn)
        bar.addWidget(self.cancel_btn)
        bar.addStretch(1)
        self.root.addLayout(bar)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.status = label("Enter a device and press Scan. Scanning your own PC? Type 127.0.0.1.", "muted", wrap=True)
        self.root.addWidget(self.progress)
        self.root.addWidget(self.status)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(True)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h.setStretchLastSection(True)
        for i, w in enumerate((70, 150, 100, 300)):
            self.table.setColumnWidth(i, w)
        self.root.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.add_btn = make_button("Keep an eye on the selected port (add a check)...")
        self.add_all_btn = make_button("Add checks for all open ports...")
        row.addWidget(self.add_btn)
        row.addWidget(self.add_all_btn)
        row.addStretch(1)
        self.root.addLayout(row)
        self.root.addWidget(HelpText("<b>Legal and polite:</b> only scan devices you own or manage. A scan only <i>connects</i> to ports to see if they answer - it does not try to break in - "
                                     "but other people's networks may treat it as hostile. Tip: add a check for each port that <i>should</i> be open, so you hear about it when one closes."))

        self.preset.currentIndexChanged.connect(lambda: self.custom.setVisible(self.preset.currentData() == "custom"))
        self.scan_btn.clicked.connect(self.start_scan)
        self.cancel_btn.clicked.connect(self._cancel)
        self.add_btn.clicked.connect(self._add_selected)
        self.add_all_btn.clicked.connect(self._add_all)
        self.host.returnPressed.connect(self.start_scan)

    def set_host(self, host: str) -> None:
        self.host.setText(host)

    def _ports(self) -> list[int]:
        if self.preset.currentData() == "custom":
            return netutil.parse_port_spec(self.custom.text())
        return list(knowledge.PORT_PRESETS[self.preset.currentData()])

    @staticmethod
    def _is_private(host: str) -> bool:
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(host))
        except (OSError, ValueError):
            return True  # can't tell; the scan itself will report the DNS failure
        return ip.is_private or ip.is_loopback or ip.is_link_local

    def start_scan(self) -> None:
        if self.task and self.task.isRunning():
            return
        host = self.host.text().strip()
        if not netutil.is_valid_host(host):
            QMessageBox.warning(self, "Port scanner", "Please enter a valid IP address or host name.")
            return
        try:
            ports = self._ports()
        except ValueError as exc:
            QMessageBox.warning(self, "Port scanner", f"Ports: {exc}")
            return
        if not ports:
            QMessageBox.warning(self, "Port scanner", "Please enter at least one port.")
            return
        if not self._is_private(host):
            ans = QMessageBox.question(self, "Scan a public address?",
                                       f"{host} does not look like a device on your own network.\n\nOnly scan systems you own or have written permission to test. Continue?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                return
        self.host_scanned = host
        self.scan_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(ports))
        self.progress.setValue(0)
        self.status.setText(f"Scanning {len(ports)} ports on {host}...")
        self.table.setRowCount(0)

        def work(t: Task):
            return netutil.scan_ports(host, ports, timeout_s=0.8, progress=lambda d, n: t.report(d, n, ""), cancel=t.cancel_event), len(ports)

        self.task = Task(work, self)
        self.task.progress.connect(self._on_progress)
        self.task.result.connect(self._done)
        self.task.failed.connect(self._failed)
        self.task.start()

    def _on_progress(self, done: int, _total: int, _text: str) -> None:
        self.progress.setValue(done)

    def _cancel(self) -> None:
        if self.task:
            self.task.cancel()

    def _finish(self) -> None:
        self.scan_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.progress.setVisible(False)

    def _failed(self, msg: str) -> None:
        self._finish()
        self.status.setText(f"Scan failed: {msg}")

    def _done(self, res) -> None:
        self._finish()
        open_ports, scanned = res
        self.open_ports = open_ports
        cancelled = self.task.cancelled if self.task else False
        self.status.setText(f"{'Cancelled. ' if cancelled else ''}{len(open_ports)} open port(s) out of {scanned} scanned on {self.host_scanned}."
                            + ("" if open_ports else " Nothing answered - the device may be off, or a firewall is blocking everything."))
        self.table.setRowCount(len(open_ports))
        for r, p in enumerate(open_ports):
            svc, what, risk, advice = knowledge.PORT_INFO.get(p, (knowledge.port_name(p) or "unknown", "No built-in description for this port.", "info", "Check what program is using it."))
            label_, color = RISK[risk]
            vals = [str(p), svc, label_, what, advice]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 2:
                    it.setForeground(QColor(color))
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                self.table.setItem(r, c, it)
        self.table.resizeRowsToContents()

    def _add_port(self, port: int) -> None:
        svc = knowledge.port_name(port)
        self.ctx.main_window.open_check_dialog(kind="tcp", params={"host": self.host_scanned, "port": port},
                                               name=f"{svc or 'Port ' + str(port)} on {self.host_scanned}")

    def _add_selected(self) -> None:
        r = self.table.currentRow()
        if 0 <= r < len(self.open_ports):
            self._add_port(self.open_ports[r])
        else:
            QMessageBox.information(self, "Port scanner", "Select a row first.")

    def _add_all(self) -> None:
        if not self.open_ports:
            return
        from ...checks import CHECKS
        from ...store import MonitorDef
        added = 0
        for p in self.open_ports:
            params = {**CHECKS["tcp"].defaults(), "host": self.host_scanned, "port": p}
            svc = knowledge.port_name(p)
            m = MonitorDef.new("tcp", f"{svc or 'Port ' + str(p)} on {self.host_scanned}", params)
            m.group = "Servers"
            self.ctx.store.add(m)
            added += 1
        self.ctx.apply_changes()
        self.ctx.toast(f"Added {added} port checks.", "ok")
