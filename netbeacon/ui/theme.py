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
    # ---- extra themes (1.2)
    "paper": dict(bg="#f6f1e7", card="#fffdf8", text="#3b3326", muted="#857a66", border="#e6dccb", accent="#b45309",
                  accent_text="#ffffff", sidebar="#3b3326", sidebar_text="#e9dfcc", sidebar_hover="#4d4333",
                  sidebar_active="#b45309", input="#fffdf8", banner="#fbefd9", banner_border="#f0d3a1", banner_text="#7c3d07",
                  row_alt="#faf6ee", selection="#f6e3c3", code_bg="#f3ecdf", danger_bg="#fdf0ec"),
    "mint": dict(bg="#eef6f3", card="#ffffff", text="#1b2e2a", muted="#5f7671", border="#d5e6e0", accent="#0d9488",
                 accent_text="#ffffff", sidebar="#123430", sidebar_text="#c5e0da", sidebar_hover="#1b4741",
                 sidebar_active="#0d9488", input="#ffffff", banner="#dff3ee", banner_border="#a7dccf", banner_text="#0b4f48",
                 row_alt="#f5faf8", selection="#cdeee6", code_bg="#e9f3f0", danger_bg="#fdf0f0"),
    "arctic": dict(bg="#2e3440", card="#3b4252", text="#eceff4", muted="#a3adbf", border="#4c566a", accent="#88c0d0",
                   accent_text="#2e3440", sidebar="#242933", sidebar_text="#d8dee9", sidebar_hover="#3b4252",
                   sidebar_active="#5e81ac", input="#2e3440", banner="#344155", banner_border="#4f6a8a", banner_text="#d8e6f3",
                   row_alt="#363d4b", selection="#4b5d78", code_bg="#2e3440", danger_bg="#4a3238"),
    "dusk": dict(bg="#1d1b2b", card="#27243a", text="#ece8f7", muted="#a49dbd", border="#3a3554", accent="#a78bfa",
                 accent_text="#1d1b2b", sidebar="#15131f", sidebar_text="#c9c1e3", sidebar_hover="#2a2640",
                 sidebar_active="#7c3aed", input="#1f1c2e", banner="#2e2550", banner_border="#51408f", banner_text="#ddd2ff",
                 row_alt="#232034", selection="#40336e", code_bg="#1f1c2e", danger_bg="#43202c"),
    "forest": dict(bg="#121a16", card="#1a2620", text="#e3eee7", muted="#93ab9c", border="#2b3c33", accent="#4ade80",
                   accent_text="#0f1a14", sidebar="#0c120f", sidebar_text="#b4cbbd", sidebar_hover="#1b2a22",
                   sidebar_active="#16a34a", input="#141e19", banner="#183323", banner_border="#2c6142", banner_text="#c4f0d4",
                   row_alt="#16211b", selection="#25503a", code_bg="#141e19", danger_bg="#3a1a1c"),
    "contrast": dict(bg="#000000", card="#0a0a0a", text="#ffffff", muted="#d4d4d4", border="#ffffff", accent="#ffd400",
                     accent_text="#000000", sidebar="#000000", sidebar_text="#ffffff", sidebar_hover="#262626",
                     sidebar_active="#1d4ed8", input="#000000", banner="#0a0a0a", banner_border="#ffd400", banner_text="#ffffff",
                     row_alt="#141414", selection="#1d4ed8", code_bg="#1a1a1a", danger_bg="#3a0000"),
}

# (key, label, is_dark) in the order shown in Settings. "system" follows Windows' light/dark setting.
THEMES = [("system", "Match Windows (light or dark)", None), ("light", "Light", False), ("dark", "Dark", True),
          ("paper", "Paper (warm light)", False), ("mint", "Mint (fresh light)", False), ("arctic", "Arctic (cool dark)", True),
          ("dusk", "Dusk (purple dark)", True), ("forest", "Forest (green dark)", True), ("contrast", "High contrast", True)]
DARK = {k for k, _l, d in THEMES if d}

# Accent colours that can be laid over any theme ("" = the theme's own accent)
ACCENTS = [("", "Theme default"), ("#2563eb", "Blue"), ("#0d9488", "Teal"), ("#16a34a", "Green"), ("#7c3aed", "Purple"),
           ("#db2777", "Pink"), ("#dc2626", "Red"), ("#ea580c", "Orange"), ("#ca8a04", "Gold")]

_current = "light"
_choice = "light"            # what the user picked (may be "system")
_accent = ""


def system_is_dark() -> bool:
    """Windows' 'Choose your app mode' setting (Qt 6.5+ reads it for us)."""
    try:
        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication.instance()
        if app is not None:
            return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:  # noqa: BLE001
        pass
    return False


def resolve(name: str) -> str:
    if name == "system":
        return "dark" if system_is_dark() else "light"
    return name if name in PALETTES else "light"


def _mix(a: str, b: str, t: float) -> str:
    ca, cb = QColor(a), QColor(b)
    return QColor(int(ca.red() + (cb.red() - ca.red()) * t), int(ca.green() + (cb.green() - ca.green()) * t),
                  int(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def palette(name: str | None = None) -> dict:
    p = dict(PALETTES[resolve(name or _current)])
    if _accent:
        dark = resolve(name or _current) in DARK
        acc = QColor(_accent)
        p["accent"] = acc.lighter(130).name() if dark else _accent
        p["sidebar_active"] = _accent
        p["accent_text"] = "#000000" if QColor(p["accent"]).lightnessF() > 0.62 else "#ffffff"
        p["selection"] = _mix(p["card"], _accent, 0.35 if dark else 0.18)
        p["banner"] = _mix(p["bg"], _accent, 0.18 if dark else 0.08)
        p["banner_border"] = _mix(p["bg"], _accent, 0.45 if dark else 0.3)
        p["banner_text"] = _mix(p["text"], _accent, 0.35)
    return p


def is_dark(name: str | None = None) -> bool:
    return resolve(name or _current) in DARK


def set_current(name: str, accent: str | None = None) -> str:
    """Remember the user's choice; returns the concrete palette name actually used."""
    global _current, _choice, _accent
    _choice = name if (name in PALETTES or name == "system") else "light"
    _current = resolve(_choice)
    if accent is not None:
        _accent = accent if (not accent or QColor(accent).isValid()) else ""
    return _current


def choice() -> str:
    return _choice


def ensure_assets(name: str) -> dict:
    """Draw the tiny check-mark and chevron icons the stylesheet needs (no image files to ship)."""
    from PySide6.QtGui import QPainterPath

    from .. import paths

    folder = paths.data_dir() / "ui-assets"
    folder.mkdir(parents=True, exist_ok=True)
    files = {"check": folder / "check.png", "chevron": folder / f"chevron-{name}-{palette(name)['muted'].lstrip('#')}.png"}
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
        pen = QPen(QColor(palette(name)["muted"]), 3.4)
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
    p = palette(name)
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
QPushButton#nav {{ background: transparent; color: {p['sidebar_text']}; border: none; border-radius: 8px; padding: 8px 14px; text-align: left; font-size: 10.5pt; }}
QScrollArea#navscroll, QWidget#navhost {{ background: transparent; border: none; }}
QFrame#sidebar QScrollBar:vertical {{ width: 6px; }}
QPushButton#nav:hover {{ background: {p['sidebar_hover']}; color: white; }}
QPushButton#nav:checked {{ background: {p['sidebar_active']}; color: white; font-weight: 600; }}
QFrame#sidebar QPushButton[kind="side"] {{ background: {p['sidebar_hover']}; color: white; border: 1px solid {p['sidebar_hover']}; padding: 6px 10px; }}
QFrame#sidebar QPushButton[kind="side"]:hover {{ border-color: {p['sidebar_active']}; }}
"""


def html_css(name: str) -> str:
    p = palette(name)
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

    p = palette(name)
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
