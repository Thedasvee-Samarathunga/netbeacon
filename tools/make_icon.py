"""Create assets/netbeacon.ico (classic bitmap frames - no PNG-compressed entries) and netbeacon.png.

    python tools/make_icon.py

Why classic bitmap frames? Some Windows tools (installers, older shells) choke on PNG-compressed
.ico files; plain 32-bit bitmaps work everywhere.
"""
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

from netbeacon.ui.theme import draw_logo  # noqa: E402

SIZES = [16, 24, 32, 48, 64, 128, 256]


def dib(size: int) -> bytes:
    img = draw_logo(size).toImage().convertToFormat(QImage.Format.Format_ARGB32)
    rows = []
    for y in range(size - 1, -1, -1):                # bottom-up
        line = bytearray()
        for x in range(size):
            c = img.pixelColor(x, y)
            line += bytes((c.blue(), c.green(), c.red(), c.alpha()))
        rows.append(bytes(line))
    pixels = b"".join(rows)
    mask_row = ((size + 31) // 32) * 4
    mask = b"\x00" * (mask_row * size)               # alpha channel does the masking
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
    return header + pixels + mask


def main() -> None:
    app = QGuiApplication([])
    out = Path(__file__).resolve().parents[1] / "assets"
    out.mkdir(exist_ok=True)
    frames = [(s, dib(s)) for s in SIZES]
    ico = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = b""
    data = b""
    for s, blob in frames:
        entries += struct.pack("<BBBBHHII", 0 if s >= 256 else s, 0 if s >= 256 else s, 0, 0, 1, 32, len(blob), offset + len(data))
        data += blob
    (out / "netbeacon.ico").write_bytes(ico + entries + data)
    draw_logo(256).save(str(out / "netbeacon.png"))
    print("wrote", out / "netbeacon.ico", (out / "netbeacon.ico").stat().st_size, "bytes")


if __name__ == "__main__":
    main()
