"""Network map: the internet, your router in the middle, and every device around it - coloured by health."""
from __future__ import annotations

import math
import time
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QInputDialog, QLabel, QSizePolicy, QVBoxLayout, QToolTip, QWidget

from ... import netutil
from ...devices import stored_rows
from .. import theme
from ..widgets import HelpText, InfoBanner, PageHeader, Task, card_frame, label, make_button
from .base import Page

RECENT_S = 12 * 3600          # a device seen within this time counts as "around"
STATE_COLORS = {"up": "#16a34a", "down": "#dc2626", "error": "#dc2626", "retry": "#f59e0b", "skipped": "#94a3b8",
                "pending": "#64748b", "paused": "#9ca3af", "watched": "#2563eb", "new": "#db2777", "away": "#9ca3af", "self": "#7c3aed"}
STATE_WORDS = {"up": "Checks OK", "down": "Problem", "error": "Problem", "retry": "Retrying", "skipped": "Waiting",
               "pending": "Checking", "paused": "Paused", "watched": "Not monitored", "new": "NEW - not reviewed", "away": "Not seen lately",
               "self": "This computer"}
WORST = ["down", "error", "retry", "skipped", "pending", "up", "paused"]


def _kind_order(kind: str) -> int:
    k = (kind or "").lower()
    for i, word in enumerate(("server", "windows", "linux", "printer", "camera", "web page", "raspberry", "vm", "apple", "phone", "chromecast")):
        if word in k:
            return i
    return 50


class MapCanvas(QWidget):
    node_clicked = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(380)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.nodes: list[dict] = []          # {key, label, sub, state, kind, tip}
        self.router: Optional[dict] = None
        self.internet_state = "watched"
        self.selected = ""
        self._pos: dict[str, tuple[QPointF, float]] = {}

    def set_model(self, router: Optional[dict], nodes: list[dict], internet_state: str) -> None:
        self.router, self.nodes, self.internet_state = router, nodes, internet_state
        self.update()

    # ---- geometry
    def _layout(self) -> None:
        self._pos.clear()
        w, h = self.width(), self.height()
        center = QPointF(w / 2, h / 2 + 30)
        self._pos["__internet"] = (QPointF(w / 2, 46), 30)
        self._pos["__router"] = (center, 34)
        n = len(self.nodes)
        if not n:
            return
        max_r = min(w / 2 - 70, (h - 90) / 2 + 10)
        spacing = 78.0
        rings: list[tuple[float, int]] = []
        r, left = max(150.0, min(w, h) * 0.30), n
        while left > 0:
            cap = max(6, int(2 * math.pi * r / spacing))
            rings.append((r, min(cap, left)))
            left -= cap
            r += 92
        scale = min(1.0, max_r / rings[-1][0]) if rings[-1][0] > max_r else 1.0
        i = 0
        for ring_no, (radius, count) in enumerate(rings):
            radius *= scale
            offset = (math.pi / count) if ring_no % 2 else 0.0
            for k in range(count):
                a = -math.pi / 2 + offset + 2 * math.pi * k / count + 0.35   # leave the top (internet line) a bit clearer
                p = QPointF(center.x() + radius * math.cos(a) * (w / max(h, 1)) ** 0.35, center.y() + radius * math.sin(a))
                self._pos[self.nodes[i]["key"]] = (p, 18 if scale > 0.7 else 14)
                i += 1

    def paintEvent(self, _e) -> None:
        pal = theme.palette()
        self._layout()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(pal["card"]))
        line = QColor(pal["border"])
        rc, rr = self._pos["__router"]
        ic, ir = self._pos["__internet"]
        p.setPen(QPen(QColor(STATE_COLORS.get(self.internet_state, "#94a3b8")), 3, Qt.PenStyle.SolidLine))
        p.drawLine(ic + QPointF(0, ir * 0.6), rc - QPointF(0, rr))
        for nd in self.nodes:
            pt, _ = self._pos[nd["key"]]
            pen = QPen(line, 1.6, Qt.PenStyle.DashLine if nd["state"] == "away" else Qt.PenStyle.SolidLine)
            if nd["state"] in ("down", "error"):
                pen = QPen(QColor(STATE_COLORS["down"]), 1.6)
            p.setPen(pen)
            p.drawLine(rc, pt)
        self._cloud(p, ic, ir, QColor(STATE_COLORS.get(self.internet_state, "#94a3b8")))
        f = QFont(self.font())
        small = QFont(f)
        small.setPointSizeF(max(7.5, f.pointSizeF() - 1.5))
        p.setFont(small)
        p.setPen(QColor(pal["muted"]))
        p.drawText(QRectF(ic.x() + ir + 8, ic.y() - 9, 200, 18), Qt.AlignmentFlag.AlignVCenter, "Internet")
        rstate = self.router["state"] if self.router else "watched"
        self._node(p, rc, rr, rstate, True, self.router["key"] == self.selected if self.router else False)
        p.setFont(f)
        p.setPen(QColor(pal["text"]))
        rl = self.router["label"] if self.router else "Router (unknown)"
        p.drawText(QRectF(rc.x() - 120, rc.y() + rr + 4, 240, 18), Qt.AlignmentFlag.AlignHCenter, rl)
        fm = QFontMetrics(small)
        for nd in self.nodes:
            pt, rad = self._pos[nd["key"]]
            self._node(p, pt, rad, nd["state"], False, nd["key"] == self.selected)
            p.setFont(small)
            p.setPen(QColor(pal["muted"] if nd["state"] == "away" else pal["text"]))
            text = fm.elidedText(nd["label"], Qt.TextElideMode.ElideRight, 110)
            p.drawText(QRectF(pt.x() - 60, pt.y() + rad + 2, 120, 16), Qt.AlignmentFlag.AlignHCenter, text)
        if not self.nodes:
            p.setPen(QColor(pal["muted"]))
            p.setFont(f)
            p.drawText(QRectF(0, self.height() - 60, self.width(), 40), Qt.AlignmentFlag.AlignCenter,
                       "No devices yet - press 'Scan network' to fill the map.")

    @staticmethod
    def _cloud(p: QPainter, c: QPointF, r: float, col: QColor) -> None:
        path = QPainterPath()
        for dx, dy, rr in ((-0.55, 0.15, 0.55), (0.0, -0.2, 0.7), (0.6, 0.12, 0.5), (0.0, 0.3, 0.55)):
            path.addEllipse(QPointF(c.x() + dx * r, c.y() + dy * r), rr * r, rr * r * 0.85)
        fill = QColor(col)
        fill.setAlpha(45)
        p.setPen(QPen(col, 2))
        p.setBrush(fill)
        p.drawPath(path.simplified())

    @staticmethod
    def _node(p: QPainter, c: QPointF, r: float, state: str, router: bool, selected: bool) -> None:
        col = QColor(STATE_COLORS.get(state, "#64748b"))
        fill = QColor(col)
        fill.setAlpha(50 if state != "away" else 25)
        if selected:
            p.setPen(QPen(QColor(theme.palette()["accent"]), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, r + 6, r + 6)
        p.setPen(QPen(col, 2.5, Qt.PenStyle.DashLine if state in ("new",) else Qt.PenStyle.SolidLine))
        p.setBrush(fill)
        if router:
            p.drawRoundedRect(QRectF(c.x() - r, c.y() - r * 0.7, 2 * r, 1.4 * r), 10, 10)
            p.setPen(QPen(col, 2.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for k, rad in enumerate((0.35, 0.6)):
                p.drawArc(QRectF(c.x() - r * rad, c.y() - r * rad - 2, 2 * r * rad, 2 * r * rad), 40 * 16, 100 * 16)
            p.setBrush(col)
            p.drawEllipse(QPointF(c.x(), c.y() + 1), 3, 3)
        else:
            p.drawEllipse(c, r, r)
            p.setBrush(col)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(c, r * 0.32, r * 0.32)

    # ---- interaction
    def _hit(self, pos: QPointF) -> Optional[str]:
        for key, (pt, rad) in self._pos.items():
            if (pt - pos).manhattanLength() <= rad * 1.6:
                return key
        return None

    def mousePressEvent(self, e) -> None:
        key = self._hit(e.position())
        if key == "__router" and self.router:
            key = self.router["key"]
        if key and not key.startswith("__"):
            self.selected = key
            self.node_clicked.emit(key)
            self.update()

    def mouseMoveEvent(self, e) -> None:
        key = self._hit(e.position())
        if key == "__router" and self.router:
            key = self.router["key"]
        nd = next((n for n in self.nodes + ([self.router] if self.router else []) if n and n["key"] == key), None)
        if key == "__internet":
            QToolTip.showText(e.globalPosition().toPoint(), "The internet. The line is red when your internet checks are failing.", self)
        elif nd:
            QToolTip.showText(e.globalPosition().toPoint(), nd["tip"], self)
        else:
            QToolTip.hideText()
        self.setCursor(Qt.CursorShape.PointingHandCursor if nd else Qt.CursorShape.ArrowCursor)


class MapPage(Page):
    key = "map"
    title = "Network map"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.rows: list[dict] = []
        self.by_key: dict[str, dict] = {}
        self._gw_task: Optional[Task] = None
        head = PageHeader("Network map", "Your router in the middle, everything else around it. Click a device for details.")
        self.scan_btn = head.add_action(make_button("Scan network", "primary"))
        self.root.addWidget(head)
        self.root.addWidget(InfoBanner("map"))
        legend = QHBoxLayout()
        for st in ("up", "down", "retry", "watched", "new", "away", "self"):
            dot = QLabel("\u25CF")
            dot.setStyleSheet(f"color:{STATE_COLORS[st]}; font-size:13pt;")
            legend.addWidget(dot)
            legend.addWidget(label(STATE_WORDS[st], "muted"))
            legend.addSpacing(10)
        legend.addStretch(1)
        self.root.addLayout(legend)
        body = QHBoxLayout()
        frame = QFrame()
        frame.setObjectName("card")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(4, 4, 4, 4)
        self.canvas = MapCanvas()
        fl.addWidget(self.canvas)
        body.addWidget(frame, 1)
        side, sl = card_frame()
        side.setFixedWidth(300)
        self.d_title = label("Pick a device", "h2", wrap=True)
        self.d_info = label("Click any circle on the map to see what it is, how its checks are doing, and what you can do with it.", "muted", wrap=True, rich=True)
        sl.addWidget(self.d_title)
        sl.addWidget(self.d_info)
        self.b_check = make_button("Monitor it (add a ping check)...")
        self.b_ports = make_button("Scan its ports...")
        self.b_wake = make_button("Wake it up (Wake-on-LAN)")
        self.b_name = make_button("Give it a name...")
        self.b_known = make_button("Mark as known")
        self.b_diag = make_button("What's wrong with it?")
        for b in (self.b_diag, self.b_check, self.b_ports, self.b_wake, self.b_name, self.b_known):
            sl.addWidget(b)
            b.setVisible(False)
        sl.addStretch(1)
        sl.addWidget(HelpText("A device with a check shows that check's colour. Devices without a check are blue: NetBeacon knows them "
                              "but isn't watching them. Dashed grey = not seen in the last 12 hours."))
        body.addWidget(side)
        self.root.addLayout(body, 1)
        self.canvas.node_clicked.connect(self._select)
        self.scan_btn.clicked.connect(lambda: self._scan())
        self.b_check.clicked.connect(lambda: self._add_check())
        self.b_ports.clicked.connect(lambda: self.ctx.main_window.scan_ports_of(self.by_key[self.canvas.selected]["ip"]))
        self.b_wake.clicked.connect(lambda: self._wake())
        self.b_name.clicked.connect(lambda: self._rename())
        self.b_known.clicked.connect(lambda: self._known())
        self.b_diag.clicked.connect(lambda: self._diagnose())
        ctx.devices_changed.connect(lambda: self.rebuild())
        ctx.snapshot_changed.connect(lambda _rows: self.rebuild() if self.isVisible() else None)
        self.rebuild()

    # ---- data
    def _device_rows(self) -> list[dict]:
        page = getattr(self.ctx.main_window, "pages", {}).get("devices") if self.ctx.main_window else None
        rows = list(page.rows) if page is not None and page.rows else stored_rows(self.ctx.history)
        return rows

    def _check_states(self) -> dict[str, list[tuple[str, str]]]:
        """ip/host -> [(check name, status)]"""
        status = {r["id"]: r["status"] for r in (self.ctx.main_window.pages["dashboard"].model.rows if self.ctx.main_window else [])}
        out: dict[str, list[tuple[str, str]]] = {}
        for m in self.ctx.store.monitors:
            host = str(m.params.get("host", "")).strip()
            if host:
                out.setdefault(host, []).append((m.name, status.get(m.id, "pending" if m.enabled else "paused")))
        return out

    def rebuild(self) -> None:
        now = time.time()
        rows = self._device_rows()
        checks = self._check_states()
        my_ips = {n.ip for n in netutil.local_networks()}
        gw_ip = self.ctx.store.get("last_gateway", "") or next((r["ip"] for r in rows if r.get("is_gateway")), "")
        self.rows = rows
        self.by_key = {}
        nodes: list[dict] = []
        router = None
        for r in rows:
            name = r["name"] or r["hostname"] or ""
            mine = checks.get(r["ip"], []) + (checks.get(r["hostname"], []) if r["hostname"] else [])
            recent = r.get("seen_now") or (now - (r.get("last_seen") or 0) < RECENT_S)
            if r.get("is_self") or r["ip"] in my_ips:
                state = "self"
            elif mine:
                state = min((s for _, s in mine), key=lambda s: WORST.index(s) if s in WORST else 99)
            elif not recent:
                state = "away"
            elif not r["known"]:
                state = "new"
            else:
                state = "watched"
            tip = [f"<b>{name or r['ip']}</b>", r["ip"]]
            if r["mac"]:
                tip.append(r["mac"] + (" (private / randomised)" if r.get("randomized") else ""))
            if r.get("kind"):
                tip.append(r["kind"])
            tip.append(STATE_WORDS.get(state, state))
            for cn, cs in mine:
                tip.append(f"{cn}: {STATE_WORDS.get(cs, cs)}")
            nd = {"key": r["key"], "label": name or r["ip"], "state": state, "kind": r.get("kind", ""), "tip": "<br>".join(tip),
                  "ip": r["ip"], "row": r, "checks": mine}
            self.by_key[r["key"]] = nd
            if gw_ip and r["ip"] == gw_ip:
                nd["label"] = name or f"Router {r['ip']}"
                router = nd
            else:
                nodes.append(nd)
        if router is None and gw_ip:
            mine = checks.get(gw_ip, [])
            state = min((s for _, s in mine), key=lambda s: WORST.index(s) if s in WORST else 99) if mine else "watched"
            router = {"key": f"ip:{gw_ip}", "label": f"Router {gw_ip}", "state": state, "kind": "Router", "ip": gw_ip, "row": None,
                      "checks": mine, "tip": f"<b>Router</b><br>{gw_ip}<br>{STATE_WORDS.get(state, state)}"}
            self.by_key[router["key"]] = router
        nodes.sort(key=lambda n: (n["state"] == "away", _kind_order(n["kind"]),
                                  tuple(int(x) for x in n["ip"].split(".")) if n["ip"].count(".") == 3 else (999,)))
        # the internet's colour = the worst state of internet-ish checks
        from ... import digest
        names = set(digest.internet_checks(self.ctx.store))
        status = {r["name"]: r["status"] for r in (self.ctx.main_window.pages["dashboard"].model.rows if self.ctx.main_window else [])}
        inet = [status[n] for n in names if n in status]
        internet_state = min(inet, key=lambda s: WORST.index(s) if s in WORST else 99) if inet else "watched"
        self.canvas.set_model(router, nodes, internet_state)
        if self.canvas.selected in self.by_key:
            self._select(self.canvas.selected)

    def on_show(self) -> None:
        self.rebuild()
        if not self.ctx.store.get("last_gateway") and not (self._gw_task and self._gw_task.isRunning()):
            self._gw_task = Task(lambda _t: netutil.default_gateway(), self)
            self._gw_task.result.connect(self._got_gateway)
            self._gw_task.start()

    def _got_gateway(self, gw) -> None:
        if gw:
            self.ctx.store.set("last_gateway", gw)
            self.rebuild()

    # ---- side panel
    def _select(self, key: str) -> None:
        nd = self.by_key.get(key)
        if not nd:
            return
        r = nd["row"] or {}
        self.d_title.setText(nd["label"])
        lines = [f"<b>IP address:</b> {nd['ip']}"]
        if r.get("hostname"):
            lines.append(f"<b>Network name:</b> {r['hostname']}")
        if r.get("mac"):
            lines.append(f"<b>MAC address:</b> {r['mac']}" + (" <i>(private)</i>" if r.get("randomized") else ""))
        if nd["kind"]:
            lines.append(f"<b>Looks like:</b> {nd['kind']}")
        if r.get("first_seen"):
            lines.append(f"<b>First seen:</b> {time.strftime('%d %b %Y', time.localtime(r['first_seen']))}")
        if r.get("last_seen"):
            lines.append(f"<b>Last seen:</b> {time.strftime('%d %b %H:%M', time.localtime(r['last_seen']))}")
        col = STATE_COLORS.get(nd["state"], "#64748b")
        lines.append(f"<b>Status:</b> <span style='color:{col}'>{STATE_WORDS.get(nd['state'], nd['state'])}</span>")
        for cn, cs in nd["checks"]:
            lines.append(f"&nbsp;&nbsp;- {cn}: <span style='color:{STATE_COLORS.get(cs, '#64748b')}'>{STATE_WORDS.get(cs, cs)}</span>")
        self.d_info.setText("<br>".join(lines))
        has_row = bool(nd["row"])
        self.b_check.setVisible(not nd["checks"])
        self.b_ports.setVisible(True)
        self.b_wake.setVisible(bool(r.get("mac")) and nd["state"] != "self")
        self.b_name.setVisible(has_row)
        self.b_known.setVisible(has_row and not r.get("known"))
        self.b_diag.setVisible(bool(nd["checks"]))

    def _add_check(self) -> None:
        nd = self.by_key.get(self.canvas.selected)
        if nd:
            self.ctx.main_window.open_check_dialog(kind="ping", params={"host": nd["ip"]}, name=f"Ping {nd['label']}")
            self.rebuild()

    def _wake(self) -> None:
        nd = self.by_key.get(self.canvas.selected)
        if nd and nd["row"] and nd["row"].get("mac"):
            self.ctx.main_window.wake_device(nd["row"]["mac"], nd["label"])

    def _rename(self) -> None:
        nd = self.by_key.get(self.canvas.selected)
        if not nd or not nd["row"]:
            return
        text, ok = QInputDialog.getText(self, "Name this device", "A friendly name (e.g. 'Reception printer'):", text=nd["row"].get("name", ""))
        if ok:
            self.ctx.history.set_device(nd["key"], name=text.strip(), known=1)
            nd["row"]["name"], nd["row"]["known"] = text.strip(), True
            self.ctx.devices_changed.emit()

    def _known(self) -> None:
        nd = self.by_key.get(self.canvas.selected)
        if nd and nd["row"]:
            self.ctx.history.set_device(nd["key"], known=1)
            nd["row"]["known"] = True
            self.ctx.devices_changed.emit()

    def _diagnose(self) -> None:
        nd = self.by_key.get(self.canvas.selected)
        if nd and nd["checks"]:
            m = self.ctx.store.by_name(nd["checks"][0][0])
            if m:
                self.ctx.main_window.diagnose(m.id)

    def _scan(self) -> None:
        dev = self.ctx.main_window.pages["devices"]
        if dev.task and dev.task.isRunning():
            self.ctx.toast("A scan is already running - the map updates when it finishes.", "info")
            return
        dev.start_scan()
        if dev.task and dev.task.isRunning():
            self.ctx.toast("Scanning your network... the map fills in when it's done (usually 5-20 seconds).", "info")
