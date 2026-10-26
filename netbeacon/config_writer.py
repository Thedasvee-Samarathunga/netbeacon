"""Turns NetBeacon's friendly settings into SimpleMonitor's two INI files.

SimpleMonitor is configured with:
  * monitor.ini   - global settings, which loggers/alerters to use, and their options
  * monitors.ini  - one [section] per check

NetBeacon writes both files every time something changes (see Activity > Config files to read them).
Every check and alert channel is test-constructed first, so one broken entry can never stop
the others from running.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import compat  # noqa: F401
from . import paths
from .checks import CHECKS
from .store import MonitorDef, Store

from simplemonitor.Alerters.alerter import get_class as get_alerter_class
from simplemonitor.Monitors.monitor import get_class as get_monitor_class
from . import sm_ext  # noqa: F401  (registers our custom types)


def _esc(value: object) -> str:
    """ConfigParser treats % specially; also keep each value on a single line."""
    return str(value).replace("%", "%%").replace("\r", " ").replace("\n", " ")


def _slug(group: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", group.strip()).strip("-") or "default"


@dataclass
class BuildResult:
    monitor_ini: Path
    monitors_ini: Path
    problems: list[str] = field(default_factory=list)
    active: list[str] = field(default_factory=list)      # names of monitors that were written
    types: dict[str, str] = field(default_factory=dict)  # name -> simplemonitor type
    alerters: list[str] = field(default_factory=list)
    loggers: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- per-monitor section
def common_options(m: MonitorDef, id_to_name: dict[str, str], kind_key: str) -> dict[str, str]:
    o: dict[str, str] = {"group": _slug(m.group)}
    if m.interval and m.interval > 0:
        o["gap"] = str(int(m.interval))
    elif kind_key == "tls":
        o["gap"] = "3600"
    if m.tolerance:
        o["tolerance"] = str(int(m.tolerance))
    deps = [id_to_name[d] for d in m.depends if d in id_to_name]
    if deps:
        o["depend"] = ",".join(deps)
    o["urgent"] = "1" if m.urgent else "0"
    o["notify"] = "1" if m.notify else "0"
    if m.remind:
        o["remind"] = str(int(m.remind))
    if m.failure_doc.strip():
        o["failure_doc"] = m.failure_doc.strip()
    if m.recover_command.strip():
        o["recover_command"] = m.recover_command.strip()
    return o


def monitor_options(m: MonitorDef, id_to_name: dict[str, str]) -> tuple[str, dict[str, str]]:
    """(simplemonitor type, full option dict) for one monitor definition."""
    ct = CHECKS[m.kind]
    opts = dict(ct.options(m.params))
    if m.kind == "compound":
        names = [id_to_name[i] for i in str(m.params.get("monitors", "")).split(",") if i in id_to_name]
        opts["monitors"] = ",".join(names)
        opts["min_fail"] = str(min(int(float(m.params.get("min_fail", 2))), max(1, len(names))))
    full = {"type": ct.sm_type}
    full.update(opts)
    full.update(common_options(m, id_to_name, m.kind))
    return ct.sm_type, full


def ini_section_text(name: str, options: dict[str, str], *, escape: bool = True) -> str:
    lines = [f"[{name}]"]
    for k, v in options.items():
        if v is None or v == "":
            continue
        lines.append(f"{k}={_esc(v) if escape else v}")
    return "\n".join(lines)


def preview_section(m: MonitorDef, store: Store) -> str:
    """The exact text NetBeacon would write for this check (used by the 'under the hood' view)."""
    id_to_name = {x.id: x.name for x in store.monitors}
    id_to_name.setdefault(m.id, m.name)
    try:
        _, opts = monitor_options(m, id_to_name)
    except Exception as exc:  # pragma: no cover - only for broken forms
        return f"; cannot build yet: {exc}"
    return ini_section_text(m.name, opts, escape=False)


# --------------------------------------------------------------------------- alert channels
def alerter_sections(store: Store) -> dict[str, dict[str, str]]:
    """name -> options for every enabled channel (not yet validated)."""
    ch = store.get("channels", {})
    rules = store.get("alert_rules", {})
    common: dict[str, str] = {"groups": "_all", "limit": str(max(1, int(rules.get("limit", 1))))}
    if rules.get("repeat"):
        common["repeat"] = "1"
    if not rules.get("recovery", True):
        common["only_failures"] = "1"
    if rules.get("quiet_enabled"):
        qf, qt = rules.get("quiet_from", "22:00"), rules.get("quiet_to", "07:00")
        if qf != qt:
            if qf < qt:   # e.g. 12:00-14:00 -> don't alert inside the window
                common.update({"times_type": "not", "time_lower": qf, "time_upper": qt})
            else:         # crosses midnight, e.g. 22:00-07:00 -> only alert in 07:00-22:00
                common.update({"times_type": "only", "time_lower": qt, "time_upper": qf})
            common["delay"] = "1"          # send "failed earlier" alerts when quiet hours end
            common["ooh_recovery"] = "1"
    if rules.get("weekdays_only"):
        common["days"] = "0,1,2,3,4"

    out: dict[str, dict[str, str]] = {}
    d = ch.get("desktop", {})
    if d.get("enabled"):
        out["desktop"] = {"type": "netbeacon_desktop", **common}
    e = ch.get("email", {})
    if e.get("enabled"):
        to = str(e.get("to", "")).replace(",", ";").replace(" ", "")
        o = {"type": "email", "host": e.get("host", ""), "port": str(e.get("port", 587)), "from": e.get("from", ""), "to": to,
             "username": e.get("username", ""), "password": e.get("password", ""), "ssl": e.get("ssl", "")}
        out["email"] = {**o, **common}
    s = ch.get("slack", {})
    if s.get("enabled"):
        out["slack"] = {"type": "slack", "url": s.get("url", ""), **common}
    t = ch.get("telegram", {})
    if t.get("enabled"):
        out["telegram"] = {"type": "telegram", "token": t.get("token", ""), "chat_id": t.get("chat_id", ""), **common}
    n = ch.get("ntfy", {})
    if n.get("enabled"):
        out["ntfy"] = {"type": "ntfy", "server": n.get("server", "https://ntfy.sh"), "topic": n.get("topic", ""),
                       "token": n.get("token", ""), **common}
    p = ch.get("pushover", {})
    if p.get("enabled"):
        out["pushover"] = {"type": "pushover", "token": p.get("token", ""), "user": p.get("user", ""), **common}
    return {k: {kk: vv for kk, vv in v.items() if vv not in ("", None)} for k, v in out.items()}


def validate_alerter(name: str, options: dict[str, str]) -> Optional[str]:
    """None if OK, otherwise a human-readable problem."""
    try:
        cls = get_alerter_class(options["type"])
        cls({**options, "name": name})
    except Exception as exc:
        return f"Alert channel '{name}': {exc}"
    return None


# --------------------------------------------------------------------------- the main build
def build(store: Store, directory: Optional[Path] = None) -> BuildResult:
    directory = directory or paths.config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    monitor_ini, monitors_ini = directory / "monitor.ini", directory / "monitors.ini"
    result = BuildResult(monitor_ini, monitors_ini)

    enabled = [m for m in store.monitors if m.enabled and m.kind in CHECKS]
    id_to_name = {m.id: m.name for m in store.monitors}

    # pass 1: which monitors are individually valid?
    good: dict[str, tuple[str, dict[str, str]]] = {}
    for m in enabled:
        problems = CHECKS[m.kind].validate(m.params)
        if problems:
            result.problems.append(f"Check '{m.name}': {problems[0]}")
            continue
        try:
            typ, opts = monitor_options(m, id_to_name)
            if m.kind != "compound":
                get_monitor_class(typ)(m.name, dict(opts))
        except Exception as exc:
            result.problems.append(f"Check '{m.name}' has a configuration problem: {exc}")
            continue
        good[m.id] = (typ, opts)

    # pass 2: drop references to checks that are missing/disabled/broken
    active_ids = set(good)
    for m in enabled:
        if m.id not in good:
            continue
        typ, opts = good[m.id]
        if "depend" in opts:
            kept = [id_to_name[d] for d in m.depends if d in active_ids and d != m.id]
            dropped = [id_to_name[d] for d in m.depends if d in id_to_name and d not in active_ids]
            if dropped:
                result.problems.append(f"Check '{m.name}' depends on {', '.join(dropped)}, which is switched off or broken - ignoring that dependency.")
            if kept:
                opts["depend"] = ",".join(kept)
            else:
                opts.pop("depend", None)
        if m.kind == "compound":
            ids = [i for i in str(m.params.get("monitors", "")).split(",") if i]
            names = [id_to_name[i] for i in ids if i in active_ids and i != m.id]
            if len(names) < len(ids) or not names:
                result.problems.append(f"Combined check '{m.name}' refers to a check that is switched off or missing.")
            if not names:
                del good[m.id]
                continue
            opts["monitors"] = ",".join(names)
            opts["min_fail"] = str(min(int(opts.get("min_fail", "2")), len(names)))

    # write monitors.ini
    chunks = ["; Generated by NetBeacon - edits will be overwritten.\n"]
    for m in enabled:
        if m.id not in good:
            continue
        typ, opts = good[m.id]
        chunks.append(ini_section_text(m.name, opts))
        result.active.append(m.name)
        result.types[m.name] = typ
    monitors_ini.write_text("\n\n".join(chunks) + "\n", encoding="utf-8")

    # alerters
    alerters: dict[str, dict[str, str]] = {}
    for name, opts in alerter_sections(store).items():
        problem = validate_alerter(name, opts)
        if problem:
            result.problems.append(problem)
        else:
            alerters[name] = opts
    result.alerters = list(alerters)

    # loggers
    loggers: dict[str, dict[str, str]] = {"netbeacon_gui": {"type": "netbeacon_gui", "groups": "_all"}}
    if store.get("status_page_enabled"):
        folder = str(store.get("status_page_folder") or paths.status_page_dir())
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
            loggers["status_page"] = {"type": "html", "folder": folder, "filename": "index.html", "groups": "_all",
                                      "navbar_title": str(store.get("status_page_title") or "Network status"), "copy_resources": "1"}
        except OSError as exc:
            result.problems.append(f"Status page folder is not usable: {exc}")
    result.loggers = list(loggers)

    interval = max(5, int(store.get("interval", 30)))
    lines = ["; Generated by NetBeacon - edits will be overwritten.", "[monitor]", f"interval={interval}",
             f"monitors={_esc(monitors_ini)}", "", "[reporting]",
             f"loggers={','.join(loggers)}", f"alerters={','.join(alerters)}", ""]
    for name, opts in {**loggers, **alerters}.items():
        lines.append(ini_section_text(name, opts))
        lines.append("")
    monitor_ini.write_text("\n".join(lines), encoding="utf-8")
    return result


# --------------------------------------------------------------------------- export for stock SimpleMonitor
README = """\
NetBeacon -> SimpleMonitor export
=================================
Created {when} by NetBeacon {version}.

These two files work with the stock SimpleMonitor project (no NetBeacon needed):

    pip install simplemonitor
    simplemonitor -f monitor.ini        (run it in this folder)
    simplemonitor -f monitor.ini -t     (just test the configuration)

Docs: https://simplemonitor.readthedocs.io/

Things to know
--------------
* Checks that have no stock equivalent (CPU load, wildcard file checks...) are included as
  commented-out lines starting with ';'.
* The stock 'dns' monitor needs the 'dig' tool installed; the stock 'host' (ping) monitor reads
  English-language ping output and does not record response times.
* Alert channels that need a password were exported as-is: protect these files accordingly.
* SimpleMonitor writes results to simplemonitor.log and a web page in the html/ folder; you can
  serve that folder with any web server.
"""


def export_standalone(store: Store, folder: Path) -> list[str]:
    """Write monitor.ini + monitors.ini that run on plain `pip install simplemonitor`. Returns notes."""
    from . import __version__

    folder.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    id_to_name = {m.id: m.name for m in store.monitors}
    enabled = {m.id for m in store.monitors if m.enabled}
    chunks = ["; Exported from NetBeacon\n"]
    for m in store.monitors:
        if not m.enabled or m.kind not in CHECKS:
            continue
        ct = CHECKS[m.kind]
        typ, opts = ct.standalone(m.params)
        if m.kind == "compound":
            names = [id_to_name[i] for i in str(m.params.get("monitors", "")).split(",") if i in enabled]
            opts = {"monitors": ",".join(names), "min_fail": str(m.params.get("min_fail", 2))}
        if typ is None:
            chunks.append(f"; '{m.name}' ({ct.title}) has no stock SimpleMonitor equivalent and was skipped.\n")
            notes.append(f"'{m.name}' skipped (no stock equivalent)")
            continue
        full = {"type": typ, **opts}
        full.update({k: v for k, v in common_options(m, id_to_name, m.kind).items()
                     if not (k == "depend" and not all(d in enabled for d in m.depends))})
        if m.kind == "compound":
            full["group"] = "default"
        chunks.append(ini_section_text(m.name, full))
    (folder / "monitors.ini").write_text("\n\n".join(chunks) + "\n", encoding="utf-8")

    interval = max(5, int(store.get("interval", 30)))
    lines = ["[monitor]", f"interval={interval}", "monitors=monitors.ini", "", "[reporting]"]
    alerters = {k: v for k, v in alerter_sections(store).items() if v.get("type") != "netbeacon_desktop"}
    for v in alerters.values():
        v["groups"] = "_all"
    lines.append("loggers=logfile,html")
    lines.append(f"alerters={','.join(alerters)}")
    lines += ["", "[logfile]", "type=logfile", "filename=simplemonitor.log", "groups=_all", "",
              "[html]", "type=html", "folder=html", "filename=index.html", "groups=_all", ""]
    (folder / "html").mkdir(exist_ok=True)
    for name, opts in alerters.items():
        lines.append(ini_section_text(name, opts))
        lines.append("")
    (folder / "monitor.ini").write_text("\n".join(lines), encoding="utf-8")
    (folder / "README.txt").write_text(README.format(when=time.strftime("%Y-%m-%d %H:%M"), version=__version__), encoding="utf-8")
    return notes
