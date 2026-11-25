"""Network helpers used by the checks and by the discovery tools.

Everything here is plain Python + the operating system's own tools (ping, arp),
so it works without administrator rights.
"""
from __future__ import annotations

import concurrent.futures as cf
import ipaddress
import os
import random
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

_HOST_RE = re.compile(r"^[A-Za-z0-9_.:%\-\[\]]+$")


def is_valid_host(host: str) -> bool:
    """Very strict host check - also stops anything starting with '-' being read as an option."""
    host = (host or "").strip()
    return bool(host) and not host.startswith("-") and len(host) <= 253 and bool(_HOST_RE.match(host))


# --------------------------------------------------------------------------- ping
@dataclass
class PingResult:
    ok: bool
    sent: int
    received: int
    avg_ms: Optional[float] = None
    min_ms: Optional[float] = None
    max_ms: Optional[float] = None
    error: str = ""

    @property
    def loss_pct(self) -> float:
        return 100.0 * (self.sent - self.received) / self.sent if self.sent else 100.0


_TTL_RE = re.compile(r"ttl\s*=\s*\d+", re.I)
_TIME_RE = re.compile(r"[=<]\s*(\d+(?:[.,]\d+)?)\s*ms", re.I)


def parse_ping_output(text: str, sent: int) -> PingResult:
    """Count replies and read round-trip times. Works with localised Windows output
    because it keys off 'TTL=' and '<number>ms' rather than English words."""
    received = 0
    times: list[float] = []
    for line in text.splitlines():
        if _TTL_RE.search(line):
            received += 1
            m = _TIME_RE.search(line)
            if m:
                value = float(m.group(1).replace(",", "."))
                if "<" in m.group(0):  # "time<1ms"
                    value = min(value, 0.5)
                times.append(value)
    if received and not times:
        times = [0.0]
    return PingResult(
        ok=received > 0,
        sent=sent,
        received=received,
        avg_ms=(sum(times) / len(times)) if times else None,
        min_ms=min(times) if times else None,
        max_ms=max(times) if times else None,
        error="" if received else "no replies",
    )


def ping_command(host: str, count: int, timeout_s: float) -> list[str]:
    timeout_s = max(1.0, float(timeout_s))
    if IS_WINDOWS:
        return ["ping", "-n", str(count), "-w", str(int(timeout_s * 1000)), host]
    if IS_MAC:
        return ["ping", "-c", str(count), "-W", str(int(timeout_s * 1000)), host]
    return ["ping", "-c", str(count), "-W", str(int(max(1, round(timeout_s)))), host]


def ping_host(host: str, count: int = 3, timeout_s: float = 4.0) -> PingResult:
    if not is_valid_host(host):
        return PingResult(False, count, 0, error=f"'{host}' is not a valid host name or IP address")
    cmd = ping_command(host.strip(), count, timeout_s)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=count * (timeout_s + 1) + 5, check=False
        )
    except FileNotFoundError:
        return PingResult(False, count, 0, error="the 'ping' command was not found on this computer")
    except subprocess.TimeoutExpired:
        return PingResult(False, count, 0, error="ping took too long")
    except OSError as exc:
        return PingResult(False, count, 0, error=str(exc))
    text = (proc.stdout or b"").decode("latin-1", errors="replace")
    result = parse_ping_output(text, count)
    if not result.ok:
        low = text.lower()
        if "could not find host" in low or "unknown host" in low or "name or service not known" in low or "cannot resolve" in low:
            result.error = "name could not be resolved (DNS problem?)"
        elif "unreachable" in low:
            result.error = "host or network unreachable"
        elif "timed out" in low or not low.strip():
            result.error = "request timed out (no reply)"
    return result


# --------------------------------------------------------------------------- tcp
def tcp_connect(host: str, port: int, timeout_s: float = 3.0) -> tuple[bool, float, str]:
    """Return (open?, milliseconds, error text)."""
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True, (time.perf_counter() - start) * 1000.0, ""
    except socket.timeout:
        return False, (time.perf_counter() - start) * 1000.0, "timed out (filtered or host down)"
    except ConnectionRefusedError:
        return False, (time.perf_counter() - start) * 1000.0, "connection refused (port closed)"
    except socket.gaierror as exc:
        return False, 0.0, f"name could not be resolved ({exc})"
    except OSError as exc:
        return False, (time.perf_counter() - start) * 1000.0, str(exc)


# --------------------------------------------------------------------------- DNS
class DnsError(Exception):
    pass


_QTYPES = {"A": 1, "NS": 2, "CNAME": 5, "MX": 15, "TXT": 16, "AAAA": 28}


def _encode_name(name: str) -> bytes:
    out = b""
    for label in name.rstrip(".").split("."):
        raw = label.encode("idna")
        if not 0 < len(raw) < 64:
            raise DnsError(f"bad DNS name '{name}'")
        out += bytes([len(raw)]) + raw
    return out + b"\x00"


def _read_name(data: bytes, offset: int) -> tuple[str, int]:
    labels: list[str] = []
    jumped = False
    end = offset
    hops = 0
    while True:
        if offset >= len(data):
            raise DnsError("malformed DNS reply")
        length = data[offset]
        if length == 0:
            offset += 1
            break
        if length & 0xC0 == 0xC0:
            pointer = ((length & 0x3F) << 8) | data[offset + 1]
            if not jumped:
                end = offset + 2
            offset = pointer
            jumped = True
            hops += 1
            if hops > 30:
                raise DnsError("malformed DNS reply (loop)")
            continue
        offset += 1
        labels.append(data[offset:offset + length].decode("ascii", errors="replace"))
        offset += length
    if not jumped:
        end = offset
    return ".".join(labels), end


def dns_query(name: str, qtype: str = "A", server: Optional[str] = None,
              timeout_s: float = 3.0, port: int = 53) -> tuple[list[str], float]:
    """Resolve `name`. Returns (answers, milliseconds). Raises DnsError."""
    qtype = qtype.upper()
    if qtype not in _QTYPES:
        raise DnsError(f"unsupported record type {qtype}")
    start = time.perf_counter()
    if not server:
        if qtype not in ("A", "AAAA"):
            raise DnsError("choose a DNS server to look up this record type")
        family = socket.AF_INET if qtype == "A" else socket.AF_INET6
        try:
            infos = socket.getaddrinfo(name, None, family, socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise DnsError(f"could not resolve {name} ({exc})") from exc
        answers = sorted({i[4][0] for i in infos})
        return answers, (time.perf_counter() - start) * 1000.0

    qid = random.randint(0, 0xFFFF)
    packet = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0) + _encode_name(name) + struct.pack(">HH", _QTYPES[qtype], 1)
    try:
        family = socket.AF_INET6 if ":" in server else socket.AF_INET
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout_s)
            sock.sendto(packet, (server, port))
            while True:
                data, _ = sock.recvfrom(4096)
                if len(data) >= 12 and struct.unpack(">H", data[:2])[0] == qid:
                    break
    except socket.timeout as exc:
        raise DnsError(f"DNS server {server} did not answer in time") from exc
    except OSError as exc:
        raise DnsError(f"could not talk to DNS server {server}: {exc}") from exc
    elapsed = (time.perf_counter() - start) * 1000.0

    _, flags, qd, an, _, _ = struct.unpack(">HHHHHH", data[:12])
    rcode = flags & 0x0F
    if rcode == 3:
        raise DnsError(f"{name} does not exist (NXDOMAIN)")
    if rcode == 2:
        raise DnsError("DNS server failure (SERVFAIL)")
    if rcode == 5:
        raise DnsError("DNS server refused the query")
    if rcode != 0:
        raise DnsError(f"DNS error code {rcode}")
    offset = 12
    for _ in range(qd):
        _, offset = _read_name(data, offset)
        offset += 4
    answers: list[str] = []
    for _ in range(an):
        _, offset = _read_name(data, offset)
        rtype, _cls, _ttl, rdlen = struct.unpack(">HHIH", data[offset:offset + 10])
        offset += 10
        rdata = data[offset:offset + rdlen]
        if rtype == 1 and rdlen == 4:
            answers.append(socket.inet_ntoa(rdata))
        elif rtype == 28 and rdlen == 16:
            answers.append(socket.inet_ntop(socket.AF_INET6, rdata))
        elif rtype in (2, 5):
            answers.append(_read_name(data, offset)[0])
        elif rtype == 15:
            pref = struct.unpack(">H", rdata[:2])[0]
            answers.append(f"{pref} {_read_name(data, offset + 2)[0]}")
        elif rtype == 16:
            text, i = b"", 0
            while i < rdlen:
                ln = rdata[i]
                text += rdata[i + 1:i + 1 + ln]
                i += 1 + ln
            answers.append(text.decode("utf-8", errors="replace"))
        offset += rdlen
    wanted = _QTYPES[qtype]
    # CNAME chains: keep only the requested type when present
    if not answers:
        raise DnsError(f"no {qtype} records returned for {name}")
    return answers, elapsed


# --------------------------------------------------------------------------- local network info
@dataclass
class NetInfo:
    iface: str
    ip: str
    netmask: str
    network: ipaddress.IPv4Network
    mac: str = ""

    @property
    def cidr(self) -> str:
        return str(self.network)

    def label(self) -> str:
        return f"{self.iface} - {self.ip} ({self.cidr})"


def local_networks() -> list[NetInfo]:
    """Active IPv4 networks of this computer (no loopback / link-local)."""
    import psutil

    out: list[NetInfo] = []
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
    except Exception:
        return out
    for iface, items in addrs.items():
        st = stats.get(iface)
        if st is not None and not st.isup:
            continue
        mac = ""
        for a in items:
            if getattr(a.family, "name", "") in ("AF_LINK", "AF_PACKET") or a.family == getattr(psutil, "AF_LINK", -1):
                mac = normalize_mac(a.address)
        for a in items:
            if a.family != socket.AF_INET or not a.address or not a.netmask:
                continue
            try:
                ip = ipaddress.ip_address(a.address)
                if ip.is_loopback or ip.is_link_local:
                    continue
                net = ipaddress.ip_network(f"{a.address}/{a.netmask}", strict=False)
            except ValueError:
                continue
            out.append(NetInfo(iface, a.address, a.netmask, net, mac))
    out.sort(key=lambda n: (not n.network.is_private, n.network.prefixlen < 16, n.iface))
    return out


def default_gateway() -> Optional[str]:
    """Best-effort default gateway (your router) without extra packages."""
    try:
        if IS_WINDOWS:
            text = subprocess.run(["route", "print", "-4", "0.0.0.0"], capture_output=True, timeout=8).stdout.decode("latin-1", "replace")
            best: tuple[int, str] | None = None
            for line in text.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                    try:
                        gw, metric = parts[2], int(parts[4])
                        ipaddress.ip_address(gw)
                    except ValueError:
                        continue
                    if best is None or metric < best[0]:
                        best = (metric, gw)
            return best[1] if best else None
        if os.path.exists("/proc/net/route"):
            with open("/proc/net/route") as fh:
                for line in list(fh)[1:]:
                    f = line.split()
                    if len(f) > 2 and f[1] == "00000000" and int(f[3], 16) & 2:
                        return socket.inet_ntoa(struct.pack("<L", int(f[2], 16)))
        if IS_MAC:
            text = subprocess.run(["route", "-n", "get", "default"], capture_output=True, timeout=8).stdout.decode("utf-8", "replace")
            m = re.search(r"gateway:\s*(\S+)", text)
            return m.group(1) if m else None
    except Exception:
        return None
    return None


def primary_ip() -> Optional[str]:
    """The IP address this computer uses to reach the outside (no packets are sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return None


# --------------------------------------------------------------------------- MAC / ARP
def normalize_mac(raw: str) -> str:
    parts = re.split(r"[-:.]", raw.strip())
    if len(parts) == 6 and all(1 <= len(p) <= 2 for p in parts):
        return ":".join(p.zfill(2) for p in parts).upper()
    if len(parts) == 3 and all(len(p) == 4 for p in parts):  # aabb.ccdd.eeff
        s = "".join(parts)
        return ":".join(s[i:i + 2] for i in range(0, 12, 2)).upper()
    return raw.strip().upper()


def is_randomized_mac(mac: str) -> bool:
    """'Locally administered' bit set: phones/PCs use these for Wi-Fi privacy."""
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except (ValueError, IndexError):
        return False


_ARP_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})\D+?([0-9a-fA-F]{1,2}(?:[-:][0-9a-fA-F]{1,2}){5})")

# Only vendors we are 100% sure of (virtual machines and Raspberry Pi). The Learn page
# explains how to look up the rest.
_KNOWN_OUI = {
    "00:0C:29": "VMware VM", "00:50:56": "VMware VM", "00:05:69": "VMware VM", "00:1C:14": "VMware VM",
    "00:15:5D": "Microsoft Hyper-V VM", "08:00:27": "VirtualBox VM", "00:16:3E": "Xen VM",
    "52:54:00": "QEMU/KVM VM",
    "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi", "E4:5F:01": "Raspberry Pi",
    "28:CD:C1": "Raspberry Pi", "D8:3A:DD": "Raspberry Pi",
}


def vendor_hint(mac: str) -> str:
    return _KNOWN_OUI.get(mac[:8].upper(), "")


def parse_arp_text(text: str) -> dict[str, str]:
    table: dict[str, str] = {}
    for line in text.splitlines():
        m = _ARP_RE.search(line)
        if not m:
            continue
        ip, mac = m.group(1), normalize_mac(m.group(2))
        low = line.lower()
        if "incomplete" in low or mac in ("00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"):
            continue
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_multicast or ip.endswith(".255") and mac.startswith("FF"):
            continue
        table[ip] = mac
    return table


def arp_table() -> dict[str, str]:
    try:
        if os.path.exists("/proc/net/arp"):
            with open("/proc/net/arp") as fh:
                rows = list(fh)[1:]
            table = {}
            for r in rows:
                f = r.split()
                if len(f) >= 4 and f[2] != "0x0" and f[3] != "00:00:00:00:00:00":
                    table[f[0]] = normalize_mac(f[3])
            return table
        text = subprocess.run(["arp", "-a"], capture_output=True, timeout=10).stdout.decode("latin-1", "replace")
        return parse_arp_text(text)
    except Exception:
        return {}


# --------------------------------------------------------------------------- device scan
SCAN_PROBE_PORTS = [445, 135, 139, 80, 443, 22, 3389, 8080, 62078, 9100, 554, 5000, 53, 8009]


@dataclass
class Device:
    ip: str
    mac: str = ""
    hostname: str = ""
    alive: bool = False          # answered ping
    rtt_ms: Optional[float] = None
    open_ports: list[int] = field(default_factory=list)
    is_gateway: bool = False
    is_self: bool = False

    @property
    def randomized(self) -> bool:
        return bool(self.mac) and is_randomized_mac(self.mac)

    @property
    def vendor(self) -> str:
        return vendor_hint(self.mac) if self.mac else ""

    def guess_kind(self) -> str:
        p = set(self.open_ports)
        if self.is_self:
            return "This computer"
        if self.is_gateway:
            return "Router / gateway"
        if self.vendor:
            return self.vendor
        if p & {9100, 515, 631}:
            return "Printer (likely)"
        if 554 in p:
            return "Camera / recorder (likely)"
        if 62078 in p:
            return "Apple phone/tablet (likely)"
        if 8009 in p:
            return "Chromecast / smart TV (likely)"
        if p & {445, 135, 139, 3389}:
            return "Windows PC or server (likely)"
        if 22 in p and not p & {80, 443}:
            return "Linux / network device (likely)"
        if p & {80, 443, 8080, 5000}:
            return "Device with a web page (likely)"
        if self.randomized:
            return "Phone / laptop using a private Wi-Fi address"
        return ""


def hosts_in(cidr: str, limit: int = 1024) -> list[str]:
    net = ipaddress.ip_network(cidr, strict=False)
    if net.version != 4:
        raise ValueError("only IPv4 networks are supported")
    if net.num_addresses > limit + 2:
        raise ValueError(f"{cidr} has too many addresses; use a /22 (1,024 hosts) or smaller")
    return [str(h) for h in net.hosts()]


def _resolve_name(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except (OSError, socket.herror, socket.gaierror):
        return ""


def scan_network(cidr: str, *, deep: bool = False, resolve_names: bool = True,
                 progress: Optional[Callable[[int, int, str], None]] = None,
                 cancel: Optional[threading.Event] = None, workers: int = 64) -> list[Device]:
    """Find devices on a network.

    1. Ping every address (this also makes the OS ask 'who has this IP?' via ARP).
    2. Read the ARP table - that reveals devices that *ignore* ping.
    3. Optionally (deep) try a handful of TCP ports on silent addresses and on every found device.
    """
    cancel = cancel or threading.Event()
    hosts = hosts_in(cidr)
    net = ipaddress.ip_network(cidr, strict=False)
    gateway = default_gateway()
    my_ips = {n.ip: n.mac for n in local_networks()}
    total_steps = len(hosts) * (2 if deep else 1) + 3
    done = 0
    lock = threading.Lock()
    found: dict[str, Device] = {}

    def tick(msg: str) -> None:
        nonlocal done
        with lock:
            done += 1
            cur = done
        if progress:
            progress(cur, total_steps, msg)

    def ping_one(ip: str) -> None:
        if cancel.is_set():
            return
        res = ping_host(ip, 1, 1.0)
        if res.ok:
            with lock:
                found[ip] = Device(ip=ip, alive=True, rtt_ms=res.avg_ms)
        tick(f"Pinging {ip}")

    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(ping_one, hosts))
    if cancel.is_set():
        return []

    arp = arp_table()
    tick("Reading the ARP table")
    for ip, mac in arp.items():
        try:
            if ipaddress.ip_address(ip) not in net or ip in (str(net.network_address), str(net.broadcast_address)):
                continue
        except ValueError:
            continue
        dev = found.setdefault(ip, Device(ip=ip))
        dev.mac = mac
    for ip, mac in my_ips.items():
        try:
            if ipaddress.ip_address(ip) in net:
                dev = found.setdefault(ip, Device(ip=ip, alive=True))
                dev.is_self, dev.mac = True, mac or dev.mac
        except ValueError:
            pass

    if deep:
        def probe_one(ip: str) -> None:
            if cancel.is_set():
                return
            dev = found.get(ip)
            ports = SCAN_PROBE_PORTS if dev is not None else SCAN_PROBE_PORTS[:8]
            opened = []
            for p in ports:
                ok, ms, _ = tcp_connect(ip, p, 0.35)
                if ok:
                    opened.append(p)
                    if dev is None:
                        break
            if opened:
                with lock:
                    d = found.setdefault(ip, Device(ip=ip))
                    d.open_ports = sorted(set(d.open_ports) | set(opened))
            tick(f"Probing {ip}")

        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(probe_one, hosts))

    for ip, dev in found.items():
        dev.is_gateway = ip == gateway
    if resolve_names and not cancel.is_set():
        with cf.ThreadPoolExecutor(max_workers=32) as pool:
            for dev, name in zip(list(found.values()), pool.map(_resolve_name, list(found.keys()))):
                dev.hostname = name if name and name != dev.ip else ""
        tick("Looking up device names")
    if progress:
        progress(total_steps, total_steps, "Done")
    return sorted(found.values(), key=lambda d: tuple(int(x) for x in d.ip.split(".")))


# --------------------------------------------------------------------------- port scan
def scan_ports(host: str, ports: Iterable[int], *, timeout_s: float = 0.8, workers: int = 100,
               progress: Optional[Callable[[int, int], None]] = None,
               cancel: Optional[threading.Event] = None) -> list[int]:
    ports = list(dict.fromkeys(int(p) for p in ports))
    cancel = cancel or threading.Event()
    open_ports: list[int] = []
    done = 0
    lock = threading.Lock()

    def one(p: int) -> None:
        nonlocal done
        if cancel.is_set():
            return
        ok, _, _ = tcp_connect(host, p, timeout_s)
        with lock:
            done += 1
            if ok:
                open_ports.append(p)
            cur = done
        if progress:
            progress(cur, len(ports))

    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, ports))
    return sorted(open_ports)


def parse_port_spec(spec: str) -> list[int]:
    """'22,80,443,8000-8010' -> [22, 80, 443, 8000, ...]"""
    ports: list[int] = []
    for chunk in re.split(r"[,\s;]+", spec.strip()):
        if not chunk:
            continue
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            lo, hi = int(a), int(b)
            if lo > hi:
                lo, hi = hi, lo
            ports.extend(range(lo, hi + 1))
        else:
            ports.append(int(chunk))
    for p in ports:
        if not 1 <= p <= 65535:
            raise ValueError(f"port {p} is outside 1-65535")
    if len(ports) > 65535:
        raise ValueError("too many ports")
    return list(dict.fromkeys(ports))


# --------------------------------------------------------------------------- this computer
def list_windows_services() -> list[dict]:
    """Windows services (empty list on other systems)."""
    import psutil

    if not hasattr(psutil, "win_service_iter"):
        return []
    out = []
    for svc in psutil.win_service_iter():
        try:
            info = svc.as_dict()
            out.append({
                "name": info.get("name", ""),
                "display_name": info.get("display_name", ""),
                "status": (info.get("status") or "").lower(),
                "start_type": (info.get("start_type") or "").lower(),
                "description": info.get("description") or "",
                "username": info.get("username") or "",
            })
        except Exception:
            continue
    return out


def list_processes() -> list[dict]:
    """Running programs, grouped by name."""
    import psutil

    groups: dict[str, dict] = {}
    for p in psutil.process_iter(["name", "memory_info", "username"]):
        try:
            name = p.info["name"] or "?"
            mem = p.info["memory_info"].rss if p.info.get("memory_info") else 0
            g = groups.setdefault(name, {"name": name, "count": 0, "memory": 0, "user": p.info.get("username") or ""})
            g["count"] += 1
            g["memory"] += mem
        except Exception:
            continue
    return sorted(groups.values(), key=lambda g: -g["memory"])


def list_listening_ports() -> list[dict]:
    """TCP ports this computer is listening on, with the program that owns them."""
    import psutil

    names: dict[int, str] = {}
    out = []
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, OSError):
        return []
    for c in conns:
        if c.status != psutil.CONN_LISTEN or not c.laddr:
            continue
        pid = c.pid
        if pid and pid not in names:
            try:
                names[pid] = psutil.Process(pid).name()
            except Exception:
                names[pid] = ""
        ip = c.laddr.ip
        exposure = "this PC only" if ip in ("127.0.0.1", "::1") else "network"
        out.append({"port": c.laddr.port, "address": ip, "pid": pid or 0,
                    "process": names.get(pid or 0, ""), "exposure": exposure})
    out = list({(o["port"], o["address"], o["pid"]): o for o in out}.values())
    return sorted(out, key=lambda o: (o["exposure"] != "network", o["port"]))


def format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


# --------------------------------------------------------------------------- Wake-on-LAN
def magic_packet(mac: str) -> bytes:
    """6 x 0xFF followed by the MAC address 16 times - the 'wake up' packet network cards listen for."""
    norm = normalize_mac(mac)
    parts = norm.split(":")
    if len(parts) != 6:
        raise ValueError(f"'{mac}' is not a MAC address")
    try:
        raw = bytes(int(p, 16) for p in parts)
    except ValueError as exc:
        raise ValueError(f"'{mac}' is not a MAC address") from exc
    return b"\xff" * 6 + raw * 16


def broadcast_addresses() -> list[str]:
    """Where to send a wake-up packet: each local network's broadcast address, plus the general one."""
    out: list[str] = []
    for n in local_networks():
        b = str(n.network.broadcast_address)
        if b not in out:
            out.append(b)
    out.append("255.255.255.255")
    return out


def wake_on_lan(mac: str, targets: Optional[list[str]] = None, port: int = 9) -> list[str]:
    """Send a magic packet. Returns the addresses it was sent to. Raises ValueError for a bad MAC."""
    packet = magic_packet(mac)
    sent: list[str] = []
    errors: list[str] = []
    for addr in (targets or broadcast_addresses()):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.sendto(packet, (addr, port))
            sent.append(addr)
        except OSError as exc:
            errors.append(f"{addr}: {exc}")
    if not sent:
        raise OSError("could not send the wake-up packet (" + "; ".join(errors) + ")")
    return sent


# --------------------------------------------------------------------------- small HTTP probe
def http_probe(url: str, timeout_s: float = 6.0, expect: str = "") -> tuple[bool, Optional[int], str, float]:
    """(ok, status code, message, ms). ok = got an answer (and the expected text, if given)."""
    import requests
    start = time.perf_counter()
    try:
        resp = requests.get(url, timeout=timeout_s, allow_redirects=False,
                            headers={"User-Agent": "NetBeacon/1.1 (+diagnosis)"})
    except requests.exceptions.SSLError as exc:
        return False, None, f"secure connection failed ({str(exc)[:120]})", (time.perf_counter() - start) * 1000
    except requests.exceptions.Timeout:
        return False, None, f"no answer within {timeout_s:.0f} s", (time.perf_counter() - start) * 1000
    except requests.exceptions.RequestException as exc:
        return False, None, f"could not connect ({str(exc)[:120]})", (time.perf_counter() - start) * 1000
    ms = (time.perf_counter() - start) * 1000
    if expect and expect not in resp.text:
        return False, resp.status_code, f"HTTP {resp.status_code}, but the page was not the expected one", ms
    return True, resp.status_code, f"HTTP {resp.status_code} in {ms:.0f} ms", ms
