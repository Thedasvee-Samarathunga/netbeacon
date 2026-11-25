"""Weekly summary: the week in plain English, prepared automatically and optionally emailed."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QSpinBox, QTextBrowser,
                               QVBoxLayout, QWidget)

from ... import digest, notify, paths
from ..widgets import HelpText, InfoBanner, PageHeader, Task, label, make_button
from .base import Page

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
PERIODS = [("Last 7 days", 7 * 86400), ("Last 30 days", 30 * 86400), ("Last 24 hours", 86400)]


def summaries_dir() -> Path:
    p = paths.data_dir() / "summaries"
    p.mkdir(parents=True, exist_ok=True)
    return p


class DigestPage(Page):
    key = "digest"
    title = "Weekly summary"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.current: Optional[digest.Digest] = None
        self._mail_task: Optional[Task] = None
        head = PageHeader("Weekly summary", "Your network's week in plain English - the bit a busy owner actually reads.")
        self.make_btn = head.add_action(make_button("Create summary now", "primary"))
        self.save_html_btn = head.add_action(make_button("Save as web page..."))
        self.email_btn = head.add_action(make_button("Email it now"))
        self.root.addWidget(head)
        self.root.addWidget(InfoBanner("digest"))
        split = QHBoxLayout()
        split.setSpacing(14)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(label("Period:", "muted"))
        self.period = QComboBox()
        for t, s in PERIODS:
            self.period.addItem(t, s)
        bar.addWidget(self.period)
        bar.addStretch(1)
        self.stamp = label("", "muted")
        bar.addWidget(self.stamp)
        ll.addLayout(bar)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        ll.addWidget(self.view, 1)
        split.addWidget(left, 1)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        g = QGroupBox("Automatic summary")
        f = QFormLayout(g)
        f.setVerticalSpacing(8)
        self.auto = QCheckBox("Prepare a summary every week")
        f.addRow(self.auto)
        self.day = QComboBox()
        self.day.addItems(DAYS)
        f.addRow("On", self.day)
        self.hour = QSpinBox()
        self.hour.setRange(0, 23)
        self.hour.setSuffix(":00")
        f.addRow("At", self.hour)
        self.email = QCheckBox("Also email it")
        f.addRow(self.email)
        f.addRow(HelpText("Uses the Email channel from the Alerts page.", always=True))
        self.email_note = HelpText("", always=True)
        f.addRow(self.email_note)
        self.save_btn = make_button("Save", "primary")
        f.addRow(self.save_btn)
        rl.addWidget(g)
        rl.addWidget(HelpText("The summary is prepared when NetBeacon is running at the chosen time (or the next time it starts). "
                              "A pop-up tells you it's ready, and a copy is kept in the <i>summaries</i> folder of NetBeacon's data folder. "
                              "In bigger tools this is called a <b>scheduled report</b>."))
        open_btn = make_button("Open the summaries folder")
        open_btn.clicked.connect(self._open_folder)
        rl.addWidget(open_btn)
        rl.addStretch(1)
        right.setFixedWidth(330)
        split.addWidget(right)
        self.root.addLayout(split, 1)

        self.make_btn.clicked.connect(lambda: self.make())
        self.period.currentIndexChanged.connect(lambda _i: self.make())
        self.save_html_btn.clicked.connect(lambda: self._save_html())
        self.email_btn.clicked.connect(lambda: self._email(self.current))
        self.save_btn.clicked.connect(lambda: self.save())
        if not self.ctx.store.get("last_digest_ts"):
            # first start: the first automatic summary is the next scheduled one, not right now
            self.ctx.store.set("last_digest_ts", time.time())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._maybe_send)
        self.timer.start(5 * 60 * 1000)
        QTimer.singleShot(30 * 1000, self._maybe_send)
        self.load()

    # ---- settings
    def load(self) -> None:
        s = self.ctx.store
        self.auto.setChecked(bool(s.get("digest_enabled", True)))
        self.day.setCurrentIndex(int(s.get("digest_weekday", 0)) % 7)
        self.hour.setValue(int(s.get("digest_hour", 9)))
        self.email.setChecked(bool(s.get("digest_email")))
        ready = notify.email_ready(s)
        self.email_note.setText("" if ready else "The Email channel isn't set up yet - add it on the Alerts page first.")
        self.email_btn.setEnabled(ready)

    def save(self) -> None:
        s = self.ctx.store
        s.settings.update({"digest_enabled": self.auto.isChecked(), "digest_weekday": self.day.currentIndex(),
                           "digest_hour": self.hour.value(), "digest_email": self.email.isChecked()})
        s.save()
        self.ctx.toast("Summary settings saved.", "ok")

    # ---- building
    def build(self, seconds: int) -> digest.Digest:
        now = time.time()
        return digest.build(self.ctx.store, self.ctx.history, now - seconds, now)

    def make(self) -> None:
        self.current = self.build(int(self.period.currentData()))
        self._show(self.current)

    def _show(self, d: digest.Digest) -> None:
        self.view.setHtml(d.html())
        self.stamp.setText(f"created {time.strftime('%d %b %H:%M')}")

    def _maybe_send(self) -> None:
        s = self.ctx.store
        if not s.get("digest_enabled", True):
            return
        if not digest.is_due(time.time(), int(s.get("digest_weekday", 0)), int(s.get("digest_hour", 9)), float(s.get("last_digest_ts", 0) or 0)):
            return
        s.set("last_digest_ts", time.time())
        d = self.build(7 * 86400)
        self.current = d
        self._show(d)
        path = summaries_dir() / f"summary-{time.strftime('%Y-%m-%d')}.html"
        try:
            path.write_text(f"<!doctype html><meta charset='utf-8'><title>NetBeacon summary</title><body style='margin:32px'>{d.html()}</body>",
                            encoding="utf-8")
        except OSError:
            pass
        self.ctx.history.add_event(time.time(), "info", None, f"Weekly summary: {d.headline}")
        if self.ctx.main_window:
            self.ctx.main_window._on_notification("Your weekly network summary is ready", d.headline, "ok")
        if s.get("digest_email") and notify.email_ready(s):
            self._email(d, quiet=True)

    def _email(self, d: Optional[digest.Digest], quiet: bool = False) -> None:
        if d is None:
            self.make()
            d = self.current
        if self._mail_task and self._mail_task.isRunning():
            return
        store = self.ctx.store
        subject = f"Network summary: {d.headline}"
        self._mail_task = Task(lambda _t: notify.send_email(store, subject, d.text(), d.html()), self)
        self._mail_task.result.connect(lambda r: self._mailed(r, quiet))
        self._mail_task.failed.connect(lambda m: self._mailed((False, m), quiet))
        self._mail_task.start()

    def _mailed(self, res, quiet: bool) -> None:
        ok, msg = res
        self.ctx.history.add_event(time.time(), "info" if ok else "warn", None, f"Summary email: {msg}")
        if not quiet or not ok:
            self.ctx.toast(("Summary emailed. " if ok else "Could not email the summary: ") + msg, "ok" if ok else "error")

    def _save_html(self) -> None:
        if self.current is None:
            self.make()
        path, _ = QFileDialog.getSaveFileName(self, "Save summary", f"network-summary-{time.strftime('%Y-%m-%d')}.html", "Web page (*.html)")
        if path:
            Path(path).write_text(f"<!doctype html><meta charset='utf-8'><title>Network summary</title><body style='margin:32px'>{self.current.html()}</body>",
                                  encoding="utf-8")
            self.ctx.toast("Summary saved. Open it in a browser or print it to PDF.", "ok")

    def _open_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(summaries_dir())))

    def on_show(self) -> None:
        self.load()
        self.make()
