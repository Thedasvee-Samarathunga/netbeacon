"""The monitoring engine: runs SimpleMonitor on a background thread.

How the pieces fit together
---------------------------
    GUI  --edits-->  Store  --config_writer-->  monitor.ini + monitors.ini
                                                      |
                              SimpleMonitor(config)  <-+
                                   |  run_loop() every N seconds:
                                   |     1. run_tests()    every enabled check (in parallel)
                                   |     2. do_recovery()  optional self-heal command
                                   |     3. do_alerts()    -> DesktopAlerter / email / Slack ...
                                   |     4. do_logs()      -> GuiLogger -> Recorder -> history DB + GUI
                                   v
                      Recorder (incidents, events)  +  snapshots for the dashboard

This file has no Qt dependency so it can be tested headless; `ui/qt_bridge.py` turns the callbacks into Qt signals.
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import compat  # noqa: F401
from . import config_writer, netutil, sm_ext
from .checks import CHECKS
from .netutil import format_duration
from .sm_ext import bridge
from .store import ST_DOWN, ST_RETRY, ST_UP, History, Store

from simplemonitor.Monitors.monitor import Monitor, MonitorFail
from simplemonitor.Monitors.monitor import get_class as get_monitor_class
from simplemonitor.simplemonitor import SimpleMonitor
from simplemonitor.util import MonitorState

log = logging.getLogger("netbeacon.engine")

# attributes of a Monitor that make up its "memory" - copied across config reloads so a
# monitor that is still down doesn't forget it is down (and re-send alerts) when you edit something else
_STATE_ATTRS = ("error_count", "success_count", "tests_run", "last_error_count", "failures", "last_failure",
                "uptime_start", "_failed_at", "_state", "last_result", "last_update", "unavailable_seconds",
                "_first_load", "response_ms", "last_run_duration", "recover_info", "recovered_info", "skip_dep")


def local_status(mon: Monitor) -> str:
    """up / retry (failing but within tolerance) / down / pending"""
    if mon.error_count > 0:
        return "down" if mon.virtual_fail_count() > 0 else "retry"
    if mon.tests_run > 0:
        return "up"
    return "pending"


# --------------------------------------------------------------------------- recorder
class Recorder:
    """Turns raw results into history rows, incidents and human-readable events."""

    def __init__(self, history: History, emit_event: Callable[[str, Optional[str], str], None]) -> None:
        self.history = history
        self.emit = emit_event
        self.prev: dict[str, str] = {}
        self.fail_start: dict[str, float] = {}
        self.last_msg: dict[str, str] = {}

    def forget(self, name: str) -> None:
        for d in (self.prev, self.fail_start, self.last_msg):
            d.pop(name, None)

    def on_result(self, name: str, mon: Monitor) -> None:
        now = time.time()
        st = local_status(mon)
        code = {"up": ST_UP, "down": ST_DOWN, "retry": ST_RETRY}.get(st)
        if code is None:
            return
        msg = mon.get_result() or ""
        latency = getattr(mon, "response_ms", None)
        self.history.add_result(now, name, code, latency, msg)
        prev = self.prev.get(name)
        if st == "retry":
            self.fail_start.setdefault(name, now)
            if prev != "retry":
                self.emit("warn", name, f"{name}: check failed ({msg}). Retrying before calling it down "
                                         f"(tolerance {mon._tolerance}).")
        elif st == "down":
            start = self.fail_start.setdefault(name, now)
            if prev != "down":
                if not self.history.has_open_incident(name):
                    self.history.open_incident(name, start, msg)
                self.emit("error", name, f"{name} is DOWN: {msg}")
            elif self.last_msg.get(name) != msg:
                self.history.update_incident_reason(name, msg)
            self.last_msg[name] = msg
        else:  # up
            if prev == "down" or self.history.has_open_incident(name):
                duration = self.history.close_incident(name, now)
                dur = f" after {format_duration(duration)}" if duration is not None else ""
                self.emit("ok", name, f"{name} has RECOVERED{dur}. {msg}")
            elif prev == "retry":
                self.emit("info", name, f"{name}: a blip - it failed briefly but recovered before it counted as down.")
            self.fail_start.pop(name, None)
            self.last_msg.pop(name, None)
        self.prev[name] = st


# --------------------------------------------------------------------------- log capture
class LogBuffer(logging.Handler):
    """Keeps SimpleMonitor's own log lines so the 'under the hood' page can show them."""

    def __init__(self, size: int = 3000) -> None:
        super().__init__(level=logging.INFO)
        self.lines: collections.deque = collections.deque(maxlen=size)
        self.listeners: list[Callable[[tuple], None]] = []
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            item = (record.created, record.levelname, record.name.replace("simplemonitor.", "sm:"), self.format(record))
        except Exception:
            return
        self.lines.append(item)
        for cb in list(self.listeners):
            try:
                cb(item)
            except Exception:
                pass


# --------------------------------------------------------------------------- engine
@dataclass
class LoopInfo:
    running: bool = False
    paused: bool = False
    last_loop_ts: float = 0.0
    last_duration: float = 0.0
    next_run_ts: float = 0.0
    loops: int = 0
    checking: bool = False


class EngineCore:
    def __init__(self, store: Store, history: History) -> None:
        self.store = store
        self.history = history
        self.sm: Optional[SimpleMonitor] = None
        self.build: Optional[config_writer.BuildResult] = None
        self.info = LoopInfo(paused=bool(store.get("paused", False)))
        self.logbuf = LogBuffer()
        self.recorder = Recorder(history, self._emit_event)

        self.on_snapshot: list[Callable[[list[dict]], None]] = []
        self.on_event: list[Callable[[dict], None]] = []
        self.on_notify: list[Callable[[str, str, str], None]] = []
        self.on_status: list[Callable[[LoopInfo], None]] = []
        self.on_problems: list[Callable[[list[str]], None]] = []

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._reload = True
        self._force = False
        self._last_purge = 0.0
        self.snapshot_cache: list[dict] = []

        sm_logger = logging.getLogger("simplemonitor")
        sm_logger.setLevel(logging.INFO)
        if self.logbuf not in sm_logger.handlers:
            sm_logger.addHandler(self.logbuf)

    # ---- callbacks
    def _emit_event(self, level: str, monitor: Optional[str], text: str) -> None:
        ts = time.time()
        try:
            self.history.add_event(ts, level, monitor, text)
        except Exception:
            log.exception("could not save event")
        item = {"ts": ts, "level": level, "monitor": monitor, "text": text}
        for cb in list(self.on_event):
            cb(item)

    def _notify(self, title: str, text: str, level: str) -> None:
        self._emit_event("alert", None, f"Alert sent: {title} - {text}")
        for cb in list(self.on_notify):
            cb(title, text, level)

    def _status(self) -> None:
        for cb in list(self.on_status):
            cb(self.info)

    # ---- control
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        bridge.on_result = self.recorder.on_result
        bridge.on_notify = self._notify
        try:
            last_seen = float(self.history.meta_get("last_seen", "0") or 0)
            self.history.close_stale_incidents(last_seen or time.time())
        except Exception:
            log.exception("stale incident cleanup failed")
        self._thread = threading.Thread(target=self._run, name="netbeacon-engine", daemon=True)
        self.info.running = True
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=15)
        self.info.running = False
        try:
            self.history.meta_set("last_seen", str(time.time()))
        except Exception:
            pass

    def reload(self) -> None:
        """Re-write the INI files and reload (call after any settings/monitor change)."""
        self._reload = True
        self._force = True
        self._wake.set()

    def check_now(self) -> None:
        self._force = True
        self._wake.set()

    def set_paused(self, paused: bool) -> None:
        self.info.paused = paused
        self.store.set("paused", paused)
        self._wake.set()
        self._status()

    # ---- building
    def _rebuild(self) -> None:
        self._reload = False
        result = config_writer.build(self.store)
        self.build = result
        old = self.sm
        try:
            new = SimpleMonitor(result.monitor_ini, max_workers=16, heartbeat=False)
        except Exception as exc:
            log.exception("SimpleMonitor refused the configuration")
            result.problems.append(f"The engine could not load the configuration: {exc}")
            for cb in list(self.on_problems):
                cb(result.problems)
            return
        if old is not None:
            for name, mon in new.monitors.items():
                prev = old.monitors.get(name)
                if prev is not None and type(prev) is type(mon):
                    for attr in _STATE_ATTRS:
                        if attr in prev.__dict__:
                            setattr(mon, attr, prev.__dict__[attr])
                    mon._force_run = True
            for name, al in new.alerters.items():
                pa = old.alerters.get(name)
                if pa is not None and type(pa) is type(al):
                    al._alert_history = pa._alert_history
                    al._ooh_failures = pa._ooh_failures
            for gone in set(old.monitors) - set(new.monitors):
                self.recorder.forget(gone)
        self.sm = new
        for cb in list(self.on_problems):
            cb(result.problems)

    # ---- snapshot
    def snapshot(self) -> list[dict]:
        rows: list[dict] = []
        live = self.sm.monitors if self.sm else {}
        problems = {}
        if self.build:
            for p in self.build.problems:
                for m in self.store.monitors:
                    if f"'{m.name}'" in p:
                        problems[m.name] = p
        statuses: dict[str, str] = {name: local_status(mon) for name, mon in live.items()}
        now = time.time()
        for m in self.store.monitors:
            row: dict[str, Any] = {"id": m.id, "name": m.name, "kind": m.kind, "group": m.group,
                                   "title": CHECKS[m.kind].title if m.kind in CHECKS else m.kind,
                                   "target": CHECKS[m.kind].target(m.params) if m.kind in CHECKS else "",
                                   "enabled": m.enabled, "tolerance": m.tolerance, "message": "", "response_ms": None,
                                   "last_check": None, "since": None, "failures": 0, "description": "", "depends": list(m.depends)}
            mon = live.get(m.name)
            if not m.enabled:
                row["status"] = "paused"
            elif mon is None:
                row["status"] = "error"
                row["message"] = problems.get(m.name, "This check could not be started - see the Activity page.")
            else:
                st = statuses[m.name]
                dep_down = [d for d in mon.dependencies if statuses.get(d) == "down"]
                if mon.state() == MonitorState.SKIPPED and dep_down:
                    st = "skipped"
                    row["message"] = f"Not checked because {', '.join(dep_down)} is down"
                else:
                    row["message"] = mon.get_result() or ""
                row["status"] = st
                row["response_ms"] = getattr(mon, "response_ms", None)
                row["last_check"] = mon.last_update.timestamp() if mon.last_update else None
                up = mon.uptime()
                row["since"] = up.total_seconds() if up and st in ("up", "retry") else None
                row["failures"] = mon.failures
                row["description"] = mon.describe()
                row["error_count"] = mon.error_count
            rows.append(row)
        self.snapshot_cache = rows
        return rows

    def _publish(self) -> None:
        rows = self.snapshot()
        for cb in list(self.on_snapshot):
            cb(rows)

    # ---- main loop
    def _run(self) -> None:
        interval = lambda: max(5, int(self.store.get("interval", 30)))  # noqa: E731
        while not self._stop.is_set():
            try:
                if self._reload or self.sm is None:
                    self._rebuild()
                    self._publish()
                if self.info.paused:
                    self.info.checking = False
                    self.info.next_run_ts = 0.0
                    self._status()
                    self._wake.wait(1.0)
                    self._wake.clear()
                    continue
                if self.sm is not None:
                    if self._force:
                        for mon in self.sm.monitors.values():
                            mon._force_run = True
                        self._force = False
                    self.info.checking = True
                    self._status()
                    t0 = time.time()
                    try:
                        self.sm.run_loop()
                    except Exception:
                        log.exception("monitoring round failed")
                    self.info.last_duration = time.time() - t0
                    self.info.last_loop_ts = time.time()
                    self.info.loops += 1
                    self.history.meta_set("last_seen", str(time.time()))
                    self.info.checking = False
                    self._publish()
                    self._maintenance()
                self.info.next_run_ts = time.time() + interval()
                self._status()
                self._wake.wait(interval())
                self._wake.clear()
            except Exception:
                log.exception("engine loop error")
                self._wake.wait(5.0)
                self._wake.clear()
        self.info.running = False

    def _maintenance(self) -> None:
        if time.time() - self._last_purge > 6 * 3600:
            self._last_purge = time.time()
            try:
                self.history.purge(int(self.store.get("retention_days", 30)))
            except Exception:
                log.exception("purge failed")


# --------------------------------------------------------------------------- alert testing
def send_test_alert(store: Store, channel: str) -> tuple[bool, str]:
    """Send a real test message through one channel using SimpleMonitor's own alerter class."""
    import copy
    tmp = Store.__new__(Store)
    tmp.settings = copy.deepcopy(store.settings)
    tmp.monitors = []
    tmp.settings["channels"][channel]["enabled"] = True
    sections = config_writer.alerter_sections(tmp)
    opts = sections.get(channel)
    if not opts:
        return False, "This channel is not configured yet."
    for k in ("times_type", "time_lower", "time_upper", "days", "delay", "ooh_recovery", "repeat", "only_failures"):
        opts.pop(k, None)
    opts["limit"] = "1"
    problem = config_writer.validate_alerter(channel, opts)
    if problem:
        return False, problem.split(": ", 1)[-1]

    from simplemonitor.Alerters.alerter import get_class as get_alerter_class
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
        alerter = get_alerter_class(opts["type"])({**opts, "name": channel})
        mon = MonitorFail("NetBeacon test", {})
        mon.record_fail("This is a test alert from NetBeacon. If you can read this, alerts are working!")
        alerter.send_alert("NetBeacon test", mon)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        root.removeHandler(catch)
    if errors:
        return False, errors[0]
    return True, "Test message sent. Check the channel now."
