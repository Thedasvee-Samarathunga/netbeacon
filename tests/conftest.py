import os
import sys
import tempfile
from pathlib import Path

# every test run gets its own private data folder
_tmp = tempfile.mkdtemp(prefix="netbeacon-test-")
os.environ["NETBEACON_HOME"] = _tmp
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("NETBEACON_HOME", str(tmp_path))
    return tmp_path
