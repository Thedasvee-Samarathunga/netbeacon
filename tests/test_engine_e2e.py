"""End-to-end: real SimpleMonitor engine + local fake servers."""
import http.server
import socket
import socketserver
import struct
import sys
import threading
import time
from pathlib import Path

import pytest

from netbeacon import config_writer, netutil
from netbeacon.checks import CHECKS
from netbeacon.engine import EngineCore
from netbeacon.store import History, MonitorDef, Store


# ----------------------------------------------------------------- fake servers
class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/missing":
            self.send_response(404)
            self.end_headers()
            return
        body = b"<html>Welcome to Acme</html>"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def http_server():
    srv = socketserver.TCPServer(("127.0.0.1", 0), _Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


@pytest.fixture()
def dns_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    stop = threading.Event()

    def loop():
        sock.settimeout(0.2)
        while not stop.is_set():
            try:
                data, addr = sock.recvfrom(512)
            except socket.timeout:
                continue
            except OSError:
                return
            qid = data[:2]
            # question section = everything after the 12-byte header
            question = data[12:]
            name_end = question.index(b"\x00") + 1
            qname = question[:name_end]
            if b"nope" in qname:
                resp = qid + struct.pack(">HHHHH", 0x8183, 1, 0, 0, 0) + question
            else:
                resp = (qid + struct.pack(">HHHHH", 0x8180, 1, 1, 0, 0) + question +
                        b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4) + bytes([203, 0, 113, 7]))
            sock.sendto(resp, addr)

    threading.Thread(target=loop, daemon=True).start()
    yield port
    stop.set()
    sock.close()


@pytest.fixture()
def tcp_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(5)
    yield s.getsockname()[1]
    s.close()


def closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def make(store, kind, name, **params):
    m = MonitorDef.new(kind, name, {**CHECKS[kind].defaults(), **params})
    store.add(m)
    return m


# ----------------------------------------------------------------- unit-ish tests
def test_every_check_type_builds_valid_options(home):
    store = Store()
    samples = {
        "ping": dict(host="127.0.0.1"), "tcp": dict(host="127.0.0.1", port=80), "dns": dict(record="example.com"),
        "http": dict(url="http://127.0.0.1/"), "tls": dict(host="example.com"), "service": dict(service="Spooler"),
        "process": dict(process_name="python"), "disk": dict(path="/"), "memory": dict(percent_free=5), "cpu": dict(),
        "file": dict(pattern="/tmp/*.zip"), "command": dict(command="echo hi"), "practice": dict(),
    }
    for kind, params in samples.items():
        make(store, kind, kind.title(), **params)
    res = config_writer.build(store)
    assert not res.problems, res.problems
    assert len(res.active) == len(samples)


def test_validation_blocks_bad_input(home):
    assert CHECKS["ping"].validate({"host": "-rf /"})
    assert CHECKS["tcp"].validate({"host": "x", "port": 70000})
    assert CHECKS["http"].validate({"url": "ftp://x", "allowed_codes": "200"})
    assert CHECKS["http"].validate({"url": "http://x", "allowed_codes": "abc"})
    assert CHECKS["dns"].validate({"record": "x", "record_type": "MX", "server": ""})
    assert not CHECKS["ping"].validate({"host": "192.168.1.1", "count": 3, "timeout": 4, "max_loss": 50, "slow_ms": 0})


def test_percent_signs_survive_ini(home):
    store = Store()
    make(store, "http", "Pct", url="http://127.0.0.1/a%20b?x=100%", regexp="100%")
    res = config_writer.build(store)
    assert not res.problems, res.problems
    text = res.monitors_ini.read_text()
    assert "%%" in text


def test_broken_check_does_not_stop_others(home):
    store = Store()
    make(store, "tcp", "Good", host="127.0.0.1", port=80)
    make(store, "http", "Bad", url="http://x/", regexp="([")
    res = config_writer.build(store)
    assert res.active == ["Good"]
    assert any("Bad" in p for p in res.problems)


def test_ping_parser_windows_english_and_german():
    en = "Reply from 192.168.1.1: bytes=32 time=3ms TTL=64\nReply from 192.168.1.1: bytes=32 time<1ms TTL=64\nRequest timed out.\n"
    r = netutil.parse_ping_output(en, 3)
    assert r.received == 2 and r.ok and r.loss_pct == pytest.approx(33.3, abs=0.5)
    de = "Antwort von 192.168.1.1: Bytes=32 Zeit=4ms TTL=64\nAntwort von 192.168.1.1: Bytes=32 Zeit<1ms TTL=64\n"
    r = netutil.parse_ping_output(de, 2)
    assert r.received == 2 and r.avg_ms is not None
    unreachable = "Reply from 192.168.1.50: Destination host unreachable.\n"
    assert not netutil.parse_ping_output(unreachable, 1).ok
    linux = "64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=12.3 ms\n"
    assert netutil.parse_ping_output(linux, 1).avg_ms == pytest.approx(12.3)


def test_arp_parsing_windows_and_linux():
    win = """
Interface: 192.168.1.10 --- 0xb
  Internet Address      Physical Address      Type
  192.168.1.1           aa-bb-cc-dd-ee-ff     dynamic
  192.168.1.255         ff-ff-ff-ff-ff-ff     static
  224.0.0.22            01-00-5e-00-00-16     static
"""
    t = netutil.parse_arp_text(win)
    assert t == {"192.168.1.1": "AA:BB:CC:DD:EE:FF"}
    mac = "? (192.168.1.20) at a:b:c:d:e:f on en0 ifscope [ethernet]\n? (192.168.1.21) at (incomplete) on en0"
    assert netutil.parse_arp_text(mac) == {"192.168.1.20": "0A:0B:0C:0D:0E:0F"}


def test_port_spec():
    assert netutil.parse_port_spec("22, 80,8000-8002") == [22, 80, 8000, 8001, 8002]
    with pytest.raises(ValueError):
        netutil.parse_port_spec("0")
    with pytest.raises(ValueError):
        netutil.parse_port_spec("70000")


def test_randomized_mac():
    assert netutil.is_randomized_mac("DA:A1:19:00:00:01")
    assert not netutil.is_randomized_mac("00:0C:29:11:22:33")


def test_dns_client(dns_server):
    answers, ms = netutil.dns_query("shop.example.com", "A", "127.0.0.1", 2, port=dns_server)
    assert answers == ["203.0.113.7"]
    with pytest.raises(netutil.DnsError, match="NXDOMAIN"):
        netutil.dns_query("nope.example.com", "A", "127.0.0.1", 2, port=dns_server)


def test_scan_ports_finds_open(tcp_port):
    assert netutil.scan_ports("127.0.0.1", [tcp_port, closed_port()], timeout_s=0.5) == [tcp_port]


# ----------------------------------------------------------------- the real thing
def wait_for(cond, timeout=40, step=0.25):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return False


def test_engine_full_cycle(home, http_server, dns_server, tcp_port, tmp_path):
    store = Store()
    store.set("interval", 5)
    hist = History()
    (tmp_path / "backup.zip").write_bytes(b"x" * 2048)

    up_tcp = make(store, "tcp", "Web port open", host="127.0.0.1", port=tcp_port)
    down_tcp = make(store, "tcp", "Closed port", host="127.0.0.1", port=closed_port(), timeout=2)
    dependent = make(store, "tcp", "Child of closed", host="127.0.0.1", port=tcp_port)
    dependent.depends = [down_tcp.id]
    store.update(dependent)
    tolerant = make(store, "tcp", "Tolerant closed", host="127.0.0.1", port=closed_port(), timeout=2)
    tolerant.tolerance = 3
    store.update(tolerant)
    make(store, "http", "Web page", url=f"http://127.0.0.1:{http_server}/", regexp="Acme")
    make(store, "http", "Web text missing", url=f"http://127.0.0.1:{http_server}/", regexp="NotThere")
    make(store, "http", "Web 404", url=f"http://127.0.0.1:{http_server}/missing")
    make(store, "dns", "DNS ok", record="shop.example.com", server="127.0.0.1", port=dns_server, expect="203.0.113.7")
    make(store, "disk", "Disk", path="/", min_free_percent=1)
    make(store, "file", "Backup fresh", pattern=str(tmp_path / "*.zip"), max_age_hours=1)
    make(store, "file", "Backup missing", pattern=str(tmp_path / "*.nothing"))
    cmd = f'{sys.executable} -c "print(42)"'
    make(store, "command", "Cmd ok", command=cmd, expect="42")
    make(store, "memory", "Mem", percent_free=1)
    make(store, "cpu", "CPU", max_percent=100, sample_seconds=1)
    make(store, "practice", "Practice", interval=3)

    engine = EngineCore(store, hist)
    events = []
    snaps = []
    engine.on_event.append(events.append)
    engine.on_snapshot.append(snaps.append)
    engine.start()
    try:
        assert wait_for(lambda: snaps and all(r["status"] != "pending" for r in snaps[-1] if r["enabled"]), 60), \
            [(r["name"], r["status"]) for r in (snaps[-1] if snaps else [])]
        by = {r["name"]: r for r in snaps[-1]}

        assert by["Web port open"]["status"] == "up"
        assert by["Web port open"]["response_ms"] is not None
        assert by["Closed port"]["status"] == "down"
        assert "refused" in by["Closed port"]["message"] or "timed out" in by["Closed port"]["message"]  # Windows can be slow to refuse
        assert by["Child of closed"]["status"] == "skipped", by["Child of closed"]
        assert by["Tolerant closed"]["status"] == "retry"          # failing, but inside tolerance
        assert by["Web page"]["status"] == "up" and by["Web page"]["response_ms"] > 0
        assert by["Web text missing"]["status"] == "down" and "NotThere" in by["Web text missing"]["message"]
        assert by["Web 404"]["status"] == "down" and "404" in by["Web 404"]["message"]
        assert by["DNS ok"]["status"] == "up", by["DNS ok"]
        assert by["Disk"]["status"] == "up"
        assert by["Backup fresh"]["status"] == "up"
        assert by["Backup missing"]["status"] == "down"
        assert by["Cmd ok"]["status"] == "up", by["Cmd ok"]
        assert by["Mem"]["status"] == "up"
        assert by["CPU"]["status"] == "up"

        # history + incident bookkeeping
        assert hist.recent_statuses("Web port open", 5)[-1] == 0
        assert hist.has_open_incident("Closed port")
        assert any(e["level"] == "error" and "Closed port" in e["text"] for e in events)
        assert not hist.has_open_incident("Tolerant closed")

        # the practice monitor fails then recovers by itself -> incident closes, 'recovered' event appears
        assert wait_for(lambda: any(e["level"] == "ok" and "Practice" in e["text"] for e in events), 60), events
        inc = hist.incidents("Practice")
        assert inc and inc[0]["ended"] is not None

        # editing config keeps state (down monitors don't reset)
        before = len(hist.incidents("Closed port"))
        engine.reload()
        time.sleep(7)
        assert len(hist.incidents("Closed port")) == before
        assert by["Closed port"]["status"] == "down"
    finally:
        engine.stop()

    av = hist.availability("Web port open", 0)
    assert av["pct"] == 100.0
    assert hist.availability("Closed port", 0)["pct"] == 0.0
    assert hist.downtime_seconds("Closed port", 0) >= 0
    csv_path = str(tmp_path / "out.csv")
    assert hist.export_csv(csv_path, None, 0) > 10


def test_stale_incident_closed_on_restart(home):
    hist = History()
    store = Store()
    hist.meta_set("last_seen", str(time.time() - 100))
    hist.open_incident("Old", time.time() - 500, "x")
    engine = EngineCore(store, hist)
    engine.start()
    time.sleep(1)
    engine.stop()
    inc = hist.incidents("Old")[0]
    assert inc["ended"] is not None and inc["interrupted"] == 1


def test_export_standalone(home, tmp_path):
    store = Store()
    make(store, "ping", "Router", host="192.168.1.1")
    make(store, "tcp", "Port", host="10.0.0.1", port=443)
    make(store, "cpu", "CPU")
    make(store, "file", "Wild", pattern="D:\\b\\*.zip")
    notes = config_writer.export_standalone(store, tmp_path / "exp")
    text = (tmp_path / "exp" / "monitors.ini").read_text()
    assert "type=host" in text and "type=tcp" in text
    assert "lan_" not in text
    assert len(notes) == 2
    import configparser
    cp = configparser.ConfigParser()
    cp.read(tmp_path / "exp" / "monitors.ini")
    assert "Router" in cp.sections()


def test_alert_test_desktop(home):
    store = Store()
    got = []
    from netbeacon.sm_ext import bridge
    from netbeacon.engine import send_test_alert
    bridge.on_notify = lambda t, x, l: got.append((t, x, l))
    ok, msg = send_test_alert(store, "desktop")
    assert ok, msg
    assert got and got[0][0].startswith("DOWN")


def test_alert_test_email_failure_is_reported(home):
    store = Store()
    store.settings["channels"]["email"].update({"host": "127.0.0.1", "port": closed_port(), "from": "a@b.c", "to": "d@e.f", "ssl": ""})
    from netbeacon.engine import send_test_alert
    ok, msg = send_test_alert(store, "email")
    assert not ok and msg


def test_compound_and_dependency_chain_one_round(home, tcp_port):
    store = Store()
    a = make(store, "tcp", "Line A", host="127.0.0.1", port=closed_port(), timeout=2)
    b = make(store, "tcp", "Line B", host="127.0.0.1", port=closed_port(), timeout=2)
    c = make(store, "tcp", "Line C", host="127.0.0.1", port=tcp_port)
    both = make(store, "compound", "Both lines down", monitors=f"{a.id},{b.id}", min_fail=2)
    one_of = make(store, "compound", "Line A+C down", monitors=f"{a.id},{c.id}", min_fail=2)
    child = make(store, "tcp", "Behind both", host="127.0.0.1", port=tcp_port)
    child.depends = [both.id]
    store.update(child)
    hist = History()
    core = EngineCore(store, hist)
    from netbeacon.sm_ext import bridge
    bridge.on_result = core.recorder.on_result
    core._rebuild()
    assert not core.build.problems, core.build.problems
    core.sm.run_loop()
    rows = {r["name"]: r["status"] for r in core.snapshot()}
    assert rows["Line A"] == "down" and rows["Line B"] == "down" and rows["Line C"] == "up"
    assert rows["Both lines down"] == "down"
    assert rows["Line A+C down"] == "up"
    assert rows["Behind both"] == "skipped"


def test_deleting_a_dependency_target_cleans_references(home):
    store = Store()
    a = make(store, "tcp", "Parent", host="127.0.0.1", port=1)
    b = make(store, "tcp", "Child", host="127.0.0.1", port=2)
    b.depends = [a.id]
    store.update(b)
    comp = make(store, "compound", "Combo", monitors=f"{a.id},{b.id}", min_fail=1)
    store.remove(a.id)
    assert store.by_id(b.id).depends == []
    assert store.by_id(comp.id).params["monitors"] == b.id
    res = config_writer.build(store)
    assert not res.problems, res.problems


def test_disabled_dependency_is_ignored_with_warning(home):
    store = Store()
    a = make(store, "tcp", "Parent", host="127.0.0.1", port=1)
    b = make(store, "tcp", "Child", host="127.0.0.1", port=2)
    b.depends = [a.id]
    store.update(b)
    a.enabled = False
    store.update(a)
    res = config_writer.build(store)
    assert res.active == ["Child"]
    assert any("Parent" in p for p in res.problems)
    from netbeacon.engine import EngineCore
    core = EngineCore(store, History())
    core._rebuild()
    assert "Child" in core.sm.monitors


def test_store_survives_corrupt_files(home):
    from netbeacon import paths
    paths.settings_file().write_text("{ not json", encoding="utf-8")
    paths.monitors_file().write_text("[1, 2", encoding="utf-8")
    s = Store()
    assert s.monitors == [] and s.get("interval") == 30
    assert list(home.glob("settings.json.broken-*"))
