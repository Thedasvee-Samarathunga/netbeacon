"""NetBeacon's extensions to SimpleMonitor.

SimpleMonitor is designed to be extended: you subclass `Monitor`, `Alerter` or `Logger`
and decorate the class with `@register`. That is exactly what we do here - which makes
this file a nice, small example of "how to add your own check to SimpleMonitor".

Why do we need extras at all?
  * `ping`  - the built-in `host` monitor only understands English Windows output and never
              reports the round-trip time, so we add a locale-proof one that also measures latency.
  * `tcp`/`http` - same behaviour as the built-ins, plus response-time measurement and timeouts.
  * `dns`   - the built-in one shells out to `dig`, which Windows does not have.
  * disk / cpu / file / command - Windows-friendly versions with sensible timeouts.

Each custom type has a built-in equivalent where one exists; see `checks.py` (`standalone_type`)
which is used when you export a config for plain SimpleMonitor.
"""
from __future__ import annotations

import glob
import os
import re
import shlex
import subprocess
import sys
import time
from typing import Any, Callable, Optional, Tuple

from . import compat  # noqa: F401  (must come before simplemonitor imports)
from . import netutil

from simplemonitor.Alerters.alerter import Alerter, AlertLength, AlertType
from simplemonitor.Alerters.alerter import register as register_alerter
from simplemonitor.Loggers.logger import Logger
from simplemonitor.Loggers.logger import register as register_logger
from simplemonitor.Monitors.monitor import Monitor
from simplemonitor.Monitors.monitor import register as register_monitor
from simplemonitor.Monitors.network import MonitorHTTP, MonitorTCP  # also loads every built-in monitor


# --------------------------------------------------------------------------- bridge to the GUI
class Bridge:
    """The engine plugs callbacks in here; the custom Logger/Alerter call them."""

    def __init__(self) -> None:
        self.on_result: Callable[[str, Monitor], None] = lambda name, mon: None
        self.on_notify: Callable[[str, str, str], None] = lambda title, text, level: None


bridge = Bridge()


# --------------------------------------------------------------------------- monitors
class _Timed:
    """Mixin: remember how long the check took so the GUI can graph it."""

    response_ms: Optional[float] = None
    slow_ms: int = 0

    def _read_slow(self) -> None:
        self.slow_ms = self.get_config_option("slow_ms", required_type="int", default=0, minimum=0)  # type: ignore[attr-defined]

    def _finish_ok(self, ms: float, message: str) -> bool:
        self.response_ms = ms
        if self.slow_ms and ms > self.slow_ms:
            return self.record_fail(f"{message} - slower than the {self.slow_ms} ms limit")  # type: ignore[attr-defined]
        return self.record_success(message)  # type: ignore[attr-defined]

    def _finish_fail(self, message: str, ms: Optional[float] = None) -> bool:
        self.response_ms = None if ms is None else ms
        return self.record_fail(message)  # type: ignore[attr-defined]


@register_monitor
class LanPing(_Timed, Monitor):
    """Ping with latency + packet loss, locale independent, no console window."""

    monitor_type = "lan_ping"

    def __init__(self, name: str, config_options: dict) -> None:
        super().__init__(name, config_options)
        self.host = self.get_config_option("host", required=True, allow_empty=False)
        self.count = self.get_config_option("count", required_type="int", default=3, minimum=1, maximum=20)
        self.timeout = self.get_config_option("timeout", required_type="int", default=4, minimum=1, maximum=60)
        self.max_loss = self.get_config_option("max_loss", required_type="int", default=50, minimum=0, maximum=100)
        self._read_slow()
        if not netutil.is_valid_host(self.host):
            raise ValueError(f"'{self.host}' is not a valid host name or IP address")

    def run_test(self) -> bool:
        res = netutil.ping_host(self.host, self.count, self.timeout)
        if not res.ok:
            return self._finish_fail(f"No reply from {self.host}: {res.error}")
        msg = f"{res.received}/{res.sent} replies, avg {res.avg_ms:.0f} ms" if res.avg_ms is not None else f"{res.received}/{res.sent} replies"
        if res.loss_pct > self.max_loss:
            return self._finish_fail(f"{msg} - packet loss {res.loss_pct:.0f}% is above the {self.max_loss}% limit", res.avg_ms)
        return self._finish_ok(res.avg_ms or 0.0, msg)

    def describe(self) -> str:
        return f"Pinging {self.host} ({self.count} packets, {self.timeout}s timeout)"

    def get_params(self) -> Tuple:
        return (self.host, self.count, self.timeout)


@register_monitor
class LanTCP(_Timed, MonitorTCP):
    """TCP port check (IPv4/IPv6) with timing."""

    monitor_type = "lan_tcp"

    def __init__(self, name: str, config_options: dict) -> None:
        super().__init__(name, config_options)
        self.timeout = self.get_config_option("timeout", required_type="int", default=5, minimum=1, maximum=60)
        self._read_slow()

    def run_test(self) -> bool:
        ok, ms, err = netutil.tcp_connect(self.host, self.port, self.timeout)
        if ok:
            return self._finish_ok(ms, f"port {self.port} open ({ms:.0f} ms)")
        return self._finish_fail(f"port {self.port} on {self.host}: {err}")


@register_monitor
class LanHTTP(_Timed, MonitorHTTP):
    """Web page check: status code, optional text match, optional speed limit."""

    monitor_type = "lan_http"

    def __init__(self, name: str, config_options: dict) -> None:
        super().__init__(name, config_options)
        self._read_slow()

    def run_test(self) -> bool:
        import requests

        headers = {"User-Agent": "NetBeacon/1.1 (+SimpleMonitor)"}
        if self.headers:
            headers.update(self.headers)
        start = time.perf_counter()
        try:
            resp = requests.request(
                self.method, self.url, headers=headers, timeout=self.request_timeout,
                verify=self.verify_hostname, allow_redirects=self.allow_redirects, auth=self.auth,
            )
        except requests.exceptions.SSLError as exc:
            return self._finish_fail(f"TLS/certificate problem: {str(exc)[:160]}")
        except requests.exceptions.Timeout:
            return self._finish_fail(f"no answer within {self.request_timeout}s")
        except requests.exceptions.ConnectionError as exc:
            return self._finish_fail(f"could not connect: {str(exc)[:160]}")
        except requests.exceptions.RequestException as exc:
            return self._finish_fail(f"request failed: {str(exc)[:160]}")
        ms = (time.perf_counter() - start) * 1000.0
        if resp.status_code not in self.allowed_codes:
            return self._finish_fail(f"got HTTP {resp.status_code} {resp.reason} (expected {', '.join(map(str, self.allowed_codes))})", ms)
        if self.regexp is not None and self.method != "HEAD" and not self.regexp.search(resp.text):
            return self._finish_fail(f"HTTP {resp.status_code} but the text /{self.regexp_text}/ was not found on the page", ms)
        return self._finish_ok(ms, f"HTTP {resp.status_code} in {ms:.0f} ms")


@register_monitor
class LanDNS(_Timed, Monitor):
    """DNS lookup (system resolver or a specific DNS server)."""

    monitor_type = "lan_dns"

    def __init__(self, name: str, config_options: dict) -> None:
        super().__init__(name, config_options)
        self.record = self.get_config_option("record", required=True, allow_empty=False)
        self.record_type = (self.get_config_option("record_type", default="A") or "A").upper()
        self.server = self.get_config_option("server") or None
        self.expect = [x.strip().lower() for x in (self.get_config_option("expect", default="") or "").split(",") if x.strip()]
        self.timeout = self.get_config_option("timeout", required_type="int", default=3, minimum=1, maximum=30)
        self.port = self.get_config_option("port", required_type="int", default=53, minimum=1, maximum=65535)
        self._read_slow()
        if self.server and not netutil.is_valid_host(self.server):
            raise ValueError("DNS server must be an IP address or host name")

    def run_test(self) -> bool:
        try:
            answers, ms = netutil.dns_query(self.record, self.record_type, self.server, self.timeout, self.port)
        except netutil.DnsError as exc:
            return self._finish_fail(str(exc))
        if self.expect:
            joined = " ".join(a.lower() for a in answers)
            missing = [e for e in self.expect if e not in joined]
            if missing:
                return self._finish_fail(f"answer {', '.join(answers)} does not contain {', '.join(missing)}", ms)
        shown = ", ".join(answers[:3]) + ("..." if len(answers) > 3 else "")
        return self._finish_ok(ms, f"{self.record} -> {shown} ({ms:.0f} ms)")

    def describe(self) -> str:
        via = f" using DNS server {self.server}" if self.server else " using this PC's DNS settings"
        return f"Looking up {self.record_type} record of {self.record}{via}"

    def get_params(self) -> Tuple:
        return (self.record, self.record_type, self.server)


@register_monitor
class LanDisk(Monitor):
    """Free disk space, in GB and/or percent."""

    monitor_type = "lan_disk"

    def __init__(self, name: str, config_options: dict) -> None:
        super().__init__(name, config_options)
        self.path = self.get_config_option("path", required=True, allow_empty=False)
        self.min_gb = self.get_config_option("min_free_gb", required_type="float", default=0.0, minimum=0)
        self.min_pct = self.get_config_option("min_free_percent", required_type="float", default=10.0, minimum=0, maximum=100)

    def run_test(self) -> bool:
        import psutil

        try:
            usage = psutil.disk_usage(self.path)
        except Exception as exc:
            return self.record_fail(f"cannot read {self.path}: {exc}")
        free_gb = usage.free / 1024 ** 3
        free_pct = 100.0 - usage.percent
        msg = f"{free_gb:.1f} GB free ({free_pct:.0f}%) on {self.path}"
        if self.min_gb and free_gb < self.min_gb:
            return self.record_fail(f"{msg} - below the {self.min_gb:g} GB limit")
        if self.min_pct and free_pct < self.min_pct:
            return self.record_fail(f"{msg} - below the {self.min_pct:g}% limit")
        return self.record_success(msg)

    def describe(self) -> str:
        return f"Free space on {self.path} (min {self.min_gb:g} GB / {self.min_pct:g}%)"

    def get_params(self) -> Tuple:
        return (self.path, self.min_gb, self.min_pct)


@register_monitor
class LanCPU(Monitor):
    """CPU busy-ness over a short sample."""

    monitor_type = "lan_cpu"

    def __init__(self, name: str, config_options: dict) -> None:
        super().__init__(name, config_options)
        self.max_percent = self.get_config_option("max_percent", required_type="int", default=90, minimum=1, maximum=100)
        self.sample = self.get_config_option("sample_seconds", required_type="int", default=2, minimum=1, maximum=30)

    def run_test(self) -> bool:
        import psutil

        pct = psutil.cpu_percent(interval=self.sample)
        msg = f"CPU {pct:.0f}% busy"
        if pct > self.max_percent:
            return self.record_fail(f"{msg} (limit {self.max_percent}%)")
        return self.record_success(msg)

    def describe(self) -> str:
        return f"CPU usage stays below {self.max_percent}%"

    def get_params(self) -> Tuple:
        return (self.max_percent,)


@register_monitor
class LanFile(Monitor):
    """File / backup freshness. The pattern may contain * and ? wildcards (newest match wins)."""

    monitor_type = "lan_file"

    def __init__(self, name: str, config_options: dict) -> None:
        super().__init__(name, config_options)
        self.pattern = self.get_config_option("pattern", required=True, allow_empty=False)
        self.max_age_hours = self.get_config_option("max_age_hours", required_type="float", default=0.0, minimum=0)
        self.min_size_mb = self.get_config_option("min_size_mb", required_type="float", default=0.0, minimum=0)

    def run_test(self) -> bool:
        matches = glob.glob(self.pattern)
        matches = [m for m in matches if os.path.isfile(m)]
        if not matches:
            return self.record_fail(f"no file matches {self.pattern}")
        newest = max(matches, key=os.path.getmtime)
        st = os.stat(newest)
        age_h = (time.time() - st.st_mtime) / 3600.0
        size_mb = st.st_size / 1024 ** 2
        msg = f"{os.path.basename(newest)}: {age_h:.1f} h old, {size_mb:.1f} MB"
        if self.max_age_hours and age_h > self.max_age_hours:
            return self.record_fail(f"{msg} - older than {self.max_age_hours:g} h")
        if self.min_size_mb and size_mb < self.min_size_mb:
            return self.record_fail(f"{msg} - smaller than {self.min_size_mb:g} MB")
        return self.record_success(msg)

    def describe(self) -> str:
        parts = [f"Newest file matching {self.pattern} exists"]
        if self.max_age_hours:
            parts.append(f"is younger than {self.max_age_hours:g} h")
        if self.min_size_mb:
            parts.append(f"is at least {self.min_size_mb:g} MB")
        return ", ".join(parts)

    def get_params(self) -> Tuple:
        return (self.pattern, self.max_age_hours, self.min_size_mb)


@register_monitor
class LanCommand(Monitor):
    """Run a program; success = exit code 0 (and optional text match). Has a timeout."""

    monitor_type = "lan_command"

    def __init__(self, name: str, config_options: dict) -> None:
        super().__init__(name, config_options)
        command = self.get_config_option("command", required=True, allow_empty=False)
        try:
            self.args = [a.strip('"') for a in shlex.split(command, posix=not netutil.IS_WINDOWS)]
        except ValueError as exc:
            raise ValueError(f"cannot understand the command: {exc}") from exc
        if not self.args:
            raise ValueError("command is empty")
        self.timeout = self.get_config_option("timeout", required_type="int", default=30, minimum=1, maximum=600)
        pattern = self.get_config_option("expect", default="")
        self.expect = re.compile(pattern) if pattern else None
        self.expect_text = pattern or ""

    def run_test(self) -> bool:
        try:
            proc = subprocess.run(self.args, capture_output=True, timeout=self.timeout, check=False)
        except FileNotFoundError:
            return self.record_fail(f"program not found: {self.args[0]}")
        except subprocess.TimeoutExpired:
            return self.record_fail(f"command did not finish within {self.timeout}s")
        except OSError as exc:
            return self.record_fail(str(exc))
        out = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
        short = (out.splitlines()[0][:120] if out else "")
        if proc.returncode != 0:
            return self.record_fail(f"exit code {proc.returncode}" + (f": {short}" if short else ""))
        if self.expect and not self.expect.search(out):
            return self.record_fail(f"output did not match /{self.expect_text}/")
        return self.record_success(f"exit code 0" + (f": {short}" if short else ""))

    def describe(self) -> str:
        return f"Running `{' '.join(self.args)}` and expecting exit code 0"

    def get_params(self) -> Tuple:
        return (tuple(self.args), self.expect_text)


@register_monitor
class LanWifi(Monitor):
    """Wi-Fi signal strength of this PC's connection (Windows, via netsh)."""

    monitor_type = "lan_wifi"

    def __init__(self, name: str, config_options: dict) -> None:
        super().__init__(name, config_options)
        self.min_signal = self.get_config_option("min_signal", required_type="int", default=50, minimum=1, maximum=100)
        self.ssid = (self.get_config_option("ssid", default="") or "").strip()

    def run_test(self) -> bool:
        from . import wifi
        st = wifi.read_status()
        if not st.available:
            return self.record_fail(st.note or "Wi-Fi details are not available")
        if not st.connected:
            return self.record_fail("this PC is not connected to Wi-Fi")
        if self.ssid and st.ssid != self.ssid:
            return self.record_fail(f"connected to '{st.ssid}', not '{self.ssid}'")
        word, _ = wifi.quality(st.signal)
        msg = f"{st.ssid}: signal {st.signal}% ({word}, about {st.dbm} dBm), {st.band or '?'} channel {st.channel or '?'}"
        if st.signal is not None and st.signal < self.min_signal:
            return self.record_fail(f"{msg} - below the {self.min_signal}% limit")
        return self.record_success(msg)

    def describe(self) -> str:
        return f"Wi-Fi signal stays above {self.min_signal}%" + (f" on '{self.ssid}'" if self.ssid else "")

    def get_params(self) -> Tuple:
        return (self.min_signal, self.ssid)


# --------------------------------------------------------------------------- logger -> GUI/history
@register_logger
class GuiLogger(Logger):
    """SimpleMonitor calls a Logger for *every* monitor after *every* round of checks.
    Ours hands each fresh result to NetBeacon's history database and GUI."""

    logger_type = "netbeacon_gui"

    def save_result2(self, name: str, monitor: Monitor) -> None:
        if monitor.ran_this_time:
            bridge.on_result(name, monitor)

    def describe(self) -> str:
        return "Sending results to the NetBeacon history database"


# --------------------------------------------------------------------------- alerter -> desktop
@register_alerter
class DesktopAlerter(Alerter):
    """SimpleMonitor decides *when* to alert (should_alert); we decide *how*: a pop-up."""

    alerter_type = "netbeacon_desktop"

    def send_alert(self, name: str, monitor: Monitor) -> None:
        alert_type = self.should_alert(monitor)
        if alert_type == AlertType.NONE:
            return
        if alert_type == AlertType.SUCCESS:
            title = f"Recovered: {name}"
            text = f"{name} is back up. It was down for {monitor.get_wasdowntime()}."
            level = "ok"
        else:
            title = f"DOWN: {name}"
            text = monitor.get_result() or "The check failed."
            level = "error"
        if not self._dry_run:
            bridge.on_notify(title, text, level)

    def _describe_action(self) -> str:
        return "showing a desktop notification"
