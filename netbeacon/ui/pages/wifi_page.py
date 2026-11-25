"""Wi-Fi health: signal, channel, link speed, nearby networks and plain-English advice."""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView, QSplitter, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ... import wifi
from .. import theme
from ..widgets import HelpText, InfoBanner, PageHeader, SeriesChart, StatCard, Task, card_frame, label, make_button
from .base import Page

RANGES = [("Last 6 hours", 6 * 3600), ("Last 24 hours", 86400), ("Last 7 days", 7 * 86400)]


class ChannelBars(QWidget):
    """How crowded each 2.4 GHz channel is (overlap included), with your channel highlighted."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(150)
        self.scores: dict[int, float] = {}
        self.mine: Optional[int] = None

    def set_data(self, scores: dict[int, float], mine: Optional[int]) -> None:
        self.scores, self.mine = scores, mine
        self.update()

    def paintEvent(self, _e) -> None:
        pal = theme.palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(pal["card"]))
        small = QFont(self.font())
        small.setPointSizeF(max(7.5, small.pointSizeF() - 1.5))
        p.setFont(small)
        if not self.scores or not any(self.scores.values()):
            p.setPen(QColor(pal["muted"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No 2.4 GHz networks seen.")
            return
        chans = list(range(1, 14))
        top = max(max(self.scores.values()), 1.0)
        w = (self.width() - 20) / len(chans)
        base = self.height() - 22
        for i, ch in enumerate(chans):
            v = self.scores.get(ch, 0.0)
            h = (base - 10) * v / top
            x = 10 + i * w
            col = QColor(pal["accent"]) if ch == self.mine else QColor("#94a3b8")
            if ch in (1, 6, 11) and ch != self.mine:
                col = QColor("#64748b")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x + 3, base - h, w - 6, max(h, 2)), 3, 3)
            p.setPen(QColor(pal["text"] if ch in (1, 6, 11) or ch == self.mine else pal["muted"]))
            p.drawText(QRectF(x, base + 3, w, 16), Qt.AlignmentFlag.AlignHCenter, str(ch))


class WifiPage(Page):
    key = "wifi"
    title = "Wi-Fi"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.status: Optional[wifi.WifiStatus] = None
        self.networks: list[wifi.WifiNetwork] = []
        self._task: Optional[Task] = None
        self._sample_task: Optional[Task] = None
        head = PageHeader("Wi-Fi health", "How good is this PC's Wi-Fi connection, and what is it competing with?")
        self.watch_btn = head.add_action(make_button("Watch the signal (add a check)..."))
        self.refresh_btn = head.add_action(make_button("Refresh", "primary"))
        self.root.addWidget(head)
        self.root.addWidget(InfoBanner("wifi"))
        self.note = label("", "muted", wrap=True, rich=True)
        self.root.addWidget(self.note)
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.c_sig = StatCard("Signal", "Windows' signal percentage, with the approximate radio strength in dBm (closer to 0 is stronger).")
        self.c_net = StatCard("Network", "The network name (SSID), band and channel this PC is using.")
        self.c_rate = StatCard("Link speed", "The speed of the radio link between this PC and the access point. Your internet can't be faster than this.")
        self.c_ap = StatCard("Access point", "Which access point (BSSID) you are connected to, the Wi-Fi standard and security.")
        for c in (self.c_sig, self.c_net, self.c_rate, self.c_ap):
            cards.addWidget(c, 1)
        self.root.addLayout(cards)

        self.advice_frame, al = card_frame()
        al.addWidget(label("What NetBeacon suggests", "h2"))
        self.advice = label("", wrap=True, rich=True)
        al.addWidget(self.advice)
        self.root.addWidget(self.advice_frame)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(label("Signal over time", "h2"))
        bar.addStretch(1)
        self.range = QComboBox()
        for t, s in RANGES:
            self.range.addItem(t, s)
        self.range.setCurrentIndex(1)
        bar.addWidget(self.range)
        ll.addLayout(bar)
        self.chart = SeriesChart("%")
        self.chart.fixed_top = 100
        self.chart.empty_text = "No samples yet. NetBeacon records the signal once a minute while it runs (Windows only)."
        ll.addWidget(self.chart, 1)
        split.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        rl.addWidget(label("Nearby networks", "h2"))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Network", "Signal", "Band", "Channel", "Security"])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 170)
        rl.addWidget(self.table, 1)
        rl.addWidget(label("2.4 GHz channel crowding (your channel in blue)", "muted"))
        self.bars = ChannelBars()
        rl.addWidget(self.bars)
        rl.addWidget(HelpText("On 2.4 GHz only channels <b>1, 6 and 11</b> don't overlap each other. Networks on the channels in between "
                              "interfere with two of them. 5 GHz has many more non-overlapping channels, which is why it's usually faster."))
        split.addWidget(right)
        split.setSizes([620, 520])
        self.root.addWidget(split, 1)

        self.refresh_btn.clicked.connect(lambda: self.refresh())
        self.range.currentIndexChanged.connect(lambda _i: self._chart())
        self.watch_btn.clicked.connect(lambda: self._watch())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._sample)
        self.timer.start(60 * 1000)
        self._loaded = False
        self._render()

    # ---- background sampling (feeds the chart and the weekly summary)
    def _sample(self) -> None:
        if not wifi.IS_WINDOWS or not self.ctx.store.get("wifi_sample_enabled", True) or self.ctx.core.info.paused:
            return
        if self._sample_task and self._sample_task.isRunning():
            return
        self._sample_task = Task(lambda _t: wifi.read_status(), self)
        self._sample_task.result.connect(self._record)
        self._sample_task.start()

    def _record(self, st: wifi.WifiStatus) -> None:
        if st.available and st.connected:
            self.ctx.history.add_wifi_sample(time.time(), st.ssid, st.bssid, st.signal, st.channel, st.band, st.rx_mbps, st.tx_mbps)
            if self.isVisible():
                self.status = st
                self._render()

    # ---- refresh
    def on_show(self) -> None:
        if not self._loaded:
            self.refresh()
        else:
            self._chart()

    def refresh(self) -> None:
        if self._task and self._task.isRunning():
            return
        self._loaded = True
        self.refresh_btn.setEnabled(False)
        self.note.setText("Reading Wi-Fi details...")

        def work(_t: Task):
            st = wifi.read_status()
            nets, note = wifi.scan_networks()
            return st, nets, note

        self._task = Task(work, self)
        self._task.result.connect(self._loaded_data)
        self._task.failed.connect(lambda m: (self.refresh_btn.setEnabled(True), self.note.setText(f"Could not read Wi-Fi details: {m}")))
        self._task.start()

    def _loaded_data(self, res) -> None:
        self.refresh_btn.setEnabled(True)
        st, nets, note = res
        self.status, self.networks = st, nets
        if st.available and st.connected:
            self._record(st)
        self._render(note)

    def _render(self, scan_note: str = "") -> None:
        st = self.status
        notes = []
        if st is None:
            notes.append("Press <b>Refresh</b> to read this PC's Wi-Fi details.")
        elif not st.available:
            notes.append(st.note)
        elif not st.connected:
            notes.append("This PC isn't connected to Wi-Fi right now (it may be using a cable - that's great, cables are more reliable).")
        if scan_note and scan_note not in notes:
            notes.append(scan_note)
        self.note.setText("<br>".join(n for n in notes if n))
        self.note.setVisible(bool(notes))
        if st and st.available and st.connected:
            word, col = wifi.quality(st.signal)
            self.c_sig.set(f"{st.signal}%" if st.signal is not None else "-", f"{word}, about {st.dbm} dBm" if st.dbm is not None else word, col)
            self.c_net.set(st.ssid or "(hidden)", f"{st.band or '?'} - channel {st.channel or '?'}")
            rate = f"{st.rx_mbps:g} Mbit/s" if st.rx_mbps is not None else "-"
            self.c_rate.set(rate, f"receive {st.rx_mbps:g} / send {st.tx_mbps:g}" if st.rx_mbps is not None and st.tx_mbps is not None else "")
            self.c_ap.set(st.radio or "-", " - ".join(x for x in (st.bssid, st.auth) if x))
            tips = wifi.advice(st, self.networks)
            self.advice.setText("<ul style='margin:0'>" + "".join(f"<li>{t}</li>" for t in tips) + "</ul>")
            self.advice_frame.setVisible(True)
        else:
            for c in (self.c_sig, self.c_net, self.c_rate, self.c_ap):
                c.set("-", "")
            self.advice_frame.setVisible(False)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.networks))
        mine = st.bssid if st else ""
        for r, n in enumerate(sorted(self.networks, key=lambda n: -(n.signal or 0))):
            vals = [n.ssid or "(hidden network)", n.signal, n.band, n.channel, n.auth]
            for c, v in enumerate(vals):
                it = QTableWidgetItem()
                it.setData(Qt.ItemDataRole.DisplayRole, v if v is not None else "")
                if n.bssid and n.bssid == mine:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                if c == 1 and isinstance(v, int):
                    it.setForeground(QColor(wifi.quality(v)[1]))
                    it.setData(Qt.ItemDataRole.DisplayRole, v)
                self.table.setItem(r, c, it)
        self.table.setSortingEnabled(True)
        self.bars.set_data(wifi.crowding(self.networks, "2.4 GHz"), st.channel if st and st.band == "2.4 GHz" else None)
        self._chart()

    def _chart(self) -> None:
        now = time.time()
        since = now - int(self.range.currentData())
        samples = self.ctx.history.wifi_samples(since)
        series = [{"name": "Signal", "color": "#2563eb", "points": [(s["ts"], s["signal"]) for s in samples if s["signal"] is not None]}]
        self.chart.set_data(series, since, now, (40, "below 40%: calls start to stutter"))

    def _watch(self) -> None:
        ssid = self.status.ssid if self.status and self.status.connected else ""
        self.ctx.main_window.open_check_dialog(kind="wifi", params={"min_signal": 40, "ssid": ssid}, name="Wi-Fi signal")
