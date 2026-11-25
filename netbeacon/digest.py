"""The weekly summary: the week, in sentences a business owner actually reads.

Everything is computed from the history database, so it's testable without Qt.
Sentences are deliberately plain: "The internet dropped 4 times, 12 minutes in total." instead of tables of numbers.
The disk forecast uses a simple straight-line trend (linear regression) of the free space the disk check recorded.
"""
from __future__ import annotations

import datetime as dt
import html
import ipaddress
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from .netutil import format_duration
from .store import ST_DOWN, History, Store

DAY = 86400.0


@dataclass
class Digest:
    since: float
    until: float
    headline: str = ""
    mood: str = "ok"                                  # ok | warn | bad
    lines: list[tuple[str, str]] = field(default_factory=list)   # (level, sentence)  level: ok | warn | bad | info

    def text(self) -> str:
        mark = {"ok": "+", "warn": "!", "bad": "!!", "info": "-"}
        out = [f"NetBeacon summary, {_day(self.since)} to {_day(self.until)}", "", self.headline, ""]
        out += [f" {mark[l]} {t}" for l, t in self.lines]
        out += ["", "Sent by NetBeacon. Open the Uptime & history page for the details."]
        return "\n".join(out)

    def html(self) -> str:
        col = {"ok": "#16a34a", "warn": "#d97706", "bad": "#dc2626", "info": "#64748b"}
        head = {"ok": "#16a34a", "warn": "#d97706", "bad": "#dc2626"}[self.mood]
        items = "".join(f"<li style='margin:0 0 10px 0'><span style='color:{col[l]};font-weight:700'>&#9679;</span> {html.escape(t)}</li>"
                        for l, t in self.lines)
        return (f"<div style='font-family:Segoe UI,Arial,sans-serif;max-width:640px;color:#1f2937'>"
                f"<p style='color:#6b7280;margin:0'>NetBeacon summary &middot; {_day(self.since)} to {_day(self.until)}</p>"
                f"<h2 style='color:{head};margin:6px 0 16px 0'>{html.escape(self.headline)}</h2>"
                f"<ul style='list-style:none;padding:0;margin:0;font-size:15px;line-height:1.45'>{items}</ul>"
                f"<p style='color:#6b7280;font-size:12px;margin-top:22px'>Generated {time.strftime('%d %b %Y %H:%M')} by NetBeacon. "
                f"The Uptime &amp; history page has every detail.</p></div>")


def _day(ts: float) -> str:
    return time.strftime("%a %d %b", time.localtime(ts))


def _when(ts: float) -> str:
    return time.strftime("%a %H:%M", time.localtime(ts))


def _mins(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f} seconds"
    if seconds < 3600:
        m = round(seconds / 60)
        return f"{m} minute{'s' if m != 1 else ''}"
    return format_duration(seconds)


def _times(n: int) -> str:
    return "once" if n == 1 else "twice" if n == 2 else f"{n} times"


def _is_public(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local)
    except ValueError:
        return False


def internet_checks(store: Store) -> list[str]:
    """Checks that stand for 'the internet': the Internet group, or pings of public addresses."""
    out = []
    for m in store.monitors:
        if m.group.lower() == "internet" and m.kind in ("ping", "dns", "tcp", "http") and m.name.lower() != "router":
            out.append(m.name)
        elif m.kind == "ping" and _is_public(str(m.params.get("host", ""))):
            out.append(m.name)
    return list(dict.fromkeys(out))


# --------------------------------------------------------------------------- disk forecast
_DISK_RE = re.compile(r"(\d+(?:\.\d+)?)\s*GB free \((\d+)%\)")


def disk_forecast(history: History, monitor: str, min_free_gb: float, min_free_pct: float, now: Optional[float] = None,
                  lookback_days: float = 30) -> Optional[dict]:
    """Straight-line forecast of when a disk check will cross its warning level.

    Returns {'free_gb', 'per_day_gb' (negative = shrinking), 'days_left' (None = not shrinking), 'limit_gb'} or None if not enough data."""
    now = now or time.time()
    pts: list[tuple[float, float, float]] = []
    for r in history.results_for(monitor, now - lookback_days * DAY):
        m = _DISK_RE.search(r["message"] or "")
        if m:
            pts.append((r["ts"], float(m.group(1)), float(m.group(2))))
    if len(pts) < 6 or pts[-1][0] - pts[0][0] < DAY:
        return None
    xs = [(p[0] - pts[0][0]) / DAY for p in pts]
    ys = [p[1] for p in pts]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    free_now, pct_now = pts[-1][1], pts[-1][2]
    total = free_now / (pct_now / 100) if pct_now > 0 else 0.0
    limit = max(min_free_gb or 0.0, total * (min_free_pct or 0.0) / 100)
    days_left = None
    if slope < -0.05:   # shrinking by more than ~50 MB a day
        days_left = max(0.0, (free_now - limit) / -slope)
    return {"free_gb": free_now, "per_day_gb": slope, "days_left": days_left, "limit_gb": limit}


def _weeks(days: float) -> str:
    if days < 1:
        return "within a day"
    if days < 10:
        return f"in about {days:.0f} day{'s' if round(days) != 1 else ''}"
    if days < 60:
        return f"in about {days / 7:.0f} weeks"
    return f"in about {days / 30:.0f} months"


# --------------------------------------------------------------------------- the summary
def build(store: Store, history: History, since: float, until: Optional[float] = None) -> Digest:
    until = until or time.time()
    d = Digest(since, until)
    names = [m.name for m in store.monitors]
    net_names = set(internet_checks(store))

    def incidents_of(name: str) -> list[dict]:
        return [i for i in history.incidents(name, since, 5000) if i["started"] <= until]

    def downtime(name: str) -> float:
        return history.downtime_seconds(name, since, until)

    total_incidents = sum(len(incidents_of(n)) for n in names)
    av = history.availability(None, since)

    # ---- internet
    net_inc: list[dict] = []
    for n in net_names:
        net_inc += incidents_of(n)
    net_inc.sort(key=lambda i: i["started"])
    merged: list[list[float]] = []            # several internet checks failing together = one outage
    for i in net_inc:
        s, e = max(i["started"], since), min(i["ended"] or until, until)
        if merged and s <= merged[-1][1] + 60:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    if net_names:
        if merged:
            total = sum(e - s for s, e in merged)
            longest = max(merged, key=lambda x: x[1] - x[0])
            d.lines.append(("bad" if total > 3600 else "warn",
                            f"The internet dropped {_times(len(merged))}, {_mins(total)} in total "
                            f"(longest: {_mins(longest[1] - longest[0])}, {_when(longest[0])})."))
        else:
            d.lines.append(("ok", "The internet connection didn't drop once."))

    # ---- other outages (backups get their own sentence below)
    kinds = {m.name: m.kind for m in store.monitors}
    still_open = {n: next((i for i in history.incidents(n, since, 50) if i["ended"] is None), None) for n in names}
    others = sorted(((downtime(n), n, len(incidents_of(n))) for n in names if n not in net_names and kinds.get(n) != "file"), reverse=True)
    others = [o for o in others if o[2] > 0]
    shown = 0
    for secs, n, cnt in others:
        if still_open.get(n):
            d.lines.append(("bad", f"{n} has been down since {_when(still_open[n]['started'])} and still is"
                                   + (f" ({_times(cnt)} this period)." if cnt > 1 else ".")))
        elif shown < 3:
            d.lines.append(("bad" if secs > 3600 else "warn", f"{n} was down {_times(cnt)}, {_mins(secs)} in total."))
            shown += 1
    hidden = sum(1 for _s, n, _c in others if not still_open.get(n)) - shown
    if hidden > 0:
        d.lines.append(("info", f"{hidden} other check(s) also had short outages."))
    for n in net_names:
        if still_open.get(n):
            d.lines.append(("bad", f"Still broken right now: {n} (since {_when(still_open[n]['started'])})."))

    # ---- flapping
    for secs, n, cnt in others:
        if cnt >= 4:
            d.lines.append(("warn", f"{n} went down and back up {cnt} times. That on-off pattern ('flapping') usually means a loose cable, "
                                    "weak Wi-Fi or an overloaded device rather than a real outage."))

    # ---- disks
    for m in store.monitors:
        if m.kind != "disk" or not m.enabled:
            continue
        fc = disk_forecast(history, m.name, float(m.params.get("min_free_gb", 0) or 0), float(m.params.get("min_free_percent", 0) or 0), until)
        if not fc:
            continue
        path = m.params.get("path", m.name)
        if fc["days_left"] is not None and fc["days_left"] <= 90:
            lvl = "bad" if fc["days_left"] < 14 else "warn"
            d.lines.append((lvl, f"Drive {path} is filling up: {fc['free_gb']:.0f} GB free, shrinking by about {-fc['per_day_gb']:.1f} GB a day. "
                                 f"It will reach your warning level {_weeks(fc['days_left'])}."))
        else:
            d.lines.append(("ok", f"Drive {path} has room to spare ({fc['free_gb']:.0f} GB free) and isn't filling up quickly."))

    # ---- certificates
    for m in store.monitors:
        if m.kind != "tls" or not m.enabled:
            continue
        last = history.last_result(m.name)
        mm = re.search(r"(\d+)\s+days?", (last["message"] if last else "") or "")
        if mm and int(mm.group(1)) <= 30:
            d.lines.append(("warn" if int(mm.group(1)) > 7 else "bad",
                            f"The certificate for {m.params.get('host', m.name)} expires in {mm.group(1)} days - renew it soon."))

    # ---- backups
    for m in store.monitors:
        if m.kind != "file" or not m.enabled:
            continue
        rows = history.results_for(m.name, since)
        if not rows:
            continue
        bad_days = sorted({time.strftime("%a", time.localtime(r["ts"])) for r in rows if r["status"] == ST_DOWN})
        if bad_days:
            d.lines.append(("bad", f"Backup check '{m.name}' failed on {len(bad_days)} day(s) ({', '.join(bad_days)}). Check your backup software."))
        else:
            d.lines.append(("ok", f"Backup check '{m.name}' passed every time."))

    # ---- speed
    tests = [t for t in history.speedtests(since) if t["down"] is not None and t["ts"] <= until]
    if tests:
        downs = [t["down"] for t in tests]
        ups = [t["up"] for t in tests if t["up"] is not None]
        avg = sum(downs) / len(downs)
        slow = min(tests, key=lambda t: t["down"])
        paid = float(store.get("speed_paid_down", 0) or 0)
        part = f" ({100 * avg / paid:.0f}% of the {paid:g} Mbit/s you pay for)" if paid else ""
        up_part = f" / {sum(ups) / len(ups):.0f} up" if ups else ""
        lvl = "ok" if not paid or avg >= 0.8 * paid else "warn" if avg >= 0.5 * paid else "bad"
        d.lines.append((lvl, f"Internet speed averaged {avg:.0f} Mbit/s down{up_part} over {len(tests)} test(s){part}; "
                             f"slowest {slow['down']:.0f} Mbit/s on {_when(slow['ts'])}."))

    # ---- Wi-Fi
    samples = [s for s in history.wifi_samples(since) if s["signal"] is not None and s["ts"] <= until]
    if len(samples) >= 5:
        from . import wifi
        sig = [s["signal"] for s in samples]
        avg = sum(sig) / len(sig)
        low = min(samples, key=lambda s: s["signal"])
        word, _ = wifi.quality(int(avg))
        lvl = "ok" if avg >= 60 else "warn" if avg >= 40 else "bad"
        d.lines.append((lvl, f"This PC's Wi-Fi signal averaged {avg:.0f}% ({word}); lowest {low['signal']}% on {_when(low['ts'])}."))

    # ---- devices
    new_dev = [e for e in history.events(limit=500, since=since, search="New device") if e["ts"] <= until]
    if new_dev:
        d.lines.append(("warn", f"New devices joined the network on {len(new_dev)} occasion(s) - have a look on the Devices page."))

    # ---- headline
    bad = sum(1 for l, _ in d.lines if l == "bad")
    warn = sum(1 for l, _ in d.lines if l == "warn")
    pct = av["pct"]
    if not names:
        d.headline, d.mood = "Nothing is being monitored yet - add a few checks and next week's summary will have something to say.", "warn"
    elif av["total"] == 0:
        d.headline, d.mood = "No results were recorded in this period - was NetBeacon running?", "warn"
    elif bad:
        d.headline, d.mood = f"A rough week: {total_incidents} outage(s), and {bad} thing(s) need attention.", "bad"
    elif warn:
        d.headline, d.mood = f"A mostly good week: everything worked {pct:.2f}% of the time, with a few things to keep an eye on.", "warn"
    else:
        d.headline, d.mood = f"A good week: everything worked {pct:.2f}% of the time.", "ok"
    if not d.lines:
        d.lines.append(("ok", "Nothing went wrong. Quiet is good!"))
    return d


# --------------------------------------------------------------------------- scheduling
def last_slot(now: float, weekday: int, hour: int) -> float:
    """The most recent moment <= now that matches 'weekday at hour:00' (local time)."""
    t = dt.datetime.fromtimestamp(now)
    slot = t.replace(hour=int(hour) % 24, minute=0, second=0, microsecond=0)
    slot -= dt.timedelta(days=(slot.weekday() - int(weekday)) % 7)
    if slot > t:
        slot -= dt.timedelta(days=7)
    return slot.timestamp()


def is_due(now: float, weekday: int, hour: int, last_sent: float) -> bool:
    return last_sent < last_slot(now, weekday, hour)
