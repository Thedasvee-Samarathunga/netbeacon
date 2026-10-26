"""Render every page off-screen with demo data (used for visual QA; also fun for documentation)."""
import os, random, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
home = tempfile.mkdtemp(prefix="nb-demo-")
os.environ["NETBEACON_HOME"] = home
out = sys.argv[1] if len(sys.argv) > 1 else "shots"
theme_name = sys.argv[2] if len(sys.argv) > 2 else "light"
os.makedirs(out, exist_ok=True)

from PySide6.QtWidgets import QApplication
from netbeacon.checks import CHECKS
from netbeacon.engine import EngineCore
from netbeacon.store import History, MonitorDef, Store, ST_UP, ST_DOWN, ST_RETRY
from netbeacon.ui import theme
from netbeacon.ui.context import AppContext
from netbeacon.ui.main_window import MainWindow, NAV
from netbeacon.ui.widgets import hub

app = QApplication([])
app.setStyle("Fusion")
theme.set_current(theme_name)
theme.apply_palette(app, theme_name)
app.setStyleSheet(theme.stylesheet(theme_name))

store = Store()
store.settings.update(first_run_done=True, minimize_to_tray=False, theme=theme_name)
hist = History()

def add(kind, name, group, **params):
    m = MonitorDef.new(kind, name, {**CHECKS[kind].defaults(), **params})
    m.group = group
    store.add(m)
    return m

router = add("ping", "Router", "Internet", host="192.168.1.1")
inet = add("ping", "Internet (1.1.1.1)", "Internet", host="1.1.1.1"); inet.depends=[router.id]; inet.tolerance=2
dns = add("dns", "DNS lookup", "Internet", record="example.com"); dns.depends=[router.id]
web = add("http", "Company website", "Websites", url="https://www.acme-widgets.com/", regexp="Acme")
cert = add("tls", "Certificate acme-widgets.com", "Websites", host="www.acme-widgets.com")
fs = add("tcp", "File server (SMB)", "Servers", host="192.168.1.20", port=445)
rdp = add("tcp", "Terminal server (RDP)", "Servers", host="192.168.1.21", port=3389)
printer = add("ping", "Reception printer", "Office", host="192.168.1.50")
disk = add("disk", "Disk space C:\\", "Servers", path="C:\\")
bak = add("file", "Backup D:\\Backups\\*.zip", "Servers", pattern="D:\\Backups\\*.zip", max_age_hours=26)
sql = add("service", "Service SQL Server", "Servers", service="MSSQLSERVER")
mem = add("memory", "Free memory", "Servers", percent_free=10); mem.tolerance = 3
for m in store.monitors: store.update(m)

now = time.time()
rng = random.Random(7)
base = {router.name: 2, inet.name: 14, dns.name: 22, web.name: 180, fs.name: 3, rdp.name: 4, printer.name: 6}
for m in store.monitors:
    t = now - 7*86400
    step = 300
    down_windows = []
    if m.name == bak.name: down_windows = [(now-2*86400, now-2*86400+7200)]
    if m.name == inet.name: down_windows = [(now-3*86400, now-3*86400+1500), (now-20*3600, now-20*3600+400)]
    if m.name == fs.name: down_windows = [(now-5*3600, now-5*3600+900)]
    if m.name == rdp.name: down_windows = [(now-3600, now+10)]
    for (a, b) in down_windows:
        hist.open_incident(m.name, a, "connection refused (port closed)" if m.kind=="tcp" else "No reply from host: request timed out (no reply)")
        if b < now: hist.close_incident(m.name, b)
    while t < now:
        down = any(a <= t <= b for a, b in down_windows)
        lat = None
        if m.name in base and not down:
            lat = max(0.5, rng.gauss(base[m.name], base[m.name]*0.25))
            if rng.random() < 0.01: lat *= 5
        hist.add_result(t, m.name, ST_DOWN if down else ST_UP, lat, "demo")
        t += step
hist.add_event(now-3600, "error", rdp.name, f"{rdp.name} is DOWN: port 3389 on 192.168.1.21: connection refused (port closed)")
hist.add_event(now-3500, "alert", None, "Alert sent: DOWN: Terminal server (RDP) - port 3389 on 192.168.1.21: connection refused")
hist.add_event(now-5*3600+900, "ok", fs.name, f"{fs.name} has RECOVERED after 15m 0s. port 445 open (3 ms)")
hist.add_event(now-5*3600, "error", fs.name, f"{fs.name} is DOWN: connection refused")
hist.add_event(now-20*3600, "warn", inet.name, f"{inet.name}: check failed (No reply). Retrying before calling it down (tolerance 2).")
hist.add_event(now-18000, "info", web.name, f"{web.name}: a blip - it failed briefly but recovered before it counted as down.")

core = EngineCore(store, hist)
ctx = AppContext(store, hist, core)
win = MainWindow(ctx, start_minimized=True)
win.resize(1380, 880)
win.show()

def rows():
    out = []
    for m in store.monitors:
        ct = CHECKS[m.kind]
        st, msg, ms = "up", "", base.get(m.name)
        if m.name == rdp.name: st, msg, ms = "down", "port 3389 on 192.168.1.21: connection refused (port closed)", None
        elif m.name == printer.name: st, msg = "retry", "No reply from 192.168.1.50: request timed out (no reply)"; ms = None
        elif m.name == bak.name: st, msg = "down", "backup-0919.zip: 51.2 h old, 812.0 MB - older than 26 h"
        elif m.name == sql.name: st, msg = "up", ""
        elif m.name == cert.name: msg = "Certificate at www.acme-widgets.com:443 has 47 days left to expiry"
        elif m.name == disk.name: msg = "212.4 GB free (46%) on C:\\"
        elif m.name == mem.name: msg = "38% free"
        elif m.kind == "tcp": msg = f"port {m.params['port']} open ({base.get(m.name,3)} ms)"
        elif m.kind == "ping": msg = f"3/3 replies, avg {base.get(m.name,2):.0f} ms"
        elif m.name == web.name: msg = "HTTP 200 in 182 ms"
        elif m.name == dns.name: msg = "example.com -> 93.184.216.34 (21 ms)"
        out.append({"id": m.id, "name": m.name, "kind": m.kind, "group": m.group, "title": ct.title, "target": ct.target(m.params),
                    "enabled": True, "tolerance": m.tolerance, "message": msg, "response_ms": ms, "last_check": now-rng.randint(1,25),
                    "since": 86400*3 if st == "up" else None, "failures": 0, "description": ct.default_name(m.params), "depends": m.depends, "status": st})
    return out

from netbeacon import devices as devmod
from netbeacon.netutil import Device
fake = [Device("192.168.1.1", "F0:9F:C2:11:22:33", "router.lan", True, 1.4, [80, 443, 53], is_gateway=True),
        Device("192.168.1.10", "3C:52:82:AA:BB:CC", "front-desk-pc", True, 2.1, [445, 135, 3389]),
        Device("192.168.1.20", "00:0C:29:5E:11:90", "fileserver", True, 1.1, [22, 445, 139]),
        Device("192.168.1.21", "00:15:5D:00:12:01", "terminal-srv", True, 1.6, [3389, 445]),
        Device("192.168.1.50", "08:00:20:AB:CD:EF", "", True, 6.0, [9100, 80, 631]),
        Device("192.168.1.63", "DA:A1:19:5C:77:10", "", True, 38.0, [62078]),
        Device("192.168.1.88", "B8:27:EB:12:34:56", "pi-sensor", True, 9.0, [22]),
        Device("192.168.1.131", "6E:11:9A:44:03:AB", "", False, None, [])]
devmod.merge_scan(hist, fake, now - 3600)
hist.mark_all_known()
rows_, fresh_ = devmod.merge_scan(hist, [d for d in fake if d.ip != "192.168.1.88"] + [Device("192.168.1.177", "9A:BC:11:22:33:44", "", True, 22.0, [])])
win.pages["devices"]._render(rows_)
win.pages["devices"].status.setText("Found 8 devices. 1 new device(s) appeared: 192.168.1.177")
win.pages["ports"].host.setText("192.168.1.21"); win.pages["ports"].host_scanned = "192.168.1.21"
win.pages["ports"]._done(([135, 445, 3389, 5985], 45))
ctx.snapshot_changed.emit(ctx.enrich(rows()))
ctx.status_changed.emit(__import__("netbeacon.engine", fromlist=["LoopInfo"]).LoopInfo(running=True, next_run_ts=now+17, last_duration=2.3))
app.processEvents()

def shot(name, widget=None):
    app.processEvents()
    (widget or win).grab().save(os.path.join(out, f"{theme_name}-{name}.png"))

for key, _ in NAV:
    win.show_page(key)
    app.processEvents()
    if key == "uptime":
        win.pages["uptime"].show_check(inet.name)
    if key == "learn":
        win.pages["learn"].list.setCurrentRow(5)
    shot(key)

from netbeacon.ui.monitor_dialog import MonitorDialog
d = MonitorDialog(ctx, win, kind="http"); d.resize(1100, 780); d.show(); d._toggle_adv(); shot("dialog-http", d); d.close()
d = MonitorDialog(ctx, win, edit=store.by_id(inet.id)); d.resize(1100, 780); d.show(); shot("dialog-edit", d); d.close()
from netbeacon.ui.wizard import SetupWizard
w = SetupWizard(ctx, win); w.show(); shot("wizard1", w)
w._next(); app.processEvents(); time.sleep(1.2); app.processEvents(); shot("wizard2", w); w.close()
print("done", out)
