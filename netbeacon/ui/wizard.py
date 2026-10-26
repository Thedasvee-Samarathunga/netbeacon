"""First-run Quick Start wizard."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QStackedWidget, QVBoxLayout,
                               QWidget)

from .. import netutil
from ..checks import CHECKS
from ..store import MonitorDef
from .widgets import HelpText, Task, label, make_button


class Suggestion:
    def __init__(self, key: str, title: str, why: str, kind: str, params: dict, group: str, tolerance: int = 1, depends_on_router: bool = False,
                 checked: bool = True) -> None:
        self.key, self.title, self.why, self.kind, self.params = key, title, why, kind, params
        self.group, self.tolerance, self.depends_on_router, self.checked = group, tolerance, depends_on_router, checked
        self.box: QCheckBox | None = None


class SetupWizard(QDialog):
    def __init__(self, ctx, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Quick Start")
        self.resize(760, 620)
        self.suggestions: list[Suggestion] = []
        self._task: Task | None = None
        lay = QVBoxLayout(self)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.stack.addWidget(self._page_welcome())
        self.page2 = QWidget()
        self.stack.addWidget(self.page2)
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
        lay = self.page2.layout()
        if lay is None:
            lay = QVBoxLayout(self.page2)
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
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
        row = QHBoxLayout()
        row.addWidget(QLabel("Your website (optional):"))
        self.site = QLineEdit()
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
            return gw, nets[0].label() if nets else ""

        self._task = Task(work, self)
        self._task.result.connect(self._detected)
        self._task.failed.connect(lambda _m: self._detected((None, "")))
        self._task.start()

    def _detected(self, res) -> None:
        gw, net = res
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

    # ------------------------------------------------------------ navigation
    def _update_nav(self) -> None:
        i = self.stack.currentIndex()
        self.back.setVisible(i > 0)
        self.next.setText("Finish" if i == 2 else "Next")

    def _back(self) -> None:
        self.stack.setCurrentIndex(max(0, self.stack.currentIndex() - 1))
        self._update_nav()

    def _next(self) -> None:
        i = self.stack.currentIndex()
        if i == 0:
            self.stack.setCurrentIndex(1)
            if not self.suggestions:
                self._detect()
        elif i == 1:
            self.stack.setCurrentIndex(2)
        else:
            self._finish()
            return
        self._update_nav()

    def _skip(self) -> None:
        self.ctx.store.set("first_run_done", True)
        self.reject()

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
        self.accept()
