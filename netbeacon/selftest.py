"""`NetBeacon.exe --selftest result.json` - proves that a built executable really works.

Used by the GitHub workflow right after building, but handy for you too if something looks broken.
It runs the real SimpleMonitor engine against a few local checks, then builds every GUI page off-screen.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
import traceback


def run(outfile: str) -> int:
    report: dict = {"ok": False, "steps": [], "python": sys.version.split()[0], "frozen": bool(getattr(sys, "frozen", False))}

    def step(name: str, ok: bool, detail: str = "") -> None:
        report["steps"].append({"step": name, "ok": ok, "detail": detail})

    home = tempfile.mkdtemp(prefix="netbeacon-selftest-")
    os.environ["NETBEACON_HOME"] = home
    srv = None
    try:
        # ---- engine -------------------------------------------------------------
        from . import config_writer, compat  # noqa: F401
        from .checks import CHECKS
        from .engine import EngineCore, local_status
        from .store import History, MonitorDef, Store

        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(5)
        port = srv.getsockname()[1]
        threading.Thread(target=lambda: [srv.accept() for _ in range(50)], daemon=True).start()

        store = Store()
        store.settings["status_page_enabled"] = True
        store.settings["status_page_folder"] = os.path.join(home, "status")
        for kind, name, params in (("tcp", "Local port", {"host": "127.0.0.1", "port": port}),
                                   ("cpu", "CPU", {"max_percent": 100, "sample_seconds": 1}),
                                   ("memory", "Memory", {"percent_free": 1}),
                                   ("disk", "Disk", {"path": os.path.abspath(os.sep), "min_free_percent": 0}),
                                   ("tcp", "Closed port", {"host": "127.0.0.1", "port": 1, "timeout": 2})):
            store.add(MonitorDef.new(kind, name, {**CHECKS[kind].defaults(), **params}))
        result = config_writer.build(store)
        step("config written", not result.problems and len(result.active) == 5, "; ".join(result.problems))
        hist = History()
        core = EngineCore(store, hist)
        from .sm_ext import bridge
        bridge.on_result = core.recorder.on_result
        core._rebuild()
        core.sm.run_loop()
        status = {name: local_status(m) for name, m in core.sm.monitors.items()}
        step("engine ran checks", status.get("Local port") == "up" and status.get("Closed port") == "down" and status.get("CPU") == "up", json.dumps(status))
        step("history recorded", len(hist.recent_statuses("Local port")) == 1)
        page = os.path.join(home, "status", "index.html")
        step("HTML status page written", os.path.exists(page) and "Local port" in open(page, encoding="utf-8", errors="replace").read(), page)
        import simplemonitor.Monitors.monitor as mm
        step("custom monitors registered", all(t in mm.all_types() for t in ("lan_ping", "lan_tcp", "lan_http", "lan_dns", "lan_wifi")))
        from . import diagnose, digest, speedtest, wifi  # noqa: F401  (the 1.1 modules must be bundled)
        st_w = wifi.parse_interfaces("    Name : Wi-Fi\n    State : connected\n    SSID : Test\n    Signal : 80%\n    Channel : 6\n")
        step("Wi-Fi parser works", st_w.connected and st_w.signal == 80 and st_w.band == "2.4 GHz")
        dg = digest.build(store, hist, time.time() - 86400)
        step("weekly summary builds", bool(dg.headline) and "<h2" in dg.html(), dg.headline)
        from .netutil import magic_packet
        step("Wake-on-LAN packet builds", len(magic_packet("00:11:22:33:44:55")) == 102)
        step("html logger available", "html" in __import__("simplemonitor.Loggers.logger", fromlist=["x"]).all_types())
        hist.close()

        # ---- GUI ----------------------------------------------------------------
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from .store import History as H2
        from .ui import theme
        from .ui.context import AppContext
        from .ui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        theme.apply_palette(app, "light")
        app.setStyleSheet(theme.stylesheet("light"))
        store2 = Store()
        store2.settings["first_run_done"] = True
        store2.settings["minimize_to_tray"] = False
        h2 = H2()
        core2 = EngineCore(store2, h2)
        ctx = AppContext(store2, h2, core2)
        win = MainWindow(ctx, start_minimized=True)
        win.resize(1280, 800)
        from .ui.main_window import NAV
        for key, _ in NAV:
            win.show_page(key)
            app.processEvents()
            win.pages[key].grab()
        step("all GUI pages render", True)
        from .ui.monitor_dialog import MonitorDialog
        dlg = MonitorDialog(ctx, win)
        for kind in CHECKS:
            dlg._select_kind(kind)
            app.processEvents()
        step("check dialog builds every form", True)
        report["ok"] = all(s["ok"] for s in report["steps"])
    except Exception:
        step("exception", False, traceback.format_exc())
        report["ok"] = False
    finally:
        try:
            if srv:
                srv.close()
        except OSError:
            pass
        with open(outfile, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
    return 0 if report["ok"] else 1
