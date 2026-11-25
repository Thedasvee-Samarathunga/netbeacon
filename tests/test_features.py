"""Tests for the 1.1 features: diagnosis, speed test, Wi-Fi parsing, weekly summary, Wake-on-LAN, broadcast alerts."""
import http.server
import socket
import socketserver
import threading
import time
from types import SimpleNamespace

import pytest

from netbeacon import diagnose, digest, netutil, notify, speedtest, wifi
from netbeacon.checks import CHECKS
from netbeacon.netutil import NetInfo, PingResult
from netbeacon.store import ST_DOWN, ST_UP, History, MonitorDef, Store


# ----------------------------------------------------------------- diagnosis
def fake_probes(router=True, internet=True, dns=True, public_dns=True, web=True, nets=True, check_ok=None, wifi_signal=None):
    import ipaddress

    def ping(host, count=1, timeout=1.0):
        up = {"192.168.1.1": router, "1.1.1.1": internet, "8.8.8.8": internet}.get(host, True)
        return PingResult(up, count, count if up else 0, avg_ms=3.0 if up else None, error="" if up else "request timed out")

    def dns_system(name):
        if not dns:
            raise OSError("getaddrinfo failed")
        return ["93.184.216.34"]

    def dns_direct(name, server):
        if not public_dns:
            raise netutil.DnsError("no answer")
        return ["93.184.216.34"]

    w = None
    if wifi_signal is not None:
        w = wifi.WifiStatus(available=True, connected=True, ssid="Office", signal=wifi_signal, channel=6, band="2.4 GHz")
    return diagnose.Probes(
        networks=lambda: [NetInfo("Ethernet", "192.168.1.10", "255.255.255.0", ipaddress.ip_network("192.168.1.0/24"))] if nets else [],
        gateway=lambda: "192.168.1.1" if nets else None,
        ping=ping,
        tcp=lambda h, p, t=1.0: (False, 0.0, "timed out"),
        dns_system=dns_system, dns_direct=dns_direct,
        http=lambda url, t=5.0, expect="": (web, 200 if web else None, "ok" if web else "could not connect", 40.0),
        wifi=lambda: w,
        run_check=(lambda m: (check_ok, "port 445 on 192.168.1.20: connection refused (port closed)" if not check_ok else "port open"))
        if check_ok is not None else None,
    )


@pytest.mark.parametrize("kwargs,culprit,words", [
    (dict(), "", "healthy"),
    (dict(nets=False), "pc", "isn't connected"),
    (dict(router=False), "router", "can't reach the router"),
    (dict(internet=False), "internet", "internet provider"),
    (dict(dns=False), "dns", "DNS server isn't answering"),
    (dict(dns=False, public_dns=False), "dns", "no DNS server"),
    (dict(web=False), "web", "web pages don't load"),
])
def test_diagnosis_finds_the_first_broken_link(kwargs, culprit, words):
    d = diagnose.run(fake_probes(**kwargs))
    assert d.culprit == culprit, d.as_text()
    assert words in d.verdict
    assert d.advice
    assert "Verdict" in d.as_text()


def test_diagnosis_of_a_check_blames_the_check():
    m = MonitorDef.new("tcp", "File server", {**CHECKS["tcp"].defaults(), "host": "192.168.1.20", "port": 445})
    d = diagnose.run(fake_probes(check_ok=False, internet=False), check=m)
    # the target is on the LAN, so a broken internet is NOT the cause - the service is
    assert d.culprit == "target"
    assert "isn't running" in " ".join(d.advice)
    assert any("Internet" in a for a in d.also)


def test_diagnosis_router_failure_beats_check_failure_and_mentions_weak_wifi():
    m = MonitorDef.new("tcp", "File server", {**CHECKS["tcp"].defaults(), "host": "192.168.1.20", "port": 445})
    d = diagnose.run(fake_probes(router=False, check_ok=False, wifi_signal=25), check=m)
    assert d.culprit == "router"
    assert "Wi-Fi signal is weak" in d.advice[0]
    assert [s.key for s in d.steps][:3] == ["pc", "wifi", "router"]


def test_diagnosis_cancel_stops_early():
    ev = threading.Event()
    ev.set()
    d = diagnose.run(fake_probes(), cancel=ev)
    assert len(d.steps) <= 3


# ----------------------------------------------------------------- speed test against a local fake server
class _SpeedHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse
        n = int(parse_qs(urlparse(self.path).query).get("bytes", ["0"])[0])
        self.send_response(200)
        self.send_header("Content-Length", str(n))
        self.end_headers()
        chunk = b"x" * 65536
        while n > 0:
            self.wfile.write(chunk[:min(n, 65536)])
            n -= 65536

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        while n > 0:
            n -= len(self.rfile.read(min(n, 65536)))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


@pytest.fixture()
def speed_server():
    class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
    srv = S(("127.0.0.1", 0), _SpeedHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_speed_test_measures_against_server(speed_server):
    said = []
    r = speedtest.run(speed_server, max_down_mb=3, max_up_mb=2, streams=3, progress=said.append)
    assert r.ok, r.error
    assert r.down_mbps > 1 and r.up_mbps > 1
    assert r.latency_ms is not None and r.jitter_ms is not None
    assert r.bytes_down >= 3 * 1024 * 1024 - 3 and r.bytes_up >= 2 * 1024 * 1024 - 3
    assert said[-1] == "Done"


def test_speed_test_unreachable_server_reports_error():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    r = speedtest.run(f"http://127.0.0.1:{port}", 1, 1)
    assert not r.ok and "could not connect" in r.error


def test_speed_verdict():
    assert "good" in speedtest.verdict(90, 100)[0]
    assert "only 30%" in speedtest.verdict(30, 100)[0]
    assert speedtest.verdict(50, 0)[0] == "50 Mbit/s"


# ----------------------------------------------------------------- Wi-Fi parsing
IFACES_EN = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : 1234abcd-0000-0000-0000-000000000000
    Physical address       : a0:b1:c2:d3:e4:f5
    Interface type         : Primary
    State                  : connected
    SSID                   : OfficeNet
    AP BSSID               : 11:22:33:44:55:66
    Band                   : 2.4 GHz
    Channel                : 4
    Network type           : Infrastructure
    Radio type             : 802.11n
    Authentication         : WPA2-Personal
    Cipher                 : CCMP
    Connection mode        : Auto Connect
    Receive rate (Mbps)    : 144.4
    Transmit rate (Mbps)   : 72
    Signal                 : 38%
    Rssi                   : -81
    Profile                : OfficeNet

    Hosted network status  : Not available
"""

IFACES_DE = """
Es ist 1 Schnittstelle auf dem System vorhanden:

    Name                   : WLAN
    Beschreibung           : Realtek 8822CE
    GUID                   : 1234
    Physische Adresse      : a0:b1:c2:d3:e4:f5
    Status                 : Verbunden
    SSID                   : Buero
    BSSID                  : aa:bb:cc:dd:ee:01
    Funktyp                : 802.11ac
    Authentifizierung      : WPA2-Personal
    Kanal                  : 36
    Empfangsrate (MBit/s)  : 866.7
    Übertragungsrate (MBit/s) : 866.7
    Signal                 : 88%
"""

IFACES_OFF = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : 1234
    Physical address       : a0:b1:c2:d3:e4:f5
    State                  : disconnected
    Radio status           : Hardware On
                             Software On
"""

NETWORKS = """
Interface name : Wi-Fi
There are 3 networks currently visible.

SSID 1 : OfficeNet
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP
    BSSID 1                 : 11:22:33:44:55:66
         Signal             : 38%
         Radio type         : 802.11n
         Band               : 2.4 GHz
         Channel            : 4
         Connected Stations : 3
         Channel Utilization: 41 (16 %)
         Basic rates (Mbps) : 1 2 5.5 11
    BSSID 2                 : 11:22:33:44:55:67
         Signal             : 80%
         Radio type         : 802.11ax
         Band               : 5 GHz
         Channel            : 44

SSID 2 : Neighbour
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    BSSID 1                 : 22:22:22:22:22:22
         Signal             : 90%
         Radio type         : 802.11n
         Channel            : 6

SSID 3 :
    Network type            : Infrastructure
    Authentication          : Open
    BSSID 1                 : 33:33:33:33:33:33
         Signal             : 60%
         Channel            : 1
"""


def test_parse_interfaces_english():
    st = wifi.parse_interfaces(IFACES_EN)
    assert st.available and st.connected
    assert (st.ssid, st.bssid, st.signal, st.rssi, st.channel, st.band) == ("OfficeNet", "11:22:33:44:55:66", 38, -81, 4, "2.4 GHz")
    assert (st.rx_mbps, st.tx_mbps, st.radio, st.auth) == (144.4, 72.0, "802.11n", "WPA2-Personal")
    assert st.dbm == -81


def test_parse_interfaces_german_and_disconnected():
    st = wifi.parse_interfaces(IFACES_DE)
    assert st.connected and st.ssid == "Buero" and st.signal == 88 and st.channel == 36 and st.band == "5 GHz"
    assert st.rx_mbps == 866.7 and st.dbm == wifi.signal_to_dbm(88)
    off = wifi.parse_interfaces(IFACES_OFF)
    assert off.available and not off.connected and off.signal is None


def test_parse_networks_and_advice():
    nets, note = wifi.parse_networks(NETWORKS)
    assert note == ""
    assert [(n.ssid, n.channel, n.band) for n in nets] == [("OfficeNet", 4, "2.4 GHz"), ("OfficeNet", 44, "5 GHz"),
                                                           ("Neighbour", 6, "2.4 GHz"), ("", 1, "2.4 GHz")]
    assert nets[3].auth == "Open"
    sc = wifi.crowding(nets, "2.4 GHz")
    assert sc[6] > sc[11]
    assert wifi.best_24_channel(nets) == 11
    tips = " ".join(wifi.advice(wifi.parse_interfaces(IFACES_EN), nets))
    assert "poor" in tips and "Channel 4 overlaps" in tips and "2.4 GHz" in tips


def test_location_permission_message():
    st = wifi.parse_interfaces("Network shell commands need location permission to access WLAN information.")
    assert not st.available and "Location" in st.note
    nets, note = wifi.parse_networks("Network shell commands need location permission to access WLAN information.")
    assert nets == [] and "Location" in note


def test_wifi_check_builds(home):
    from netbeacon import config_writer
    store = Store()
    store.add(MonitorDef.new("wifi", "Wi-Fi signal", {**CHECKS["wifi"].defaults()}))
    res = config_writer.build(store)
    assert not res.problems and res.types["Wi-Fi signal"] == "lan_wifi"


# ----------------------------------------------------------------- weekly summary
def test_digest_sentences(home):
    store, h = Store(), History()
    now = time.time()
    since = now - 7 * 86400
    store.add(MonitorDef.new("ping", "Internet connection", {**CHECKS["ping"].defaults(), "host": "1.1.1.1"}))
    store.add(MonitorDef.new("tcp", "Printer", {**CHECKS["tcp"].defaults(), "host": "192.168.1.50", "port": 9100}))
    disk = store.add(MonitorDef.new("disk", "Disk C", {**CHECKS["disk"].defaults(), "path": "C:\\", "min_free_percent": 10}))
    for name in ("Internet connection", "Printer"):
        for i in range(100):
            h.add_result(since + i * 3600, name, ST_UP, 5.0, "ok")
    # two internet drops of 10 and 5 minutes
    h.open_incident("Internet connection", now - 3 * 86400, "no reply")
    h.close_incident("Internet connection", now - 3 * 86400 + 600)
    h.open_incident("Internet connection", now - 86400, "no reply")
    h.close_incident("Internet connection", now - 86400 + 300)
    # a flapping printer
    for k in range(5):
        h.open_incident("Printer", now - 5 * 86400 + k * 7200, "timed out")
        h.close_incident("Printer", now - 5 * 86400 + k * 7200 + 120)
    # a disk losing 2 GB a day: 500 GB total, 100 GB free now
    for k in range(15):
        free = 128 - 2 * k
        h.add_result(now - (14 - k) * 86400, disk.name, ST_UP, None, f"{free:.1f} GB free ({free / 5:.0f}%) on C:\\")
    h.add_speedtest(now - 7200, 40.0, 9.0, 12.0, 1.0, "test")
    h.add_speedtest(now - 3600, 60.0, 11.0, 12.0, 1.0, "test")
    store.set("speed_paid_down", 100)
    for k in range(6):
        h.add_wifi_sample(now - k * 600, "Office", "aa", 50 + k, 6, "2.4 GHz", 72, 72)
    h.add_event(now - 1000, "warn", None, "New device(s) on the network: 192.168.1.77")
    d = digest.build(store, h, since, now)
    text = d.text()
    assert "The internet dropped twice, 15 minutes in total" in text
    assert "Printer was down 5 times" in text and "flapping" in text
    assert "Drive C:\\ is filling up" in text and "shrinking by about 2.0 GB a day" in text
    assert "averaged 50 Mbit/s down / 10 up over 2 test(s) (50% of the 100 Mbit/s" in text
    assert "Wi-Fi signal averaged" in text and "New devices joined" in text
    assert d.mood == "warn"
    assert "<h2" in d.html() and "&lt;" not in d.headline


def test_digest_forecast_math(home):
    h = History()
    now = time.time()
    for k in range(10):
        h.add_result(now - (9 - k) * 86400, "D", ST_UP, None, f"{100 - 5 * k:.1f} GB free ({(100 - 5 * k) / 4:.0f}%) on X")
    fc = digest.disk_forecast(h, "D", 0, 10, now)
    assert fc["per_day_gb"] == pytest.approx(-5, abs=0.01)
    # 55 GB free now, 400 GB disk -> limit 40 GB -> 15 GB to go at 5 GB/day = 3 days
    assert fc["days_left"] == pytest.approx(3, abs=0.3)


def test_digest_empty_and_schedule(home):
    d = digest.build(Store(), History(), time.time() - 86400)
    assert "Nothing is being monitored" in d.headline
    import datetime as dt
    monday_10 = dt.datetime(2026, 11, 23, 10, 0).timestamp()        # a Monday
    slot = digest.last_slot(monday_10, 0, 9)
    assert dt.datetime.fromtimestamp(slot) == dt.datetime(2026, 11, 23, 9, 0)
    assert digest.is_due(monday_10, 0, 9, last_sent=slot - 1)
    assert not digest.is_due(monday_10, 0, 9, last_sent=slot + 5)
    monday_8 = dt.datetime(2026, 11, 23, 8, 0).timestamp()
    assert dt.datetime.fromtimestamp(digest.last_slot(monday_8, 0, 9)) == dt.datetime(2026, 11, 16, 9, 0)


# ----------------------------------------------------------------- Wake-on-LAN
def test_magic_packet_and_send():
    pkt = netutil.magic_packet("aa-bb-cc-dd-ee-ff")
    assert len(pkt) == 102 and pkt[:6] == b"\xff" * 6 and pkt[6:12] == bytes.fromhex("aabbccddeeff")
    with pytest.raises(ValueError):
        netutil.magic_packet("not a mac")
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(3)
    sent = netutil.wake_on_lan("AA:BB:CC:DD:EE:FF", ["127.0.0.1"], rx.getsockname()[1])
    assert sent == ["127.0.0.1"]
    assert rx.recvfrom(200)[0] == pkt
    rx.close()


# ----------------------------------------------------------------- broadcast + email
def test_broadcast_uses_desktop_and_reports_channel_errors(home):
    from netbeacon.sm_ext import bridge
    got = []
    bridge.on_notify = lambda t, x, l: got.append((t, x, l))
    store = Store()
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dead = s.getsockname()[1]
    s.close()
    store.settings["channels"]["email"].update({"enabled": True, "host": "127.0.0.1", "port": dead, "from": "a@b.c", "to": "d@e.f", "ssl": ""})
    res = notify.broadcast(store, "New device on your network", "192.168.1.77 joined")
    assert res["desktop"] == "" and got[0][0] == "New device on your network"
    assert res["email"]                      # the dead mail server is reported, not raised


def test_send_email_with_a_tiny_smtp_server(home):
    received = {}

    def serve(sock):
        conn, _ = sock.accept()
        f = conn.makefile("rwb")

        def w(line):
            f.write(line.encode() + b"\r\n")
            f.flush()
        w("220 test")
        data_mode, body = False, []
        while True:
            line = f.readline().decode().rstrip("\r\n")
            if data_mode:
                if line == ".":
                    data_mode = False
                    received["body"] = "\n".join(body)
                    w("250 ok")
                else:
                    body.append(line)
                continue
            cmd = line.split(" ")[0].upper()
            if cmd in ("EHLO", "HELO"):
                w("250 test")
            elif cmd == "DATA":
                data_mode = True
                w("354 go")
            elif cmd == "QUIT":
                w("221 bye")
                break
            else:
                received.setdefault("cmds", []).append(line)
                w("250 ok")
        conn.close()

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    threading.Thread(target=serve, args=(sock,), daemon=True).start()
    store = Store()
    store.settings["channels"]["email"].update({"host": "127.0.0.1", "port": sock.getsockname()[1], "from": "nb@x.y", "to": "a@x.y; b@x.y", "ssl": ""})
    ok, msg = notify.send_email(store, "Weekly summary", "plain", "<b>html</b>")
    assert ok, msg
    assert "Subject: Weekly summary" in received["body"] and "<b>html</b>" in received["body"]
    assert any("b@x.y" in c for c in received["cmds"])


def test_new_tables_purge_and_clear(home):
    h = History()
    old = time.time() - 400 * 86400
    h.add_speedtest(old, 1, 1, 1, 1, "s")
    h.add_speedtest(time.time(), 2, 2, 2, 2, "s")
    h.add_wifi_sample(time.time() - 40 * 86400, "a", "b", 50, 6, "2.4 GHz", 1, 1)
    h.purge(30)
    assert len(h.speedtests()) == 1 and h.wifi_samples() == []
    h.clear_all()
    assert h.speedtests() == []
