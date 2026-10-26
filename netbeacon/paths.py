"""Where NetBeacon keeps its files."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def data_dir() -> Path:
    override = os.environ.get("NETBEACON_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / APP_NAME.lower()
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_dir() -> Path:
    p = data_dir() / "simplemonitor-config"
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_dir() -> Path:
    p = data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def status_page_dir() -> Path:
    p = data_dir() / "status-page"
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_file() -> Path:
    return data_dir() / "settings.json"


def monitors_file() -> Path:
    return data_dir() / "monitors.json"


def history_file() -> Path:
    return data_dir() / "history.sqlite3"
