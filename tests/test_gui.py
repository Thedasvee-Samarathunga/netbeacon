"""GUI tests (run headless with QT_QPA_PLATFORM=offscreen)."""
import socket
import threading
import time

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from netbeacon import config_writer, devices  # noqa: E402
from netbeacon.checks import CHECKS  # noqa: E402
from netbeacon.engine import EngineCore  # noqa: E402
from netbeacon.netutil import Device  # noqa: E402
from netbeacon.store import History, MonitorDef, Store  # noqa: E402
from netbeacon.ui import theme  # noqa: E402
from netbeacon.ui.context import AppContext  # noqa: E402
from netbeacon.ui.main_window import NAV, MainWindow  # noqa: E402
from netbeacon.ui.monitor_dialog import MonitorDialog  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    theme.set_current("light")
    theme.apply_palette(a, "light")
    a.setStyleSheet(theme.stylesheet("light"))
    return a


@pytest.fixture()
def env(home, app):
    store = Store()
    store.settings["first_run_done"] = True
    store.settings["minimize_to_tray"] = False
    hist = History()
    core = EngineCore(store, hist)
    ctx = AppContext(store, hist, core)
    win = MainWindow(ctx, start_minimized=True)
    yield ctx, win, app
    core.stop()
    win.close()
    for t in win.findChildren(__import__("netbeacon.ui.widgets", fromlist=["Task"]).Task):
        t.cancel()
        t.wait(5000)
    win.deleteLater()                 # really dispose of it: a later setStyleSheet must not restyle old windows
    for w in app.topLevelWidgets():
        if w is not win and not w.isVisible():
            w.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)   # processEvents() alone skips deferred deletes
    app.processEvents()
    hist.close()


def pump(app, seconds=0.2):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def listening_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(10)
    threading.Thread(target=lambda: [s.accept() for _ in range(200)], daemon=True).start()
    return s, s.getsockname()[1]


def test_every_page_renders(env):
    ctx, win, app = env
    for key, _ in NAV:
        win.show_page(key)
        pump(app, 0.05)
        assert win.pages[key].grab().width() > 100


def test_dialog_creates_check(env):
    ctx, win, app = env
    d = MonitorDialog(ctx, win, kind="tcp")
    d._setters["host"]("10.0.0.5")
    d._setters["port"](8443)
    pump(app)
    assert d.name_edit.text() == "Port 8443 on 10.0.0.5"          # auto-name follows the fields
    d.tol_spin.setValue(2)
    d._save()
    m = ctx.store.monitors[0]
    assert m.kind == "tcp" and m.params["port"] == 8443 and m.tolerance == 2
    assert ctx.core._reload is True


def test_dialog_rejects_bad_input(env):
    ctx, win, app = env
    d = MonitorDialog(ctx, win, kind="ping")
    d._setters["host"]("-bad host")
    d._save()
    assert not ctx.store.monitors
    assert "valid host" in d.problem_label.text()


def test_dialog_edit_and_rename_keeps_history(env):
    ctx, win, app = env
    m = ctx.store.add(MonitorDef.new("tcp", "Old name", {**CHECKS["tcp"].defaults(), "host": "127.0.0.1", "port": 80}))
    ctx.history.add_result(time.time(), "Old name", 0, 5.0, "ok")
    d = MonitorDialog(ctx, win, edit=m)
    d.name_edit.setText("New name")
    d._save()
    assert ctx.store.monitors[0].name == "New name"
    assert ctx.history.recent_statuses("New name") == [0]
    assert ctx.history.recent_statuses("Old name") == []


def test_dependency_loop_is_blocked(env):
    ctx, win, app = env
    a = ctx.store.add(MonitorDef.new("tcp", "A", {**CHECKS["tcp"].defaults(), "host": "127.0.0.1", "port": 1}))
    b = MonitorDef.new("tcp", "B", {**CHECKS["tcp"].defaults(), "host": "127.0.0.1", "port": 2})
    b.depends = [a.id]
    ctx.store.add(b)
    d = MonitorDialog(ctx, win, edit=a)
    for i in range(d.dep_list.count()):
        if d.dep_list.item(i).text() == "B":
            d.dep_list.item(i).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked)
    d._save()
    assert a.depends == [] and "loop" in d.problem_label.text()


def test_dialog_live_test_button(env):
    ctx, win, app = env
    srv, port = listening_port()
    d = MonitorDialog(ctx, win, kind="tcp")
    d._setters["host"]("127.0.0.1")
    d._setters["port"](port)
    d._test_now()
    for _ in range(100):
        pump(app, 0.05)
        if d.test_btn.isEnabled():
            break
    assert "Works" in d.test_result.text(), d.test_result.text()
    srv.close()


def test_every_form_has_all_fields_and_valid_defaults(env):
    ctx, win, app = env
    d = MonitorDialog(ctx, win)
    for kind, ct in CHECKS.items():
        d._select_kind(kind)
        pump(app, 0.01)
        assert set(d._getters) == {f.key for f in ct.fields}, kind
        assert d.preview.toPlainText().startswith("["), kind


def test_live_engine_feeds_gui_and_alerts(env):
    ctx, win, app = env
    srv, port = listening_port()
    ctx.store.set("interval", 5)
    ctx.store.add(MonitorDef.new("tcp", "Up service", {**CHECKS["tcp"].defaults(), "host": "127.0.0.1", "port": port}))
    ctx.store.add(MonitorDef.new("tcp", "Dead service", {**CHECKS["tcp"].defaults(), "host": "127.0.0.1", "port": 1, "timeout": 2}))
    notes = []
    ctx.notification.connect(lambda t, x, l: notes.append((t, x, l)))
    ctx.core.start()
    dash = win.pages["dashboard"]
    for _ in range(300):
        pump(app, 0.05)
        if len(dash.model.rows) == 2 and {r["status"] for r in dash.model.rows} == {"up", "down"}:
            break
    assert {r["name"]: r["status"] for r in dash.model.rows} == {"Up service": "up", "Dead service": "down"}
    for _ in range(100):
        pump(app, 0.05)
        if notes:
            break
    assert notes and notes[0][0].startswith("DOWN: Dead service")
    assert "(1)" in win.nav_buttons["dashboard"].text()
    assert ctx.history.has_open_incident("Dead service")
    # toggling pause is reflected
    ctx.core.set_paused(True)
    pump(app, 0.3)
    assert win.pause_btn.text() == "Resume"
    ctx.core.set_paused(False)
    srv.close()


def test_device_merge_flags_new_devices(home):
    h = History()
    scan = [Device(ip="192.168.1.1", mac="AA:BB:CC:00:00:01", alive=True, is_gateway=True),
            Device(ip="192.168.1.20", mac="DA:BB:CC:00:00:02", alive=True, open_ports=[445])]
    rows, fresh = devices.merge_scan(h, scan)
    assert len(fresh) == 2 and not any(r["known"] for r in rows)
    h.mark_all_known()
    scan.append(Device(ip="192.168.1.77", mac="00:11:22:33:44:55", alive=True))
    rows, fresh = devices.merge_scan(h, scan[1:])      # router silent this time
    assert [f["ip"] for f in fresh] == ["192.168.1.77"]
    router = next(r for r in rows if r["ip"] == "192.168.1.1")
    assert router["seen_now"] is False and router["known"] is True
    pc = next(r for r in rows if r["ip"] == "192.168.1.20")
    assert pc["randomized"] and pc["kind"].startswith("Windows")


def test_alert_page_saves_and_validates(env):
    ctx, win, app = env
    page = win.pages["alerts"]
    box = page.boxes["email"]
    box.setChecked(True)
    box.setters["host"]("smtp.example.com")
    box.setters["from"]("a@example.com")
    box.setters["to"]("b@example.com, c@example.com")
    page.limit.setValue(3)
    page.quiet.setChecked(True)
    page.save()
    assert ctx.store.settings["channels"]["email"]["host"] == "smtp.example.com"
    sections = config_writer.alerter_sections(ctx.store)
    assert sections["email"]["to"] == "b@example.com;c@example.com"
    assert sections["email"]["limit"] == "3"
    assert sections["email"]["times_type"] == "only" and sections["email"]["time_lower"] == "07:00"
    assert not config_writer.validate_alerter("email", sections["email"])


def test_settings_page_roundtrip(env):
    ctx, win, app = env
    page = win.pages["settings"]
    page.interval.setValue(45)
    page.teaching.setChecked(False)
    page.save()
    assert ctx.store.get("interval") == 45
    from netbeacon.ui.widgets import hub
    assert hub.enabled is False
    hub.set(True)


def test_wizard_creates_checks(env):
    ctx, win, app = env
    from netbeacon.ui.wizard import SetupWizard, Suggestion
    w = SetupWizard(ctx, win)
    w.suggestions = [Suggestion("router", "Router (10.0.0.1)", "x", "ping", {"host": "10.0.0.1"}, "Internet", 1),
                     Suggestion("internet", "Internet connection (1.1.1.1)", "x", "ping", {"host": "1.1.1.1"}, "Internet", 2, depends_on_router=True)]
    w._build_page2()
    w.site.setText("https://example.org")
    w.cb_watch.setChecked(False)          # don't start a real network scan in the test
    w._finish()
    names = [m.name for m in ctx.store.monitors]
    assert names[:2] == ["Router", "Internet connection"] and "Company website" in names and "Certificate example.org" in names
    internet = ctx.store.by_name("Internet connection")
    assert internet.depends == [ctx.store.by_name("Router").id]
    assert ctx.store.get("first_run_done")
    assert not config_writer.build(ctx.store).problems


def test_report_html(home):
    from netbeacon import reports
    store = Store()
    hist = History()
    m = store.add(MonitorDef.new("ping", "Router <1>", {**CHECKS["ping"].defaults(), "host": "10.0.0.1"}))
    now = time.time()
    hist.add_result(now - 60, m.name, 0, 3.0, "ok")
    hist.add_result(now - 30, m.name, 1, None, "down")
    hist.open_incident(m.name, now - 30, "No reply <script>")
    out = reports.build_report(store, hist, now - 3600, now)
    assert "Router &lt;1&gt;" in out and "No reply &lt;script&gt;" in out and "50.000%" in out



# ======================================================================= 1.1 features
def wait_until(app, cond, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        pump(app, 0.05)
        if cond():
            return True
    return False


def test_nav_has_the_new_pages(env):
    ctx, win, app = env
    for key in ("map", "wifi", "speed", "digest"):
        assert key in win.pages and key in win.nav_buttons


def test_diagnose_dialog_shows_verdict(env, monkeypatch):
    ctx, win, app = env
    from tests.test_features import fake_probes
    from netbeacon.ui import diagnose_dialog
    fp = fake_probes(internet=False)
    monkeypatch.setattr(diagnose_dialog.diagnose, "Probes", lambda: fp)
    m = ctx.store.add(MonitorDef.new("ping", "Internet", {**CHECKS["ping"].defaults(), "host": "1.1.1.1"}))
    dlg = diagnose_dialog.DiagnoseDialog(ctx, win, check=m)
    assert wait_until(app, lambda: dlg.result is not None)
    assert dlg.result.culprit == "internet"
    assert "internet provider" in dlg.verdict_text.text()
    assert dlg.steps_lay.count() - 1 == len(dlg.result.steps) >= 5
    assert ctx.store.get("last_gateway") == "192.168.1.1"
    assert any("Diagnosis:" in e["text"] for e in ctx.history.events(limit=20))
    dlg.done(0)


def test_map_page_colours_devices_by_check(env):
    ctx, win, app = env
    h = ctx.history
    scan = [Device(ip="192.168.1.1", mac="AA:BB:CC:00:00:01", alive=True, is_gateway=True),
            Device(ip="192.168.1.20", mac="AA:BB:CC:00:00:02", alive=True, open_ports=[445]),
            Device(ip="192.168.1.30", mac="AA:BB:CC:00:00:03", alive=True)]
    rows, _ = devices.merge_scan(h, scan)
    h.set_device("AA:BB:CC:00:00:02", known=1)
    ctx.store.set("last_gateway", "192.168.1.1")
    m = ctx.store.add(MonitorDef.new("tcp", "File server", {**CHECKS["tcp"].defaults(), "host": "192.168.1.20", "port": 445}))
    win.pages["dashboard"].model.set_rows([{"id": m.id, "name": m.name, "status": "down"}])
    page = win.pages["map"]
    win.pages["devices"].rows = devices.stored_rows(h)
    for r in win.pages["devices"].rows:
        r["seen_now"] = True
    win.show_page("map")
    pump(app, 0.1)
    page.rebuild()
    states = {n["ip"]: n["state"] for n in page.canvas.nodes}
    assert page.canvas.router["ip"] == "192.168.1.1"
    assert states["192.168.1.20"] == "down" and states["192.168.1.30"] == "new"
    page._select("AA:BB:CC:00:00:02")
    assert "File server" in page.d_info.text() and page.b_diag.isVisibleTo(page) and page.b_wake.isVisibleTo(page)
    assert page.grab().width() > 100


def test_speed_page_runs_and_records(env):
    ctx, win, app = env
    from tests.test_features import _SpeedHandler
    import http.server
    import socketserver

    class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
    srv = S(("127.0.0.1", 0), _SpeedHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ctx.store.settings.update(speed_server=f"http://127.0.0.1:{srv.server_address[1]}", speed_max_down_mb=2, speed_max_up_mb=1,
                              speed_paid_down=10000)
    page = win.pages["speed"]
    page.run_test()
    assert wait_until(app, lambda: page.table.rowCount() == 1, 30)
    assert ctx.history.speedtests()[0]["down"] > 0
    assert "%" in page.c_plan.value.text()
    assert any("Speed test:" in e["text"] for e in ctx.history.events(limit=10))
    srv.shutdown()


def test_speed_page_schedule(env):
    ctx, win, app = env
    page = win.pages["speed"]
    called = []
    page.run_test = lambda silent=False: called.append(silent)
    ctx.store.settings.update(speed_enabled=True, speed_every_hours=6, last_speedtest_ts=time.time() - 7 * 3600)
    page._maybe_run()
    assert called == [True]
    ctx.store.settings["last_speedtest_ts"] = time.time()
    page._maybe_run()
    assert called == [True]


def test_wifi_page_renders_status_and_networks(env):
    ctx, win, app = env
    from tests.test_features import IFACES_EN, NETWORKS
    from netbeacon import wifi
    page = win.pages["wifi"]
    page.status = wifi.parse_interfaces(IFACES_EN)
    page.networks = wifi.parse_networks(NETWORKS)[0]
    page._record(page.status)
    page._render()
    assert page.c_sig.value.text() == "38%" and "poor" in page.c_sig.sub.text()
    assert page.table.rowCount() == 4 and "overlaps" in page.advice.text()
    assert ctx.history.wifi_samples()[0]["signal"] == 38
    win.show_page("wifi")
    page._loaded = True
    pump(app, 0.05)
    assert page.grab().width() > 100


def test_digest_page_creates_and_schedules(env):
    ctx, win, app = env
    page = win.pages["digest"]
    ctx.store.add(MonitorDef.new("ping", "Router", {**CHECKS["ping"].defaults(), "host": "10.0.0.1"}))
    ctx.history.add_result(time.time() - 60, "Router", 0, 2.0, "ok")
    page.make()
    assert "A good week" in page.view.toHtml()
    notes = []
    win._on_notification = lambda t, x, l: notes.append(t)
    ctx.store.settings.update(digest_enabled=True, last_digest_ts=time.time() - 8 * 86400)
    page._maybe_send()
    assert notes == ["Your weekly network summary is ready"]
    assert any(e["text"].startswith("Weekly summary") for e in ctx.history.events(limit=10))
    from netbeacon.ui.pages.digest_page import summaries_dir
    assert list(summaries_dir().glob("summary-*.html"))
    page._maybe_send()                     # not due again
    assert len(notes) == 1


def test_wake_and_new_device_alerts(env, monkeypatch):
    ctx, win, app = env
    from netbeacon import netutil, notify
    sent = []
    monkeypatch.setattr(netutil, "wake_on_lan", lambda mac, *a, **k: sent.append(mac) or ["192.168.1.255"])
    assert win.wake_device("AA:BB:CC:DD:EE:FF", "Accounts PC")
    assert sent == ["AA:BB:CC:DD:EE:FF"]
    assert any("Wake-on-LAN" in e["text"] for e in ctx.history.events(limit=5))
    broadcasts = []
    monkeypatch.setattr(notify, "broadcast", lambda store, title, msg, **k: broadcasts.append((title, msg)) or {"email": "boom"})
    win._on_notification = lambda *a: None
    devices.merge_scan(ctx.history, [Device(ip="192.168.1.1", mac="AA:00:00:00:00:01", alive=True)])
    ctx.history.mark_all_known()
    win._watch_done([Device(ip="192.168.1.1", mac="AA:00:00:00:00:01", alive=True),
                     Device(ip="192.168.1.99", mac="AA:00:00:00:00:99", alive=True, open_ports=[9100])])
    assert wait_until(app, lambda: broadcasts and any("via email" in e["text"] for e in ctx.history.events(limit=10)))
    assert "192.168.1.99" in broadcasts[0][1] and "Printer" in broadcasts[0][1]


def test_wizard_extras_and_device_suggestions(env):
    ctx, win, app = env
    from netbeacon import wifi
    from netbeacon.ui.wizard import SetupWizard, Suggestion, suggestions_for_devices
    found = [Device(ip="192.168.1.1", is_gateway=True, open_ports=[80]),
             Device(ip="192.168.1.50", hostname="printer.lan", open_ports=[9100, 80]),
             Device(ip="192.168.1.60", open_ports=[5000]),
             Device(ip="192.168.1.70", mac="00:11:22:00:00:70", open_ports=[445])]
    sug = suggestions_for_devices(found)
    assert [s.title for s in sug] == ["Printer printer", "Storage 192.168.1.60 (web page)", "File sharing on 192.168.1.70"]
    w = SetupWizard(ctx, win)
    w.suggestions = [Suggestion("router", "Router (10.0.0.1)", "x", "ping", {"host": "10.0.0.1"}, "Internet", 1)]
    w._build_page2()
    w.site.setText("https://example.org")
    w._devices_found(found)                       # rebuilding keeps the site text
    assert w.site.text() == "https://example.org" and len(w.suggestions) == 4
    w.wifi_status = wifi.WifiStatus(available=True, connected=True, ssid="Office", signal=70)
    w.wifi_card.setVisible(True)
    w.cb_watch.setChecked(False)
    w.paid.setValue(200)
    w._finish()
    names = [m.name for m in ctx.store.monitors]
    assert "Printer printer" in names and "Wi-Fi signal" in names and "File sharing on 192.168.1.70" not in names
    printer = ctx.store.by_name("Printer printer")
    assert printer.depends == [ctx.store.by_name("Router").id]
    assert ctx.store.get("speed_enabled") and ctx.store.get("speed_paid_down") == 200 and ctx.store.get("digest_enabled")
    assert not config_writer.build(ctx.store).problems


# ======================================================================= 1.2 themes
def test_every_theme_and_accent_builds(env):
    ctx, win, app = env
    from netbeacon.ui import theme as th
    keys = ("bg", "card", "text", "muted", "border", "accent", "accent_text", "sidebar", "sidebar_text", "sidebar_hover",
            "sidebar_active", "input", "banner", "banner_border", "banner_text", "row_alt", "selection", "code_bg", "danger_bg")
    for key, _label, _dark in th.THEMES:
        if key != "system":
            assert set(th.PALETTES[key]) == set(keys), key
        win.apply_theme(key)
        assert th.choice() == key and th.palette()["accent"].startswith("#")
        assert th.stylesheet(th.resolve(key))
    for accent, _n in th.ACCENTS:             # accents are pure maths on the palette - no restyle needed
        th.set_current("dusk", accent)
        p = th.palette()
        assert p["accent"].startswith("#") and (not accent or p["sidebar_active"] == accent)
        assert accent in th.stylesheet("dusk") if accent else True
    assert th.resolve("system") in ("light", "dark")
    ctx.store.settings["accent"] = ""
    win.apply_theme("light")


def test_settings_theme_applies_live(env):
    ctx, win, app = env
    from netbeacon.ui import theme as th
    page = win.pages["settings"]
    page.theme.setCurrentIndex(page.theme.findData("dusk"))
    page._preview_timer.stop(); page._preview()
    assert th.choice() == "dusk" and th.is_dark() and ctx.store.get("theme") == "dusk"
    page.accent.setCurrentIndex(page.accent.findData("#ea580c"))
    page._preview_timer.stop(); page._preview()
    assert ctx.store.get("accent") == "#ea580c" and th.palette()["sidebar_active"] == "#ea580c"
    assert "#ea580c" in app.styleSheet()
    page.load()
    assert page.theme.currentData() == "dusk" and page.accent.currentData() == "#ea580c"
    page.theme.setCurrentIndex(page.theme.findData("light"))
    page.accent.setCurrentIndex(0)
    page._preview_timer.stop(); page._preview()
    assert th.choice() == "light" and not th.is_dark()
