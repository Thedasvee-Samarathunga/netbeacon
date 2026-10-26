"""Persistence: settings, monitor definitions (JSON) and history (SQLite)."""
from __future__ import annotations

import copy
import csv
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from . import paths

# status codes stored in the history table
ST_UP, ST_DOWN, ST_SKIPPED, ST_RETRY = 0, 1, 2, 3

DEFAULT_SETTINGS: dict[str, Any] = {
    "interval": 30,                 # seconds between rounds of checks
    "retention_days": 30,
    "theme": "light",               # light | dark
    "teaching_mode": True,          # show explanations everywhere
    "minimize_to_tray": True,
    "start_with_windows": False,
    "start_minimized": False,
    "first_run_done": False,
    "paused": False,
    "status_page_enabled": False,
    "status_page_folder": "",
    "status_page_title": "Network status",
    "scan_watch_enabled": False,
    "scan_watch_minutes": 60,
    "scan_cidr": "",
    "devices_baseline_done": False,
    "channels": {
        "desktop": {"enabled": True},
        "email": {"enabled": False, "host": "", "port": 587, "ssl": "starttls", "username": "", "password": "", "from": "", "to": ""},
        "slack": {"enabled": False, "url": ""},
        "telegram": {"enabled": False, "token": "", "chat_id": ""},
        "ntfy": {"enabled": False, "server": "https://ntfy.sh", "topic": "", "token": ""},
        "pushover": {"enabled": False, "token": "", "user": ""},
    },
    "alert_rules": {
        "limit": 1,                  # failed checks (after tolerance) before alerting
        "repeat": False,             # keep alerting while still down
        "recovery": True,            # tell me when it's back
        "quiet_enabled": False,
        "quiet_from": "22:00",
        "quiet_to": "07:00",
        "weekdays_only": False,
    },
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


_NAME_BAD = re.compile(r"[\[\]\r\n\t%,]")


def clean_name(name: str) -> str:
    """SimpleMonitor uses names as INI section headers, so keep them tame."""
    return re.sub(r"\s+", " ", _NAME_BAD.sub(" ", name)).strip()


@dataclass
class MonitorDef:
    id: str
    name: str
    kind: str                                   # key in checks.CHECKS
    params: dict = field(default_factory=dict)
    enabled: bool = True
    group: str = "General"
    interval: int = 0                           # seconds between checks of this monitor (0 = every round)
    tolerance: int = 0                          # extra failed checks before it's called DOWN
    depends: list[str] = field(default_factory=list)   # ids of monitors this one depends on
    urgent: bool = True
    notify: bool = True
    remind: int = 0                             # minutes between reminders while down (0 = never)
    failure_doc: str = ""                       # "what to do when this fails"
    recover_command: str = ""
    created: float = field(default_factory=time.time)

    @staticmethod
    def new(kind: str, name: str, params: dict) -> "MonitorDef":
        return MonitorDef(id=uuid.uuid4().hex[:10], name=clean_name(name), kind=kind, params=dict(params))


class Store:
    """Settings + monitor list, saved as JSON next to the history database."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.settings: dict[str, Any] = copy.deepcopy(DEFAULT_SETTINGS)
        self.monitors: list[MonitorDef] = []
        self.load()

    # ----- load/save
    def load(self) -> None:
        with self._lock:
            sf, mf = paths.settings_file(), paths.monitors_file()
            if sf.exists():
                try:
                    self.settings = _deep_merge(DEFAULT_SETTINGS, json.loads(sf.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    self._quarantine(sf)
            if mf.exists():
                try:
                    raw = json.loads(mf.read_text(encoding="utf-8"))
                    known = set(MonitorDef.__dataclass_fields__)
                    self.monitors = [MonitorDef(**{k: v for k, v in item.items() if k in known}) for item in raw]
                except (OSError, ValueError, TypeError):
                    self._quarantine(mf)

    @staticmethod
    def _quarantine(path: Path) -> None:
        try:
            path.replace(path.with_suffix(path.suffix + f".broken-{int(time.time())}"))
        except OSError:
            pass

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def save(self) -> None:
        with self._lock:
            self._atomic_write(paths.settings_file(), json.dumps(self.settings, indent=2))
            self._atomic_write(paths.monitors_file(), json.dumps([asdict(m) for m in self.monitors], indent=2))

    # ----- settings helpers
    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any, save: bool = True) -> None:
        with self._lock:
            self.settings[key] = value
            if save:
                self.save()

    # ----- monitors
    def by_id(self, mid: str) -> Optional[MonitorDef]:
        return next((m for m in self.monitors if m.id == mid), None)

    def by_name(self, name: str) -> Optional[MonitorDef]:
        return next((m for m in self.monitors if m.name.lower() == name.lower()), None)

    def unique_name(self, wanted: str, ignore_id: str = "") -> str:
        base = clean_name(wanted) or "Monitor"
        taken = {m.name.lower() for m in self.monitors if m.id != ignore_id}
        name, n = base, 2
        while name.lower() in taken:
            name = f"{base} ({n})"
            n += 1
        return name

    def add(self, m: MonitorDef) -> MonitorDef:
        with self._lock:
            m.name = self.unique_name(m.name)
            self.monitors.append(m)
            self.save()
        return m

    def update(self, m: MonitorDef) -> None:
        with self._lock:
            for i, old in enumerate(self.monitors):
                if old.id == m.id:
                    m.name = self.unique_name(m.name, ignore_id=m.id)
                    self.monitors[i] = m
                    break
            self.save()

    def remove(self, mid: str) -> None:
        with self._lock:
            self.monitors = [m for m in self.monitors if m.id != mid]
            for m in self.monitors:
                if mid in m.depends:
                    m.depends.remove(mid)
                if m.kind == "compound":
                    names = {x.id: x.name for x in self.monitors}
                    ids = [i for i in str(m.params.get("monitors", "")).split(",") if i and i != mid]
                    m.params["monitors"] = ",".join(i for i in ids if i in names)
            self.save()

    def would_cycle(self, mid: str, depends: Iterable[str]) -> bool:
        """True if making `mid` depend on `depends` would create a loop."""
        graph = {m.id: list(m.depends) for m in self.monitors}
        graph[mid] = list(depends)
        seen: set[str] = set()

        def visit(node: str, stack: set[str]) -> bool:
            if node in stack:
                return True
            if node in seen:
                return False
            seen.add(node)
            return any(visit(n, stack | {node}) for n in graph.get(node, []))

        return visit(mid, set())

    def groups(self) -> list[str]:
        return sorted({m.group for m in self.monitors if m.group}, key=str.lower)


# =========================================================================== history
class History:
    """SQLite database of results, incidents, events and known devices."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or paths.history_file()
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        with self._lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS results(
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, monitor TEXT NOT NULL,
                status INTEGER NOT NULL, latency REAL, message TEXT);
            CREATE INDEX IF NOT EXISTS idx_results_m_ts ON results(monitor, ts);
            CREATE INDEX IF NOT EXISTS idx_results_ts ON results(ts);
            CREATE TABLE IF NOT EXISTS incidents(
                id INTEGER PRIMARY KEY AUTOINCREMENT, monitor TEXT NOT NULL, started REAL NOT NULL,
                ended REAL, reason TEXT, interrupted INTEGER DEFAULT 0);
            CREATE INDEX IF NOT EXISTS idx_inc_m ON incidents(monitor, started);
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, level TEXT NOT NULL,
                monitor TEXT, text TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
            CREATE TABLE IF NOT EXISTS devices(
                key TEXT PRIMARY KEY, mac TEXT, ip TEXT, hostname TEXT, name TEXT, notes TEXT,
                first_seen REAL, last_seen REAL, known INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
            """)

    def close(self) -> None:
        with self._lock:
            try:
                self.db.close()
            except sqlite3.Error:
                pass

    def _x(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.db.execute(sql, args)

    def _all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.db.execute(sql, args).fetchall()

    # ----- meta
    def meta_get(self, key: str, default: str = "") -> str:
        rows = self._all("SELECT value FROM meta WHERE key=?", (key,))
        return rows[0]["value"] if rows else default

    def meta_set(self, key: str, value: str) -> None:
        self._x("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    # ----- results
    def add_result(self, ts: float, monitor: str, status: int, latency: Optional[float], message: str) -> None:
        self._x("INSERT INTO results(ts,monitor,status,latency,message) VALUES(?,?,?,?,?)",
                (ts, monitor, status, latency, (message or "")[:500]))

    def recent_statuses(self, monitor: str, n: int = 40) -> list[int]:
        rows = self._all("SELECT status FROM results WHERE monitor=? ORDER BY ts DESC LIMIT ?", (monitor, n))
        return [r["status"] for r in reversed(rows)]

    def availability(self, monitor: Optional[str], since: float) -> dict:
        """Check-based availability: (up + retry) / (up + retry + down)."""
        q = "SELECT status, COUNT(*) c FROM results WHERE ts>=? AND status IN (0,1,3)"
        args: list[Any] = [since]
        if monitor:
            q += " AND monitor=?"
            args.append(monitor)
        q += " GROUP BY status"
        counts = {r["status"]: r["c"] for r in self._all(q, tuple(args))}
        up, retry, down = counts.get(ST_UP, 0), counts.get(ST_RETRY, 0), counts.get(ST_DOWN, 0)
        total = up + retry + down
        pct = None if total == 0 else 100.0 * (up + retry) / total
        return {"total": total, "up": up, "retry": retry, "down": down, "pct": pct}

    def latency_stats(self, monitor: Optional[str], since: float) -> dict:
        q = "SELECT AVG(latency) a, MIN(latency) mn, MAX(latency) mx, COUNT(latency) c FROM results WHERE ts>=? AND latency IS NOT NULL"
        args: list[Any] = [since]
        if monitor:
            q += " AND monitor=?"
            args.append(monitor)
        r = self._all(q, tuple(args))[0]
        return {"avg": r["a"], "min": r["mn"], "max": r["mx"], "count": r["c"]}

    def series(self, monitor: str, since: float, until: Optional[float] = None, buckets: int = 120) -> list[dict]:
        """Bucketed history for charts: [{'ts', 'avg', 'max', 'fails', 'n'}]"""
        until = until or time.time()
        span = max(until - since, 1.0)
        width = span / buckets
        rows = self._all("SELECT ts, status, latency FROM results WHERE monitor=? AND ts>=? AND ts<=? ORDER BY ts",
                         (monitor, since, until))
        out: dict[int, dict] = {}
        for r in rows:
            i = min(int((r["ts"] - since) / width), buckets - 1)
            b = out.setdefault(i, {"ts": since + (i + 0.5) * width, "sum": 0.0, "n_lat": 0, "max": None, "fails": 0, "n": 0})
            b["n"] += 1
            if r["status"] == ST_DOWN:
                b["fails"] += 1
            if r["latency"] is not None:
                b["sum"] += r["latency"]
                b["n_lat"] += 1
                b["max"] = r["latency"] if b["max"] is None else max(b["max"], r["latency"])
        return [{"ts": b["ts"], "avg": (b["sum"] / b["n_lat"]) if b["n_lat"] else None, "max": b["max"],
                 "fails": b["fails"], "n": b["n"]} for _, b in sorted(out.items())]

    def last_result(self, monitor: str) -> Optional[sqlite3.Row]:
        rows = self._all("SELECT * FROM results WHERE monitor=? ORDER BY ts DESC LIMIT 1", (monitor,))
        return rows[0] if rows else None

    # ----- incidents
    def open_incident(self, monitor: str, started: float, reason: str) -> int:
        cur = self._x("INSERT INTO incidents(monitor,started,reason) VALUES(?,?,?)", (monitor, started, (reason or "")[:500]))
        return int(cur.lastrowid or 0)

    def update_incident_reason(self, monitor: str, reason: str) -> None:
        self._x("UPDATE incidents SET reason=? WHERE monitor=? AND ended IS NULL", ((reason or "")[:500], monitor))

    def close_incident(self, monitor: str, ended: float, interrupted: bool = False) -> Optional[float]:
        rows = self._all("SELECT id, started FROM incidents WHERE monitor=? AND ended IS NULL ORDER BY started DESC LIMIT 1", (monitor,))
        if not rows:
            return None
        self._x("UPDATE incidents SET ended=?, interrupted=? WHERE id=?", (ended, 1 if interrupted else 0, rows[0]["id"]))
        return max(0.0, ended - rows[0]["started"])

    def has_open_incident(self, monitor: str) -> bool:
        return bool(self._all("SELECT 1 FROM incidents WHERE monitor=? AND ended IS NULL LIMIT 1", (monitor,)))

    def close_stale_incidents(self, last_seen: float) -> int:
        """Called at start-up: incidents left open when the app was closed are ended at the last moment we were watching."""
        cur = self._x("UPDATE incidents SET ended=MAX(started, ?), interrupted=1 WHERE ended IS NULL", (last_seen,))
        return cur.rowcount

    def incidents(self, monitor: Optional[str] = None, since: float = 0, limit: int = 500) -> list[dict]:
        q = "SELECT * FROM incidents WHERE (ended IS NULL OR ended>=?)"
        args: list[Any] = [since]
        if monitor:
            q += " AND monitor=?"
            args.append(monitor)
        q += " ORDER BY started DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self._all(q, tuple(args))]

    def downtime_seconds(self, monitor: Optional[str], since: float, until: Optional[float] = None) -> float:
        until = until or time.time()
        total = 0.0
        for inc in self.incidents(monitor, since, 5000):
            s = max(inc["started"], since)
            e = min(inc["ended"] or until, until)
            if e > s:
                total += e - s
        return total

    # ----- events
    def add_event(self, ts: float, level: str, monitor: Optional[str], text: str) -> None:
        self._x("INSERT INTO events(ts,level,monitor,text) VALUES(?,?,?,?)", (ts, level, monitor, text[:800]))

    def events(self, limit: int = 500, since: float = 0, levels: Optional[Iterable[str]] = None, search: str = "") -> list[dict]:
        q = "SELECT * FROM events WHERE ts>=?"
        args: list[Any] = [since]
        lv = list(levels) if levels else []
        if lv:
            q += f" AND level IN ({','.join('?' * len(lv))})"
            args.extend(lv)
        if search:
            q += " AND (text LIKE ? OR monitor LIKE ?)"
            args.extend([f"%{search}%", f"%{search}%"])
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self._all(q, tuple(args))]

    # ----- housekeeping
    def purge(self, retention_days: int) -> None:
        cutoff = time.time() - retention_days * 86400
        self._x("DELETE FROM results WHERE ts<?", (cutoff,))
        self._x("DELETE FROM events WHERE ts<?", (cutoff,))
        self._x("DELETE FROM incidents WHERE ended IS NOT NULL AND ended<?", (cutoff,))

    def rename_monitor(self, old: str, new: str) -> None:
        for table in ("results", "incidents", "events"):
            self._x(f"UPDATE {table} SET monitor=? WHERE monitor=?", (new, old))

    def delete_monitor_data(self, monitor: str) -> None:
        for table in ("results", "incidents", "events"):
            self._x(f"DELETE FROM {table} WHERE monitor=?", (monitor,))

    def clear_all(self) -> None:
        for table in ("results", "incidents", "events"):
            self._x(f"DELETE FROM {table}")

    def export_csv(self, path: str, monitor: Optional[str], since: float) -> int:
        q = "SELECT ts, monitor, status, latency, message FROM results WHERE ts>=?"
        args: list[Any] = [since]
        if monitor:
            q += " AND monitor=?"
            args.append(monitor)
        q += " ORDER BY ts"
        names = {ST_UP: "up", ST_DOWN: "down", ST_SKIPPED: "skipped", ST_RETRY: "retrying"}
        n = 0
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["time", "check", "status", "response_ms", "message"])
            for r in self._all(q, tuple(args)):
                w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"])), r["monitor"], names.get(r["status"], r["status"]),
                            "" if r["latency"] is None else f"{r['latency']:.1f}", r["message"]])
                n += 1
        return n

    # ----- devices
    @staticmethod
    def device_key(mac: str, ip: str) -> str:
        return mac.upper() if mac else f"ip:{ip}"

    def upsert_device(self, mac: str, ip: str, hostname: str, now: float, known: Optional[bool] = None) -> tuple[dict, bool]:
        """Returns (row, is_new)."""
        key = self.device_key(mac, ip)
        rows = self._all("SELECT * FROM devices WHERE key=?", (key,))
        if rows:
            self._x("UPDATE devices SET ip=?, hostname=COALESCE(NULLIF(?,''),hostname), last_seen=? WHERE key=?", (ip, hostname, now, key))
            if known is not None:
                self._x("UPDATE devices SET known=? WHERE key=?", (1 if known else 0, key))
            return dict(self._all("SELECT * FROM devices WHERE key=?", (key,))[0]), False
        self._x("INSERT INTO devices(key,mac,ip,hostname,name,notes,first_seen,last_seen,known) VALUES(?,?,?,?,?,?,?,?,?)",
                (key, mac.upper(), ip, hostname, "", "", now, now, 1 if known else 0))
        return dict(self._all("SELECT * FROM devices WHERE key=?", (key,))[0]), True

    def devices(self) -> list[dict]:
        return [dict(r) for r in self._all("SELECT * FROM devices")]

    def set_device(self, key: str, **fields: Any) -> None:
        allowed = {"name", "notes", "known"}
        for k, v in fields.items():
            if k in allowed:
                self._x(f"UPDATE devices SET {k}=? WHERE key=?", (v, key))

    def forget_device(self, key: str) -> None:
        self._x("DELETE FROM devices WHERE key=?", (key,))

    def mark_all_known(self) -> None:
        self._x("UPDATE devices SET known=1")
