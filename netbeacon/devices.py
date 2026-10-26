"""Merging scan results with the remembered-devices table (no Qt here, so it is testable)."""
from __future__ import annotations

import time
from typing import Optional

from .netutil import Device, normalize_mac
from .store import History


def merge_scan(history: History, scan: list[Device], now: Optional[float] = None) -> tuple[list[dict], list[dict]]:
    """Store what a scan found.

    Returns (rows, newly_discovered): rows = every known device (seen now or not),
    newly_discovered = devices that were never seen before this scan.
    """
    now = now or time.time()
    seen_keys: set[str] = set()
    rows: list[dict] = []
    fresh: list[dict] = []
    for dev in scan:
        mac = normalize_mac(dev.mac) if dev.mac else ""
        row, is_new = history.upsert_device(mac, dev.ip, dev.hostname, now)
        key = row["key"]
        seen_keys.add(key)
        out = {
            "key": key, "ip": dev.ip, "mac": mac, "hostname": row["hostname"] or dev.hostname, "name": row["name"] or "",
            "known": bool(row["known"]), "seen_now": True, "rtt_ms": dev.rtt_ms, "ports": list(dev.open_ports),
            "kind": dev.guess_kind(), "randomized": dev.randomized, "first_seen": row["first_seen"], "last_seen": now,
            "is_gateway": dev.is_gateway, "is_self": dev.is_self, "alive": dev.alive, "notes": row["notes"] or "",
        }
        rows.append(out)
        if is_new:
            fresh.append(out)
    for row in history.devices():
        if row["key"] in seen_keys:
            continue
        rows.append({
            "key": row["key"], "ip": row["ip"] or "", "mac": row["mac"] or "", "hostname": row["hostname"] or "", "name": row["name"] or "",
            "known": bool(row["known"]), "seen_now": False, "rtt_ms": None, "ports": [], "kind": "", "randomized": False,
            "first_seen": row["first_seen"], "last_seen": row["last_seen"], "is_gateway": False, "is_self": False,
            "alive": False, "notes": row["notes"] or "",
        })
    rows.sort(key=lambda r: tuple(int(x) for x in r["ip"].split(".")) if r["ip"].count(".") == 3 else (999,))
    return rows, fresh


def stored_rows(history: History) -> list[dict]:
    """Devices remembered from earlier scans (shown when the page opens)."""
    rows, _ = merge_scan(history, [])
    return rows
