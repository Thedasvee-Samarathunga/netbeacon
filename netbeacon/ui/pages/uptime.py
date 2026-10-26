"""Uptime, downtime, incidents and response-time history."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ... import netutil
from ..widgets import HelpText, InfoBanner, LineChart, PageHeader, StatCard, label, make_button
from .base import Page

RANGES = [("Last hour", 3600), ("Last 24 hours", 86400), ("Last 7 days", 7 * 86400), ("Last 30 days", 30 * 86400)]


def _tbl(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.setShowGrid(False)
    t.horizontalHeader().setStretchLastSection(True)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    return t


def fmt_ts(ts: float) -> str:
    return time.strftime("%d %b %H:%M", time.localtime(ts))


class UptimePage(Page):
    key = "uptime"
    title = "Uptime & history"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        head = PageHeader("Uptime & history", "How reliable has everything been - and when did it go wrong?")
        self.report_btn = head.add_action(make_button("Report (HTML)"))
        self.export_btn = head.add_action(make_button("Export CSV"))
        self.refresh_btn = head.add_action(make_button("Refresh"))
        self.root.addWidget(head)
        self.root.addWidget(InfoBanner("uptime"))

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Show:"))
        self.check = QComboBox()
        self.check.setMinimumWidth(260)
        self.range = QComboBox()
        for t, s in RANGES:
            self.range.addItem(t, s)
        self.range.setCurrentIndex(1)
        bar.addWidget(self.check)
        bar.addWidget(self.range)
        bar.addStretch(1)
        self.root.addLayout(bar)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.c_av = StatCard("Availability", "Share of checks that succeeded in this period.")
        self.c_down = StatCard("Total downtime", "Added-up length of all incidents in this period.")
        self.c_inc = StatCard("Incidents", "Separate outages. Many short ones (flapping) is a different problem from one long one.")
        self.c_mttr = StatCard("Average outage", "Mean time to recover (MTTR): average length of finished incidents.")
        self.c_lat = StatCard("Response time", "Average, with the fastest and slowest in the period.")
        for c in (self.c_av, self.c_down, self.c_inc, self.c_mttr, self.c_lat):
            cards.addWidget(c, 1)
        self.root.addLayout(cards)
        self.sla = HelpText("")
        self.root.addWidget(self.sla)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        tl = QVBoxLayout(left)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(label("All checks (click one to focus)", "h2"))
        self.summary = _tbl(["Check", "Uptime", "Downtime", "Incidents"])
        self.summary.setColumnWidth(0, 190)
        self.summary.setColumnWidth(1, 80)
        self.summary.setColumnWidth(2, 90)
        tl.addWidget(self.summary, 1)
        left.setMinimumWidth(400)
        split.addWidget(left)
        right = QSplitter(Qt.Orientation.Vertical)
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addWidget(label("Response time and status", "h2"))
        self.chart = LineChart()
        ml.addWidget(self.chart, 1)
        right.addWidget(mid)
        bot = QWidget()
        bl = QVBoxLayout(bot)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(label("Incidents (newest first)", "h2"))
        self.incidents = _tbl(["Check", "Started", "Ended", "Lasted", "What went wrong"])
        self.incidents.setColumnWidth(0, 160)
        self.incidents.setColumnWidth(1, 110)
        self.incidents.setColumnWidth(2, 110)
        self.incidents.setColumnWidth(3, 80)
        bl.addWidget(self.incidents, 1)
        right.addWidget(bot)
        right.setSizes([300, 220])
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([430, 700])
        self.root.addWidget(split, 1)

        self.refresh_btn.clicked.connect(self.refresh)
        self.export_btn.clicked.connect(self._export)
        self.report_btn.clicked.connect(self._report)
        self.check.currentIndexChanged.connect(self.refresh)
        self.range.currentIndexChanged.connect(self.refresh)
        self.summary.cellClicked.connect(self._summary_clicked)
        ctx.checks_changed.connect(self._reload_names)
        self._reload_names()

    # ------------------------------------------------------------------
    def _reload_names(self) -> None:
        cur = self.check.currentData()
        self.check.blockSignals(True)
        self.check.clear()
        self.check.addItem("All checks", "")
        for m in self.ctx.store.monitors:
            self.check.addItem(m.name, m.name)
        self.check.setCurrentIndex(max(0, self.check.findData(cur)))
        self.check.blockSignals(False)

    def show_check(self, name: str) -> None:
        self._reload_names()
        i = self.check.findData(name)
        if i >= 0:
            self.check.setCurrentIndex(i)
        self.refresh()

    def on_show(self) -> None:
        self._reload_names()
        self.refresh()

    def _summary_clicked(self, row: int, _col: int) -> None:
        it = self.summary.item(row, 0)
        if it:
            i = self.check.findData(it.text())
            if i >= 0:
                self.check.setCurrentIndex(i)

    @staticmethod
    def _dur(seconds: float) -> str:
        return netutil.format_duration(seconds) if seconds > 0 else "none"

    def refresh(self) -> None:
        h = self.ctx.history
        now = time.time()
        span = int(self.range.currentData())
        since = now - span
        selected = self.check.currentData() or None
        names = [m.name for m in self.ctx.store.monitors]

        # summary table
        self.summary.setRowCount(len(names))
        for r, n in enumerate(names):
            av = h.availability(n, since)
            inc = h.incidents(n, since)
            down = h.downtime_seconds(n, since, now)
            lat = h.latency_stats(n, since)
            longest = max([((i["ended"] or now) - i["started"]) for i in inc], default=0)
            pct = f"{av['pct']:.2f}%" if av["pct"] is not None else "no data"
            vals = [n, pct, self._dur(down), str(len(inc))]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 1 and av["pct"] is not None:
                    it.setForeground(QColor("#16a34a" if av["pct"] >= 99.5 else "#f59e0b" if av["pct"] >= 95 else "#dc2626"))
                self.summary.setItem(r, c, it)

        # cards
        av = h.availability(selected, since)
        inc = h.incidents(selected, since)
        down = h.downtime_seconds(selected, since, now) if selected else sum(h.downtime_seconds(n, since, now) for n in names)
        closed = [i["ended"] - i["started"] for i in inc if i["ended"]]
        lat = h.latency_stats(selected, since)
        if av["pct"] is None:
            self.c_av.set("-", "no data in this period yet")
        else:
            self.c_av.set(f"{av['pct']:.3f}%", f"{av['down']} of {av['total']} checks failed", "#16a34a" if av["pct"] >= 99.5 else "#f59e0b" if av["pct"] >= 95 else "#dc2626")
        self.c_down.set(self._dur(down), "added up over all incidents" if not selected else "")
        self.c_inc.set(str(len(inc)), f"{sum(1 for i in inc if i['ended'] is None)} still open" if any(i["ended"] is None for i in inc) else "")
        self.c_mttr.set(netutil.format_duration(sum(closed) / len(closed)) if closed else "-", "mean time to recover")
        self.c_lat.set(f"{lat['avg']:.0f} ms" if lat["avg"] is not None else "-", f"fastest {lat['min']:.0f}, slowest {lat['max']:.0f} ms" if lat["avg"] is not None else "not measured")
        allowed = span * 0.001
        self.sla.setText(f"<b>What would 99.9% mean?</b> In this period a 99.9% target allows about {netutil.format_duration(allowed)} of downtime"
                         f" - you had {self._dur(down)}{' (per check, summed)' if not selected else ''}. "
                         "Availability promises like this are exactly how internet providers and cloud services describe reliability.")

        # chart
        if selected:
            pts = h.series(selected, since, now, buckets=120)
            self.chart.empty_text = "No results recorded for this check in this period yet."
            self.chart.set_data(pts, since, now)
        else:
            self.chart.empty_text = "Choose a single check above to see its chart."
            self.chart.set_data([], since, now)

        # incidents
        self.incidents.setRowCount(len(inc))
        for r, i in enumerate(inc[:300]):
            lasted = (i["ended"] or now) - i["started"]
            reason = i["reason"] or ""
            if i["interrupted"]:
                reason += "  (NetBeacon was closed during this incident, so the end time is approximate)"
            vals = [i["monitor"], fmt_ts(i["started"]), fmt_ts(i["ended"]) if i["ended"] else "ONGOING", netutil.format_duration(lasted), reason]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if i["ended"] is None:
                    it.setForeground(QColor("#dc2626"))
                self.incidents.setItem(r, c, it)

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export results", "netbeacon-results.csv", "CSV (*.csv)")
        if path:
            n = self.ctx.history.export_csv(path, self.check.currentData() or None, time.time() - int(self.range.currentData()))
            self.ctx.toast(f"Exported {n:,} rows.", "ok")

    def _report(self) -> None:
        from ... import reports
        path, _ = QFileDialog.getSaveFileName(self, "Save report", "network-uptime-report.html", "Web page (*.html)")
        if not path:
            return
        now = time.time()
        text = reports.build_report(self.ctx.store, self.ctx.history, now - int(self.range.currentData()), now)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.ctx.toast("Report saved. Open it in your browser or print it to PDF.", "ok")
