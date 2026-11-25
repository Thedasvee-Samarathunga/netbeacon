"""The application window: sidebar, pages, tray icon, toasts."""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton, QScrollArea,
                               QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from .. import devices, netutil, notify
from ..engine import LoopInfo
from . import theme
from .context import AppContext
from .monitor_dialog import MonitorDialog
from .pages.activity import ActivityPage
from .pages.alerts import AlertsPage
from .pages.checks_page import ChecksPage
from .pages.dashboard import DashboardPage
from .pages.devices import DevicesPage
from .pages.digest_page import DigestPage
from .pages.learn import LearnPage
from .pages.netmap import MapPage
from .pages.ports import PortsPage
from .pages.services import ServicesPage
from .pages.settings_page import SettingsPage
from .pages.speed import SpeedPage
from .pages.uptime import UptimePage
from .pages.wifi_page import WifiPage
from .widgets import Task, hub, make_button

NAV = [("dashboard", "Dashboard"), ("checks", "Checks"),
       ("devices", "Devices"), ("map", "Network map"), ("ports", "Port scanner"), ("services", "Services & programs"),
       ("wifi", "Wi-Fi"), ("speed", "Internet speed"),
       ("uptime", "Uptime & history"), ("digest", "Weekly summary"), ("alerts", "Alerts"),
       ("activity", "Activity & logs"), ("learn", "Learn"), ("settings", "Settings")]
NAV_GAP_AFTER = ("checks", "services", "speed", "alerts")


class Toast(QLabel):
    COLORS = {"ok": "#16a34a", "error": "#dc2626", "info": "#2563eb", "warn": "#f59e0b"}

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setMaximumWidth(420)
        self.hide()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def show_message(self, text: str, level: str = "info", ms: int = 4500) -> None:
        pal = theme.palette()
        c = self.COLORS.get(level, "#2563eb")
        self.setStyleSheet(f"background:{pal['card']}; color:{pal['text']}; border:1px solid {pal['border']}; border-left:5px solid {c}; border-radius:8px; padding:12px 16px;")
        self.setText(text)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self.timer.start(ms)

    def reposition(self) -> None:
        p = self.parentWidget()
        if p:
            self.move(p.width() - self.width() - 24, p.height() - self.height() - 24)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext, start_minimized: bool = False) -> None:
        super().__init__()
        self.ctx = ctx
        ctx.main_window = self
        self._quitting = False
        self._info: Optional[LoopInfo] = None
        self._tray_hint_shown = False
        self._watch_task: Optional[Task] = None
        self.setWindowTitle("NetBeacon")
        self.setWindowIcon(theme.app_icon())
        self.resize(1360, 860)
        self.setMinimumSize(1080, 680)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- sidebar
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(218)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 18, 14, 14)
        sl.setSpacing(3)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(theme.draw_logo(34))
        name = QLabel("NetBeacon")
        name.setObjectName("brand")
        brand.addWidget(logo)
        brand.addWidget(name)
        brand.addStretch(1)
        sl.addLayout(brand)
        sl.addSpacing(10)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        nav_scroll = QScrollArea()                  # 14 pages: scrolls instead of squashing on small screens
        nav_scroll.setObjectName("navscroll")
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setFrameShape(QFrame.Shape.NoFrame)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav_host = QWidget()
        nav_host.setObjectName("navhost")
        nl = QVBoxLayout(nav_host)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(2)
        for key, text in NAV:
            b = QPushButton(text.replace("&", "&&"))
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav_group.addButton(b)
            self.nav_buttons[key] = b
            nl.addWidget(b)
            if key in NAV_GAP_AFTER:
                nl.addSpacing(7)
        nl.addStretch(1)
        nav_scroll.setWidget(nav_host)
        sl.addWidget(nav_scroll, 1)
        self.diag_btn = make_button("What's wrong?", "side", "Check the connection step by step and find where it breaks.")
        sl.addWidget(self.diag_btn)
        self.engine_label = QLabel("Starting...")
        self.engine_label.setWordWrap(True)
        sl.addWidget(self.engine_label)
        row = QHBoxLayout()
        self.now_btn = make_button("Check now", "side")
        self.pause_btn = make_button("Pause", "side")
        row.addWidget(self.now_btn)
        row.addWidget(self.pause_btn)
        sl.addLayout(row)
        root.addWidget(side)

        # ---- pages
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.pages = {
            "dashboard": DashboardPage(ctx), "checks": ChecksPage(ctx), "devices": DevicesPage(ctx), "ports": PortsPage(ctx),
            "services": ServicesPage(ctx), "uptime": UptimePage(ctx), "alerts": AlertsPage(ctx), "activity": ActivityPage(ctx),
            "learn": LearnPage(ctx), "settings": SettingsPage(ctx),
            "wifi": WifiPage(ctx), "speed": SpeedPage(ctx), "digest": DigestPage(ctx),
        }
        self.pages["map"] = MapPage(ctx)            # last: it reads the devices and dashboard pages
        for key, _ in NAV:
            self.stack.addWidget(self.pages[key])

        self.toast = Toast(central)
        self.now_btn.clicked.connect(ctx.core.check_now)
        self.diag_btn.clicked.connect(lambda: self.diagnose())
        self.pause_btn.clicked.connect(self._toggle_pause)

        # ---- signals
        ctx.navigate.connect(self.show_page)
        ctx.toast_requested.connect(self.toast.show_message)
        ctx.snapshot_changed.connect(self._on_snapshot)
        ctx.status_changed.connect(self._on_status)
        ctx.notification.connect(self._on_notification)
        ctx.problems_changed.connect(self._on_problems)
        ctx.settings_changed.connect(self._apply_settings)
        ctx.theme_changed.connect(self.apply_theme)

        self._tray = self._make_tray()
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._update_engine_label)
        self._tick.start(1000)
        self._watch_timer = QTimer(self)
        self._watch_timer.timeout.connect(self._watch_scan)
        self._apply_settings()
        self.show_page("dashboard")
        if not start_minimized and not ctx.store.get("start_minimized"):
            self.show()
        elif not self._tray:
            self.show()
        if not ctx.store.get("first_run_done"):
            QTimer.singleShot(400, self.run_wizard)

    # ------------------------------------------------------------------ navigation
    def show_page(self, key: str) -> None:
        if key not in self.pages:
            return
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        self.nav_buttons[key].setChecked(True)
        page.on_show()
        if not self.isVisible():
            self.show()

    def show_uptime_for(self, name: str) -> None:
        self.show_page("uptime")
        self.pages["uptime"].show_check(name)

    def scan_ports_of(self, host: str) -> None:
        self.show_page("ports")
        self.pages["ports"].set_host(host)

    # ------------------------------------------------------------------ dialogs
    def open_check_dialog(self, kind: Optional[str] = None, params: Optional[dict] = None, name: Optional[str] = None, duplicate_of=None) -> None:
        dlg = MonitorDialog(self.ctx, self, kind=kind, params=params, name=name, duplicate_of=duplicate_of)
        dlg.exec()

    def edit_check(self, monitor_id: str) -> None:
        m = self.ctx.store.by_id(monitor_id)
        if m:
            MonitorDialog(self.ctx, self, edit=m).exec()

    def diagnose(self, monitor_id: Optional[str] = None) -> None:
        """Open the 'What's wrong?' window, optionally for one check."""
        from .diagnose_dialog import DiagnoseDialog
        m = self.ctx.store.by_id(monitor_id) if monitor_id else None
        if not self.isVisible():
            self._restore()
        DiagnoseDialog(self.ctx, self, check=m).exec()

    def wake_device(self, mac: str, label_: str = "") -> bool:
        """Send a Wake-on-LAN packet and say what happened."""
        try:
            sent = netutil.wake_on_lan(mac)
        except (ValueError, OSError) as exc:
            self.toast.show_message(f"Could not send the wake-up packet: {exc}", "error")
            return False
        who = label_ or mac
        self.ctx.history.add_event(time.time(), "info", None, f"Wake-on-LAN packet sent to {who} ({mac}) via {', '.join(sent)}")
        self.toast.show_message(f"Wake-up packet sent to {who}. A sleeping PC takes 10-60 seconds to appear. "
                                "Nothing happening? Wake-on-LAN must be switched on in that PC's BIOS and network adapter settings.", "ok", 9000)
        return True

    def baseline_scan(self) -> None:
        """Scan once, remember every device as 'known', and start watching for newcomers (used by the Quick Start wizard)."""
        cidr = self.ctx.store.get("scan_cidr") or (netutil.local_networks()[0].cidr if netutil.local_networks() else "")
        if not cidr:
            return
        self.ctx.store.set("scan_cidr", cidr)

        def work(t: Task):
            return netutil.scan_network(cidr, deep=False, cancel=t.cancel_event)

        task = Task(work, self)

        def done(found) -> None:
            if found:
                devices.merge_scan(self.ctx.history, found)
                gw = next((d.ip for d in found if d.is_gateway), "")
                if gw:
                    self.ctx.store.set("last_gateway", gw)
            self.ctx.history.mark_all_known()
            self.ctx.store.set("devices_baseline_done", True)
            self.ctx.devices_changed.emit()
            self.toast.show_message(f"Learned the {len(found or [])} devices on your network. From now on NetBeacon tells you when a new one appears.", "ok", 8000)

        task.result.connect(done)
        task.start()

    def run_wizard(self) -> None:
        from .wizard import SetupWizard
        SetupWizard(self.ctx, self).exec()
        self.show_page("dashboard")

    # ------------------------------------------------------------------ settings / theme
    def _apply_settings(self) -> None:
        hub.set(bool(self.ctx.store.get("teaching_mode", True)))
        if self.ctx.store.get("scan_watch_enabled"):
            self._watch_timer.start(max(5, int(self.ctx.store.get("scan_watch_minutes", 60))) * 60 * 1000)
        else:
            self._watch_timer.stop()

    def apply_theme(self, name: str) -> None:
        theme.set_current(name)
        app = QApplication.instance()
        theme.apply_palette(app, name)
        app.setStyleSheet(theme.stylesheet(name))
        for p in self.pages.values():
            p.retheme()
        self.pages["dashboard"]._refresh_events()

    # ------------------------------------------------------------------ engine feedback
    def _on_snapshot(self, rows: list[dict]) -> None:
        active = [r for r in rows if r["enabled"]]
        down = sum(1 for r in active if r["status"] in ("down", "error"))
        retry = sum(1 for r in active if r["status"] == "retry")
        self.nav_buttons["dashboard"].setText("Dashboard" + (f"  ({down})" if down else ""))
        if self._tray:
            if self.ctx.core.info.paused:
                col, tip = "#9ca3af", "paused"
            elif down:
                col, tip = "#dc2626", f"{down} problem(s)"
            elif retry:
                col, tip = "#f59e0b", f"{retry} retrying"
            elif active:
                col, tip = "#16a34a", "everything is OK"
            else:
                col, tip = "#64748b", "no checks yet"
            self._tray.setIcon(theme.app_icon(col))
            self._tray.setToolTip(f"NetBeacon - {tip}")
        self.setWindowIcon(theme.app_icon())

    def _on_status(self, info: LoopInfo) -> None:
        self._info = info
        self.pause_btn.setText("Resume" if info.paused else "Pause")
        self._update_engine_label()

    def _update_engine_label(self) -> None:
        info = self._info
        if info is None:
            return
        if info.paused:
            text = "<b style='color:#f59e0b'>\u25CF Paused</b><br>Nothing is being checked."
        elif info.checking:
            text = "<b style='color:#60a5fa'>\u25CF Checking...</b>"
        else:
            nxt = max(0, int(info.next_run_ts - time.time())) if info.next_run_ts else 0
            text = f"<b style='color:#4ade80'>\u25CF Monitoring</b><br>next round in {nxt} s"
            if info.last_duration:
                text += f"<br>last round took {info.last_duration:.1f} s"
        self.engine_label.setText(text)

    def _toggle_pause(self) -> None:
        self.ctx.core.set_paused(not self.ctx.core.info.paused)

    def _on_problems(self, problems: list[str]) -> None:
        self.ctx.problems = problems
        if problems:
            self.toast.show_message(problems[0] + (f"  (+{len(problems) - 1} more - see Activity)" if len(problems) > 1 else ""), "warn", 7000)

    def _on_notification(self, title: str, text: str, level: str) -> None:
        if self._tray and self._tray.isVisible():
            icon = QSystemTrayIcon.MessageIcon.Critical if level == "error" else QSystemTrayIcon.MessageIcon.Information
            self._tray.showMessage(title, text, icon, 10000)
        else:
            self.toast.show_message(f"{title}\n{text}", "error" if level == "error" else "ok", 9000)

    # ------------------------------------------------------------------ device watch
    def _watch_scan(self) -> None:
        if not self.ctx.store.get("devices_baseline_done"):
            return
        if self._watch_task and self._watch_task.isRunning():
            return
        cidr = self.ctx.store.get("scan_cidr") or (netutil.local_networks()[0].cidr if netutil.local_networks() else "")
        if not cidr:
            return

        def work(t: Task):
            return netutil.scan_network(cidr, deep=False, cancel=t.cancel_event)

        self._watch_task = Task(work, self)
        self._watch_task.result.connect(self._watch_done)
        self._watch_task.start()

    def _watch_done(self, found) -> None:
        if not found:
            return
        _rows, fresh = devices.merge_scan(self.ctx.history, found)
        self.ctx.devices_changed.emit()
        if fresh:
            text = ", ".join(f"{d['ip']} ({d['mac'] or 'unknown MAC'}" + (f", {d['kind']}" if d.get("kind") else "") + ")" for d in fresh[:5])
            self.ctx.history.add_event(time.time(), "warn", None, f"New device(s) joined the network: {text}")
            self.ctx.event_added.emit({"ts": time.time(), "level": "warn", "monitor": None, "text": f"New device(s): {text}"})
            self._on_notification("New device on your network", text, "error")
            if self.ctx.store.get("new_device_all_channels", True):
                store = self.ctx.store
                msg = (f"{len(fresh)} unknown device(s) joined your network: {text}. "
                       "If you recognise them, mark them as known on NetBeacon's Devices page.")
                t = Task(lambda _t: notify.broadcast(store, "Unknown device on your network", msg, desktop=False), self)
                t.result.connect(self._broadcast_done)
                t.start()

    def _broadcast_done(self, results: dict) -> None:
        failed = {k: v for k, v in (results or {}).items() if v}
        for ch, err in failed.items():
            self.ctx.history.add_event(time.time(), "warn", None, f"Could not send the new-device alert via {ch}: {err}")

    # ------------------------------------------------------------------ tray
    def _make_tray(self) -> Optional[QSystemTrayIcon]:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(theme.app_icon("#64748b"), self)
        menu = QMenu()
        act_open = QAction("Open NetBeacon", self)
        act_open.triggered.connect(self._restore)
        act_now = QAction("Check everything now", self)
        act_now.triggered.connect(self.ctx.core.check_now)
        act_diag = QAction("What's wrong? (diagnose my connection)", self)
        act_diag.triggered.connect(lambda: self.diagnose())
        act_quit = QAction("Quit NetBeacon", self)
        act_quit.triggered.connect(self.quit_app)
        for a in (act_open, act_now, act_diag):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(act_quit)
        self._tray_menu = menu
        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_clicked)
        tray.setToolTip("NetBeacon")
        tray.show()
        return tray

    def _tray_clicked(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._restore()

    def _restore(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e: QCloseEvent) -> None:
        if not self._quitting and self._tray and self.ctx.store.get("minimize_to_tray", True):
            e.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self._tray.showMessage("NetBeacon is still running", "Monitoring continues in the background. Right-click the tray icon to quit.",
                                       QSystemTrayIcon.MessageIcon.Information, 6000)
            return
        self.quit_app()

    def quit_app(self) -> None:
        self._quitting = True
        try:
            for t in self.findChildren(Task):          # scans etc. still running in the background
                if t.isRunning():
                    t.cancel()
                    t.wait(3000)
            self.ctx.core.stop()
            self.ctx.store.save()
        finally:
            if self._tray:
                self._tray.hide()
            QApplication.instance().quit()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.toast.reposition()
