"""'What's wrong?' - a step-by-step diagnosis that finds WHERE the network breaks.

It walks outwards from this PC, the way an experienced technician would:

    this PC  ->  Wi-Fi link  ->  router  ->  internet (by number)  ->  DNS (names)  ->  the web  ->  [the check you asked about]

The first step that fails is almost always the cause; everything after it fails *because* of it.
Big monitoring tools call this "root cause analysis" or "topology-aware alerting".

No Qt in here: every network call goes through a `Probes` object, so tests can fake a broken router
or a dead DNS server without touching a real network.
"""
from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import netutil

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"

PUBLIC_IPS = ("1.1.1.1", "8.8.8.8")
TEST_NAME = "example.com"
NCSI_URL = "http://www.msftconnecttest.com/connecttest.txt"   # what Windows itself uses to detect "No internet"
NCSI_TEXT = "Microsoft Connect Test"
HTTPS_URL = "https://www.example.com/"


@dataclass
class Step:
    key: str
    title: str
    status: str = SKIP           # ok | warn | fail | skip
    detail: str = ""             # what we measured
    teach: str = ""              # what this step proves (teaching mode)
    ms: Optional[float] = None


@dataclass
class Diagnosis:
    steps: list[Step] = field(default_factory=list)
    verdict: str = ""            # one plain-English sentence
    advice: list[str] = field(default_factory=list)
    culprit: str = ""            # key of the step that is the likely cause ("" = nothing found)
    also: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    finished: float = 0.0

    @property
    def level(self) -> str:
        if self.culprit:
            return FAIL
        return WARN if any(s.status == WARN for s in self.steps) else OK

    def as_text(self) -> str:
        icon = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]", SKIP: "[SKIP]"}
        lines = [f"NetBeacon diagnosis - {time.strftime('%d %b %Y %H:%M', time.localtime(self.started))}", "",
                 f"Verdict: {self.verdict}", ""]
        for s in self.steps:
            lines.append(f"{icon[s.status]} {s.title}: {s.detail}")
        if self.advice:
            lines += ["", "What to do:"] + [f"  - {a}" for a in self.advice]
        if self.also:
            lines += ["", "Also noticed:"] + [f"  - {a}" for a in self.also]
        return "\n".join(lines)


# --------------------------------------------------------------------------- probes (replaceable in tests)
def _dns_system(name: str) -> list[str]:
    infos = socket.getaddrinfo(name, None, socket.AF_INET, socket.SOCK_STREAM)
    return sorted({i[4][0] for i in infos})


def _dns_direct(name: str, server: str) -> list[str]:
    return netutil.dns_query(name, "A", server, 3.0)[0]


def _wifi() -> Any:
    from . import wifi
    return wifi.read_status()


@dataclass
class Probes:
    networks: Callable[[], list] = netutil.local_networks
    gateway: Callable[[], Optional[str]] = netutil.default_gateway
    ping: Callable[..., Any] = netutil.ping_host
    tcp: Callable[..., tuple] = netutil.tcp_connect
    dns_system: Callable[[str], list[str]] = _dns_system
    dns_direct: Callable[[str, str], list[str]] = _dns_direct
    http: Callable[..., tuple] = netutil.http_probe
    wifi: Callable[[], Any] = _wifi
    run_check: Optional[Callable[[Any], tuple[bool, str]]] = None   # (ok, message) for a MonitorDef


def _is_private(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return host.endswith((".local", ".lan", ".home", ".internal", ".corp")) or "." not in host


def _target_host(m: Any) -> str:
    p = getattr(m, "params", {}) or {}
    if p.get("host"):
        return str(p["host"]).strip()
    url = str(p.get("url", ""))
    if "//" in url:
        return url.split("//", 1)[1].split("/", 1)[0].split(":")[0]
    return ""


# --------------------------------------------------------------------------- the diagnosis
def run(probes: Optional[Probes] = None, check: Any = None, on_step: Optional[Callable[[Step], None]] = None,
        cancel: Optional[Any] = None) -> Diagnosis:
    """Run every step (later steps still run after a failure - the full picture teaches more)."""
    pr = probes or Probes()
    d = Diagnosis()

    def add(step: Step) -> Step:
        d.steps.append(step)
        if on_step:
            on_step(step)
        return step

    def cancelled() -> bool:
        return bool(cancel is not None and cancel.is_set())

    # 1. this PC -----------------------------------------------------------------
    s = Step("pc", "This PC is on a network", teach="Checks that this computer has a working network adapter with an address. "
             "If not, nothing else can work: it's a cable, Wi-Fi or adapter problem on this PC.")
    try:
        nets = pr.networks()
    except Exception as exc:  # noqa: BLE001
        nets = []
        s.detail = f"could not read network adapters: {exc}"
    if nets:
        s.status, s.detail = OK, ", ".join(f"{n.iface} {n.ip}" for n in nets[:3])
    else:
        s.status = FAIL
        s.detail = s.detail or "no active network adapter with an IP address"
    add(s)

    # 1b. Wi-Fi (only if this PC is on Wi-Fi) ----------------------------------------
    try:
        w = pr.wifi()
    except Exception:  # noqa: BLE001
        w = None
    if w is not None and getattr(w, "available", False) and getattr(w, "connected", False):
        from . import wifi as wifimod
        word, _ = wifimod.quality(w.signal)
        s = Step("wifi", "Wi-Fi link", teach="Your PC talks to the router over radio. A weak signal causes slowness and drop-outs "
                 "even when everything else is fine.")
        s.detail = f"{w.ssid}: signal {w.signal}% ({word}), {w.band or '?'} channel {w.channel or '?'}"
        s.status = OK if (w.signal or 0) >= 40 else WARN
        add(s)

    # 2. router --------------------------------------------------------------------
    s = Step("router", "Router answers", teach="The router (your 'default gateway') is the door from your office network to everything else. "
             "If this PC can't reach it, the problem is local: the router, a switch, a cable or the Wi-Fi.")
    gw = None
    try:
        gw = pr.gateway()
    except Exception:  # noqa: BLE001
        gw = None
    if cancelled():
        return _finish(d, check)
    if not gw:
        s.status = FAIL if not nets else WARN
        s.detail = "no default gateway is set (this PC doesn't know its router)"
    else:
        r = pr.ping(gw, 2, 2.0)
        if r.ok:
            s.status, s.ms = OK, r.avg_ms
            s.detail = f"{gw} replied in {r.avg_ms:.0f} ms" if r.avg_ms is not None else f"{gw} replied"
            if r.loss_pct > 0:
                s.status = WARN
                s.detail += f", but {r.loss_pct:.0f}% of packets were lost"
        else:
            # some routers ignore ping - try the doors routers usually have open
            opened = next((p for p in (53, 80, 443) if pr.tcp(gw, p, 1.5)[0]), None)
            if opened:
                s.status, s.detail = OK, f"{gw} ignores ping but answers on port {opened}"
            else:
                s.status, s.detail = FAIL, f"{gw} does not answer ({r.error or 'no reply'})"
    add(s)

    # 3. internet by number ------------------------------------------------------------------
    s = Step("internet", "Internet reachable (by number)", teach="Pings well-known public addresses (1.1.1.1, 8.8.8.8). "
             "This skips DNS, so it proves the raw internet connection - your modem and your provider - works.")
    if cancelled():
        return _finish(d, check)
    best = None
    for ip in PUBLIC_IPS:
        r = pr.ping(ip, 2, 2.0)
        if r.ok:
            best = (ip, r)
            break
    if best:
        ip, r = best
        s.status, s.ms = OK, r.avg_ms
        s.detail = f"{ip} replied in {r.avg_ms:.0f} ms" if r.avg_ms is not None else f"{ip} replied"
        if r.avg_ms is not None and r.avg_ms > 150:
            s.status, s.detail = WARN, s.detail + " - that is slow for a nearby server"
    else:
        tcp_ok = next((ip for ip in PUBLIC_IPS if pr.tcp(ip, 443, 2.5)[0]), None)
        if tcp_ok:
            s.status, s.detail = OK, f"ping is blocked, but {tcp_ok}:443 answers (a firewall is filtering ping)"
        else:
            s.status, s.detail = FAIL, "neither 1.1.1.1 nor 8.8.8.8 answers"
    add(s)

    # 4. DNS -----------------------------------------------------------------------------------
    s = Step("dns", "Names work (DNS)", teach="Turns 'example.com' into an address using this PC's DNS settings. When this fails but the "
             "step above works, people say 'the internet is down' - but really only the internet's phone book is.")
    if cancelled():
        return _finish(d, check)
    t0 = time.perf_counter()
    dns_ok = False
    try:
        ans = pr.dns_system(TEST_NAME)
        dns_ok = bool(ans)
        s.ms = (time.perf_counter() - t0) * 1000
        s.status, s.detail = OK, f"{TEST_NAME} -> {', '.join(ans[:2])} ({s.ms:.0f} ms)"
    except Exception as exc:  # noqa: BLE001
        s.status = FAIL
        s.detail = f"this PC's DNS could not look up {TEST_NAME} ({str(exc)[:80]})"
        try:
            pr.dns_direct(TEST_NAME, PUBLIC_IPS[0])
            s.detail += f"; but asking {PUBLIC_IPS[0]} directly works"
            s.ms = -1.0          # marker: public DNS works
        except Exception:  # noqa: BLE001
            s.detail += f"; asking {PUBLIC_IPS[0]} directly fails too"
    add(s)

    # 5. the web ------------------------------------------------------------------------------
    s = Step("web", "Web pages load", teach="Downloads Microsoft's tiny connectivity-test page (the same one Windows uses for its 'No internet' "
             "icon) and a secure page. If the first returns something else, you are behind a login page (hotel / guest Wi-Fi) or a proxy.")
    if cancelled():
        return _finish(d, check)
    ok1, code1, msg1, ms1 = pr.http(NCSI_URL, 6.0, NCSI_TEXT)
    ok2, code2, msg2, ms2 = pr.http(HTTPS_URL, 8.0)
    if ok1 and ok2:
        s.status, s.ms, s.detail = OK, ms2, f"test page and {HTTPS_URL} load ({ms2:.0f} ms)"
    elif ok2 and not ok1:
        s.status, s.detail = WARN, f"secure page loads, but the test page didn't ({msg1})"
    elif ok1 and not ok2:
        s.status, s.detail = WARN, f"test page loads, but {HTTPS_URL} doesn't ({msg2})"
    else:
        s.status = FAIL
        s.detail = f"no web page loads ({msg1})" if code1 is None else f"the test page was replaced by something else (HTTP {code1}) - probably a login page or proxy"
    add(s)

    # 6. the check the user asked about ---------------------------------------------------------
    if check is not None and not cancelled():
        host = _target_host(check)
        if host and netutil.is_valid_host(host):
            s = Step("target_reach", f"{host} is reachable", teach="Can this PC reach the device or server the check is about at all?")
            r = pr.ping(host, 2, 2.0)
            if r.ok:
                s.status, s.ms = OK, r.avg_ms
                s.detail = f"replied in {r.avg_ms:.0f} ms" if r.avg_ms is not None else "replied"
            else:
                s.status, s.detail = WARN, f"no ping reply ({r.error or 'no reply'}) - many servers ignore ping, so this alone proves little"
            add(s)
        if pr.run_check is not None:
            s = Step("target", f"The check itself: {getattr(check, 'name', '')}", teach="Runs the check once, right now, exactly as the engine does.")
            try:
                ok, msg = pr.run_check(check)
                s.status, s.detail = (OK if ok else FAIL), msg or ""
            except Exception as exc:  # noqa: BLE001
                s.status, s.detail = FAIL, f"could not run it: {exc}"
            add(s)
    return _finish(d, check)


# --------------------------------------------------------------------------- the verdict
def _step(d: Diagnosis, key: str) -> Optional[Step]:
    return next((s for s in d.steps if s.key == key), None)


def _check_advice(check: Any, message: str) -> list[str]:
    kind = getattr(check, "kind", "")
    m = (message or "").lower()
    if "refused" in m:
        return ["The machine is on, but the program behind that port isn't running. Restart the service or program on that machine.",
                "If it keeps stopping, look at that machine's event log, disk space and memory."]
    if "timed out" in m or "no reply" in m or "unreachable" in m:
        return ["The machine doesn't answer at all: check that it's switched on and plugged in, and that its IP address hasn't changed.",
                "If it is on, a firewall may be blocking the connection."]
    if kind == "http":
        if any(c in m for c in ("http 5", " 50", "502", "503", "500")):
            return ["The web server answers, but the application behind it is failing (5xx error). Contact whoever hosts the site."]
        if "404" in m:
            return ["The page address doesn't exist (404). Check the address in the check, or ask whoever maintains the site."]
        if "certificate" in m or "tls" in m:
            return ["The site's security certificate has a problem - often expired. Ask whoever hosts the site to renew it."]
        return ["The site answers but not as expected. Open it in a browser to see what visitors see."]
    if kind == "tls":
        return ["Renew the certificate before it expires (or check that automatic renewal, e.g. Let's Encrypt, is still working)."]
    if kind == "disk":
        return ["Free up space: empty the Recycle Bin, run Disk Cleanup, move old files or backups elsewhere."]
    if kind == "file":
        return ["The backup didn't run or didn't finish. Open your backup software and check its last job and error log."]
    if kind in ("service", "process"):
        return ["Start it again (Services app: right-click > Start), then check the Windows event log for why it stopped."]
    if kind == "wifi":
        return ["Move closer to the access point or reduce obstacles. The Wi-Fi page has more detailed advice."]
    if kind == "dns":
        return ["The DNS record or the DNS server is the problem. Compare the answer with what your domain provider shows."]
    return ["Open the check (Edit) and use 'Test this check now' after fixing; its message says what failed."]


def _finish(d: Diagnosis, check: Any = None) -> Diagnosis:
    d.finished = time.time()
    st = {s.key: s for s in d.steps}
    host = _target_host(check) if check is not None else ""
    local_target = bool(host) and _is_private(host)
    order = ["pc", "router"] if local_target else ["pc", "router", "internet", "dns", "web"]
    culprit = next((k for k in order if k in st and st[k].status == FAIL), "")
    if not culprit and "target" in st and st["target"].status == FAIL:
        culprit = "target"
    d.culprit = culprit

    gw_detail = st["router"].detail.split(" ")[0] if "router" in st else "the router"
    if culprit == "pc":
        d.verdict = "This PC isn't connected to any network - the problem is right here, not out on the network."
        d.advice = ["Check the network cable is clicked in at both ends (the light on the port should blink), or that Wi-Fi is on and connected.",
                    "Turn off Airplane mode. Try another PC: if it works, this PC's network adapter or driver is the problem."]
    elif culprit == "router":
        d.verdict = "This PC can't reach the router, so nothing beyond it can work. The problem is inside your office network."
        d.advice = ["Look at the router: is it powered on, are its lights normal? A router that is restarting takes 2-5 minutes.",
                    "If other PCs work fine, the problem is this PC's cable, switch port or Wi-Fi connection.",
                    "If no PC works, restart the router (unplug for 30 seconds)."]
        if "wifi" in st and st["wifi"].status == WARN:
            d.advice.insert(0, "The Wi-Fi signal is weak - move closer to the access point and try again.")
    elif culprit == "internet":
        d.verdict = "Your office network is fine, but the internet beyond your router isn't reachable. This is usually the modem or your internet provider."
        d.advice = ["Check the modem / fibre box lights (often a red or blinking 'internet', 'PON' or 'LOS' light).",
                    "Restart the modem, then the router (unplug for 30 seconds each, modem first).",
                    "Still down after 10 minutes? Call your provider and tell them: 'the router is reachable but nothing past it is'."]
    elif culprit == "dns":
        public = "dns" in st and st["dns"].ms == -1.0
        if public:
            d.verdict = "The internet works, but your DNS server isn't answering - so websites 'don't work' even though the connection is fine."
            d.advice = [f"Restart the router: it usually acts as the DNS server ({gw_detail}) and its DNS often gets stuck.",
                        "As a quick fix, set this PC's DNS server to 1.1.1.1 and 8.8.8.8 (adapter settings > IPv4).",
                        "If you have a Windows server doing DNS (Active Directory), check its DNS Server service."]
        else:
            d.verdict = "The internet answers, but no DNS server does - something is blocking name lookups."
            d.advice = ["A firewall or security filter may be blocking DNS (port 53). Check recent changes to the firewall.",
                        "Restart the router, then try again."]
    elif culprit == "web":
        d.verdict = "Basic internet and names work, but web pages don't load. Something between you and the web is interfering."
        d.advice = ["On guest or hotel Wi-Fi, open a browser: a login or 'accept terms' page may be waiting.",
                    "Check for a proxy or web filter (Settings > Network & internet > Proxy) and any firewall or antivirus web protection."]
    elif culprit == "target":
        msg = st["target"].detail
        d.verdict = (f"Your network and internet are fine. The problem is '{getattr(check, 'name', 'the check')}' itself: {msg}"
                     if not local_target else f"Your network is fine. The problem is '{getattr(check, 'name', 'the check')}' itself: {msg}")
        d.advice = _check_advice(check, msg)
    else:
        if check is not None and "target" in st and st["target"].status == OK:
            d.verdict = f"Everything checks out, including '{getattr(check, 'name', 'the check')}' - it has recovered or the problem was brief."
            d.advice = ["If it keeps happening, look at its history on the Uptime page: many short outages (flapping) point to a flaky cable, "
                        "Wi-Fi or an overloaded device."]
        else:
            d.verdict = "Everything NetBeacon can test from this PC looks healthy."
            d.advice = ["If one program or device still misbehaves, right-click its check on the Dashboard and choose 'What's wrong with this?'.",
                        "If everything is just slow, run a test on the Internet speed page."]

    full = ["pc", "wifi", "router", "internet", "dns", "web", "target_reach", "target"]

    def pos(k: str) -> int:
        return full.index(k) if k in full else 99

    for s in d.steps:
        if s.key != culprit and s.status in (FAIL, WARN):
            if culprit and s.status == FAIL and pos(culprit) < pos(s.key) and s.key in order + ["target"]:
                continue     # failing *because* of the culprit - not worth repeating
            d.also.append(f"{s.title}: {s.detail}")
    return d
