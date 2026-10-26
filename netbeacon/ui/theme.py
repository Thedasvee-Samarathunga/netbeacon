"""Colours, stylesheet and the app icon (drawn in code - no image files needed)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPen, QPixmap

STATUS_COLORS = {
    "up": "#16a34a", "down": "#dc2626", "retry": "#f59e0b", "skipped": "#94a3b8",
    "pending": "#64748b", "paused": "#9ca3af", "error": "#a21caf",
}
STATUS_LABELS = {
    "up": "Up", "down": "DOWN", "retry": "Retrying", "skipped": "Waiting", "pending": "Checking...",
    "paused": "Paused", "error": "Problem",
}

PALETTES = {
    "light": dict(bg="#f3f5f9", card="#ffffff", text="#1f2937", muted="#6b7280", border="#e1e6ee", accent="#2563eb",
                  accent_text="#ffffff", sidebar="#0f172a", sidebar_text="#cbd5e1", sidebar_hover="#1e293b",
                  sidebar_active="#2563eb", input="#ffffff", banner="#eaf2ff", banner_border="#bfd6ff", banner_text="#1e3a8a",
                  row_alt="#f8fafc", selection="#dbeafe", code_bg="#f1f5f9", danger_bg="#fef2f2"),
    "dark": dict(bg="#0e1420", card="#162033", text="#e5e9f0", muted="#94a3b8", border="#27344b", accent="#4f8cff",
                 accent_text="#ffffff", sidebar="#0a0f1a", sidebar_text="#aab6c8", sidebar_hover="#152036",
                 sidebar_active="#2f6ff0", input="#0f1828", banner="#13264a", banner_border="#26457f", banner_text="#bcd3ff",
                 row_alt="#131d2f", selection="#1e3a6e", code_bg="#0f1828", danger_bg="#3a1618"),
}

_current = "light"


def palette(name: str | None = None) -> dict:
    return PALETTES[name or _current]


def set_current(name: str) -> None:
    global _current
    _current = name if name in PALETTES else "light"


def ensure_assets(name: str) -> dict:
    """Draw the tiny check-mark and chevron icons the stylesheet needs (no image files to ship)."""
    from PySide6.QtGui import QPainterPath

    from .. import paths

    folder = paths.data_dir() / "ui-assets"
    folder.mkdir(parents=True, exist_ok=True)
    files = {"check": folder / "check.png", "chevron": folder / f"chevron-{name}.png"}
    if not files["check"].exists():
        pm = QPixmap(32, 32)
        pm.fill(Qt.GlobalColor.transparent)
        pt = QPainter(pm)
        pt.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("white"), 4.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pt.setPen(pen)
        path = QPainterPath()
        path.moveTo(8, 17)
        path.lineTo(14, 23)
        path.lineTo(24, 9)
        pt.drawPath(path)
        pt.end()
        pm.save(str(files["check"]))
    if not files["chevron"].exists():
        pm = QPixmap(32, 32)
        pm.fill(Qt.GlobalColor.transparent)
        pt = QPainter(pm)
        pt.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(PALETTES[name]["muted"]), 3.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pt.setPen(pen)
        path = QPainterPath()
        path.moveTo(8, 12)
        path.lineTo(16, 20)
        path.lineTo(24, 12)
        pt.drawPath(path)
        pt.end()
        pm.save(str(files["chevron"]))
    return {k: v.as_posix() for k, v in files.items()}


def stylesheet(name: str) -> str:
    p = PALETTES[name]
    a = ensure_assets(name)
    return f"""
* {{ font-family: "Segoe UI", "Inter", "Noto Sans", "Helvetica Neue", Arial, sans-serif; font-size: 10pt; }}
QWidget {{ color: {p['text']}; }}
QMainWindow, QDialog, QWidget#page {{ background: {p['bg']}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QToolTip {{ background: {p['card']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 6px; }}

QFrame#card, QGroupBox {{ background: {p['card']}; border: 1px solid {p['border']}; border-radius: 10px; }}
QGroupBox {{ margin-top: 14px; padding: 14px 12px 10px 12px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {p['text']}; background: {p['bg']}; }}
QFrame#banner {{ background: {p['banner']}; border: 1px solid {p['banner_border']}; border-radius: 10px; }}
QFrame#banner QLabel {{ color: {p['banner_text']}; background: transparent; }}
QFrame#dangerbox {{ background: {p['danger_bg']}; border: 1px solid #f87171; border-radius: 8px; }}

QLabel#h1 {{ font-size: 19pt; font-weight: 700; }}
QLabel#h2 {{ font-size: 12.5pt; font-weight: 650; }}
QLabel#muted, QLabel[muted="true"] {{ color: {p['muted']}; }}
QLabel#statvalue {{ font-size: 21pt; font-weight: 700; }}
QLabel#help {{ color: {p['muted']}; font-size: 9pt; }}

QPushButton {{ background: {p['card']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {p['accent']}; }}
QPushButton:disabled {{ color: {p['muted']}; background: {p['bg']}; }}
QPushButton[kind="primary"] {{ background: {p['accent']}; color: {p['accent_text']}; border: 1px solid {p['accent']}; font-weight: 600; }}
QPushButton[kind="primary"]:hover {{ background: {p['accent']}; border-color: {p['text']}; }}
QPushButton[kind="danger"] {{ color: #dc2626; }}
QPushButton[kind="link"] {{ border: none; background: transparent; color: {p['accent']}; padding: 2px 4px; text-align: left; }}

QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {p['input']}; border: 1px solid {p['border']}; border-radius: 7px; padding: 5px 8px;
    selection-background-color: {p['accent']}; selection-color: white; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {p['accent']}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({a['chevron']}); width: 12px; height: 12px; }}
QCheckBox::indicator, QGroupBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {p['muted']}; background: {p['input']}; }}
QCheckBox::indicator:checked, QGroupBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; image: url({a['check']}); }}
QCheckBox::indicator:disabled {{ border-color: {p['border']}; }}
QComboBox QAbstractItemView {{ background: {p['card']}; border: 1px solid {p['border']}; selection-background-color: {p['selection']}; selection-color: {p['text']}; }}
QCheckBox {{ spacing: 8px; }}
QProgressBar {{ border: 1px solid {p['border']}; border-radius: 6px; text-align: center; background: {p['input']}; height: 14px; }}
QProgressBar::chunk {{ background: {p['accent']}; border-radius: 5px; }}

QTableView, QTreeView, QListWidget, QListView {{ background: {p['card']}; alternate-background-color: {p['row_alt']};
    border: 1px solid {p['border']}; border-radius: 10px; gridline-color: transparent; selection-background-color: {p['selection']};
    selection-color: {p['text']}; outline: 0; }}
QTableView::item, QListWidget::item {{ padding: 4px 6px; }}
QHeaderView {{ qproperty-defaultAlignment: AlignLeft; }}
QHeaderView::section {{ background: {p['card']}; color: {p['muted']}; border: none; border-bottom: 1px solid {p['border']};
    padding: 8px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {p['card']}; border: none; }}

QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 10px; background: {p['card']}; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 8px 16px; margin-right: 2px; border-top-left-radius: 8px; border-top-right-radius: 8px; color: {p['muted']}; }}
QTabBar::tab:selected {{ background: {p['card']}; color: {p['text']}; border: 1px solid {p['border']}; border-bottom: 1px solid {p['card']}; font-weight: 600; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p['muted']}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['border']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QSplitter::handle {{ background: transparent; }}
QMenu {{ background: {p['card']}; border: 1px solid {p['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background: {p['selection']}; }}
QTextBrowser {{ background: {p['card']}; border: 1px solid {p['border']}; border-radius: 10px; padding: 8px; }}

QFrame#sidebar {{ background: {p['sidebar']}; }}
QFrame#sidebar QLabel {{ color: {p['sidebar_text']}; }}
QFrame#sidebar QLabel#brand {{ color: white; font-size: 14pt; font-weight: 700; }}
QPushButton#nav {{ background: transparent; color: {p['sidebar_text']}; border: none; border-radius: 8px; padding: 10px 14px; text-align: left; font-size: 10.5pt; }}
QPushButton#nav:hover {{ background: {p['sidebar_hover']}; color: white; }}
QPushButton#nav:checked {{ background: {p['sidebar_active']}; color: white; font-weight: 600; }}
QFrame#sidebar QPushButton[kind="side"] {{ background: {p['sidebar_hover']}; color: white; border: 1px solid #334155; padding: 6px 10px; }}
QFrame#sidebar QPushButton[kind="side"]:hover {{ border-color: {p['sidebar_active']}; }}
"""


def html_css(name: str) -> str:
    p = PALETTES[name]
    return (f"body {{ color:{p['text']}; }} h2 {{ margin-top:0; }} h3 {{ margin-bottom:2px; }} a {{ color:{p['accent']}; }} "
            f"code {{ background:{p['code_bg']}; padding:1px 4px; }} "
            f"table {{ border-collapse: collapse; }} th {{ text-align:left; background:{p['code_bg']}; padding:5px 10px; }} "
            f"td {{ padding:5px 10px; border-bottom:1px solid {p['border']}; }} li {{ margin-bottom:4px; }}")


# --------------------------------------------------------------------------- icon
def draw_logo(size: int, dot: str | None = None) -> QPixmap:
    """The NetBeacon logo: a signal beacon. If `dot` is a colour, a status dot is added (for the tray)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    grad = QLinearGradient(0, 0, s, s)
    grad.setColorAt(0, QColor("#3b82f6"))
    grad.setColorAt(1, QColor("#1d4ed8"))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92), s * 0.22, s * 0.22)
    pen = QPen(QColor("white"))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setWidthF(s * 0.075)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = s * 0.5, s * 0.62
    for i, r in enumerate((0.17, 0.30, 0.43)):
        rect = QRectF(cx - s * r, cy - s * r, s * r * 2, s * r * 2)
        p.setOpacity(1.0 - i * 0.22)
        p.drawArc(rect, 35 * 16, 110 * 16)
    p.setOpacity(1.0)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("white"))
    p.drawEllipse(QPointF(cx, cy), s * 0.075, s * 0.075)
    if dot:
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(s * 0.78, s * 0.78), s * 0.2, s * 0.2)
        p.setBrush(QColor(dot))
        p.drawEllipse(QPointF(s * 0.78, s * 0.78), s * 0.155, s * 0.155)
    p.end()
    return pm


def app_icon(dot: str | None = None) -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(draw_logo(size, dot))
    return icon


def apply_palette(app, name: str) -> None:
    """Fusion + matching QPalette so native bits (check marks, spin arrows) look right in both themes."""
    from PySide6.QtGui import QPalette

    p = PALETTES[name]
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(p["bg"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(p["text"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(p["input"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(p["row_alt"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(p["text"]))
    pal.setColor(QPalette.ColorRole.Button, QColor(p["card"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(p["text"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(p["accent"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(p["card"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(p["text"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(p["muted"]))
    app.setPalette(pal)
