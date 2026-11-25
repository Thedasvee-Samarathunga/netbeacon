"""The catalogue of check types NetBeacon offers.

Every entry knows:
  * which SimpleMonitor `type` it uses (`sm_type`)
  * the form fields the GUI should show, with plain-English help text
  * a "what / why / under the hood" explanation for the learning panel
  * how to turn the form values into a SimpleMonitor `monitors.ini` section
  * (optionally) the *built-in* SimpleMonitor type to use when exporting a config for
    stock SimpleMonitor (`standalone_type`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import netutil


@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"               # text | int | float | choice | bool | path | password
    default: Any = ""
    help: str = ""
    placeholder: str = ""
    choices: Optional[list[tuple[str, str]]] = None   # (value, label)
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    required: bool = False
    suffix: str = ""


@dataclass
class CheckType:
    key: str
    title: str
    category: str
    sm_type: str
    summary: str
    what: str
    why: str
    how: str
    fields: list[Field]
    standalone_type: Optional[str] = None
    windows_only: bool = False
    tips: list[str] = field(default_factory=list)
    target_fn: Optional[Callable[[dict], str]] = None
    name_fn: Optional[Callable[[dict], str]] = None
    extra_validate: Optional[Callable[[dict], list[str]]] = None
    options_fn: Optional[Callable[[dict], dict]] = None
    standalone_fn: Optional[Callable[[dict], tuple[str, dict]]] = None
    measures_latency: bool = False

    # ---- helpers --------------------------------------------------------
    def defaults(self) -> dict:
        return {f.key: f.default for f in self.fields}

    def target(self, params: dict) -> str:
        if self.target_fn:
            try:
                return self.target_fn(params)
            except Exception:
                return ""
        return ""

    def default_name(self, params: dict) -> str:
        if self.name_fn:
            try:
                return self.name_fn(params)
            except Exception:
                pass
        return self.title

    def validate(self, params: dict) -> list[str]:
        problems: list[str] = []
        for f in self.fields:
            value = params.get(f.key, f.default)
            if f.required and (value is None or str(value).strip() == ""):
                problems.append(f"'{f.label}' is required.")
                continue
            if f.kind in ("int", "float") and str(value).strip() != "":
                try:
                    num = float(value)
                except (TypeError, ValueError):
                    problems.append(f"'{f.label}' must be a number.")
                    continue
                if f.minimum is not None and num < f.minimum:
                    problems.append(f"'{f.label}' must be at least {f.minimum:g}.")
                if f.maximum is not None and num > f.maximum:
                    problems.append(f"'{f.label}' must be at most {f.maximum:g}.")
        if not problems and self.extra_validate:
            problems.extend(self.extra_validate(params))
        return problems

    def options(self, params: dict) -> dict[str, str]:
        """SimpleMonitor options (strings) for monitors.ini."""
        if self.options_fn:
            return {k: v for k, v in self.options_fn(params).items() if v not in (None, "")}
        out: dict[str, str] = {}
        for f in self.fields:
            value = params.get(f.key, f.default)
            if f.kind == "bool":
                out[f.key] = "1" if value in (True, "1", 1, "true", "True") else "0"
            elif value is None or str(value).strip() == "":
                continue
            elif f.kind == "int":
                out[f.key] = str(int(float(value)))
            else:
                out[f.key] = str(value).strip()
        return out

    def standalone(self, params: dict) -> tuple[Optional[str], dict]:
        """(built-in type, options) for plain SimpleMonitor, or (None, {}) if there is no equivalent."""
        if self.standalone_fn:
            return self.standalone_fn(params)
        if self.standalone_type:
            return self.standalone_type, self.options(params)
        return None, {}


# --------------------------------------------------------------------------- validators / helpers
def _v_host(params: dict, key: str = "host") -> list[str]:
    host = str(params.get(key, "")).strip()
    return [] if netutil.is_valid_host(host) else [f"'{host}' is not a valid host name or IP address."]


def _v_url(params: dict) -> list[str]:
    url = str(params.get("url", "")).strip()
    if not url.lower().startswith(("http://", "https://")):
        return ["The web address must start with http:// or https://"]
    return []


def _v_dns(params: dict) -> list[str]:
    out = []
    rt = str(params.get("record_type", "A")).upper()
    server = str(params.get("server", "")).strip()
    if rt not in ("A", "AAAA") and not server:
        out.append("Please enter a DNS server to look up this kind of record (or switch to A / AAAA).")
    if server and not netutil.is_valid_host(server):
        out.append("The DNS server must be an IP address or host name.")
    return out


def _v_codes(params: dict) -> list[str]:
    try:
        codes = [int(c) for c in str(params.get("allowed_codes", "200")).replace(" ", "").split(",") if c]
        if not codes or any(not 100 <= c <= 599 for c in codes):
            raise ValueError
    except ValueError:
        return ["HTTP status codes must be numbers like 200 or 200,301."]
    return []


def _v_regexp(params: dict) -> list[str]:
    import re
    pattern = str(params.get("regexp", "")).strip()
    if pattern:
        try:
            re.compile(pattern)
        except re.error as exc:
            return [f"The text to look for is not a valid pattern: {exc}"]
    return []


def _opt_http(params: dict) -> dict:
    return {
        "url": str(params.get("url", "")).strip(),
        "method": str(params.get("method", "GET")),
        "allowed_codes": str(params.get("allowed_codes", "200")).replace(" ", ""),
        "regexp": str(params.get("regexp", "")).strip(),
        "timeout": str(int(float(params.get("timeout", 10)))),
        "verify_hostname": "1" if params.get("verify_hostname", True) in (True, "1", 1, "true", "True") else "0",
        "allow_redirects": "1" if params.get("allow_redirects", True) in (True, "1", 1, "true", "True") else "0",
        "slow_ms": str(int(float(params.get("slow_ms", 0) or 0))) if float(params.get("slow_ms", 0) or 0) else "",
    }


def _std_http(params: dict) -> tuple[str, dict]:
    o = _opt_http(params)
    o.pop("slow_ms", None)
    return "http", o


def _std_ping(params: dict) -> tuple[str, dict]:
    return "host", {"host": str(params["host"]).strip(), "count": str(int(float(params.get("count", 1)))),
                    "ping_ttl": str(int(float(params.get("timeout", 5))))}


def _std_tcp(params: dict) -> tuple[str, dict]:
    return "tcp", {"host": str(params["host"]).strip(), "port": str(int(float(params["port"])))}


def _std_dns(params: dict) -> tuple[str, dict]:
    o = {"record": str(params["record"]).strip(), "record_type": str(params.get("record_type", "A"))}
    if str(params.get("server", "")).strip():
        o["server"] = str(params["server"]).strip()
    if str(params.get("expect", "")).strip():
        o["desired_val"] = str(params["expect"]).replace(",", "\n").strip()
    return "dns", o


def _std_disk(params: dict) -> tuple[Optional[str], dict]:
    gb = float(params.get("min_free_gb", 0) or 0)
    return "diskspace", {"partition": str(params["path"]).strip(), "limit": f"{max(1, int(gb))}G"}


def _std_file(params: dict) -> tuple[Optional[str], dict]:
    pattern = str(params["pattern"]).strip()
    if any(ch in pattern for ch in "*?["):
        return None, {}
    o = {"filename": pattern}
    hours = float(params.get("max_age_hours", 0) or 0)
    if hours:
        o["maxage"] = str(int(hours * 3600))
    mb = float(params.get("min_size_mb", 0) or 0)
    if mb:
        o["minsize"] = str(int(mb * 1024 * 1024))
    return "filestat", o


def _std_cmd(params: dict) -> tuple[str, dict]:
    o = {"command": str(params["command"]).strip()}
    if str(params.get("expect", "")).strip():
        o["result_regexp"] = str(params["expect"]).strip()
    return "command", o


def _opt_process(params: dict) -> dict:
    mx = int(float(params.get("max_count", 0) or 0))
    return {"process_name": str(params["process_name"]).strip(),
            "min_count": str(int(float(params.get("min_count", 1)))),
            "max_count": str(mx if mx > 0 else -1)}


# --------------------------------------------------------------------------- the catalogue
_COMMON_SLOW = Field("slow_ms", "Count it as a failure if slower than", "int", 0, minimum=0, maximum=60000, suffix="ms (0 = never)",
                     help="Optional speed limit. Slow is often the first sign of trouble. Leave at 0 to only care about up/down.")

CHECKS: dict[str, CheckType] = {}


def _add(ct: CheckType) -> None:
    CHECKS[ct.key] = ct


_add(CheckType(
    key="ping", title="Ping a device", category="Is it reachable?", sm_type="lan_ping", standalone_type=None,
    standalone_fn=_std_ping, measures_latency=True,
    summary="Is this computer, printer, router or server switched on and answering on the network?",
    what="<p>A <b>ping</b> sends a tiny 'are you there?' message (called an ICMP echo request) to a device and waits for the "
         "'yes, I'm here' reply. The time between the two is the <b>latency</b>.</p>",
    why="<p>It is the quickest way to learn whether a device is on the network at all, and the latency tells you how healthy the "
        "connection is. Several packets are sent each time so we can also see <b>packet loss</b> - a flaky cable or weak Wi-Fi "
        "often shows up as lost packets long before a complete outage.</p>"
        "<p><b>Careful:</b> some devices (many Windows PCs by default) deliberately ignore pings. If a device is up but never answers, "
        "monitor one of its ports instead.</p>",
    how="<p>Uses a NetBeacon extension of SimpleMonitor's <code>host</code> monitor (type <code>lan_ping</code>). The stock "
        "<code>host</code> monitor only reads English Windows output and doesn't report timings; ours reads the replies in any language.</p>",
    fields=[
        Field("host", "Device address", "text", "", required=True, placeholder="192.168.1.1 or router.local",
              help="An IP address (like 192.168.1.1) or a name (like printer.office.local)."),
        Field("count", "Packets per check", "int", 3, minimum=1, maximum=20,
              help="More packets give a better picture of packet loss. 3 is a good balance."),
        Field("timeout", "Wait for each reply", "int", 4, minimum=1, maximum=60, suffix="seconds",
              help="How long to wait before treating a packet as lost."),
        Field("max_loss", "Fail if packet loss is above", "int", 50, minimum=0, maximum=100, suffix="%",
              help="With 3 packets, 1 lost packet is 33% loss. Lower numbers make the check pickier."),
        _COMMON_SLOW,
    ],
    target_fn=lambda p: str(p.get("host", "")), name_fn=lambda p: f"Ping {p.get('host', '')}",
    extra_validate=_v_host,
    tips=["Ping your router first: if the router is down, almost everything else will look down too (see 'Depends on' under Advanced).",
          "Latency over ~100 ms inside an office network, or steady packet loss, is worth investigating."],
))

_add(CheckType(
    key="tcp", title="Check a network port (TCP)", category="Is it reachable?", sm_type="lan_tcp", standalone_type=None,
    standalone_fn=_std_tcp, measures_latency=True,
    summary="Is a specific service (web server, database, remote desktop, printer...) accepting connections?",
    what="<p>Every network service listens on a numbered <b>port</b>: web = 80/443, remote desktop = 3389, file sharing = 445, "
         "SSH = 22, and so on. This check tries to open a <b>TCP connection</b> (the 'three-way handshake') to that port. "
         "If the connection opens, the service is listening.</p>",
    why="<p>A server can answer ping while the program you actually care about has crashed. Checking the real port catches that. "
        "It also works for devices that ignore ping.</p>",
    how="<p>Uses SimpleMonitor's <code>tcp</code> monitor (extended as <code>lan_tcp</code> to add a timeout, IPv6 and response-time measurement).</p>",
    fields=[
        Field("host", "Device address", "text", "", required=True, placeholder="192.168.1.20"),
        Field("port", "Port number", "int", 443, required=True, minimum=1, maximum=65535,
              help="Common ports: 22 SSH, 25 mail, 53 DNS, 80 web, 443 secure web, 445 file sharing, 1433 SQL Server, 3306 MySQL, 3389 Remote Desktop."),
        Field("timeout", "Give up after", "int", 5, minimum=1, maximum=60, suffix="seconds"),
        _COMMON_SLOW,
    ],
    target_fn=lambda p: f"{p.get('host', '')}:{p.get('port', '')}", name_fn=lambda p: f"Port {p.get('port', '')} on {p.get('host', '')}",
    extra_validate=_v_host,
    tips=["'Connection refused' means the machine is up but nothing is listening. 'Timed out' usually means a firewall or the machine is off."],
))

_add(CheckType(
    key="dns", title="DNS lookup", category="Is it reachable?", sm_type="lan_dns", standalone_type=None,
    standalone_fn=_std_dns, measures_latency=True,
    summary="Can names like 'example.com' still be turned into IP addresses?",
    what="<p><b>DNS</b> is the internet's phone book: it converts names people type into the numbers computers use. "
         "When DNS breaks, 'the internet is down' even though your connection is fine.</p>",
    why="<p>DNS is one of the most common hidden causes of outages. Leave the server box empty to test the DNS settings of this PC, "
        "or enter your router / a public resolver (for example 1.1.1.1 or 8.8.8.8) to test that specific server.</p>",
    how="<p>NetBeacon extension <code>lan_dns</code>. SimpleMonitor's own <code>dns</code> monitor needs the Linux tool <code>dig</code>, which Windows doesn't have, "
        "so NetBeacon includes a tiny built-in DNS client. The export function maps it back to <code>dns</code>.</p>",
    fields=[
        Field("record", "Name to look up", "text", "example.com", required=True, placeholder="www.yourcompany.com"),
        Field("record_type", "Record type", "choice", "A", choices=[("A", "A  (IPv4 address)"), ("AAAA", "AAAA  (IPv6 address)"),
                                                                    ("CNAME", "CNAME  (alias)"), ("MX", "MX  (mail server)"),
                                                                    ("TXT", "TXT  (text)"), ("NS", "NS  (name servers)")],
              help="A is what you want in most cases."),
        Field("server", "DNS server (optional)", "text", "", placeholder="blank = this PC's DNS",
              help="Leave empty to use Windows' own DNS settings. Needed for MX/TXT/CNAME/NS."),
        Field("expect", "Answer must contain (optional)", "text", "", placeholder="e.g. 203.0.113.10",
              help="Catches DNS records that were changed or hijacked. Separate several values with commas."),
        Field("port", "DNS server port", "int", 53, minimum=1, maximum=65535,
              help="DNS normally listens on port 53. Only change this if your DNS server is set up differently."),
        Field("timeout", "Give up after", "int", 3, minimum=1, maximum=30, suffix="seconds"),
        _COMMON_SLOW,
    ],
    target_fn=lambda p: f"{p.get('record', '')} ({p.get('record_type', 'A')})", name_fn=lambda p: f"DNS {p.get('record', '')}",
    extra_validate=_v_dns,
))

_add(CheckType(
    key="http", title="Website / web app", category="Websites & certificates", sm_type="lan_http", standalone_fn=_std_http,
    measures_latency=True,
    summary="Does a web page load correctly, quickly, and show what it should?",
    what="<p>Downloads a web address like a browser would and checks the <b>HTTP status code</b> (200 = OK, 404 = not found, "
         "500 = server error, 301/302 = redirect). You can also require some text on the page.</p>",
    why="<p>A page can return '200 OK' while showing an error message, so matching a word that should <i>always</i> be on the page "
        "(like your company name) is much more reliable than the status code alone.</p>",
    how="<p>Uses SimpleMonitor's <code>http</code> monitor (extended as <code>lan_http</code> for response-time measurement and clearer messages).</p>",
    fields=[
        Field("url", "Web address", "text", "https://", required=True, placeholder="https://www.yourcompany.com/"),
        Field("method", "Method", "choice", "GET", choices=[("GET", "GET (load the page)"), ("HEAD", "HEAD (headers only, lighter)")]),
        Field("allowed_codes", "Accepted status codes", "text", "200", help="Comma separated, e.g. 200 or 200,301,302."),
        Field("regexp", "Page must contain (optional)", "text", "", placeholder="e.g. Welcome|Log in",
              help="Text or a pattern (regular expression) that must appear on the page. Not used with HEAD."),
        Field("timeout", "Give up after", "int", 10, minimum=1, maximum=120, suffix="seconds"),
        Field("allow_redirects", "Follow redirects", "bool", True, help="If ticked, a redirect to another page counts as that page's result."),
        Field("verify_hostname", "Verify the TLS certificate", "bool", True,
              help="Leave ticked. Untick only for internal sites with self-signed certificates."),
        _COMMON_SLOW,
    ],
    target_fn=lambda p: str(p.get("url", "")), name_fn=lambda p: "Web " + str(p.get("url", "")).split("//")[-1].strip("/"),
    options_fn=_opt_http,
    extra_validate=lambda p: _v_url(p) + _v_codes(p) + _v_regexp(p),
    tips=["Also monitor the web address your customers actually use, not just the server's internal address."],
))

_add(CheckType(
    key="tls", title="Certificate expiry (HTTPS)", category="Websites & certificates", sm_type="tls_expiry", standalone_type="tls_expiry",
    summary="Warn me before a website's security certificate runs out.",
    what="<p>HTTPS sites prove their identity with a <b>TLS certificate</b> that expires (usually after 90 days to a year). "
         "When it expires, browsers show scary warnings and customers leave.</p>",
    why="<p>Expired certificates are one of the most avoidable outages. This check turns red <i>before</i> expiry, giving you time to renew.</p>",
    how="<p>SimpleMonitor's built-in <code>tls_expiry</code> monitor. NetBeacon runs it hourly by default (certificates change slowly).</p>",
    fields=[
        Field("host", "Server address", "text", "", required=True, placeholder="www.yourcompany.com"),
        Field("port", "Port", "int", 443, minimum=1, maximum=65535),
        Field("min_days", "Warn when fewer than", "int", 14, minimum=0, maximum=365, suffix="days left"),
        Field("sni", "Site name (SNI)", "text", "", placeholder="usually the same as the address",
              help="Needed when many sites share one server. Also makes the name on the certificate be verified."),
    ],
    target_fn=lambda p: f"{p.get('host', '')}:{p.get('port', 443)}", name_fn=lambda p: f"Certificate {p.get('host', '')}",
    extra_validate=_v_host,
))

_add(CheckType(
    key="service", title="Windows service is running", category="This PC / server health", sm_type="service", standalone_type="service",
    windows_only=True,
    summary="Is an important Windows service (like the print spooler or SQL Server) running?",
    what="<p>A <b>Windows service</b> is a program that runs in the background without anyone logged in - databases, backups, "
         "print spooler, antivirus. Open the <b>Services &amp; Programs</b> page to pick one from a list.</p>",
    why="<p>Services stop for many reasons (crash, update, full disk). Monitoring them tells you about the problem before users do. "
        "This check only works on the computer NetBeacon runs on.</p>",
    how="<p>SimpleMonitor's built-in <code>service</code> monitor (Windows only; reads the service state through <code>psutil</code>).</p>",
    fields=[
        Field("service", "Service name", "text", "", required=True, placeholder="Spooler",
              help="The short name, not the display name. Pick it from the Services page to avoid typos."),
        Field("state", "Should be", "choice", "RUNNING", choices=[("RUNNING", "Running"), ("STOPPED", "Stopped")]),
    ],
    target_fn=lambda p: str(p.get("service", "")), name_fn=lambda p: f"Service {p.get('service', '')}",
))

_add(CheckType(
    key="process", title="Program is running", category="This PC / server health", sm_type="process", standalone_fn=lambda p: ("process", _opt_process(p)),
    options_fn=_opt_process,
    summary="Is a particular program (process) running on this computer?",
    what="<p>Looks for a running program by its file name, e.g. <code>sqlservr.exe</code> or <code>QuickBooks.exe</code>. "
         "You can require a minimum - and optionally maximum - number of copies.</p>",
    why="<p>Useful for programs that are not Windows services, or to notice runaway duplicates (maximum count).</p>",
    how="<p>SimpleMonitor's built-in <code>process</code> monitor.</p>",
    fields=[
        Field("process_name", "Program file name", "text", "", required=True, placeholder="sqlservr.exe"),
        Field("min_count", "At least", "int", 1, minimum=0, maximum=1000, suffix="running"),
        Field("max_count", "At most", "int", 0, minimum=0, maximum=100000, suffix="running (0 = no limit)"),
    ],
    target_fn=lambda p: str(p.get("process_name", "")), name_fn=lambda p: f"Program {p.get('process_name', '')}",
))

_add(CheckType(
    key="disk", title="Free disk space", category="This PC / server health", sm_type="lan_disk", standalone_fn=_std_disk,
    summary="Will this drive run out of room?",
    what="<p>Checks how much space is free on a drive (like <code>C:\\</code>) or folder, as a number of gigabytes and/or a percentage.</p>",
    why="<p>A full disk quietly breaks databases, backups, updates and logging. It's easy to prevent with a warning at 10-15% free.</p>",
    how="<p>NetBeacon extension <code>lan_disk</code> (the built-in <code>diskspace</code> monitor needs the extra pywin32 library on Windows). "
        "It maps to <code>diskspace</code> when exporting.</p>",
    fields=[
        Field("path", "Drive or folder", "path", "C:\\", required=True, placeholder="C:\\"),
        Field("min_free_percent", "Warn when less than", "float", 10, minimum=0, maximum=100, suffix="% free (0 = off)"),
        Field("min_free_gb", "...or less than", "float", 0, minimum=0, suffix="GB free (0 = off)"),
    ],
    target_fn=lambda p: str(p.get("path", "")), name_fn=lambda p: f"Disk space {p.get('path', '')}",
))

_add(CheckType(
    key="memory", title="Free memory (RAM)", category="This PC / server health", sm_type="memory", standalone_type="memory",
    summary="Is this computer running out of memory?",
    what="<p>Checks the percentage of RAM that is still available.</p>",
    why="<p>When memory runs out Windows slows to a crawl and programs crash. A server that sits below 10-15% free usually needs more RAM or has a leaky program.</p>",
    how="<p>SimpleMonitor's built-in <code>memory</code> monitor.</p>",
    fields=[Field("percent_free", "Warn when less than", "int", 10, required=True, minimum=1, maximum=99, suffix="% available")],
    target_fn=lambda p: f">{p.get('percent_free', '')}% free", name_fn=lambda p: "Free memory",
    tips=["Brief dips are normal - set 'Failures before it counts as down' (Advanced) to 3 or more to avoid false alarms."],
))

_add(CheckType(
    key="cpu", title="CPU load", category="This PC / server health", sm_type="lan_cpu", standalone_type=None,
    summary="Is the processor pinned at 100%?",
    what="<p>Samples how busy the CPU is for a couple of seconds.</p>",
    why="<p>A CPU stuck near 100% means everything is slow. Short spikes are normal, so combine this check with a failure tolerance of 3-5 checks.</p>",
    how="<p>NetBeacon extension <code>lan_cpu</code> (SimpleMonitor's <code>loadavg</code> doesn't work on Windows). No stock equivalent - skipped on export.</p>",
    fields=[Field("max_percent", "Warn when above", "int", 90, minimum=1, maximum=100, suffix="% busy"),
            Field("sample_seconds", "Sample for", "int", 2, minimum=1, maximum=30, suffix="seconds")],
    target_fn=lambda p: f"<{p.get('max_percent', '')}%", name_fn=lambda p: "CPU load",
))

_add(CheckType(
    key="wifi", title="Wi-Fi signal strength", category="This PC / server health", sm_type="lan_wifi", standalone_type=None,
    windows_only=True,
    summary="Is this PC's Wi-Fi signal strong enough?",
    what="<p>Reads the strength of this computer's Wi-Fi connection, the same number Windows shows as bars, as a percentage. "
         "Around 60% and above is comfortable; below 40% video calls start to stutter.</p>",
    why="<p>A weak or fading signal is the most common cause of 'the internet is slow at that desk'. Watching it over time shows whether "
        "it is always weak (move the access point) or only sometimes (interference, a microwave, a crowded channel).</p>",
    how="<p>NetBeacon extension <code>lan_wifi</code>. It reads Windows' <code>netsh wlan show interfaces</code>. There is no stock SimpleMonitor "
        "equivalent, so it is skipped on export. The <b>Wi-Fi</b> page shows the full picture.</p>",
    fields=[Field("min_signal", "Warn when the signal is below", "int", 50, minimum=1, maximum=100, suffix="%",
                  help="Windows' percentage: 50% is about -75 dBm. Lower numbers make the check more relaxed."),
            Field("ssid", "Must be connected to (optional)", "text", "", placeholder="e.g. OfficeNet",
                  help="Also fail if this PC has jumped to another network, such as a neighbour's or the guest Wi-Fi.")],
    target_fn=lambda p: str(p.get("ssid") or "this PC's Wi-Fi"), name_fn=lambda p: "Wi-Fi signal",
    tips=["Pair this with a ping check of your router: if both go red at once, the Wi-Fi link itself is the problem."],
))

_add(CheckType(
    key="file", title="File or backup is fresh", category="Backups & files", sm_type="lan_file", standalone_fn=_std_file,
    summary="Did last night's backup actually run?",
    what="<p>Looks at a file (or, with wildcards like <code>*.bak</code>, the <b>newest</b> matching file) and checks it exists, "
         "isn't older than a limit, and isn't suspiciously small.</p>",
    why="<p>Backups fail silently all the time. A backup file that hasn't changed in 30 hours is a loud signal. "
        "Point this at the backup folder, e.g. <code>D:\\Backups\\*.zip</code> with a maximum age of 26 hours.</p>",
    how="<p>NetBeacon extension <code>lan_file</code>; it maps to SimpleMonitor's <code>filestat</code> when the pattern has no wildcard.</p>",
    fields=[
        Field("pattern", "File or pattern", "path", "", required=True, placeholder="D:\\Backups\\*.zip"),
        Field("max_age_hours", "Must be newer than", "float", 26, minimum=0, suffix="hours (0 = ignore)"),
        Field("min_size_mb", "Must be at least", "float", 0, minimum=0, suffix="MB (0 = ignore)"),
    ],
    target_fn=lambda p: str(p.get("pattern", "")), name_fn=lambda p: "Backup " + str(p.get("pattern", "")).replace("\\", "/").split("/")[-1],
))

_add(CheckType(
    key="command", title="Run a command / script", category="Advanced", sm_type="lan_command", standalone_fn=_std_cmd,
    summary="Run any program or script - success means it exits with code 0.",
    what="<p>Runs a program and treats <b>exit code 0</b> as success (the standard way programs say 'all good'). "
         "You can additionally require some text in the output.</p>",
    why="<p>This is the escape hatch: anything you can script can become a check. It runs with the same permissions as NetBeacon, so only use commands you trust.</p>",
    how="<p>NetBeacon extension <code>lan_command</code> (adds a timeout and Windows-path-friendly parsing to SimpleMonitor's <code>command</code> monitor).</p>",
    fields=[
        Field("command", "Command", "text", "", required=True, placeholder='powershell -NoProfile -Command "Get-Date"'),
        Field("expect", "Output must match (optional)", "text", "", help="A text or pattern that has to appear in the output."),
        Field("timeout", "Give up after", "int", 30, minimum=1, maximum=600, suffix="seconds"),
    ],
    target_fn=lambda p: str(p.get("command", ""))[:60], name_fn=lambda p: "Command " + str(p.get("command", "")).split(" ")[0],
    extra_validate=lambda p: _v_regexp({"regexp": p.get("expect", "")}),
))

_add(CheckType(
    key="compound", title="Combine checks (fail only if several fail)", category="Advanced", sm_type="compound", standalone_type="compound",
    summary="Only raise the alarm when several other checks are failing at the same time.",
    what="<p>A <b>compound</b> check watches other checks. It fails only when at least <i>N</i> of them are failing. "
         "Example: you have two internet lines; alarm only when <i>both</i> are down.</p>",
    why="<p>It is a simple way to describe redundancy ('one of two is OK') and to cut false alarms.</p>",
    how="<p>SimpleMonitor's built-in <code>compound</code> monitor.</p>",
    fields=[
        Field("monitors", "Checks to combine", "text", "", required=True, help="Pick two or more checks in the list."),
        Field("min_fail", "Fail when at least this many are failing", "int", 2, minimum=1, maximum=50),
    ],
    target_fn=lambda p: f"{p.get('min_fail', '')} of {len(str(p.get('monitors', '')).split(',')) if p.get('monitors') else 0} checks",
    name_fn=lambda p: "Combined check",
    options_fn=lambda p: {"monitors": str(p.get("monitors", "")), "min_fail": str(int(float(p.get("min_fail", 2))))},
))

_add(CheckType(
    key="practice", title="Practice check (fails on purpose)", category="Practice", sm_type="fail", standalone_type="fail",
    summary="A harmless fake check that fails a few times, then recovers - perfect for trying out alerts.",
    what="<p>Fails every time except once per cycle. Create one, watch it turn red, see the alert pop up, then see it recover. "
         "Delete it when you're done.</p>",
    why="<p>The best time to learn how alerts feel is <i>before</i> something real breaks.</p>",
    how="<p>SimpleMonitor's built-in <code>fail</code> monitor, which exists exactly for testing alerters.</p>",
    fields=[Field("interval", "Recover after this many failed checks", "int", 5, minimum=1, maximum=100)],
    target_fn=lambda p: "simulated", name_fn=lambda p: "Practice outage",
))

CATEGORY_ORDER = ["Is it reachable?", "Websites & certificates", "This PC / server health", "Backups & files", "Advanced", "Practice"]


def checks_by_category() -> list[tuple[str, list[CheckType]]]:
    out = []
    for cat in CATEGORY_ORDER:
        items = [c for c in CHECKS.values() if c.category == cat]
        if items:
            out.append((cat, items))
    return out
