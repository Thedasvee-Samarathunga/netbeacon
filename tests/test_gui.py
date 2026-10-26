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
