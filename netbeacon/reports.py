"""A shareable, self-contained HTML uptime report (handy evidence for your internet provider)."""
from __future__ import annotations

import html
import time

from . import netutil
from .store import History, Store


def build_report(store: Store, history: History, since: float, until: float, title: str = "Network uptime report") -> str:
    esc = html.escape
    span = until - since
    rows = []
    total_down = 0.0
    for m in store.monitors:
        av = history.availability(m.name, since)
        down = history.downtime_seconds(m.name, since, until)
        inc = history.incidents(m.name, since)
        lat = history.latency_stats(m.name, since)
        total_down += down
        pct = "no data" if av["pct"] is None else f"{av['pct']:.3f}%"
        color = "#16a34a" if (av["pct"] or 0) >= 99.5 else "#f59e0b" if (av["pct"] or 0) >= 95 else "#dc2626"
        if av["pct"] is None:
            color = "#64748b"
        avg_txt = "" if lat["avg"] is None else "%.0f ms" % lat["avg"]
        rows.append(f"<tr><td>{esc(m.name)}</td><td>{esc(m.group)}</td><td style='color:{color};font-weight:600'>{pct}</td>"
                    f"<td>{esc(netutil.format_duration(down)) if down else 'none'}</td><td>{len(inc)}</td>"
                    f"<td>{avg_txt}</td></tr>")
    incs = history.incidents(None, since, 1000)
    inc_rows = []
    for i in incs:
        end = i["ended"]
        lasted = (end or until) - i["started"]
        inc_rows.append(f"<tr><td>{esc(i['monitor'])}</td><td>{time.strftime('%Y-%m-%d %H:%M', time.localtime(i['started']))}</td>"
                        f"<td>{time.strftime('%Y-%m-%d %H:%M', time.localtime(end)) if end else 'ongoing'}</td>"
                        f"<td>{esc(netutil.format_duration(lasted))}</td><td>{esc(i['reason'] or '')}</td></tr>")
    when = f"{time.strftime('%d %b %Y %H:%M', time.localtime(since))} to {time.strftime('%d %b %Y %H:%M', time.localtime(until))}"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{esc(title)}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:32px;color:#1f2937}}h1{{margin-bottom:0}}.muted{{color:#6b7280}}
table{{border-collapse:collapse;width:100%;margin:12px 0 28px}}th{{text-align:left;background:#f1f5f9;padding:8px}}td{{padding:8px;border-bottom:1px solid #e5e7eb}}</style></head>
<body><h1>{esc(title)}</h1><p class="muted">Period: {when} ({esc(netutil.format_duration(span))}). Generated {time.strftime('%d %b %Y %H:%M')} by NetBeacon.</p>
<h2>Availability per check</h2>
<table><tr><th>Check</th><th>Group</th><th>Availability</th><th>Downtime</th><th>Incidents</th><th>Avg response</th></tr>{''.join(rows)}</table>
<h2>Incidents</h2>
<table><tr><th>Check</th><th>Started</th><th>Ended</th><th>Lasted</th><th>What went wrong</th></tr>{''.join(inc_rows) or '<tr><td colspan=5>No incidents in this period.</td></tr>'}</table>
<p class="muted">Availability = share of checks that succeeded; brief failures inside a check's tolerance count as up. Incident times start at the first failed check.</p>
</body></html>"""
