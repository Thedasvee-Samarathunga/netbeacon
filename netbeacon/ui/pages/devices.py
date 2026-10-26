"""Network device discovery."""
from __future__ import annotations

import csv
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QMenu, QMessageBox, QProgressBar, QTableWidget, QTableWidgetItem)

from ... import knowledge, netutil
from ...devices import merge_scan, stored_rows
from .. import theme
from ..widgets import HelpText, InfoBanner, PageHeader, Task, label, make_button
from .base import Page

HEADERS = ["State", "IP address", "Name", "Network name", "MAC address", "Looks like (a guess)", "Ping", "Open ports"]


class DevicesPage(Page):
    key = "devices"
    title = "Devices"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.rows: list[dict] = []
        self.task: Task | None = None
        head = PageHeader("Network devices", "Find everything connected to your network and spot anything unfamiliar.")
        self.root.addWidget(head)
        self.root.addWidget(InfoBanner("devices"))

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Network to scan:"))
        self.net = QComboBox()
        self.net.setEditable(True)
        self.net.setMinimumWidth(300)
        bar.addWidget(self.net)
        self.deep = QCheckBox("Deep scan")
        self.deep.setToolTip("Also try a few common TCP ports. Finds devices that ignore ping and helps guess what each device is. Slower.")
        bar.addWidget(self.deep)
        self.scan_btn = make_button("Scan network", "primary")
        self.cancel_btn = make_button("Cancel")
        self.cancel_btn.setVisible(False)
        bar.addWidget(self.scan_btn)
        bar.addWidget(self.cancel_btn)
        bar.addStretch(1)
        self.known_btn = make_button("Mark selected as known")
        self.all_btn = make_button("Mark all as known")
        bar.addWidget(self.known_btn)
        bar.addWidget(self.all_btn)
        self.root.addLayout(bar)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.status = label("", "muted")
        self.root.addWidget(self.progress)
        self.root.addWidget(self.status)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setSortingEnabled(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h.setStretchLastSection(True)
        for i, w in enumerate((100, 120, 170, 180, 150, 230, 70)):
            self.table.setColumnWidth(i, w)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.root.addWidget(self.table, 1)

        self.hint = HelpText("<b>Reading the table:</b> <b>NEW</b> = never reviewed. <b>Known</b> = you've confirmed it. <b>Not seen</b> = remembered from an earlier scan but silent now (a phone that left, or a PC that's off). "
                             "A MAC address starting with a '2', '6', 'A' or 'E' in the second character is <i>randomised</i> - phones and laptops do this on purpose for Wi-Fi privacy, "
                             "so the same phone can appear as a 'new' device after a settings change. Right-click a device for more options.")
        self.root.addWidget(self.hint)
        row = QHBoxLayout()
        self.export_btn = make_button("Export list (CSV)")
        row.addWidget(self.export_btn)
        row.addStretch(1)
        self.root.addLayout(row)

        self.scan_btn.clicked.connect(self.start_scan)
        self.cancel_btn.clicked.connect(self._cancel)
        self.known_btn.clicked.connect(self._mark_selected)
        self.all_btn.clicked.connect(self._mark_all)
        self.export_btn.clicked.connect(self._export)
        self.table.customContextMenuRequested.connect(self._menu)
        self._fill_networks()
        self._render(stored_rows(ctx.history))

    # ------------------------------------------------------------------ networks
    def _fill_networks(self) -> None:
        self.net.clear()
        nets = netutil.local_networks()
        for n in nets:
            self.net.addItem(n.label(), n.cidr)
        saved = self.ctx.store.get("scan_cidr", "")
        if saved:
            i = self.net.findData(saved)
            if i >= 0:
                self.net.setCurrentIndex(i)
            else:
                self.net.setEditText(saved)
        if not nets:
            self.status.setText("No active network found. Connect to a network or type one such as 192.168.1.0/24.")

    def _cidr(self) -> str:
        text = self.net.currentText().strip()
        data = self.net.currentData()
        if data and text == self.net.itemText(self.net.currentIndex()):
            return data
        return text.split()[0] if text else ""

    # ------------------------------------------------------------------ scanning
    def start_scan(self, silent: bool = False) -> None:
        if self.task and self.task.isRunning():
            return
        cidr = self._cidr()
        try:
            netutil.hosts_in(cidr)
        except ValueError as exc:
            QMessageBox.warning(self, "Network", f"Can't scan '{cidr}': {exc}")
            return
        self.ctx.store.set("scan_cidr", cidr)
        deep = self.deep.isChecked()
        self.scan_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status.setText("Scanning... this usually takes 5-20 seconds (a deep scan takes longer).")

        def work(t: Task):
            return netutil.scan_network(cidr, deep=deep, progress=t.report, cancel=t.cancel_event)

        self.task = Task(work, self)
        self.task.progress.connect(self._on_progress)
        self.task.result.connect(self._on_result)
        self.task.failed.connect(self._on_failed)
        self.task.start()

    def _on_progress(self, done: int, total: int, text: str) -> None:
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        self.status.setText(text)

    def _cancel(self) -> None:
        if self.task:
            self.task.cancel()
        self.status.setText("Cancelling...")

    def _finish(self) -> None:
        self.scan_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.progress.setVisible(False)

    def _on_failed(self, msg: str) -> None:
        self._finish()
        self.status.setText(f"Scan failed: {msg}")

    def _on_result(self, devices) -> None:
        self._finish()
        if self.task and self.task.cancelled:
            self.status.setText("Scan cancelled.")
            return
        known_before = [d for d in self.ctx.history.devices() if d["known"]]
        rows, fresh = merge_scan(self.ctx.history, devices)
        self._render(rows)
        found = len(devices)
        baseline = bool(self.ctx.store.get("devices_baseline_done"))
        msg = f"Found {found} devices."
        if not baseline:
            msg += " First scan! Look through the list, then click 'Mark all as known' to set your baseline - after that NetBeacon can warn you about newcomers."
        elif fresh:
            msg += f" {len(fresh)} new device(s) appeared: " + ", ".join(f['ip'] for f in fresh[:5])
            self.ctx.history.add_event(time.time(), "warn", None, f"New device(s) on the network: " + ", ".join(f"{f['ip']} ({f['mac'] or 'no MAC'})" for f in fresh[:8]))
        self.status.setText(msg)

    # ------------------------------------------------------------------ table
    def _render(self, rows: list[dict]) -> None:
        self.rows = rows
        self.table.setRowCount(len(rows))
        pal = theme.palette()
        for r, d in enumerate(rows):
            if not d["seen_now"]:
                state, color = "Not seen", pal["muted"]
            elif d["known"]:
                state, color = "Known", "#16a34a"
            else:
                state, color = "NEW", "#f59e0b"
            ports = ", ".join(f"{p}" + (f" ({knowledge.port_name(p)})" if knowledge.port_name(p) else "") for p in d["ports"])
            name = d["name"] or ("This computer" if d["is_self"] else "")
            mac = d["mac"] + (" (private)" if d["randomized"] else "")
            ping = f"{d['rtt_ms']:.0f} ms" if d["rtt_ms"] is not None else ("replies" if d["alive"] else "-")
            kind = d["kind"] or ("" if d["seen_now"] else "last seen " + time.strftime("%d %b %H:%M", time.localtime(d["last_seen"])))
            vals = [state, d["ip"], name, d["hostname"], mac, kind, ping, ports]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 0:
                    it.setForeground(QColor(color))
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                elif not d["seen_now"]:
                    it.setForeground(QColor(pal["muted"]))
                self.table.setItem(r, c, it)

    def _selected(self) -> dict | None:
        r = self.table.currentRow()
        return self.rows[r] if 0 <= r < len(self.rows) else None

    def _mark_selected(self) -> None:
        d = self._selected()
        if d:
            self.ctx.history.set_device(d["key"], known=1)
            self._render(self._refresh_flags())

    def _mark_all(self) -> None:
        self.ctx.history.mark_all_known()
        self.ctx.store.set("devices_baseline_done", True)
        self._render(self._refresh_flags())
        self.status.setText("All devices marked as known. From now on, newcomers will be flagged as NEW.")

    def _refresh_flags(self) -> list[dict]:
        db = {d["key"]: d for d in self.ctx.history.devices()}
        for r in self.rows:
            if r["key"] in db:
                r["known"] = bool(db[r["key"]]["known"])
                r["name"] = db[r["key"]]["name"] or ""
        return self.rows

    def _rename(self) -> None:
        d = self._selected()
        if not d:
            return
        text, ok = QInputDialog.getText(self, "Name this device", "A friendly name (e.g. 'Reception printer'):", text=d["name"])
        if ok:
            self.ctx.history.set_device(d["key"], name=text.strip(), known=1)
            self._render(self._refresh_flags())

    def _forget(self) -> None:
        d = self._selected()
        if d:
            self.ctx.history.forget_device(d["key"])
            self.rows = [r for r in self.rows if r["key"] != d["key"]]
            self._render(self.rows)

    def _monitor(self) -> None:
        d = self._selected()
        if d:
            label_ = d["name"] or d["hostname"] or d["ip"]
            self.ctx.main_window.open_check_dialog(kind="ping", params={"host": d["ip"]}, name=f"Ping {label_}")

    def _copy_mac(self) -> None:
        d = self._selected()
        if d and d["mac"]:
            QGuiApplication.clipboard().setText(d["mac"])
            self.ctx.toast("MAC copied. Paste the first 8 characters at wireshark.org/tools/oui-lookup.html to see the manufacturer.", "info")

    def _menu(self, pos) -> None:
        if not self._selected():
            return
        m = QMenu(self)
        m.addAction("Name this device...", self._rename)
        m.addAction("Mark as known", self._mark_selected)
        m.addAction("Monitor this device (add a ping check)...", self._monitor)
        m.addAction("Scan its ports...", lambda: self.ctx.main_window.scan_ports_of(self._selected()["ip"]))
        m.addAction("Copy MAC address (for vendor lookup)", self._copy_mac)
        m.addSeparator()
        m.addAction("Forget this device", self._forget)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export devices", "network-devices.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(HEADERS + ["Notes"])
            for d in self.rows:
                w.writerow(["Known" if d["known"] else "NEW", d["ip"], d["name"], d["hostname"], d["mac"], d["kind"],
                            "" if d["rtt_ms"] is None else f"{d['rtt_ms']:.0f}", " ".join(map(str, d["ports"])), d["notes"]])
        self.ctx.toast("Device list exported.", "ok")

    def on_show(self) -> None:
        self._render(self._refresh_flags() if self.rows else stored_rows(self.ctx.history))
