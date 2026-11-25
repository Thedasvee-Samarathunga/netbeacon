"""Wi-Fi health: reads Windows' own `netsh wlan` output (no extra drivers, no admin rights).

Everything that parses text is a plain function so it can be tested with sample output.
`netsh` output is translated into the Windows display language, so the parsers mostly look at
the *shape* of each value (a percentage, '5 GHz', '802.11ax', a MAC address) instead of English words.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional

IS_WINDOWS = sys.platform == "win32"

_KV = re.compile(r"^\s*([^:]+?)\s+:\s?(.*)$")
_MAC = re.compile(r"([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}")
_PCT = re.compile(r"^(\d{1,3})\s*%$")
_GHZ = re.compile(r"(\d+(?:[.,]\d+)?)\s*GHz", re.I)
_CHANNEL_WORDS = ("channel", "kanal", "canal", "canale", "chaîne", "kanaal", "kanał", "csatorna", "kanava", "チャネル", "通道", "信道", "채널")
_STATE_CONNECTED = ("connected", "verbunden", "connecté", "conectado", "connesso", "verbonden", "połączono", "ansluten", "tilsluttet",
                    "接続されました", "已连接", "연결됨")
_STATE_DISCONNECTED = ("disconnected", "getrennt", "déconnecté", "desconectado", "disconnesso", "verbinding verbroken", "rozłączono",
                       "frånkopplad", "afbrudt", "切断されました", "已断开连接", "연결 끊김")
LOCATION_NOTE = ("Windows is hiding Wi-Fi details because NetBeacon has no location permission. Open Settings > Privacy & security > "
                 "Location, turn on 'Let desktop apps access your location', then press Refresh. (Windows treats nearby Wi-Fi names as location data.)")


@dataclass
class WifiStatus:
    available: bool = False          # could we read anything at all?
    connected: bool = False
    interface: str = ""
    ssid: str = ""
    bssid: str = ""
    signal: Optional[int] = None     # percent, as Windows reports it
    rssi: Optional[int] = None       # dBm (newer Windows versions report it; otherwise estimated)
    channel: Optional[int] = None
    band: str = ""
    radio: str = ""
    auth: str = ""
    rx_mbps: Optional[float] = None
    tx_mbps: Optional[float] = None
    note: str = ""

    @property
    def dbm(self) -> Optional[int]:
        if self.rssi is not None:
            return self.rssi
        return signal_to_dbm(self.signal) if self.signal is not None else None


@dataclass
class WifiNetwork:
    ssid: str
    bssid: str = ""
    signal: Optional[int] = None
    channel: Optional[int] = None
    band: str = ""
    auth: str = ""
    radio: str = ""


# --------------------------------------------------------------------------- helpers
def signal_to_dbm(pct: int) -> int:
    """Windows' signal % is roughly linear between -100 dBm (0%) and -50 dBm (100%)."""
    return int(round(max(0, min(100, pct)) / 2 - 100))


def quality(pct: Optional[int]) -> tuple[str, str]:
    """(word, colour) for a signal percentage."""
    if pct is None:
        return "unknown", "#64748b"
    if pct >= 80:
        return "excellent", "#16a34a"
    if pct >= 60:
        return "good", "#16a34a"
    if pct >= 40:
        return "fair", "#f59e0b"
    return "poor", "#dc2626"


def band_of(channel: Optional[int], band_text: str = "") -> str:
    m = _GHZ.search(band_text or "")
    if m:
        v = float(m.group(1).replace(",", "."))
        return "6 GHz" if v >= 5.9 else "5 GHz" if v >= 4.9 else "2.4 GHz"
    if channel is None:
        return ""
    return "2.4 GHz" if channel <= 14 else "5 GHz"


def _num(text: str) -> Optional[float]:
    m = re.search(r"\d+(?:[.,]\d+)?", text or "")
    return float(m.group(0).replace(",", ".")) if m else None


def _is_channel_key(key: str) -> bool:
    k = key.lower()
    return any(w in k for w in _CHANNEL_WORDS) and "util" not in k and "auslast" not in k


# --------------------------------------------------------------------------- parsers
def parse_interfaces(text: str) -> WifiStatus:
    """Parse `netsh wlan show interfaces`."""
    if "location" in (text or "").lower() and "permission" in (text or "").lower():
        return WifiStatus(available=False, note=LOCATION_NOTE)
    blocks: list[list[tuple[str, str]]] = []
    cur: list[tuple[str, str]] = []
    for line in (text or "").splitlines():
        m = _KV.match(line)
        if not m:
            if cur:
                blocks.append(cur)
                cur = []
            continue
        cur.append((m.group(1).strip(), m.group(2).strip()))
    if cur:
        blocks.append(cur)
    blocks = [b for b in blocks if len(b) >= 4]
    if not blocks:
        return WifiStatus(available=False, note="No Wi-Fi adapter was found on this computer.")
    # prefer the block that has a signal value (that's the connected adapter)
    block = next((b for b in blocks if any(_PCT.match(v) for _, v in b)), blocks[0])
    st = WifiStatus(available=True)
    rates: list[float] = []
    for key, val in block:
        kl = key.lower()
        if not st.interface and kl in ("name", "nom", "nombre", "nome", "naam", "nazwa", "namn", "名前", "名称", "이름"):
            st.interface = val
        elif key.upper() == "SSID":
            st.ssid = val
        elif "bssid" in kl and _MAC.search(val):
            st.bssid = _MAC.search(val).group(0).replace("-", ":").upper()
        elif _PCT.match(val) and st.signal is None:
            st.signal = int(_PCT.match(val).group(1))
        elif kl == "rssi":
            n = _num(val.replace("-", ""))
            st.rssi = -int(n) if n is not None else None
        elif _GHZ.search(val) and not st.band:
            st.band = band_of(None, val)
        elif val.lower().startswith("802.11"):
            st.radio = val
        elif _is_channel_key(key) and _num(val) is not None:
            st.channel = int(_num(val))
        elif "(mbps)" in kl or "mbit" in kl:
            n = _num(val)
            if n is not None:
                rates.append(n)
        elif kl.startswith(("authentication", "authentifizierung", "authentification", "autenticación", "autenticazione")):
            st.auth = val
        elif kl in ("state", "status", "état", "estado", "stato", "staat", "stan", "tillstånd", "状態", "状态", "상태"):
            vl = val.lower()
            st.connected = any(w == vl or vl.startswith(w) for w in _STATE_CONNECTED) and not any(vl.startswith(w) for w in _STATE_DISCONNECTED)
    if rates:
        st.rx_mbps = rates[0]
        st.tx_mbps = rates[1] if len(rates) > 1 else None
    if not st.band and st.channel:
        st.band = band_of(st.channel)
    if st.ssid and st.signal is not None:
        st.connected = True
    return st


def parse_networks(text: str) -> tuple[list[WifiNetwork], str]:
    """Parse `netsh wlan show networks mode=bssid`. Returns (networks, note)."""
    low = (text or "").lower()
    if "location" in low and "permission" in low:
        return [], LOCATION_NOTE
    out: list[WifiNetwork] = []
    ssid = ""
    auth = ""
    ap: Optional[WifiNetwork] = None
    for line in (text or "").splitlines():
        m = re.match(r"^SSID\s+\d+\s*:\s?(.*)$", line.strip())
        if m:
            ssid = m.group(1).strip()
            auth = ""
            ap = None
            continue
        m = re.match(r"^BSSID\s+\d+\s*:\s*(.+)$", line.strip())
        if m:
            mac = _MAC.search(m.group(1))
            ap = WifiNetwork(ssid=ssid, bssid=mac.group(0).replace("-", ":").upper() if mac else "", auth=auth)
            out.append(ap)
            continue
        kv = _KV.match(line)
        if not kv:
            continue
        key, val = kv.group(1).strip(), kv.group(2).strip()
        if ap is None:
            if key.lower().startswith(("authentication", "authentifizierung", "authentification", "autenticación", "autenticazione")):
                auth = val
            continue
        if _PCT.match(val) and ap.signal is None:
            ap.signal = int(_PCT.match(val).group(1))
        elif _GHZ.search(val) and not ap.band:
            ap.band = band_of(None, val)
        elif val.lower().startswith("802.11"):
            ap.radio = val
        elif _is_channel_key(key) and _num(val) is not None and ap.channel is None:
            ap.channel = int(_num(val))
    for n in out:
        if not n.band:
            n.band = band_of(n.channel)
    return out, ""


# --------------------------------------------------------------------------- reading
def _netsh(*args: str) -> str:
    proc = subprocess.run(["netsh", "wlan", *args], capture_output=True, timeout=15, check=False)
    raw = proc.stdout or b""
    for enc in ("utf-8", "mbcs", "cp850", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace")


def read_status() -> WifiStatus:
    if not IS_WINDOWS:
        return WifiStatus(available=False, note="Wi-Fi details are read with Windows' netsh tool, so they are only available on Windows.")
    try:
        return parse_interfaces(_netsh("show", "interfaces"))
    except (OSError, subprocess.SubprocessError) as exc:
        return WifiStatus(available=False, note=f"Could not read Wi-Fi details: {exc}")


def scan_networks() -> tuple[list[WifiNetwork], str]:
    if not IS_WINDOWS:
        return [], "Nearby networks can only be listed on Windows."
    try:
        return parse_networks(_netsh("show", "networks", "mode=bssid"))
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"Could not list nearby networks: {exc}"


# --------------------------------------------------------------------------- analysis
def crowding(networks: list[WifiNetwork], band: str) -> dict[int, float]:
    """How busy each channel is. On 2.4 GHz neighbours within 4 channels overlap, so they count partly."""
    score: dict[int, float] = {}
    nets = [n for n in networks if n.channel and n.band == band]
    if band == "2.4 GHz":
        for ch in range(1, 14):
            s = 0.0
            for n in nets:
                d = abs(n.channel - ch)
                if d <= 4:
                    weight = (5 - d) / 5          # same channel = 1, 4 away = 0.2
                    strength = (n.signal or 50) / 100
                    s += weight * strength
            score[ch] = round(s, 2)
    else:
        for n in nets:
            score[n.channel] = round(score.get(n.channel, 0.0) + (n.signal or 50) / 100, 2)
    return score


def best_24_channel(networks: list[WifiNetwork]) -> Optional[int]:
    sc = crowding(networks, "2.4 GHz")
    if not any(n.band == "2.4 GHz" for n in networks):
        return None
    return min((1, 6, 11), key=lambda c: (sc.get(c, 0), c))


def advice(st: WifiStatus, networks: list[WifiNetwork]) -> list[str]:
    tips: list[str] = []
    if not st.available or not st.connected:
        return tips
    word, _ = quality(st.signal)
    if st.signal is not None and st.signal < 40:
        tips.append(f"The signal is {word} ({st.signal}%, about {st.dbm} dBm). Move closer to the access point, remove obstacles "
                    "(walls, metal cabinets, fish tanks), or add a mesh point / second access point.")
    elif st.signal is not None and st.signal < 60:
        tips.append(f"The signal is only {word} ({st.signal}%). It works, but video calls may stutter. Moving the access point higher and more central usually helps.")
    if st.band == "2.4 GHz":
        tips.append("You are on 2.4 GHz: it reaches further but is slower and more crowded. If your access point offers 5 GHz, use it for desks near the access point.")
        same = [n for n in networks if n.band == "2.4 GHz" and n.channel == st.channel and n.bssid != st.bssid]
        if st.channel and st.channel not in (1, 6, 11):
            tips.append(f"Channel {st.channel} overlaps two of the standard channels (1, 6, 11). Setting the access point to 1, 6 or 11 reduces interference.")
        best = best_24_channel(networks)
        if best and st.channel and best != st.channel:
            sc = crowding(networks, "2.4 GHz")
            if sc.get(st.channel, 0) - sc.get(best, 0) >= 0.5:
                tips.append(f"Channel {best} looks quieter than your channel {st.channel} right now - consider switching the access point to it.")
        if len(same) >= 3:
            tips.append(f"{len(same)} other networks share channel {st.channel} with you.")
    if st.rx_mbps is not None and st.rx_mbps < 50:
        tips.append(f"The link speed is only {st.rx_mbps:g} Mbit/s - usually a sign of a weak signal or an old Wi-Fi standard.")
    if st.radio and st.radio.lower() in ("802.11b", "802.11g", "802.11a"):
        tips.append(f"This connection uses {st.radio}, an old Wi-Fi standard. A newer access point or adapter would be much faster.")
    if st.auth and ("wep" in st.auth.lower() or "open" in st.auth.lower()):
        tips.append(f"Security is '{st.auth}'. Open or WEP networks are not safe for business use - switch the access point to WPA2 or WPA3.")
    if not tips:
        tips.append("This Wi-Fi connection looks healthy.")
    return tips
