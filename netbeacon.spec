# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for NetBeacon.
#   one-file .exe :   pyinstaller netbeacon.spec
#   one-folder    :   NB_ONEDIR=1 pyinstaller netbeacon.spec      (starts faster, fewer antivirus false alarms)
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ONEDIR = os.environ.get("NB_ONEDIR") == "1"
IS_WIN = sys.platform == "win32"

# SimpleMonitor loads its monitors / alerters / loggers by name at run time, so list every sub-module,
# and ship its html/ status-page templates plus its package metadata (it reads its own version).
hidden = collect_submodules("simplemonitor") + [
    "netbeacon.sm_ext", "netbeacon.compat", "netbeacon.selftest",
    "netbeacon.diagnose", "netbeacon.digest", "netbeacon.notify", "netbeacon.speedtest", "netbeacon.wifi",
    "icmplib", "jinja2", "markupsafe", "colorlog", "arrow", "dateutil", "psutil", "requests",
]
datas = collect_data_files("simplemonitor") + copy_metadata("simplemonitor") + [("assets/netbeacon.png", "assets")]

# Things NetBeacon never uses (keeps the download smaller)
excludes = [
    "tkinter", "unittest", "pydoc", "test", "lib2to3",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtMultimedia",
    "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtQuick", "PySide6.QtQml",
    "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth", "PySide6.QtSerialPort",
    "boto3", "botocore", "twilio", "paramiko", "pyaarlo", "ring_doorbell", "paho",
    "numpy", "matplotlib", "pandas", "PIL.ImageQt",
]

version_info = None
if IS_WIN:
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
                                                      VarStruct, VSVersionInfo)
    ver = (1, 2, 0, 0)
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=ver, prodvers=ver, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
        kids=[StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "NetBeacon"), StringStruct("FileDescription", "NetBeacon network monitor"),
            StringStruct("FileVersion", "1.2.0"), StringStruct("InternalName", "NetBeacon"),
            StringStruct("OriginalFilename", "NetBeacon.exe"), StringStruct("ProductName", "NetBeacon"),
            StringStruct("ProductVersion", "1.2.0")])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])])

a = Analysis(
    ["run_netbeacon.py"], pathex=["."], binaries=[], datas=datas, hiddenimports=hidden,
    hookspath=[], runtime_hooks=[], excludes=excludes, noarchive=False,
)
pyz = PYZ(a.pure)

icon = "assets/netbeacon.ico" if IS_WIN else None

if ONEDIR:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="NetBeacon", console=False, icon=icon,
              version=version_info, upx=False, disable_windowed_traceback=False)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="NetBeacon")
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="NetBeacon", console=False, icon=icon,
              version=version_info, upx=False, runtime_tmpdir=None, disable_windowed_traceback=False)
