"""Global settings, exports and backups."""
from __future__ import annotations

import json
import platform
import sys
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from ... import __version__, config_writer, paths
from .. import system
from ..widgets import HelpText, InfoBanner, PageHeader, label, make_button
from .base import Page


def _wrap(w: QWidget, help_text: str = "") -> QWidget:
    c = QWidget()
    cl = QVBoxLayout(c)
    cl.setContentsMargins(0, 0, 0, 0)
    cl.setSpacing(2)
    cl.addWidget(w)
    if help_text:
        cl.addWidget(HelpText(help_text))
    return c


class SettingsPage(Page):
    key = "settings"
    title = "Settings"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        head = PageHeader("Settings", "")
        self.save_btn = head.add_action(make_button("Save settings", "primary"))
        self.root.addWidget(head)
        self.root.addWidget(InfoBanner("settings"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setSpacing(14)
        lay.setContentsMargins(0, 0, 8, 0)

        # --- general
        g = QGroupBox("Monitoring")
        f = QFormLayout(g)
        f.setVerticalSpacing(8)
        self.interval = QSpinBox()
        self.interval.setRange(5, 3600)
        self.interval.setSuffix(" seconds")
        f.addRow("Run all checks every", _wrap(self.interval, "How often a round of checks happens (SimpleMonitor's <code>interval</code>). 30 seconds is a good default; "
                                                               "individual checks can be set to run less often under <i>Advanced</i>."))
        self.retention = QSpinBox()
        self.retention.setRange(1, 730)
        self.retention.setSuffix(" days")
        f.addRow("Keep history for", _wrap(self.retention, "Older results are deleted automatically. 30 days keeps the database small; 90+ is useful for monthly reports."))
        lay.addWidget(g)

        # --- app
        a = QGroupBox("The app")
        af = QFormLayout(a)
        af.setVerticalSpacing(8)
        self.theme = QComboBox()
        self.theme.addItem("Light", "light")
        self.theme.addItem("Dark", "dark")
        af.addRow("Theme", self.theme)
        self.teaching = QCheckBox("Teaching mode: show explanations on every page")
        af.addRow("", _wrap(self.teaching, "Turn this off when you know your way around: the blue boxes and grey help text disappear. Lessons stay available under Learn."))
        self.tray = QCheckBox("Keep running in the system tray when I close the window")
        af.addRow("", _wrap(self.tray, "Monitoring only works while NetBeacon is running, so this is recommended. Quit from the tray icon menu."))
        self.autostart = QCheckBox("Start NetBeacon when I sign in to Windows")
        self.autostart.setEnabled(system.autostart_supported())
        af.addRow("", _wrap(self.autostart, "" if system.autostart_supported() else "Only available on Windows."))
        self.minimized = QCheckBox("Start minimised to the tray")
        af.addRow("", self.minimized)
        lay.addWidget(a)

        # --- watch
        w = QGroupBox("Watch for new devices")
        wf = QFormLayout(w)
        self.watch = QCheckBox("Rescan my network regularly and tell me when an unknown device joins")
        wf.addRow("", _wrap(self.watch, "Needs a baseline first: scan on the Devices page and press <i>Mark all as known</i>. Uses the network chosen there."))
        self.watch_min = QSpinBox()
        self.watch_min.setRange(5, 1440)
        self.watch_min.setSuffix(" minutes")
        wf.addRow("Rescan every", self.watch_min)
        self.watch_all = QCheckBox("Also send new-device alerts to email / phone channels, not just the pop-up")
        wf.addRow("", _wrap(self.watch_all, "Uses the channels on the Alerts page. Handy when nobody is sitting at this PC."))
        lay.addWidget(w)

        # --- status page
        s = QGroupBox("Status web page (SimpleMonitor's HTML logger)")
        sf = QFormLayout(s)
        self.sp_enable = QCheckBox("Write an HTML status page after every round of checks")
        sf.addRow("", _wrap(self.sp_enable, "Great for a wall display or sharing with staff: put the folder on a web server or network share. "
                                            "It's SimpleMonitor's built-in <code>html</code> logger."))
        row = QHBoxLayout()
        self.sp_folder = QLineEdit()
        self.sp_folder.setPlaceholderText(str(paths.status_page_dir()))
        browse = make_button("Browse...")
        browse.clicked.connect(self._browse_status)
        openb = make_button("Open page")
        openb.clicked.connect(self._open_status)
        row.addWidget(self.sp_folder, 1)
        row.addWidget(browse)
        row.addWidget(openb)
        rw = QWidget()
        rw.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        sf.addRow("Folder", rw)
        self.sp_title = QLineEdit()
        sf.addRow("Page title", self.sp_title)
        lay.addWidget(s)

        # --- data
        d = QGroupBox("Your data")
        dl = QVBoxLayout(d)
        dl.addWidget(HelpText("NetBeacon stores everything in <code>" + str(paths.data_dir()) + "</code> - nothing is sent anywhere except alerts you configure.", always=True))
        btns = QHBoxLayout()
        self.export_btn = make_button("Export for stock SimpleMonitor...")
        self.export_btn.setToolTip("Writes monitor.ini + monitors.ini that run on plain 'pip install simplemonitor' - your path to a headless, always-on setup.")
        self.backup_btn = make_button("Back up settings...")
        self.restore_btn = make_button("Restore from backup...")
        self.folder_btn = make_button("Open data folder")
        for b in (self.export_btn, self.backup_btn, self.restore_btn, self.folder_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        dl.addLayout(btns)
        btns2 = QHBoxLayout()
        self.wizard_btn = make_button("Run the Quick Start wizard again")
        self.clear_btn = make_button("Delete all history...", "danger")
        btns2.addWidget(self.wizard_btn)
        btns2.addWidget(self.clear_btn)
        btns2.addStretch(1)
        dl.addLayout(btns2)
        lay.addWidget(d)

        # --- about
        ab = QGroupBox("About")
        abl = QVBoxLayout(ab)
        try:
            import importlib.metadata as md
            sm_ver = md.version("simplemonitor")
        except Exception:
            sm_ver = "1.15"
        abl.addWidget(label(f"<b>NetBeacon {__version__}</b>  -  engine: SimpleMonitor {sm_ver}  -  Python {platform.python_version()}", wrap=True, rich=True))
        abl.addWidget(label("SimpleMonitor (c) James Seward, BSD 3-Clause. Docs: <a href='https://simplemonitor.readthedocs.io/'>simplemonitor.readthedocs.io</a>. "
                            "GUI built with Qt for Python (PySide6, LGPL).", "muted", wrap=True, rich=True))
        lay.addWidget(ab)
        lay.addStretch(1)
        scroll.setWidget(host)
        self.root.addWidget(scroll, 1)

        self.save_btn.clicked.connect(self.save)
        self.export_btn.clicked.connect(self._export)
        self.backup_btn.clicked.connect(self._backup)
        self.restore_btn.clicked.connect(self._restore)
        self.folder_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.data_dir()))))
        self.clear_btn.clicked.connect(self._clear)
        self.wizard_btn.clicked.connect(lambda: ctx.main_window.run_wizard())
        self.load()

    # ------------------------------------------------------------------
    def load(self) -> None:
        s = self.ctx.store
        self.interval.setValue(int(s.get("interval", 30)))
        self.retention.setValue(int(s.get("retention_days", 30)))
        self.theme.setCurrentIndex(max(0, self.theme.findData(s.get("theme", "light"))))
        self.teaching.setChecked(bool(s.get("teaching_mode", True)))
        self.tray.setChecked(bool(s.get("minimize_to_tray", True)))
        self.autostart.setChecked(system.is_autostart() if system.autostart_supported() else bool(s.get("start_with_windows")))
        self.minimized.setChecked(bool(s.get("start_minimized")))
        self.watch.setChecked(bool(s.get("scan_watch_enabled")))
        self.watch_min.setValue(int(s.get("scan_watch_minutes", 60)))
        self.watch_all.setChecked(bool(s.get("new_device_all_channels", True)))
        self.sp_enable.setChecked(bool(s.get("status_page_enabled")))
        self.sp_folder.setText(str(s.get("status_page_folder", "")))
        self.sp_title.setText(str(s.get("status_page_title", "Network status")))

    def save(self) -> None:
        s = self.ctx.store
        old_theme = s.get("theme")
        s.settings.update({
            "interval": self.interval.value(), "retention_days": self.retention.value(), "theme": self.theme.currentData(),
            "teaching_mode": self.teaching.isChecked(), "minimize_to_tray": self.tray.isChecked(),
            "start_with_windows": self.autostart.isChecked(), "start_minimized": self.minimized.isChecked(),
            "scan_watch_enabled": self.watch.isChecked(), "scan_watch_minutes": self.watch_min.value(),
            "new_device_all_channels": self.watch_all.isChecked(),
            "status_page_enabled": self.sp_enable.isChecked(), "status_page_folder": self.sp_folder.text().strip(),
            "status_page_title": self.sp_title.text().strip() or "Network status",
        })
        s.save()
        if system.autostart_supported() and not system.set_autostart(self.autostart.isChecked()):
            self.ctx.toast("Could not change the Windows start-up setting.", "error")
        self.ctx.apply_changes()
        self.ctx.settings_changed.emit()
        if old_theme != s.get("theme"):
            self.ctx.theme_changed.emit(s.get("theme"))
        self.ctx.toast("Settings saved.", "ok")

    def _browse_status(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "Folder for the status page", self.sp_folder.text() or str(paths.status_page_dir()))
        if p:
            self.sp_folder.setText(p)

    def _open_status(self) -> None:
        folder = Path(self.sp_folder.text().strip() or paths.status_page_dir())
        page = folder / "index.html"
        if page.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(page)))
        else:
            QMessageBox.information(self, "Status page", "The page doesn't exist yet. Tick the box, press Save, and wait for one round of checks.")

    def _export(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "Choose a folder for the exported SimpleMonitor files")
        if not p:
            return
        folder = Path(p) / f"netbeacon-export-{time.strftime('%Y%m%d-%H%M')}"
        notes = config_writer.export_standalone(self.ctx.store, folder)
        msg = f"Exported to:\n{folder}\n\nRun it anywhere with:\n  pip install simplemonitor\n  simplemonitor -f monitor.ini"
        if notes:
            msg += "\n\nNotes:\n- " + "\n- ".join(notes)
        QMessageBox.information(self, "Export finished", msg)

    def _backup(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Back up settings", f"netbeacon-backup-{time.strftime('%Y%m%d')}.zip", "Zip (*.zip)")
        if not path:
            return
        self.ctx.store.save()
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(paths.settings_file(), "settings.json")
            z.write(paths.monitors_file(), "monitors.json")
        self.ctx.toast("Backup saved. It contains passwords - keep it safe.", "ok")

    def _restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Restore from backup", "", "Zip (*.zip)")
        if not path:
            return
        if QMessageBox.question(self, "Restore", "This replaces your current checks and settings. Continue?") != QMessageBox.StandardButton.Yes:
            return
        try:
            with zipfile.ZipFile(path) as z:
                settings = json.loads(z.read("settings.json"))
                monitors = json.loads(z.read("monitors.json"))
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            QMessageBox.warning(self, "Restore", "That doesn't look like a NetBeacon backup.")
            return
        paths.settings_file().write_text(json.dumps(settings, indent=2), encoding="utf-8")
        paths.monitors_file().write_text(json.dumps(monitors, indent=2), encoding="utf-8")
        self.ctx.store.load()
        self.load()
        self.ctx.apply_changes()
        self.ctx.settings_changed.emit()
        self.ctx.theme_changed.emit(self.ctx.store.get("theme", "light"))
        self.ctx.toast("Backup restored.", "ok")

    def _clear(self) -> None:
        if QMessageBox.question(self, "Delete history", "Delete all results, incidents and events? Your checks and settings stay.") == QMessageBox.StandardButton.Yes:
            self.ctx.history.clear_all()
            self.ctx.toast("History deleted.", "info")

    def on_show(self) -> None:
        self.load()
