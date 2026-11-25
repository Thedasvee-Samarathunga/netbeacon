"""Internet speed: scheduled speed tests, history, and a comparison with what you pay for."""
from __future__ import annotations

import csv
import time
from typing import Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ... import speedtest
from ..widgets import HelpText, InfoBanner, PageHeader, SeriesChart, StatCard, Task, label, make_button
from .base import Page

RANGES = [("Last 7 days", 7 * 86400), ("Last 30 days", 30 * 86400), ("Last 90 days", 90 * 86400), ("Last year", 365 * 86400)]


class SpeedPage(Page):
    key = "speed"
    title = "Internet speed"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.task: Optional[Task] = None
        head = PageHeader("Internet speed", "Are you getting the speed you pay for? Regular tests build the evidence.")
        self.run_btn = head.add_action(make_button("Run a speed test now", "primary"))
        self.cancel_btn = head.add_action(make_button("Cancel"))
        self.cancel_btn.setVisible(False)
        self.export_btn = head.add_action(make_button("Export CSV"))
        self.root.addWidget(head)
        self.root.addWidget(InfoBanner("speed"))
        self.status = label("", "muted", wrap=True)
        self.status.setVisible(False)
        self.root.addWidget(self.status)
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.c_down = StatCard("Download", "How fast data arrives - what matters for browsing, downloads and video.")
        self.c_up = StatCard("Upload", "How fast data leaves - what matters for video calls, sending files and cloud backup.")
        self.c_lat = StatCard("Latency / jitter", "Latency: how long a message takes to reach the test server. Jitter: how much that varies. "
                                                  "High jitter makes calls choppy even on a fast line.")
        self.c_plan = StatCard("Compared with your plan", "Average download in the chosen period vs. what your plan promises.")
        for c in (self.c_down, self.c_up, self.c_lat, self.c_plan):
            cards.addWidget(c, 1)
        self.root.addLayout(cards)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(label("History", "h2"))
        bar.addStretch(1)
        self.range = QComboBox()
        for t, s in RANGES:
            self.range.addItem(t, s)
        bar.addWidget(self.range)
        ll.addLayout(bar)
        self.chart = SeriesChart("Mbit/s")
        self.chart.empty_text = "No speed tests yet - press 'Run a speed test now'."
        ll.addWidget(self.chart, 2)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["When", "Download", "Upload", "Latency", "Jitter", "Notes"])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 130)
        ll.addWidget(self.table, 1)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        g = QGroupBox("Settings")
        f = QFormLayout(g)
        f.setVerticalSpacing(8)
        self.auto = QCheckBox("Test automatically")
        self.every = QSpinBox()
        self.every.setRange(1, 168)
        self.every.setSuffix(" hours")
        f.addRow(self.auto)
        f.addRow("Every", self.every)
        self.paid_down = QDoubleSpinBox()
        self.paid_up = QDoubleSpinBox()
        for sp in (self.paid_down, self.paid_up):
            sp.setRange(0, 100000)
            sp.setDecimals(0)
            sp.setSuffix(" Mbit/s")
            sp.setSpecialValueText("not set")
        f.addRow("My plan: download", self.paid_down)
        f.addRow("My plan: upload", self.paid_up)
        self.max_down = QSpinBox()
        self.max_up = QSpinBox()
        for sp, hi in ((self.max_down, 500), (self.max_up, 200)):
            sp.setRange(1, hi)
            sp.setSuffix(" MB")
        f.addRow("Data per test: download", self.max_down)
        f.addRow("Data per test: upload", self.max_up)
        self.server = QLineEdit()
        self.server.setPlaceholderText(speedtest.DEFAULT_SERVER)
        f.addRow("Test server", self.server)
        self.data_note = HelpText("", always=True)
        f.addRow(self.data_note)
        self.save_btn = make_button("Save", "primary")
        f.addRow(self.save_btn)
        rl.addWidget(g)
        rl.addWidget(HelpText("<b>Getting fair results:</b> test from a PC on a <b>cable</b>, not Wi-Fi - Wi-Fi usually becomes the bottleneck. "
                              "A single slow test means little (someone may have been downloading); a <i>pattern</i> of slow evenings is evidence. "
                              "The test stops after about 12 seconds per direction or when the data limit is reached, so very fast lines "
                              "(above a few hundred Mbit/s) may read a little low with small limits."))
        rl.addStretch(1)
        right.setMinimumWidth(320)
        right.setMaximumWidth(380)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        self.root.addWidget(split, 1)

        self.run_btn.clicked.connect(lambda: self.run_test())
        self.cancel_btn.clicked.connect(lambda: self.task.cancel() if self.task else None)
        self.save_btn.clicked.connect(lambda: self.save())
        self.export_btn.clicked.connect(lambda: self._export())
        self.range.currentIndexChanged.connect(lambda _i: self.refresh())
        for w in (self.every, self.max_down, self.max_up):
            w.valueChanged.connect(lambda _v: self._update_note())
        self.auto.toggled.connect(lambda _v: self._update_note())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._maybe_run)
        self.timer.start(60 * 1000)
        self.load()
        self.refresh()

    # ---- settings
    def load(self) -> None:
        s = self.ctx.store
        self.auto.setChecked(bool(s.get("speed_enabled")))
        self.every.setValue(int(s.get("speed_every_hours", 6)))
        self.paid_down.setValue(float(s.get("speed_paid_down", 0) or 0))
        self.paid_up.setValue(float(s.get("speed_paid_up", 0) or 0))
        self.max_down.setValue(int(s.get("speed_max_down_mb", 25)))
        self.max_up.setValue(int(s.get("speed_max_up_mb", 10)))
        server = s.get("speed_server", speedtest.DEFAULT_SERVER)
        self.server.setText("" if server == speedtest.DEFAULT_SERVER else server)
        self._update_note()

    def save(self) -> None:
        s = self.ctx.store
        server = self.server.text().strip().rstrip("/")
        if server and not server.lower().startswith(("http://", "https://")):
            self.ctx.toast("The test server must start with http:// or https://", "error")
            return
        s.settings.update({"speed_enabled": self.auto.isChecked(), "speed_every_hours": self.every.value(),
                           "speed_paid_down": self.paid_down.value(), "speed_paid_up": self.paid_up.value(),
                           "speed_max_down_mb": self.max_down.value(), "speed_max_up_mb": self.max_up.value(),
                           "speed_server": server or speedtest.DEFAULT_SERVER})
        s.save()
        self.ctx.toast("Speed test settings saved.", "ok")
        self.refresh()

    def _update_note(self) -> None:
        per = self.max_down.value() + self.max_up.value()
        if self.auto.isChecked():
            per_month = per * (24 / max(1, self.every.value())) * 30 / 1024
            self.data_note.setText(f"Uses up to {per} MB per test - about {per_month:.1f} GB a month at this schedule. "
                                   "Mind this on metered or mobile connections.")
        else:
            self.data_note.setText(f"Uses up to {per} MB per test.")

    def _say(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    # ---- running
    def _maybe_run(self) -> None:
        s = self.ctx.store
        if not s.get("speed_enabled") or (self.task and self.task.isRunning()) or self.ctx.core.info.paused:
            return
        if time.time() - float(s.get("last_speedtest_ts", 0) or 0) >= int(s.get("speed_every_hours", 6)) * 3600:
            self.run_test(silent=True)

    def run_test(self, silent: bool = False) -> None:
        if self.task and self.task.isRunning():
            return
        s = self.ctx.store
        server = s.get("speed_server") or speedtest.DEFAULT_SERVER
        mdown, mup = int(s.get("speed_max_down_mb", 25)), int(s.get("speed_max_up_mb", 10))
        s.set("last_speedtest_ts", time.time())
        self.run_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self._say("Starting the speed test...")

        def work(t: Task):
            return speedtest.run(server, mdown, mup, progress=lambda text: t.report(0, 0, text), cancel=t.cancel_event)

        self.task = Task(work, self)
        self.task.progress.connect(lambda _d, _n, text: self._say(text))
        self.task.result.connect(lambda r: self._done(r, silent))
        self.task.failed.connect(self._failed)
        self.task.start()

    def _done(self, r: speedtest.SpeedResult, silent: bool) -> None:
        self.run_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        if r.error == "cancelled":
            self._say("Speed test cancelled.")
            return
        h = self.ctx.history
        h.add_speedtest(r.ts, r.down_mbps, r.up_mbps, r.latency_ms, r.jitter_ms, r.server, r.error)
        paid = float(self.ctx.store.get("speed_paid_down", 0) or 0)
        if r.down_mbps is None:
            self._say(f"The speed test failed: {r.error}")
            h.add_event(time.time(), "warn", None, f"Speed test failed: {r.error}")
        else:
            up = f"{r.up_mbps:.1f}" if r.up_mbps is not None else "?"
            text = f"Speed test: {r.down_mbps:.1f} Mbit/s down, {up} up, latency {r.latency_ms:.0f} ms."
            if r.error:
                text += f" ({r.error})"
            self._say(text + f" Next automatic test in about {self.ctx.store.get('speed_every_hours', 6)} hours."
                                if self.ctx.store.get("speed_enabled") else text)
            low = paid and r.down_mbps < 0.5 * paid
            h.add_event(time.time(), "warn" if low else "info", None,
                        text + (f" That is under half of the {paid:g} Mbit/s you pay for." if low else ""))
            if not silent:
                self.ctx.toast(text, "warn" if low else "ok")
        self.refresh()

    def _failed(self, msg: str) -> None:
        self.run_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self._say(f"The speed test failed: {msg}")

    # ---- display
    def refresh(self) -> None:
        now = time.time()
        since = now - int(self.range.currentData())
        rows = self.ctx.history.speedtests(since)
        good = [r for r in rows if r["down"] is not None]
        paid_d = float(self.ctx.store.get("speed_paid_down", 0) or 0)
        paid_u = float(self.ctx.store.get("speed_paid_up", 0) or 0)
        last = good[0] if good else None
        if last:
            self.c_down.set(f"{last['down']:.0f} Mbit/s", "latest test" + (f" - plan {paid_d:g}" if paid_d else ""))
            self.c_up.set(f"{last['up']:.0f} Mbit/s" if last["up"] is not None else "-", "latest test" + (f" - plan {paid_u:g}" if paid_u else ""))
            self.c_lat.set(f"{last['latency']:.0f} ms" if last["latency"] is not None else "-",
                           f"jitter {last['jitter']:.1f} ms" if last["jitter"] is not None else "")
            avg = sum(r["down"] for r in good) / len(good)
            text, col = speedtest.verdict(avg, paid_d)
            if paid_d:
                self.c_plan.set(f"{100 * avg / paid_d:.0f}%", f"average {avg:.0f} Mbit/s over {len(good)} test(s)", col)
            else:
                self.c_plan.set("-", "enter your plan's speed in Settings to compare")
        else:
            for c in (self.c_down, self.c_up, self.c_lat):
                c.set("-", "no tests yet")
            self.c_plan.set("-", "")
        pts = sorted(good, key=lambda r: r["ts"])
        series = [{"name": "Download", "color": "#2563eb", "points": [(r["ts"], r["down"]) for r in pts]},
                  {"name": "Upload", "color": "#16a34a", "points": [(r["ts"], r["up"]) for r in pts]}]
        self.chart.set_data(series, since, now, (paid_d, f"your plan: {paid_d:g} Mbit/s down") if paid_d else None)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [time.strftime("%d %b %H:%M", time.localtime(r["ts"])),
                    "-" if r["down"] is None else f"{r['down']:.1f} Mbit/s", "-" if r["up"] is None else f"{r['up']:.1f} Mbit/s",
                    "-" if r["latency"] is None else f"{r['latency']:.0f} ms", "-" if r["jitter"] is None else f"{r['jitter']:.1f} ms",
                    r["error"] or ""]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 1 and r["down"] is not None and paid_d:
                    it.setForeground(QColor(speedtest.verdict(r["down"], paid_d)[1]))
                if r["down"] is None:
                    it.setForeground(QColor("#dc2626"))
                self.table.setItem(i, c, it)

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export speed tests", "speed-tests.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["time", "download_mbps", "upload_mbps", "latency_ms", "jitter_ms", "server", "error"])
            for r in reversed(self.ctx.history.speedtests(0, 100000)):
                w.writerow([time.strftime("%Y-%m-%d %H:%M", time.localtime(r["ts"])), r["down"], r["up"], r["latency"], r["jitter"],
                            r["server"], r["error"]])
        self.ctx.toast("Speed tests exported.", "ok")

    def on_show(self) -> None:
        self.load()
        self.refresh()
