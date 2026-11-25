"""Sending messages that are not ordinary check failures - "a new device joined", "your weekly summary".

`broadcast()` reuses SimpleMonitor's own alerter classes (email, Slack, Telegram, ntfy, Pushover), exactly like the
'Send a test alert' button does, so every channel you configured on the Alerts page works without extra setup.
`send_email()` sends a proper formatted email (used for the weekly summary, which is too long for a push message).
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

from . import compat  # noqa: F401
from . import config_writer
from .sm_ext import bridge
from .store import Store

_TIME_RULES = ("times_type", "time_lower", "time_upper", "days", "delay", "ooh_recovery", "repeat", "only_failures")


def broadcast(store: Store, title: str, message: str, level: str = "warn", channels: Optional[list[str]] = None,
              desktop: bool = True) -> dict[str, str]:
    """Send `message` through every enabled channel. Returns {channel: "" (ok) or error text}.

    Quiet hours are not applied: these are one-off messages, and holding them back would need the
    engine's alert memory. The desktop pop-up goes straight to the GUI."""
    from simplemonitor.Alerters.alerter import get_class as get_alerter_class
    from simplemonitor.Monitors.monitor import MonitorFail

    results: dict[str, str] = {}
    for name, opts in config_writer.alerter_sections(store).items():
        if channels is not None and name not in channels:
            continue
        if opts.get("type") == "netbeacon_desktop":
            if desktop:
                bridge.on_notify(title, message, level)
                results[name] = ""
            continue
        opts = {k: v for k, v in opts.items() if k not in _TIME_RULES}
        opts["limit"] = "1"
        problem = config_writer.validate_alerter(name, opts)
        if problem:
            results[name] = problem.split(": ", 1)[-1]
            continue
        errors: list[str] = []

        class Catch(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                if record.levelno >= logging.WARNING:
                    text = record.getMessage()
                    if record.exc_info and record.exc_info[1]:
                        text += f" ({record.exc_info[1]})"
                    errors.append(text)

        catch = Catch()
        root = logging.getLogger("simplemonitor")
        root.addHandler(catch)
        try:
            alerter = get_alerter_class(opts["type"])({**opts, "name": name})
            mon = MonitorFail(title, {})
            mon.record_fail(message)
            alerter.send_alert(title, mon)
            results[name] = errors[0] if errors else ""
        except Exception as exc:  # noqa: BLE001
            results[name] = f"{type(exc).__name__}: {exc}"
        finally:
            root.removeHandler(catch)
    return results


def email_ready(store: Store) -> bool:
    e = store.get("channels", {}).get("email", {})
    return bool(e.get("enabled") and e.get("host") and e.get("from") and e.get("to"))


def send_email(store: Store, subject: str, text: str, html: str = "", timeout: float = 20.0) -> tuple[bool, str]:
    """Send a formatted email with the settings of the Email alert channel."""
    e = store.get("channels", {}).get("email", {})
    if not (e.get("host") and e.get("from") and e.get("to")):
        return False, "Set up the Email channel on the Alerts page first (server, from and to)."
    to = [a.strip() for a in str(e.get("to", "")).replace(",", ";").split(";") if a.strip()]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = e["from"]
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    port = int(e.get("port") or 587)
    mode = str(e.get("ssl") or "")
    try:
        if mode == "yes":
            server: smtplib.SMTP = smtplib.SMTP_SSL(e["host"], port, timeout=timeout, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(e["host"], port, timeout=timeout)
        with server:
            if mode == "starttls":
                server.starttls(context=ssl.create_default_context())
            if e.get("username"):
                server.login(e["username"], e.get("password", ""))
            server.send_message(msg, to_addrs=to)
    except (OSError, smtplib.SMTPException) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, f"Sent to {', '.join(to)}."
