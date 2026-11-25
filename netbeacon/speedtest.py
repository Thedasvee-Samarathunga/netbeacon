"""Internet speed test: latency, download and upload.

How it measures (the same idea as most web speed tests):
  * latency - opens a few TCP connections to the test server and times the handshake; jitter is how much that varies.
  * download - fetches N bytes from <server>/__down?bytes=N over a few parallel connections and divides bits by seconds.
  * upload   - sends N bytes to <server>/__up the same way.

The default server is Cloudflare's public speed-test service. Any server that answers those two
addresses works, so you can point it at your own. Data use is capped per test (Settings on the Internet speed page).

Honest limits: a test from one PC measures *that PC's* path. Wi-Fi, a busy network or a slow PC lower the result,
so for ISP evidence use a PC on a cable and look at the trend, not a single test.
"""
from __future__ import annotations

import statistics
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse

from . import netutil

DEFAULT_SERVER = "https://speed.cloudflare.com"
CHUNK = 64 * 1024
MAX_SECONDS = 12.0          # a phase stops after this long even if the data cap isn't reached


@dataclass
class SpeedResult:
    ts: float
    server: str
    down_mbps: Optional[float] = None
    up_mbps: Optional[float] = None
    latency_ms: Optional[float] = None
    jitter_ms: Optional[float] = None
    bytes_down: int = 0
    bytes_up: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.down_mbps is not None and not self.error


def _host_port(server: str) -> tuple[str, int]:
    u = urlparse(server)
    port = u.port or (443 if u.scheme == "https" else 80)
    return u.hostname or "", port


def measure_latency(server: str, samples: int = 6, tcp: Callable = netutil.tcp_connect) -> tuple[Optional[float], Optional[float]]:
    host, port = _host_port(server)
    times: list[float] = []
    for i in range(samples):
        ok, ms, _ = tcp(host, port, 3.0)
        if ok and i > 0:                  # the first one also pays for the DNS lookup - ignore it
            times.append(ms)
    if not times:
        return None, None
    jitter = statistics.mean(abs(a - b) for a, b in zip(times, times[1:])) if len(times) > 1 else 0.0
    return statistics.median(times), jitter


def _parallel(n: int, fn: Callable[[int], int], cancel: threading.Event) -> tuple[int, float, list[str]]:
    total = [0] * n
    errors: list[str] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            total[i] = fn(i)
        except Exception as exc:  # noqa: BLE001
            with lock:
                errors.append(f"{type(exc).__name__}: {str(exc)[:140]}")

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(MAX_SECONDS + 20)
    return sum(total), time.perf_counter() - t0, errors


def run(server: str = DEFAULT_SERVER, max_down_mb: float = 25, max_up_mb: float = 10, streams: int = 3,
        progress: Optional[Callable[[str], None]] = None, cancel: Optional[threading.Event] = None,
        timeout_s: float = 20.0) -> SpeedResult:
    import requests

    server = (server or DEFAULT_SERVER).rstrip("/")
    cancel = cancel or threading.Event()
    res = SpeedResult(ts=time.time(), server=server)
    say = progress or (lambda _t: None)
    session_headers = {"User-Agent": "NetBeacon/1.1 speed test"}

    say("Measuring latency...")
    res.latency_ms, res.jitter_ms = measure_latency(server)
    if res.latency_ms is None:
        res.error = f"could not connect to the test server {server}"
        return res
    if cancel.is_set():
        res.error = "cancelled"
        return res

    # ---- download
    say("Measuring download speed...")
    per = max(1, int(max_down_mb * 1024 * 1024 / streams))
    deadline = time.perf_counter() + MAX_SECONDS

    def down(_i: int) -> int:
        got = 0
        with requests.get(f"{server}/__down", params={"bytes": per}, stream=True, timeout=timeout_s, headers=session_headers) as r:
            r.raise_for_status()
            for chunk in r.iter_content(CHUNK):
                got += len(chunk)
                if cancel.is_set() or time.perf_counter() > deadline:
                    break
        return got

    got, secs, errors = _parallel(streams, down, cancel)
    if errors and got == 0:
        res.error = "download failed: " + errors[0]
        return res
    res.bytes_down = got
    res.down_mbps = round(got * 8 / max(secs, 1e-6) / 1e6, 2)
    if cancel.is_set():
        res.error = "cancelled"
        return res

    # ---- upload
    say("Measuring upload speed...")
    per_up = max(1, int(max_up_mb * 1024 * 1024 / streams))
    payload = (b"NetBeacon-speed-test-" * (per_up // 21 + 1))[:per_up]

    def up(_i: int) -> int:
        r = requests.post(f"{server}/__up", data=payload, timeout=timeout_s + MAX_SECONDS,
                          headers={**session_headers, "Content-Type": "application/octet-stream"})
        r.raise_for_status()
        return len(payload)

    sent, secs, errors = _parallel(streams, up, cancel)
    if errors and sent == 0:
        res.error = "upload failed: " + errors[0]       # download result is still kept
    res.bytes_up = sent
    if sent:
        res.up_mbps = round(sent * 8 / max(secs, 1e-6) / 1e6, 2)
    say("Done")
    return res


def verdict(down: Optional[float], paid: float) -> tuple[str, str]:
    """(sentence, colour) comparing a result with what the plan promises."""
    if down is None:
        return "no result", "#64748b"
    if not paid:
        return f"{down:.0f} Mbit/s", "#2563eb"
    pct = 100 * down / paid
    if pct >= 80:
        return f"{pct:.0f}% of the {paid:g} Mbit/s you pay for - good", "#16a34a"
    if pct >= 50:
        return f"{pct:.0f}% of the {paid:g} Mbit/s you pay for - below par", "#f59e0b"
    return f"only {pct:.0f}% of the {paid:g} Mbit/s you pay for", "#dc2626"
