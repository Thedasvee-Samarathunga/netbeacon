"""Alert channels and rules."""
from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QScrollArea,
                               QSpinBox, QTimeEdit, QVBoxLayout, QWidget)

from ...engine import send_test_alert
from ...store import Store
from ..widgets import HelpText, InfoBanner, PageHeader, Task, label, make_button
from .base import Page

CHANNELS: list[dict] = [
    {"key": "desktop", "title": "Desktop pop-up", "fields": [],
     "help": "A notification on this PC (and the tray icon changes colour). Works even when the internet is down - which is exactly when you need it. "
             "Only helps if someone is at the computer, so combine it with a phone channel."},
    {"key": "email", "title": "Email", "fields": [
        ("host", "SMTP server", "text", "smtp.office365.com", "The outgoing mail server of your email provider."),
        ("port", "Port", "int", "", "587 (STARTTLS) is the usual choice; 465 for SSL; 25 for plain."),
        ("ssl", "Security", "choice", "", "STARTTLS is the modern default."),
        ("username", "Username", "text", "", "Often your full email address. Leave empty if the server needs no login."),
        ("password", "Password", "password", "", "Use an app password if your provider offers them. Stored on this PC in plain text."),
        ("from", "Send from", "text", "alerts@yourcompany.com", ""),
        ("to", "Send to", "text", "you@yourcompany.com; colleague@yourcompany.com", "Separate several addresses with semicolons."),
    ], "help": "Works anywhere, reaches people's phones, and gives a record. Remember: it can't be delivered while the internet is down."},
    {"key": "slack", "title": "Slack", "fields": [
        ("url", "Webhook URL", "text", "https://hooks.slack.com/services/...", "In Slack: create an app with 'Incoming Webhooks' and copy the URL for your channel."),
    ], "help": "Posts to a Slack channel using an Incoming Webhook."},
    {"key": "telegram", "title": "Telegram", "fields": [
        ("token", "Bot token", "text", "123456:ABC-DEF...", "Create a bot by chatting with @BotFather and copy the token."),
        ("chat_id", "Chat ID", "text", "", "The ID of the chat or group the bot should write to."),
    ], "help": "Free, fast phone notifications through a Telegram bot."},
    {"key": "ntfy", "title": "ntfy (phone push)", "fields": [
        ("server", "Server", "text", "https://ntfy.sh", "The public server ntfy.sh works out of the box; you can also run your own."),
        ("topic", "Topic", "text", "my-company-alerts-8f3k", "Choose a long, hard-to-guess name: anyone who knows the topic can read it. Subscribe to it in the ntfy phone app."),
        ("token", "Access token (optional)", "password", "", "Only needed for protected topics."),
    ], "help": "The simplest way to get push notifications on your phone without accounts."},
    {"key": "pushover", "title": "Pushover", "fields": [
        ("token", "Application token", "text", "", "From your Pushover application page."),
        ("user", "User key", "text", "", "From your Pushover account page."),
    ], "help": "Paid phone-notification service with priority levels."},
]


class ChannelBox(QGroupBox):
    def __init__(self, page: "AlertsPage", spec: dict) -> None:
        super().__init__(spec["title"])
        self.page, self.spec = page, spec
        self.setCheckable(True)
        self.getters: dict[str, Any] = {}
        self.setters: dict[str, Any] = {}
        lay = QVBoxLayout(self)
        lay.addWidget(HelpText(spec["help"], always=True))
        form = QFormLayout()
        form.setVerticalSpacing(6)
        for key, text, kind, ph, hlp in spec["fields"]:
            if kind == "int":
                w: QWidget = QSpinBox()
                w.setRange(1, 65535)
                self.getters[key] = w.value
                self.setters[key] = lambda v, ww=w: ww.setValue(int(v or 587))
            elif kind == "choice":
                w = QComboBox()
                for t, v in (("STARTTLS (recommended)", "starttls"), ("SSL/TLS", "yes"), ("None", "")):
                    w.addItem(t, v)
                self.getters[key] = w.currentData
                self.setters[key] = lambda v, ww=w: ww.setCurrentIndex(max(0, ww.findData(v or "")))
            else:
                w = QLineEdit()
                w.setPlaceholderText(ph)
                if kind == "password":
                    w.setEchoMode(QLineEdit.EchoMode.Password)
                self.getters[key] = lambda ww=w: ww.text().strip()
                self.setters[key] = lambda v, ww=w: ww.setText(str(v or ""))
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(2)
            bl.addWidget(w)
            if hlp:
                bl.addWidget(HelpText(hlp))
            form.addRow(text, box)
        lay.addLayout(form)
        row = QHBoxLayout()
        self.test_btn = make_button("Send a test alert")
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.result.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self.test_btn)
        row.addWidget(self.result, 1)
        lay.addLayout(row)
        self.test_btn.clicked.connect(self._test)
        self._task: Task | None = None

    def load(self, cfg: dict) -> None:
        self.setChecked(bool(cfg.get("enabled")))
        for k, setter in self.setters.items():
            setter(cfg.get(k, ""))

    def values(self) -> dict:
        d = {k: g() for k, g in self.getters.items()}
        d["enabled"] = self.isChecked()
        return d

    def _test(self) -> None:
        tmp = Store.__new__(Store)
        tmp.settings = copy.deepcopy(self.page.ctx.store.settings)
        tmp.monitors = []
        tmp.settings["channels"][self.spec["key"]].update(self.values())
        key = self.spec["key"]
        self.test_btn.setEnabled(False)
        self.result.setText("Sending...")
        self._task = Task(lambda _t: send_test_alert(tmp, key), self)
        self._task.result.connect(self._done)
        self._task.failed.connect(self._failed)
        self._task.start()

    def _done(self, res) -> None:
        ok, msg = res
        self.test_btn.setEnabled(True)
        self.result.setText(f"<b style='color:{'#16a34a' if ok else '#dc2626'}'>{'Sent.' if ok else 'Failed.'}</b> {msg}")

    def _failed(self, msg: str) -> None:
        self.test_btn.setEnabled(True)
        self.result.setText(f"<b style='color:#dc2626'>Failed.</b> {msg}")


class AlertsPage(Page):
    key = "alerts"
    title = "Alerts"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        head = PageHeader("Alerts", "Decide who hears about problems, and when.")
        self.save_btn = head.add_action(make_button("Save and apply", "primary"))
        self.root.addWidget(head)
        self.root.addWidget(InfoBanner("alerts"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setSpacing(14)
        lay.setContentsMargins(0, 0, 8, 0)

        # --- rules first: they apply to every channel
        rules = QGroupBox("When should an alert be sent?")
        rl = QFormLayout(rules)
        rl.setVerticalSpacing(8)
        self.limit = QSpinBox()
        self.limit.setRange(1, 20)
        self.limit.setSuffix(" failed check(s) in a row, beyond each check's own tolerance")
        rl.addRow("Alert after", self._help(self.limit, "SimpleMonitor option <code>limit</code>. 1 = alert as soon as a check is DOWN. Use a higher number for less sensitive channels."))
        self.repeat = QCheckBox("Keep repeating the alert while it is still down")
        rl.addRow("", self._help(self.repeat, "Repeats every <i>limit</i> failures. Handy when something important stays broken, annoying otherwise."))
        self.recovery = QCheckBox("Also tell me when it is back up")
        self.recovery.setChecked(True)
        rl.addRow("", self._help(self.recovery, "Recommended. It ends the worry and shows how long the outage lasted."))
        self.quiet = QCheckBox("Quiet hours: hold alerts back between")
        self.q_from, self.q_to = QTimeEdit(QTime(22, 0)), QTimeEdit(QTime(7, 0))
        for t in (self.q_from, self.q_to):
            t.setDisplayFormat("HH:mm")
        qrow = QHBoxLayout()
        qrow.addWidget(self.quiet)
        qrow.addWidget(self.q_from)
        qrow.addWidget(QLabel("and"))
        qrow.addWidget(self.q_to)
        qrow.addStretch(1)
        qw = QWidget()
        qw.setLayout(qrow)
        qrow.setContentsMargins(0, 0, 0, 0)
        rl.addRow("", self._help(qw, "Alerts that happen overnight are held back, and a 'failed earlier' catch-up is sent when quiet hours end. Checks still run and are recorded."))
        self.weekdays = QCheckBox("Only alert Monday to Friday")
        rl.addRow("", self.weekdays)
        lay.addWidget(rules)

        lay.addWidget(label("Where should alerts go?", "h2"))
        self.boxes: dict[str, ChannelBox] = {}
        for spec in CHANNELS:
            b = ChannelBox(self, spec)
            self.boxes[spec["key"]] = b
            lay.addWidget(b)
        lay.addWidget(HelpText("<b>Careful:</b> email, Slack, Telegram and ntfy need a working internet connection. If the internet is what failed, "
                               "those alerts can't leave the building - keep the desktop pop-up on as well. Passwords are stored on this PC in your user profile, unencrypted: use app passwords or tokens, not your main password.", always=True))
        lay.addStretch(1)
        scroll.setWidget(host)
        self.root.addWidget(scroll, 1)
        self.save_btn.clicked.connect(self.save)
        self.load()

    @staticmethod
    def _help(w: QWidget, text: str) -> QWidget:
        c = QWidget()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        cl.addWidget(w)
        cl.addWidget(HelpText(text))
        return c

    def load(self) -> None:
        s = self.ctx.store
        r = s.get("alert_rules", {})
        self.limit.setValue(int(r.get("limit", 1)))
        self.repeat.setChecked(bool(r.get("repeat")))
        self.recovery.setChecked(bool(r.get("recovery", True)))
        self.quiet.setChecked(bool(r.get("quiet_enabled")))
        self.q_from.setTime(QTime.fromString(r.get("quiet_from", "22:00"), "HH:mm"))
        self.q_to.setTime(QTime.fromString(r.get("quiet_to", "07:00"), "HH:mm"))
        self.weekdays.setChecked(bool(r.get("weekdays_only")))
        ch = s.get("channels", {})
        for k, box in self.boxes.items():
            box.load(ch.get(k, {}))

    def save(self) -> None:
        s = self.ctx.store
        s.settings["alert_rules"] = {
            "limit": self.limit.value(), "repeat": self.repeat.isChecked(), "recovery": self.recovery.isChecked(),
            "quiet_enabled": self.quiet.isChecked(), "quiet_from": self.q_from.time().toString("HH:mm"),
            "quiet_to": self.q_to.time().toString("HH:mm"), "weekdays_only": self.weekdays.isChecked(),
        }
        for k, box in self.boxes.items():
            s.settings["channels"][k].update(box.values())
        s.save()
        self.ctx.apply_changes()
        from ... import config_writer
        problems = [p for n, o in config_writer.alerter_sections(s).items() if (p := config_writer.validate_alerter(n, o))]
        if problems:
            self.ctx.toast(problems[0], "error")
        else:
            self.ctx.toast("Alert settings saved.", "ok")

    def on_show(self) -> None:
        self.load()
