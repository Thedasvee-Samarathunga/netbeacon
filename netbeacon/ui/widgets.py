"""Reusable widgets: banners, stat cards, status delegates, charts, background tasks."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem, QToolTip, QVBoxLayout, QWidget)

from . import theme
from .. import knowledge
from ..store import ST_DOWN, ST_RETRY, ST_SKIPPED, ST_UP


# --------------------------------------------------------------------------- teaching mode hub
class TeachingHub(QObject):
    changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.enabled = True

    def set(self, value: bool) -> None:
        if value != self.enabled:
            self.enabled = value
            self.changed.emit(value)


hub = TeachingHub()


def make_button(text: str, kind: str = "", tooltip: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def label(text: str = "", name: str = "", wrap: bool = False, rich: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    if rich:
        lb.setTextFormat(Qt.TextFormat.RichText)
        lb.setOpenExternalLinks(True)
    return lb


class HelpText(QLabel):
    """A small grey explanation that only appears in Teaching mode."""

    def __init__(self, text: str, always: bool = False) -> None:
        super().__init__(text)
        self.setObjectName("help")
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setOpenExternalLinks(True)
        self.always = always
        self.setVisible(always or hub.enabled)
        hub.changed.connect(lambda on: self.setVisible(self.always or on))


class InfoBanner(QFrame):
    """The blue 'Did you know?' box at the top of each page."""

    def __init__(self, key: str) -> None:
        super().__init__()
        self.setObjectName("banner")
        title, text = knowledge.TIPS[key]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)
        t = QLabel(f"<b>{title}</b>")
        t.setTextFormat(Qt.TextFormat.RichText)
        b = QLabel(text)
        b.setWordWrap(True)
        b.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(t)
        lay.addWidget(b)
        self.setVisible(hub.enabled)
        hub.changed.connect(self.setVisible)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label(title, "h1"))
        if subtitle:
            s = label(subtitle, "muted", wrap=True)
            col.addWidget(s)
        self.row.addLayout(col, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self.row.addLayout(self.actions)

    def add_action(self, w: QWidget) -> QWidget:
        self.actions.addWidget(w)
        return w


class StatCard(QFrame):
    def __init__(self, title: str, tooltip: str = "") -> None:
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(0)
        self.title = label(title, "muted")
        self.value = label("-", "statvalue")
        self.sub = label("", "muted")
        self.sub.setWordWrap(True)
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)
        if tooltip:
            self.setToolTip(tooltip)

    def set(self, value: str, sub: str = "", color: str | None = None) -> None:
        self.value.setText(value)
        self.sub.setText(sub)
        self.value.setStyleSheet(f"color: {color};" if color else "")


def card_frame() -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    return f, lay


# --------------------------------------------------------------------------- delegates
ROLE_STATUS = Qt.ItemDataRole.UserRole + 1
ROLE_BARS = Qt.ItemDataRole.UserRole + 2
ROLE_SORT = Qt.ItemDataRole.UserRole + 3

BAR_COLORS = {ST_UP: "#16a34a", ST_DOWN: "#dc2626", ST_RETRY: "#f59e0b", ST_SKIPPED: "#94a3b8"}


class StatusDelegate(QStyledItemDelegate):
    """Coloured pill with the status word."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight().color().lighter(170) if theme._current == "light" else QColor(theme.palette()["selection"]))
        status = index.data(ROLE_STATUS) or "pending"
        color = QColor(theme.STATUS_COLORS.get(status, "#64748b"))
        text = theme.STATUS_LABELS.get(status, status)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont(option.font)
        f.setBold(True)
        f.setPointSizeF(max(8.0, f.pointSizeF() - 1))
        painter.setFont(f)
        fm = QFontMetrics(f)
        w = fm.horizontalAdvance(text) + 26
        h = fm.height() + 6
        r = QRectF(option.rect.left() + 8, option.rect.center().y() - h / 2, w, h)
        bg = QColor(color)
        bg.setAlpha(34)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(r, h / 2, h / 2)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(r.left() + 11, r.center().y()), 4, 4)
        painter.setPen(color.darker(115) if theme._current == "light" else color.lighter(120))
        painter.drawText(QRectF(r.left() + 20, r.top(), w - 20, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(120, 34)


class BarsDelegate(QStyledItemDelegate):
    """Row of tiny coloured bars: the most recent results, newest on the right."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(theme.palette()["selection"]))
        bars = index.data(ROLE_BARS) or []
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        n = 40
        r = option.rect.adjusted(6, 9, -6, -9)
        gap = 1
        bw = max(2, (r.width() - gap * (n - 1)) // n)
        total = n * bw + (n - 1) * gap
        x = r.right() - total + 1
        shown = bars[-n:]
        offset = n - len(shown)
        empty = QColor(theme.palette()["border"])
        for i in range(n):
            if i < offset:
                painter.fillRect(QRect(x + i * (bw + gap), r.top(), bw, r.height()), empty)
            else:
                st = shown[i - offset]
                painter.fillRect(QRect(x + i * (bw + gap), r.top(), bw, r.height()), QColor(BAR_COLORS.get(st, "#94a3b8")))
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(220, 34)


# --------------------------------------------------------------------------- chart
class LineChart(QWidget):
    """Response-time line + status strip. Hover for details."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(230)
        self.setMouseTracking(True)
        self.points: list[dict] = []
        self.since = 0.0
        self.until = 0.0
        self.unit = "ms"
        self.empty_text = "Choose a check to see its history."
        self._hover: Optional[int] = None

    def set_data(self, points: list[dict], since: float, until: float) -> None:
        self.points, self.since, self.until = points, since, until
        self._hover = None
        self.update()

    def _geometry(self) -> tuple[QRectF, QRectF]:
        w, h = self.width(), self.height()
        plot = QRectF(52, 14, w - 70, h - 72)
        strip = QRectF(52, h - 40, w - 70, 12)
        return plot, strip

    def _x(self, ts: float, plot: QRectF) -> float:
        span = max(self.until - self.since, 1.0)
        return plot.left() + (ts - self.since) / span * plot.width()

    def paintEvent(self, _event) -> None:
        pal = theme.palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(pal["card"]))
        plot, strip = self._geometry()
        muted = QColor(pal["muted"])
        grid = QColor(pal["border"])
        if not self.points:
            p.setPen(muted)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)
            return
        lat = [pt["avg"] for pt in self.points if pt["avg"] is not None]
        mx = max([pt["max"] or 0 for pt in self.points] + [1.0])
        top = _nice_ceiling(mx)
        small = QFont(self.font())
        small.setPointSizeF(max(7.5, small.pointSizeF() - 1.5))
        p.setFont(small)
        # grid + y labels
        for i in range(5):
            y = plot.bottom() - plot.height() * i / 4
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(muted)
            if lat:
                p.drawText(QRectF(0, y - 8, plot.left() - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{top * i / 4:g}")
        # x labels
        for i in range(5):
            ts = self.since + (self.until - self.since) * i / 4
            x = plot.left() + plot.width() * i / 4
            fmt = "%H:%M" if (self.until - self.since) <= 2 * 86400 else "%d %b"
            p.setPen(muted)
            p.drawText(QRectF(x - 40, plot.bottom() + 4, 80, 16), Qt.AlignmentFlag.AlignHCenter, time.strftime(fmt, time.localtime(ts)))
        # latency line
        if lat:
            pts = [(self._x(pt["ts"], plot), plot.bottom() - (pt["avg"] / top) * plot.height()) for pt in self.points if pt["avg"] is not None]
            accent = QColor(pal["accent"])
            poly = QPolygonF([QPointF(pts[0][0], plot.bottom())] + [QPointF(x, y) for x, y in pts] + [QPointF(pts[-1][0], plot.bottom())])
            fill = QColor(accent)
            fill.setAlpha(40)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawPolygon(poly)
            p.setPen(QPen(accent, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in pts]))
            p.setPen(muted)
            p.drawText(QRectF(plot.left() + 4, plot.top() - 2, 160, 14), f"response time ({self.unit})")
        else:
            p.setPen(muted)
            p.drawText(plot, Qt.AlignmentFlag.AlignCenter, "This check type has no response time - see the status strip below.")
        # status strip
        span = max(self.until - self.since, 1.0)
        bw = max(2.0, plot.width() / max(len(self.points), 1) * 0.9)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grid)
        p.drawRoundedRect(strip, 3, 3)
        for pt in self.points:
            x = self._x(pt["ts"], plot)
            color = "#dc2626" if pt["fails"] else "#16a34a"
            p.setBrush(QColor(color))
            p.drawRect(QRectF(x - bw / 2, strip.top(), bw, strip.height()))
            if pt["fails"] and lat:
                p.setPen(QPen(QColor("#dc2626"), 1, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
                p.setPen(Qt.PenStyle.NoPen)
        p.setPen(muted)
        p.drawText(QRectF(0, strip.top() - 2, plot.left() - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "status")
        # hover
        if self._hover is not None and 0 <= self._hover < len(self.points):
            pt = self.points[self._hover]
            x = self._x(pt["ts"], plot)
            p.setPen(QPen(muted, 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(x, plot.top()), QPointF(x, strip.bottom()))

    def mouseMoveEvent(self, e) -> None:
        if not self.points:
            return
        plot, _ = self._geometry()
        x = e.position().x()
        best = min(range(len(self.points)), key=lambda i: abs(self._x(self.points[i]["ts"], plot) - x))
        if abs(self._x(self.points[best]["ts"], plot) - x) > 30:
            self._hover = None
            QToolTip.hideText()
        else:
            self._hover = best
            pt = self.points[best]
            when = time.strftime("%d %b %H:%M", time.localtime(pt["ts"]))
            parts = [when]
            if pt["avg"] is not None:
                parts.append(f"avg {pt['avg']:.0f} ms, max {pt['max']:.0f} ms")
            parts.append(f"{pt['fails']} failed of {pt['n']} checks" if pt["fails"] else f"all {pt['n']} checks OK")
            QToolTip.showText(e.globalPosition().toPoint(), "\n".join(parts), self)
        self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = None
        self.update()


def _nice_ceiling(v: float) -> float:
    for step in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 30000, 60000):
        if v <= step:
            return float(step)
    return float(v)


# --------------------------------------------------------------------------- background task
class Task(QThread):
    """Run a function off the GUI thread. The function receives the task so it can report progress
    (`t.report(done, total, text)`) and poll `t.cancelled`."""

    progress = Signal(int, int, str)
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[["Task"], Any], parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._fn = fn
        self.cancel_event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self) -> None:
        self.cancel_event.set()

    def report(self, done: int, total: int, text: str = "") -> None:
        self.progress.emit(done, total, text)

    def run(self) -> None:
        try:
            res = self._fn(self)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.result.emit(res)
