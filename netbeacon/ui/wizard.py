"""First-run Quick Start wizard."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from .. import netutil, wifi
from ..checks import CHECKS
from ..store import MonitorDef
from .widgets import HelpText, Task, label, make_button


class Suggestion:
    def __init__(self, key: str, title: str, why: str, kind: str, params: dict, group: str, tolerance: int = 1, depends_on_router: bool = False,
                 checked: bool = True) -> None:
        self.key, self.title, self.why, self.kind, self.params = key, title, why, kind, params
        self.group, self.tolerance, self.depends_on_router, self.checked = group, tolerance, depends_on_router, checked
        self.box: QCheckBox | None = None


def _clear_layout(lay) -> None:
    """Remove everything from a layout, including widgets inside nested layouts."""
    while lay.count():
        it = lay.takeAt(0)
        if it.widget() is not None:
            it.widget().deleteLater()
        elif it.layout() is not None:
            _clear_layout(it.layout())
            it.layout().deleteLater()


def suggestions_for_devices(found, have: set[str] | None = None, limit: int = 10) -> list[Suggestion]:
    """Turn a deep scan into check suggestions for the devices a small business cares about."""
    have = have or set()
    out: list[Suggestion] = []
    for d in found:
        if d.is_self or d.is_gateway:
            continue
        name = d.hostname.split(".")[0] if d.hostname else d.ip
        p = set(d.open_ports)
        if p & {9100, 515, 631}:
            out.append(Suggestion(f"dev-{d.ip}-print", f"Printer {name}", "Looks like a printer. A ping check tells you when it drops off the network.",
                                  "ping", {"host": d.ip}, "Office", tolerance=2, depends_on_router=True))
        elif p & {5000, 5001}:
            out.append(Suggestion(f"dev-{d.ip}-nas", f"Storage {name} (web page)", "Looks like a NAS / storage box. Checking its web port catches a hung box, not just a powered-off one.",
                                  "tcp", {"host": d.ip, "port": 5000 if 5000 in p else 5001}, "Servers", tolerance=1, depends_on_router=True))
        elif 445 in p and not d.randomized:
            out.append(Suggestion(f"dev-{d.ip}-smb", f"File sharing on {name}", "This device shares files (port 445). Checking the port catches a stopped file service.",
                                  "tcp", {"host": d.ip, "port": 445}, "Servers", tolerance=1, depends_on_router=True, checked=False))
        elif 3389 in p:
            out.append(Suggestion(f"dev-{d.ip}-rdp", f"Remote Desktop on {name}", "This machine accepts Remote Desktop. Watch it if people work on it remotely.",
                                  "tcp", {"host": d.ip, "port": 3389}, "Servers", tolerance=1, depends_on_router=True, checked=False))
        elif 554 in p:
            out.append(Suggestion(f"dev-{d.ip}-cam", f"Camera {name}", "Looks like a camera or video recorder. A ping check tells you when it goes offline.",
                                  "ping", {"host": d.ip}, "Office", tolerance=2, depends_on_router=True, checked=False))
    return [s for s in out if s.key not in have][:limit]


class SetupWizard(QDialog):
    def __init__(self, ctx, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Quick Start")
        self.resize(780, 680)
        self.suggestions: list[Suggestion] = []
        self._task: Task | None = None
        self._scan_task: Task | None = None
        self.wifi_status: wifi.WifiStatus | None = None
        self.gateway: str | None = None
        self.scan_note = ""
        lay = QVBoxLayout(self)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.stack.addWidget(self._page_welcome())
        self.page2 = QWidget()
        self.page2_scroll = QScrollArea()
        self.page2_scroll.setWidgetResizable(True)
        self.page2_scroll.setWidget(self.page2)
        self.stack.addWidget(self.page2_scroll)
        self.stack.addWidget(self._page_extras())
        self.stack.addWidget(self._page_alerts())
        nav = QHBoxLayout()
        self.back = make_button("Back")
        self.next = make_button("Next", "primary")
        self.skip = make_button("Skip the wizard", "link")
        nav.addWidget(self.skip)
        nav.addStretch(1)
        nav.addWidget(self.back)
        nav.addWidget(self.next)
        lay.addLayout(nav)
        self.back.clicked.connect(self._back)
        self.next.clicked.connect(self._next)
        self.skip.clicked.connect(self._skip)
        self._update_nav()

    # ------------------------------------------------------------ pages
    def _page_welcome(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(12)
        l.addWidget(label("Welcome to NetBeacon", "h1"))
        l.addWidget(label("NetBeacon keeps an eye on your network so you find out about problems <b>before your staff or customers do</b>.", wrap=True, rich=True))
        for head, text in (
            ("Checks", "small questions asked over and over: <i>does the router answer? is the website up? is the disk nearly full?</i>"),
            ("Alerts", "a pop-up (or email, or phone message) when a check fails - and again when it recovers."),
            ("History", "every result is remembered, so you can see uptime and outages and show your provider the evidence."),
            ("Learning", "every screen explains itself. The <b>Learn</b> section has short lessons, and you can switch the hints off any time."),
        ):
            f = QFrame()
            f.setObjectName("card")
            fl = QVBoxLayout(f)
            fl.setContentsMargins(14, 10, 14, 10)
            fl.addWidget(label(f"<b>{head}</b>", rich=True))
            fl.addWidget(label(text, "muted", wrap=True, rich=True))
            l.addWidget(f)
        l.addWidget(HelpText("Under the hood NetBeacon uses <b>SimpleMonitor</b>, a small open-source monitoring engine. NetBeacon writes SimpleMonitor's configuration files for you - "
                             "and shows them to you - so nothing is a black box.", always=True))
        l.addStretch(1)
        return w

    def _page_extras(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(10)
        l.addWidget(label("A few extras", "h1"))
        l.addWidget(label("These run in the background and need nothing from you. Untick anything you don't want.", "muted", wrap=True))

        def card(box: QCheckBox, text: str, extra: QWidget | None = None) -> QFrame:
            f = QFrame()
            f.setObjectName("card")
            fl = QVBoxLayout(f)
            fl.setContentsMargins(12, 8, 12, 8)
            fl.setSpacing(3)
            fl.addWidget(box)
            fl.addWidget(label(text, "muted", wrap=True, rich=True))
            if extra is not None:
                fl.addWidget(extra)
            l.addWidget(f)
            return f

        self.cb_watch = QCheckBox("Tell me when an unknown device joins the network")
        self.cb_watch.setChecked(True)
        card(self.cb_watch, "NetBeacon scans once now to learn the devices you already have, then rescans every hour and tells you about newcomers "
                            "(by pop-up, and by email/phone if you add those channels later).")
        self.cb_speed = QCheckBox("Test my internet speed every 6 hours")
        self.cb_speed.setChecked(True)
        paid = QWidget()
        pl = QHBoxLayout(paid)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(QLabel("My plan's download speed (optional):"))
        self.paid = QDoubleSpinBox()
        self.paid.setRange(0, 100000)
        self.paid.setDecimals(0)
        self.paid.setSuffix(" Mbit/s")
        self.paid.setSpecialValueText("don't know")
        pl.addWidget(self.paid)
        pl.addStretch(1)
        card(self.cb_speed, "Builds a history that shows whether you get what you pay for. Uses up to 35 MB per test (about 4 GB a month) - "
                            "untick this on a metered or mobile connection.", paid)
        self.cb_wifi = QCheckBox("Watch this PC's Wi-Fi signal")
        self.cb_wifi.setChecked(True)
        self.wifi_card = card(self.cb_wifi, "Adds a check that warns when the signal gets weak, and records it for the Wi-Fi page.")
        self.wifi_card.setVisible(False)
        self.cb_digest = QCheckBox("Prepare a plain-English summary every Monday at 9:00")
        self.cb_digest.setChecked(True)
        card(self.cb_digest, "A short 'how was the week' with outages, slow trends (like a disk filling up), speed and Wi-Fi. "
                             "You can have it emailed too, once email is set up on the Alerts page.")
        l.addStretch(1)
        return w

    def _page_alerts(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(12)
        l.addWidget(label("How should we tell you?", "h1"))
        self.cb_desktop = QCheckBox("Show a pop-up on this PC when something goes down or recovers")
        self.cb_desktop.setChecked(True)
        l.addWidget(self.cb_desktop)
        l.addWidget(HelpText("A pop-up works even when the internet is down. Later, on the <b>Alerts</b> page, you can add email, Slack, Telegram or phone push messages.", always=True))
        self.cb_tray = QCheckBox("Keep NetBeacon running in the system tray when I close the window")
        self.cb_tray.setChecked(True)
        l.addWidget(self.cb_tray)
        self.cb_start = QCheckBox("Start NetBeacon when I sign in to Windows")
        self.cb_start.setChecked(sys.platform == "win32")
        self.cb_start.setEnabled(sys.platform == "win32")
        l.addWidget(self.cb_start)
        l.addWidget(HelpText("Monitoring only works while NetBeacon is running - these two options make sure it always is.", always=True))
        self.cb_teach = QCheckBox("Teaching mode: show explanations on each page (you can turn this off in Settings)")
        self.cb_teach.setChecked(True)
        l.addWidget(self.cb_teach)
        l.addStretch(1)
        return w

    def _build_page2(self) -> None:
        site_text = self.site.text() if hasattr(self, "site") else ""
        lay = self.page2.layout()
        if lay is None:
            lay = QVBoxLayout(self.page2)
        _clear_layout(lay)
        lay.setSpacing(8)
        lay.addWidget(label("What shall we watch?", "h1"))
        lay.addWidget(label("We looked around your network and suggest these checks. Untick anything you don't want - you can add or change checks any time.", "muted", wrap=True))
        for s in self.suggestions:
            f = QFrame()
            f.setObjectName("card")
            fl = QVBoxLayout(f)
            fl.setContentsMargins(12, 8, 12, 8)
            fl.setSpacing(2)
            s.box = QCheckBox(s.title)
            s.box.setChecked(s.checked)
            fl.addWidget(s.box)
            fl.addWidget(label(s.why, "muted", wrap=True))
            lay.addWidget(f)
        scan_row = QHBoxLayout()
        self.scan_btn = make_button("Also look for printers, servers and storage...")
        self.scan_btn.setToolTip("A quick scan of your network (about 20-40 seconds) to suggest checks for the devices that matter.")
        self.scan_btn.clicked.connect(self._scan_devices)
        scan_row.addWidget(self.scan_btn)
        self.scan_label = label(self.scan_note, "muted", wrap=True)
        scan_row.addWidget(self.scan_label, 1)
        lay.addLayout(scan_row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Your website (optional):"))
        self.site = QLineEdit(site_text)
        self.site.setPlaceholderText("https://www.yourcompany.com")
        row.addWidget(self.site, 1)
        lay.addLayout(row)
        lay.addStretch(1)

    # ------------------------------------------------------------ detection
    def _detect(self) -> None:
        self.page2.setLayout(QVBoxLayout()) if self.page2.layout() is None else None
        lay = self.page2.layout()
        lay.addWidget(label("Looking around your network...", "h1"))
        self.next.setEnabled(False)

        def work(_t: Task):
            gw = netutil.default_gateway()
            nets = netutil.local_networks()
            return gw, nets[0].label() if nets else "", wifi.read_status()

        self._task = Task(work, self)
        self._task.result.connect(self._detected)
        self._task.failed.connect(lambda _m: self._detected((None, "", None)))
        self._task.start()

    def _detected(self, res) -> None:
        gw, net, wst = res
        self.gateway = gw
        if gw:
            self.ctx.store.set("last_gateway", gw)
        self.wifi_status = wst
        on_wifi = bool(wst and wst.available and wst.connected)
        self.wifi_card.setVisible(on_wifi)
        if on_wifi:
            self.cb_wifi.setText(f"Watch this PC's Wi-Fi signal (now {wst.signal}% on '{wst.ssid}')")
        self.suggestions = []
        if gw:
            self.suggestions.append(Suggestion("router", f"Router / gateway ({gw})", "Is your local network and router alive? Everything else depends on this one.",
                                               "ping", {"host": gw}, "Internet", tolerance=1))
        self.suggestions.append(Suggestion("internet", "Internet connection (1.1.1.1)", "Can you reach the internet by number? If this fails but the router works, the problem is your provider.",
                                           "ping", {"host": "1.1.1.1"}, "Internet", tolerance=2, depends_on_router=True))
        self.suggestions.append(Suggestion("dns", "DNS lookup (example.com)", "Can names be turned into addresses? When this fails but the internet check works, it's a DNS problem.",
                                           "dns", {"record": "example.com"}, "Internet", tolerance=2, depends_on_router=True))
        disk = "C:\\" if sys.platform == "win32" else "/"
        self.suggestions.append(Suggestion("disk", f"Free disk space on {disk}", "Warns you when this computer's drive is below 10% free.", "disk", {"path": disk, "min_free_percent": 10}, "This PC", tolerance=0))
        self.suggestions.append(Suggestion("mem", "Free memory on this PC", "Warns you when memory runs low. (Tolerance 3: short spikes are ignored.)", "memory", {"percent_free": 10}, "This PC", tolerance=3, checked=False))
        self._build_page2()
        self.next.setEnabled(True)
        self._update_nav()

    # ------------------------------------------------------------ device discovery
    def _remember_ticks(self) -> None:
        for s in self.suggestions:
            if s.box is not None:
                s.checked = s.box.isChecked()

    def _scan_devices(self) -> None:
        if self._scan_task and self._scan_task.isRunning():
            return
        nets = netutil.local_networks()
        if not nets:
            self.scan_label.setText("No network found to scan.")
            return
        cidr = nets[0].cidr
        self.scan_btn.setEnabled(False)
        self.scan_label.setText(f"Scanning {cidr}... (about 20-40 seconds)")

        def work(t: Task):
            return netutil.scan_network(cidr, deep=True, cancel=t.cancel_event)

        self._scan_task = Task(work, self)
        self._scan_task.result.connect(self._devices_found)
        self._scan_task.failed.connect(lambda m: (self.scan_btn.setEnabled(True), self.scan_label.setText(f"Scan failed: {m}")))
        self._scan_task.start()

    def _devices_found(self, found) -> None:
        self.scan_btn.setEnabled(True)
        self._remember_ticks()
        have = {s.key for s in self.suggestions}
        added = suggestions_for_devices(found or [], have)
        self.suggestions.extend(added)
        self.scan_note = (f"Found {len(found or [])} devices; {len(added)} look worth watching (added below)." if added
                          else f"Found {len(found or [])} devices, but none look like printers, servers or storage.")
        self._build_page2()
        self.scan_label.setText(self.scan_note)
        from .. import devices
        if found:
            devices.merge_scan(self.ctx.history, found)
            self.ctx.devices_changed.emit()

    # ------------------------------------------------------------ navigation
    def _update_nav(self) -> None:
        i = self.stack.currentIndex()
        self.back.setVisible(i > 0)
        self.next.setText("Finish" if i == 3 else "Next")

    def _back(self) -> None:
        self.stack.setCurrentIndex(max(0, self.stack.currentIndex() - 1))
        self._update_nav()

    def _next(self) -> None:
        i = self.stack.currentIndex()
        if i == 0:
            self.stack.setCurrentIndex(1)
            if not self.suggestions:
                self._detect()
        elif i in (1, 2):
            self.stack.setCurrentIndex(i + 1)
        else:
            self._finish()
            return
        self._update_nav()

    def _skip(self) -> None:
        self.ctx.store.set("first_run_done", True)
        self.reject()

    def done(self, r: int) -> None:
        for t in (self._task, self._scan_task):
            if t is not None and t.isRunning():
                t.cancel()
                t.wait(5000)
        super().done(r)

    def _finish(self) -> None:
        s = self.ctx.store
        router_id = None
        created = []
        for sug in self.suggestions:
            if sug.box is None or not sug.box.isChecked():
                continue
            m = MonitorDef.new(sug.kind, sug.title.split(" (")[0] if sug.key in ("router",) else sug.title, {**CHECKS[sug.kind].defaults(), **sug.params})
            m.group, m.tolerance = sug.group, sug.tolerance
            if sug.key == "router":
                m.name = "Router"
            if sug.key == "internet":
                m.name = "Internet connection"
            if sug.key == "dns":
                m.name = "DNS lookup"
            if sug.key.startswith("dev-"):
                m.name = sug.title
            if sug.depends_on_router and router_id:
                m.depends = [router_id]
            s.add(m)
            if sug.key == "router":
                router_id = m.id
            created.append(m)
        site = self.site.text().strip() if hasattr(self, "site") else ""
        if site.lower().startswith(("http://", "https://")):
            w = MonitorDef.new("http", "Company website", {**CHECKS["http"].defaults(), "url": site})
            w.group, w.tolerance = "Websites", 2
            if router_id:
                w.depends = [router_id]
            s.add(w)
            if site.lower().startswith("https://"):
                host = site.split("//", 1)[1].split("/", 1)[0].split(":")[0]
                t = MonitorDef.new("tls", f"Certificate {host}", {**CHECKS["tls"].defaults(), "host": host})
                t.group = "Websites"
                s.add(t)
        if self.cb_wifi.isChecked() and not self.wifi_card.isHidden() and self.wifi_status and self.wifi_status.connected:
            wf = MonitorDef.new("wifi", "Wi-Fi signal", {**CHECKS["wifi"].defaults(), "min_signal": 40, "ssid": self.wifi_status.ssid})
            wf.group, wf.tolerance = "This PC", 2
            s.add(wf)
        s.settings["speed_enabled"] = self.cb_speed.isChecked()
        if self.paid.value():
            s.settings["speed_paid_down"] = self.paid.value()
        s.settings["digest_enabled"] = self.cb_digest.isChecked()
        s.settings["digest_weekday"], s.settings["digest_hour"] = 0, 9
        s.settings["scan_watch_enabled"] = self.cb_watch.isChecked()
        s.settings["channels"]["desktop"]["enabled"] = self.cb_desktop.isChecked()
        s.settings["minimize_to_tray"] = self.cb_tray.isChecked()
        s.settings["teaching_mode"] = self.cb_teach.isChecked()
        s.settings["start_with_windows"] = self.cb_start.isChecked()
        s.settings["first_run_done"] = True
        s.save()
        from . import system
        if system.autostart_supported():
            system.set_autostart(self.cb_start.isChecked())
        self.ctx.apply_changes()
        self.ctx.settings_changed.emit()
        if self.cb_watch.isChecked() and self.ctx.main_window is not None and not s.get("devices_baseline_done"):
            self.ctx.main_window.baseline_scan()
        self.accept()
