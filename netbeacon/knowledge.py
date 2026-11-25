"""All of NetBeacon's teaching content lives here so it is easy to improve.

Rich text is simple HTML (rendered by Qt's QTextBrowser / QLabel).
"""
from __future__ import annotations

# --------------------------------------------------------------------------- page banners (shown in Teaching mode)
TIPS: dict[str, tuple[str, str]] = {
    "dashboard": ("Your network at a glance",
                  "Every row is a <b>check</b> - a small question NetBeacon asks again and again, like <i>'does the router answer?'</i> "
                  "Green means yes, red means no. Amber means <b>retrying</b>: the check failed but hasn't failed often enough to be called down yet "
                  "(this avoids false alarms). The little bars show the most recent results, newest on the right."),
    "monitors": ("Checks are the heart of monitoring",
                 "Add one check for each thing your business can't live without: the router, the internet connection, the file server, "
                 "your website, the backup. Start small - <b>5 to 15 well-chosen checks beat 100 noisy ones</b>."),
    "devices": ("Who is on my network?",
                "NetBeacon asks every address in your network <i>'are you there?'</i>, then reads your computer's ARP table (its list of "
                "neighbours it has recently talked to) to also catch devices that ignore ping. New, unfamiliar devices deserve a look: "
                "it might be a visitor's phone - or someone who shouldn't be there."),
    "ports": ("What doors are open?",
              "A <b>port</b> is like a numbered door on a computer. A program (service) waits behind each open door. "
              "Scanning shows which doors are open. Only scan devices you own or administer - scanning other people's networks can be illegal."),
    "services": ("What is running on this computer?",
                 "Windows services and programs are the engines behind your business software. From here you can turn any of them into a check "
                 "with one click, so you hear about it the moment one stops."),
    "uptime": ("Uptime, downtime and why 99.9% isn't what it sounds like",
               "<b>Availability</b> is the share of checks that succeeded. Each outage is recorded as an <b>incident</b> with a start, an end and a reason. "
               "Use this page to answer questions like <i>'how often did the internet drop last month?'</i> - ideal evidence when talking to your provider."),
    "alerts": ("Get told - without being nagged",
               "A monitor nobody looks at is useless, but one that cries wolf gets ignored. Choose where alerts go, "
               "how many failed checks make a real problem, and when it is OK to stay quiet (nights, weekends)."),
    "activity": ("What happened, and how does it work inside?",
                 "<b>Events</b> is the diary of everything that changed. <b>Engine log</b> shows SimpleMonitor, the engine under the hood, talking. "
                 "<b>Config files</b> shows the exact settings NetBeacon gives SimpleMonitor - the same files you can use with plain SimpleMonitor later."),
    "learn": ("The 10-minute network monitoring course",
              "Short lessons about the ideas behind this tool - and how to recognise when you've outgrown it."),
    "map": ("Your network as a picture",
            "This is a <b>network map</b> (bigger tools call it a <i>topology map</i>). Your router sits in the middle because everything passes "
            "through it - if it fails, every line fails. A device with a check takes that check's colour; blue devices are known but not monitored. "
            "When something goes red, the map shows at a glance whether it's one device or everything behind the router."),
    "speed": ("Are you getting what you pay for?",
              "A speed test downloads and uploads some data and measures how fast it went, in <b>megabits per second</b> (Mbit/s). "
              "Providers sell 'up to' speeds, so a single slow result proves little - but tests every few hours build a <b>trend</b>, "
              "and a pattern of slow evenings is solid evidence when you call your provider."),
    "wifi": ("Wi-Fi is radio",
             "Wi-Fi is a radio conversation between this PC and an access point. Walls, distance and <b>other networks on the same channel</b> "
             "all weaken it. The signal percentage is what Windows shows as bars; <b>dBm</b> is the engineer's unit (closer to 0 is stronger: "
             "-50 is excellent, -70 is fine, -80 is poor). Most 'the internet is slow at that desk' complaints start here."),
    "digest": ("The week in sentences",
               "Graphs are great for technicians; owners want sentences. Every week NetBeacon turns its history into a short summary: "
               "outages, what is slowly getting worse (a disk filling up), speed and Wi-Fi. Fixing the slow trends <i>before</i> they become "
               "outages is what professionals call <b>capacity planning</b>."),
    "settings": ("Make NetBeacon yours",
                 "Most people never need to change anything here, except maybe 'Start with Windows' so monitoring survives reboots."),
}

TERM_HELP = {
    "tolerance": "How many extra failed checks in a row are allowed before the check is called DOWN. "
                 "Tolerance 2 means the 3rd failure in a row turns it red. Prevents false alarms caused by one lost packet.",
    "interval": "How often each round of checks runs. 30 s is a good default. Faster means quicker detection but more network traffic.",
    "depends": "If the thing you pick here is down, this check is paused instead of failing. If your router dies, you get ONE alert about the router "
               "- not 20 alerts about everything behind it.",
    "group": "A label to organise checks (for example 'Office', 'Servers', 'Internet').",
    "remind": "Repeat the alert every N minutes while the problem continues. 0 = tell me once.",
    "failure_doc": "Write down what to do when this fails (who to call, which switch to reboot). It is included in alert messages. "
                   "In big companies this is called a runbook.",
    "recover": "ADVANCED: a command run once when the check first fails, e.g. to restart a stuck service. Be careful - it runs with your permissions.",
    "urgent": "Urgent checks use every alert channel. Non-urgent checks only use channels you haven't marked as 'urgent only'.",
}

# --------------------------------------------------------------------------- glossary
GLOSSARY: dict[str, str] = {
    "Availability": "The percentage of time (or checks) something worked. 99.9% sounds perfect but still allows almost 9 hours of outage a year.",
    "ARP": "Address Resolution Protocol. How devices on one network find each other's hardware (MAC) address from an IP address.",
    "Bandwidth": "How much data per second a connection can carry (e.g. 100 Mbit/s). Not the same as latency.",
    "CIDR": "A short way of writing a network range: 192.168.1.0/24 means 192.168.1.0 to 192.168.1.255 (256 addresses).",
    "DHCP": "The service (usually in your router) that hands out IP addresses to devices when they join the network.",
    "DNS": "The internet's phone book: turns names (example.com) into IP addresses.",
    "Gateway": "The device (your router) that connects your local network to other networks, including the internet.",
    "HTTP status code": "The server's answer code: 2xx = success, 3xx = redirect, 4xx = you asked wrong (404 not found), 5xx = server broke.",
    "ICMP": "The protocol behind ping and 'host unreachable' messages.",
    "Incident": "One continuous period when a check was down - with a start, an end and a cause.",
    "Jitter": "How much latency varies from one moment to the next. High jitter makes calls and video choppy even on a fast line.",
    "Mbit/s": "Megabits per second - the unit of internet speed. Divide by 8 for megabytes per second: 100 Mbit/s moves about 12 MB a second.",
    "dBm / RSSI": "Wi-Fi signal strength in decibel-milliwatts. Always negative; closer to 0 is stronger. -50 excellent, -70 fine, -80 poor.",
    "Wi-Fi band": "2.4 GHz reaches further but is slower and crowded; 5 GHz (and 6 GHz) is faster but weaker through walls.",
    "Wi-Fi channel": "The slice of radio a Wi-Fi network uses. On 2.4 GHz only channels 1, 6 and 11 don't overlap.",
    "Wake-on-LAN": "Switching a sleeping or powered-off PC on over the network by sending it a 'magic packet'. Must be enabled in the PC's BIOS.",
    "Magic packet": "The Wake-on-LAN message: six 0xFF bytes followed by the target's MAC address repeated 16 times.",
    "Root cause": "The first thing that broke. Everything after it in the chain fails because of it - fix the root cause and the rest recovers.",
    "Topology": "How devices are connected to each other (what is behind what). A network map is a picture of the topology.",
    "IP address": "A device's address on a network, such as 192.168.1.20.",
    "Latency": "How long a message takes to travel there and back, in milliseconds (ms). Lower is better.",
    "MAC address": "A device's hardware address, burned in at the factory (or randomised for privacy on phones).",
    "MTTR": "Mean Time To Repair/Recover: the average length of your incidents. Shorter is better.",
    "NAT": "Network Address Translation. Lets all your devices share one public internet address.",
    "Packet loss": "The share of network messages that never arrive. Even 2-3% makes calls and video choppy.",
    "Polling": "Asking a device for its status at regular intervals - what NetBeacon does. The opposite is devices 'phoning home' when something happens.",
    "Port": "A numbered door (1-65535) on a device. Web servers use 80/443, remote desktop 3389, etc.",
    "RTO / RPO": "Recovery Time / Recovery Point Objective: how long you can be down, and how much data you can afford to lose.",
    "SLA": "Service Level Agreement. A promise (often by an ISP or cloud provider) about availability, e.g. 99.9%.",
    "SNMP": "Simple Network Management Protocol. Lets switches, routers and printers report detailed statistics. Larger monitoring tools use it heavily.",
    "Subnet": "A slice of an IP network, e.g. all of 192.168.1.x.",
    "TCP": "The reliable connection-based protocol used by web, email, file sharing and most business apps.",
    "TLS certificate": "A digital ID card that proves a website is who it claims and enables the padlock in the browser. It expires.",
    "Tolerance": "In SimpleMonitor: how many failures in a row are forgiven before a check is declared down.",
    "TTL": "Time To Live. A counter that stops lost packets circling forever; also shown in ping replies.",
    "UDP": "A fast, connectionless protocol used by DNS, VoIP and video. Harder to test because there is no 'connection' to confirm.",
    "Uptime": "How long something has been continuously working.",
    "VLAN": "A way to split one physical network into separate virtual networks (e.g. guests vs staff).",
}

# --------------------------------------------------------------------------- ports
# port -> (service, what it is, risk, advice)   risk: info | caution | danger
PORT_INFO: dict[int, tuple[str, str, str, str]] = {
    20: ("FTP data", "File transfer (data channel).", "caution", "FTP sends passwords unencrypted. Prefer SFTP."),
    21: ("FTP", "File Transfer Protocol.", "caution", "Unencrypted. Replace with SFTP/FTPS if possible."),
    22: ("SSH", "Secure remote command line and file copy.", "info", "Normal on servers and network gear. Use keys or strong passwords; never expose to the internet without protection."),
    23: ("Telnet", "Old remote command line.", "danger", "Everything, including passwords, travels in clear text. Turn it off; use SSH."),
    25: ("SMTP", "Mail delivery between servers.", "info", "Expected only on mail servers."),
    53: ("DNS", "Name lookups.", "info", "Expected on routers and DNS/AD servers."),
    80: ("HTTP", "Web (unencrypted).", "info", "Normal for web pages and device admin pages. Prefer HTTPS."),
    110: ("POP3", "Mail download (unencrypted).", "caution", "Prefer POP3S/IMAPS (encrypted)."),
    111: ("rpcbind", "Unix remote procedure call helper.", "caution", "Rarely needed - close it if unused."),
    135: ("MS RPC", "Windows remote procedure calls.", "caution", "Normal on Windows internally; must never be reachable from the internet."),
    139: ("NetBIOS", "Legacy Windows file sharing.", "caution", "Legacy. Disable if not needed."),
    143: ("IMAP", "Mail access (unencrypted).", "caution", "Prefer IMAPS 993."),
    161: ("SNMP", "Device statistics (UDP).", "caution", "Change default 'public' community; never expose to the internet."),
    389: ("LDAP", "Directory lookups (Active Directory).", "info", "Expected on domain controllers."),
    443: ("HTTPS", "Secure web.", "info", "Expected for web servers and many device admin pages."),
    445: ("SMB", "Windows file and printer sharing.", "caution", "Normal inside the office. Never expose to the internet - ransomware favourite."),
    465: ("SMTPS", "Secure mail sending.", "info", ""),
    514: ("Syslog", "Log messages (UDP).", "info", ""),
    515: ("LPD", "Legacy network printing.", "info", "Printers often have this on."),
    554: ("RTSP", "Video streaming (IP cameras).", "caution", "Make sure cameras have non-default passwords."),
    587: ("SMTP submission", "Mail sending from clients.", "info", ""),
    631: ("IPP", "Internet Printing Protocol.", "info", "Printers."),
    636: ("LDAPS", "Secure directory lookups.", "info", ""),
    993: ("IMAPS", "Secure mail access.", "info", ""),
    995: ("POP3S", "Secure mail download.", "info", ""),
    1433: ("SQL Server", "Microsoft SQL Server database.", "caution", "Databases should only be reachable by the servers that need them."),
    1521: ("Oracle DB", "Oracle database.", "caution", "Restrict to application servers."),
    1723: ("PPTP VPN", "Old VPN protocol.", "danger", "Considered insecure. Use a modern VPN."),
    1883: ("MQTT", "IoT messaging.", "caution", "Check that authentication is on."),
    2049: ("NFS", "Unix file sharing.", "caution", "Restrict to trusted machines."),
    3306: ("MySQL / MariaDB", "Database.", "caution", "Restrict to application servers."),
    3389: ("Remote Desktop", "Windows Remote Desktop (RDP).", "danger", "Great for admins - and a top target for attackers. Never expose directly to the internet; use a VPN."),
    5000: ("UPnP / NAS web", "Synology NAS web page or UPnP.", "info", ""),
    5432: ("PostgreSQL", "Database.", "caution", "Restrict to application servers."),
    5900: ("VNC", "Remote screen sharing.", "danger", "Often weakly protected. Use a VPN or a modern tool."),
    5985: ("WinRM (HTTP)", "Windows remote management.", "caution", "Admin tool. Restrict to admin machines."),
    5986: ("WinRM (HTTPS)", "Windows remote management, encrypted.", "info", ""),
    6379: ("Redis", "In-memory database.", "danger", "Often runs without a password. Never expose it."),
    8000: ("HTTP alt", "Alternative web port.", "info", ""),
    8009: ("Chromecast / AJP", "Chromecast control (or Tomcat AJP).", "info", ""),
    8080: ("HTTP alt", "Alternative web port; proxies and admin pages.", "info", ""),
    8443: ("HTTPS alt", "Alternative secure web port.", "info", ""),
    9100: ("JetDirect", "Raw network printing.", "info", "Printers."),
    27017: ("MongoDB", "Database.", "danger", "Has often been left open without a password."),
    62078: ("iOS sync", "Apple iPhone/iPad service.", "info", "Indicates an Apple mobile device."),
}

PORT_PRESETS: dict[str, list[int]] = {
    "Common business ports (about 45)": sorted(PORT_INFO),
    "Web only (80, 443, 8080, 8443)": [80, 443, 8080, 8443],
    "Remote access (22, 23, 3389, 5900, 5985, 5986)": [22, 23, 3389, 5900, 5985, 5986],
    "Databases": [1433, 1521, 3306, 5432, 6379, 27017],
    "File sharing & printing": [21, 22, 139, 445, 515, 631, 2049, 9100],
    "First 1,024 ports (slower)": list(range(1, 1025)),
}


def port_name(port: int) -> str:
    if port in PORT_INFO:
        return PORT_INFO[port][0]
    import socket
    try:
        return socket.getservbyport(port, "tcp")
    except OSError:
        return ""


# --------------------------------------------------------------------------- SLA table
SLA_LEVELS = [90.0, 95.0, 99.0, 99.5, 99.9, 99.95, 99.99, 99.999]


def sla_rows() -> list[tuple[str, str, str, str]]:
    def fmt(seconds: float) -> str:
        if seconds >= 86400 * 2:
            return f"{seconds / 86400:.1f} days"
        if seconds >= 3600:
            return f"{seconds / 3600:.1f} hours"
        if seconds >= 60:
            return f"{seconds / 60:.1f} minutes"
        return f"{seconds:.1f} seconds"

    rows = []
    for pct in SLA_LEVELS:
        down = 1 - pct / 100.0
        rows.append((f"{pct:g}%", fmt(down * 86400), fmt(down * 30 * 86400), fmt(down * 365 * 86400)))
    return rows


# --------------------------------------------------------------------------- lessons
def _sla_html() -> str:
    rows = "".join(f"<tr><td><b>{a}</b></td><td>{b}</td><td>{c}</td><td>{d}</td></tr>" for a, b, c, d in sla_rows())
    return ("<table><tr><th>Availability</th><th>Down per day</th><th>Down per month</th><th>Down per year</th></tr>"
            f"{rows}</table>")


LESSONS: list[dict] = [
    {
        "id": "what", "title": "1. What is network monitoring?", "minutes": 3,
        "html": """
<h2>What is network monitoring?</h2>
<p>Network monitoring means <b>asking questions about your network, automatically and repeatedly</b>, and telling a human when the answer is bad.
That's it. Everything else - graphs, maps, dashboards - is decoration around that loop:</p>
<ol><li><b>Check</b> - ask a question ("does 192.168.1.1 answer a ping?").</li>
<li><b>Decide</b> - is the answer good, bad, or slow?</li>
<li><b>Record</b> - remember it, so you can see trends and prove what happened.</li>
<li><b>Alert</b> - if it's bad for long enough, tell someone.</li></ol>
<h3>Two big families</h3>
<ul><li><b>Availability</b> monitoring: is it up? (ping, port, website)</li>
<li><b>Performance</b> monitoring: is it healthy? (latency, disk space, CPU, memory)</li></ul>
<h3>Who does the asking?</h3>
<p>NetBeacon is <b>active / polling</b> monitoring: it contacts things. Bigger tools can also use <b>agents</b> (small programs on each server that report in)
and <b>passive</b> sources (devices that send logs or SNMP traps). See lesson 13.</p>
<p><b>Try it:</b> open <i>Checks</i> and add a Ping check for your router. You've just built the simplest possible monitoring system.</p>
"""},
    {
        "id": "ping", "title": "2. Ping, latency and packet loss", "minutes": 4,
        "html": """
<h2>Ping, latency and packet loss</h2>
<p><b>Ping</b> sends an ICMP "echo request" and waits for the "echo reply". Two numbers matter:</p>
<ul><li><b>Latency</b> - the round-trip time. On a healthy office network it's 1-5 ms to the router; to a website a few thousand km away, 20-150 ms.</li>
<li><b>Packet loss</b> - replies that never arrive. Any sustained loss is a symptom: bad cable, congested Wi-Fi, failing hardware or an overloaded link.</li></ul>
<h3>Why ping can lie</h3>
<p>A device that doesn't answer ping is not necessarily down: many firewalls (Windows' included) block it on purpose.
And a device that <i>does</i> answer may still have a crashed application. So combine ping (is the machine alive?) with a <b>port or website check</b> (is the service alive?).</p>
<h3>How NetBeacon does it</h3>
<p>It runs your computer's own <code>ping</code> program - no administrator rights needed - several packets at a time, and reads the replies.
The engine is SimpleMonitor; its stock <code>host</code> monitor does the same but only understands English output, so NetBeacon adds a language-proof version.</p>
"""},
    {
        "id": "tcp", "title": "3. TCP ports and services", "minutes": 4,
        "html": """
<h2>TCP ports and services</h2>
<p>An IP address finds a <i>computer</i>; a <b>port</b> finds a <i>program</i> on it. Think of an apartment building: the IP address is the street address, the port is the flat number.</p>
<p>To use a service, a client performs the <b>TCP three-way handshake</b>: SYN ("may I connect?"), SYN-ACK ("yes"), ACK ("great"). A port check simply does that handshake and hangs up.</p>
<h3>Three possible outcomes</h3>
<table><tr><th>Result</th><th>Meaning</th></tr>
<tr><td><b>Open</b></td><td>The handshake worked: a program is listening.</td></tr>
<tr><td><b>Closed (refused)</b></td><td>The machine answered "nobody here" - the computer is up but the service isn't running.</td></tr>
<tr><td><b>Filtered (timed out)</b></td><td>No answer at all: a firewall dropped it, or the machine is off.</td></tr></table>
<p>That difference makes error messages a great diagnostic: <i>refused</i> = restart the program, <i>timed out</i> = check power, cable and firewall.</p>
<p>Common ports: 22 SSH, 25 mail, 53 DNS, 80 web, 443 secure web, 445 Windows file sharing, 3389 Remote Desktop.</p>
"""},
    {
        "id": "dns", "title": "4. DNS - the usual suspect", "minutes": 3,
        "html": """
<h2>DNS - the usual suspect</h2>
<p>People use names (<code>www.example.com</code>); computers use numbers (<code>203.0.113.7</code>). <b>DNS</b> converts one into the other.</p>
<p>When DNS fails, "the internet is down" - yet ping to <code>8.8.8.8</code> still works. A famous IT saying goes: <i>"It's always DNS."</i></p>
<h3>A great trio of checks</h3>
<ol><li>Ping your <b>router</b> - is my local network OK?</li>
<li>Ping a public IP such as <b>1.1.1.1</b> - can I reach the internet?</li>
<li><b>DNS lookup</b> of a well-known name - can I use names?</li></ol>
<p>With all three, the pattern of red and green tells you where the problem is without any guesswork. NetBeacon's setup wizard creates exactly these.</p>
<p>You can point a DNS check at a specific server (your router, 1.1.1.1, 8.8.8.8) to compare them.</p>
"""},
    {
        "id": "web", "title": "5. Websites, status codes and certificates", "minutes": 4,
        "html": """
<h2>Websites, status codes and certificates</h2>
<p>Web checks fetch a page like a browser. The server answers with a <b>status code</b>:</p>
<table><tr><th>Code</th><th>Means</th></tr>
<tr><td>200</td><td>OK</td></tr><tr><td>301 / 302</td><td>Redirect to another address</td></tr>
<tr><td>401 / 403</td><td>Login needed / not allowed</td></tr><tr><td>404</td><td>Page not found</td></tr>
<tr><td>500 / 502 / 503</td><td>The server (or something behind it) is broken or overloaded</td></tr></table>
<h3>Check the content, not just the code</h3>
<p>A broken site can happily return 200 with an error page. Require a word that must always be on the page (your company name, "Log in") for a trustworthy check.</p>
<h3>TLS certificates</h3>
<p>The padlock in your browser comes from a <b>TLS certificate</b>. They expire - commonly every 90 days to a year - and when they do, visitors get a scary warning.
The <i>Certificate expiry</i> check warns you 14 days (by default) ahead. It's one of the cheapest, most valuable checks you can add.</p>
"""},
    {
        "id": "uptime", "title": "6. Uptime, downtime and SLAs", "minutes": 4,
        "html": """
<h2>Uptime, downtime and SLAs</h2>
<p><b>Availability</b> = time working &divide; total time. It's usually quoted in "nines". The table shows how little room each level leaves:</p>
""" + _sla_html() + """
<p>So "99%" allows about <b>3.7 days</b> of outage per year, and "99.9%" nearly <b>9 hours</b>. When an internet provider promises 99.9%, you now know what that means.</p>
<h3>Incidents and MTTR</h3>
<p>Each continuous outage is an <b>incident</b>. The <b>mean time to recover (MTTR)</b> - the average incident length - often matters more than the count: ten 1-minute blips are better than one 10-hour outage.</p>
<h3>How NetBeacon calculates it</h3>
<p>Availability is the share of <i>checks</i> that succeeded (retries inside the tolerance count as up). That way the hours when NetBeacon wasn't running don't distort the result.
Incidents start when the first failing check happened - even if the check only turned red after the tolerance - so downtimes are honest.</p>
"""},
    {
        "id": "falsealarms", "title": "7. False alarms: tolerance and flapping", "minutes": 4,
        "html": """
<h2>False alarms: tolerance and flapping</h2>
<p>Networks drop a packet now and then. If every single hiccup sends an alert, people learn to ignore alerts - and then miss the real one. This is <b>alert fatigue</b>.</p>
<h3>Tolerance (SimpleMonitor: <code>tolerance</code>)</h3>
<p>Require <i>N extra failures in a row</i> before a check turns red. With a 30-second interval and tolerance 2, a check must fail 3 times (about 90 s) to count as an outage.
While waiting, it shows amber <b>Retrying</b>.</p>
<h3>Trade-off</h3>
<table><tr><th>Tolerance</th><th>You hear about real outages</th><th>False alarms</th></tr>
<tr><td>0</td><td>Instantly</td><td>Frequent</td></tr><tr><td>2-3</td><td>After 1-2 minutes</td><td>Rare</td></tr><tr><td>10</td><td>After 5 minutes</td><td>Almost none</td></tr></table>
<h3>Flapping</h3>
<p>A check that bounces between up and down is <b>flapping</b> - typical for a bad cable or weak Wi-Fi. Use the Uptime page's incident list to spot it; it's a problem worth fixing even though each outage is short.</p>
<h3>Rule of thumb</h3>
<p>CPU/memory: tolerance 3-5. Ping/ports on a stable LAN: 1-2. Internet/websites: 2-3. Things that really matter, immediately: 0.</p>
"""},
    {
        "id": "dependencies", "title": "8. Dependencies: one alert, not twenty", "minutes": 3,
        "html": """
<h2>Dependencies: one alert, not twenty</h2>
<p>Imagine the router dies. Suddenly the internet check, the website check, the DNS check and every server behind it all fail. You'd get a flood of 20 alerts, all with the same cause - an <b>alert storm</b>.</p>
<p>The fix is to describe the <b>parent/child</b> relationship: <i>"the file server depends on the switch; the switch depends on the router."</i>
In SimpleMonitor this is the <code>depend</code> setting. When the parent is down, its children are <b>skipped</b> (shown grey as "Not checked because... is down") instead of failing.</p>
<p>In the check editor, open <b>Advanced</b> and use <i>Depends on</i>. Draw a mental map first: the thing closest to the internet is the top parent.</p>
<p>Bigger tools call this "parents" (Nagios), "dependencies" (PRTG) or "trigger dependencies" (Zabbix).</p>
"""},
    {
        "id": "alerts", "title": "9. Alerts people actually read", "minutes": 4,
        "html": """
<h2>Alerts people actually read</h2>
<ul><li><b>Pick the channel to match the urgency.</b> A desktop pop-up is fine at work; at night you need something on your phone (ntfy, Telegram, Pushover) or email.</li>
<li><b>Tell people what to do.</b> Fill in <i>What to do if this fails</i> on each check: who to ring, which plug to pull. Alerts include it.</li>
<li><b>Use quiet hours.</b> Not everything is worth waking someone for. NetBeacon (via SimpleMonitor's alert-time rules) can hold alerts back overnight and send a "failed earlier" catch-up in the morning.</li>
<li><b>Send recovery messages.</b> "It's back" ends the worry and shows how long the outage lasted.</li>
<li><b>Test it!</b> Use <i>Send test alert</i> and the <b>Practice check</b> to see what an alert looks like <i>before</i> you need it.</li></ul>
<h3>Urgency</h3>
<p>Mark non-critical checks as "not urgent" so urgent-only channels (like SMS) aren't wasted on them.</p>
<h3>Single point of failure</h3>
<p>If your internet is down, an email or Slack alert can't leave the building! Add at least one channel that doesn't depend on the thing being monitored (e.g. a desktop pop-up or a mobile-data phone).</p>
"""},
    {
        "id": "discovery", "title": "10. Discovering devices (and unwelcome guests)", "minutes": 4,
        "html": """
<h2>Discovering devices</h2>
<p>You can't monitor what you don't know about. Discovery sweeps your network:</p>
<ol><li>Ping every address in the range (a <b>ping sweep</b>).</li>
<li>Read the <b>ARP table</b>. Before a computer can send to 192.168.1.20 on the same network it must ask "who has this address?" and learns the answer's <b>MAC address</b>. A device that ignores ping still answers ARP, so it shows up.</li>
<li>Look up the device's name through reverse DNS.</li></ol>
<h3>IP vs MAC</h3>
<p>The IP address can change (DHCP hands them out); the MAC address identifies the hardware. NetBeacon remembers devices by MAC.
Phones and modern laptops often use a <b>private (randomised) MAC</b> per Wi-Fi network - you'll see them flagged - which can make the same phone look "new" after a settings change.</p>
<h3>New device alerts</h3>
<p>Mark everything you recognise as <i>known</i>. After that, enable <b>watch for new devices</b> in Settings: NetBeacon rescans periodically and notifies you when a stranger joins.</p>
<h3>Tip</h3>
<p>Give important devices a fixed address (a "DHCP reservation" in your router) so checks that use their IP don't break.</p>
"""},
    {
        "id": "security", "title": "11. Open ports and basic security", "minutes": 3,
        "html": """
<h2>Open ports and basic security</h2>
<p>Every open port is something an attacker can try. Normal inside the office - risky when reachable from the internet.</p>
<ul><li><b>Danger zone:</b> Telnet (23), Remote Desktop (3389) and VNC (5900) open to the internet, unprotected databases (Redis, MongoDB, SQL Server), and Windows file sharing (445) exposed.</li>
<li><b>Scan your own public address</b> from outside (a phone on mobile data) to see what the world sees.</li>
<li><b>Keep a baseline.</b> Scan important servers once, note what's open, and add a port check for each expected port. An <i>unexpected</i> new port is a signal.</li></ul>
<p>The Port Scanner explains each open port and flags the risky ones. It is a teaching aid, not a full vulnerability scanner.</p>
<p><b>Legal note:</b> Only scan networks and devices you own or are explicitly authorised to test.</p>
"""},
    {
        "id": "health", "title": "12. Server health: disks, memory, services, backups", "minutes": 4,
        "html": """
<h2>Server health: disks, memory, services, backups</h2>
<p>Most "network" problems are really host problems. Four cheap checks prevent a surprising number of outages:</p>
<ul><li><b>Free disk space</b> - warn at 10-15% free. Full disks break databases, backups and updates.</li>
<li><b>Free memory</b> - low memory makes everything slow. Use a tolerance, spikes are normal.</li>
<li><b>Critical services</b> - the database, the print spooler, your accounting software's service.</li>
<li><b>Backup freshness</b> - "was a backup file written in the last 26 hours?" The best insurance you can monitor.</li></ul>
<p>Open <i>Services &amp; Programs</i> to browse everything running on this PC and create a check with a click.</p>
<p>These checks run on the computer where NetBeacon runs. To watch other servers' disks and services you need an <b>agent</b> on each (see the next lesson).</p>
"""},
    {
        "id": "methods", "title": "13. Monitoring methods: polling, SNMP, agents, logs", "minutes": 5,
        "html": """
<h2>Monitoring methods</h2>
<table>
<tr><th>Method</th><th>How it works</th><th>Good for</th><th>In NetBeacon?</th></tr>
<tr><td><b>Active checks</b> (ping, port, HTTP, DNS)</td><td>The monitor contacts the target</td><td>Availability from the user's point of view</td><td>Yes</td></tr>
<tr><td><b>SNMP polling</b></td><td>Ask switches/routers/printers for counters (traffic per port, toner level, temperature)</td><td>Network gear, bandwidth graphs</td><td>No - next step</td></tr>
<tr><td><b>Agents</b></td><td>A small program on each server reports CPU, disk, services, logs</td><td>Deep server health on many machines</td><td>No (local PC only)</td></tr>
<tr><td><b>Traps / syslog</b></td><td>Devices push a message when something happens</td><td>Event-driven alerts, security logs</td><td>No</td></tr>
<tr><td><b>Flow data</b> (NetFlow/sFlow)</td><td>Records who talked to whom, how much</td><td>"Where is my bandwidth going?"</td><td>No</td></tr>
<tr><td><b>Synthetic transactions</b></td><td>A script performs a real task (log in, place an order)</td><td>Proving the business process works</td><td>Via "Run a command"</td></tr>
</table>
<p>SimpleMonitor can also run in several places (e.g. one per office) and <b>send results to a central instance</b> - its simple answer to "remote sites".</p>
"""},
    {
        "id": "rootcause", "title": "14. Finding the cause: diagnosis, Wi-Fi and speed", "minutes": 5,
        "html": """
<h2>Finding the cause</h2>
<p>"The internet is down" can mean five very different things. Professionals find out which by testing <b>outwards from the PC</b>,
one link at a time - exactly what NetBeacon's <b>What's wrong?</b> button does:</p>
<table><tr><th>Step</th><th>If it fails, the problem is...</th></tr>
<tr><td>This PC has a network address</td><td>this PC: cable, Wi-Fi, adapter, Airplane mode</td></tr>
<tr><td>The router answers</td><td>inside the office: router, switch, cable, Wi-Fi</td></tr>
<tr><td>1.1.1.1 answers (by number)</td><td>the modem or your internet provider</td></tr>
<tr><td>Names work (DNS)</td><td>the DNS server - often the router itself</td></tr>
<tr><td>Web pages load</td><td>a proxy, firewall or a guest-Wi-Fi login page</td></tr></table>
<p>The <b>first</b> failure is the <b>root cause</b>; everything after it fails <i>because</i> of it. That's also why dependencies
(lesson 8) matter: they stop you getting twenty alerts for one root cause.</p>
<h3>Slow is not the same as down</h3>
<ul><li><b>Wi-Fi</b>: a weak signal (below about 40%, or -80 dBm) or a crowded channel makes everything slow and flaky, while every check
still says 'up'. The Wi-Fi page shows signal, channel and neighbours, and the <i>Wi-Fi signal</i> check can alert you.</li>
<li><b>Internet speed</b>: regular speed tests show whether the line delivers what you pay for, and when it doesn't (evenings are typical).
Test from a cabled PC for fair numbers.</li></ul>
<h3>Waking things up</h3>
<p>The Devices page and the map can send a <b>Wake-on-LAN</b> packet to switch on a sleeping PC - handy before remote work or overnight updates.
It needs to be enabled in that PC's BIOS/UEFI and network adapter settings, and usually only works inside the same network.</p>
"""},
    {
        "id": "graduate", "title": "15. Outgrowing NetBeacon: what next?", "minutes": 5,
        "html": "@@GRADUATE@@"},
]


def _graduate_html() -> str:
    return """
<h2>Outgrowing NetBeacon</h2>
<p>NetBeacon is deliberately small. That is a feature - but you may eventually need more. Signs it's time to move on:</p>
<ul><li>More than ~50-100 devices, or several sites.</li>
<li>You need <b>bandwidth graphs per switch port</b> (SNMP), or temperature/toner/battery readings.</li>
<li>You need <b>agents</b> on many servers, or log monitoring.</li>
<li>Several people need their own logins and dashboards.</li>
<li>You need on-call schedules, escalation, or compliance reports.</li>
<li>Monitoring must run 24/7 and survive this PC being switched off.</li></ul>
<h3>Step 1 - run the same engine on a small always-on machine</h3>
<p>Use <b>Settings &gt; Export for stock SimpleMonitor</b> to get <code>monitor.ini</code> and <code>monitors.ini</code>. Install SimpleMonitor
(<code>pip install simplemonitor</code>) on a Raspberry Pi or a small server, run <code>simplemonitor -f monitor.ini</code>, and you have headless monitoring.
SimpleMonitor can forward results to a central instance, and writes an HTML status page.</p>
<h3>Step 2 - pick a bigger tool</h3>
<table>
<tr><th>Tool</th><th>Style</th><th>Consider it when...</th></tr>
<tr><td><b>Uptime Kuma</b></td><td>Self-hosted, friendly uptime monitor with status pages</td><td>You like NetBeacon's simplicity but want a web UI, multiple users and 24/7 on a server.</td></tr>
<tr><td><b>Zabbix</b></td><td>Open-source all-in-one: agents, SNMP, auto-discovery, templates, triggers</td><td>You want one free system for servers <i>and</i> network gear and can invest time in learning it.</td></tr>
<tr><td><b>Checkmk</b></td><td>Agent-based, auto-discovers what to monitor on each host (free Raw edition and paid editions)</td><td>Mostly servers and services; you want less manual setup.</td></tr>
<tr><td><b>PRTG</b></td><td>Commercial Windows all-in-one built from "sensors"</td><td>You want a polished product with support (check current licensing and free-tier limits).</td></tr>
<tr><td><b>LibreNMS</b></td><td>Open-source, SNMP-centred, auto-discovers switches/routers</td><td>The network equipment is your main concern; you want traffic graphs.</td></tr>
<tr><td><b>Nagios Core / Icinga</b></td><td>The classic plugin-based approach</td><td>You need maximum flexibility and are happy to edit configuration files.</td></tr>
<tr><td><b>Prometheus + Grafana</b></td><td>Metrics database + dashboards</td><td>Application and server metrics, dashboards and engineering-style alerting.</td></tr>
<tr><td><b>Netdata</b></td><td>Per-second health metrics on each host</td><td>You mainly need deep performance insight into servers.</td></tr>
</table>
<h3>Rosetta stone: NetBeacon words in other tools</h3>
<table>
<tr><th>NetBeacon / SimpleMonitor</th><th>You'll hear in bigger tools</th></tr>
<tr><td>Check (monitor)</td><td>Sensor, service check, item + trigger, monitor</td></tr>
<tr><td>Failures before it counts as down (<code>tolerance</code>)</td><td>Max check attempts, retries, consecutive failures</td></tr>
<tr><td>Depends on (<code>depend</code>)</td><td>Parent, dependency, trigger dependency</td></tr>
<tr><td>Alert channel (alerter)</td><td>Notification method, media type, contact</td></tr>
<tr><td>Group</td><td>Host group, tag, device group</td></tr>
<tr><td>What to do if this fails (<code>failure_doc</code>)</td><td>Runbook, KB link, comment</td></tr>
<tr><td>Quiet hours</td><td>Notification period, schedule, maintenance window</td></tr>
<tr><td>Incident</td><td>Problem, event, outage</td></tr>
<tr><td>What's wrong? (diagnosis)</td><td>Root cause analysis, topology-aware alerting</td></tr>
<tr><td>Network map</td><td>Topology map, network map, maps (Zabbix), device tree (PRTG)</td></tr>
<tr><td>Weekly summary</td><td>Scheduled report, SLA report</td></tr>
</table>
<p>The concepts carry over almost one-to-one - you will not be starting from scratch.</p>
"""


for _l in LESSONS:
    if _l["html"] == "@@GRADUATE@@":
        _l["html"] = _graduate_html()


# --------------------------------------------------------------------------- how it works (for the Activity page)
HOW_IT_WORKS = """
<h3>How NetBeacon uses SimpleMonitor</h3>
<ol>
<li><b>You</b> add checks in the friendly interface.</li>
<li>NetBeacon writes them as <code>monitors.ini</code> (one <code>[section]</code> per check) and writes <code>monitor.ini</code> (interval, alert channels, loggers).</li>
<li>The <b>SimpleMonitor engine</b> loads those files and, every interval, runs all checks in parallel, honours <code>depend</code> and <code>tolerance</code>,
and calls its <b>alerters</b> (desktop, email, Slack...) and <b>loggers</b> (NetBeacon's history recorder, the optional HTML status page).</li>
<li>NetBeacon shows the results and keeps the history in a small database so you can see uptime and incidents.</li></ol>
<p>Nothing is hidden: the two tabs next to this one show the real files and the engine's own log.</p>
"""
