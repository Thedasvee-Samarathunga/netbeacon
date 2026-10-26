"""Start-up shims. Import this module BEFORE importing simplemonitor.

What it does (and why):

1. Lightweight stand-ins for SimpleMonitor's *optional* heavy dependencies
   (boto3, twilio, paramiko, pyaarlo, ring_doorbell, paho-mqtt ...).
   SimpleMonitor imports these at module level even though NetBeacon never
   uses the monitors/alerters that need them. If the real package is installed
   it is used; if not, a harmless stub is created. This keeps the Windows
   executable much smaller.
2. On Windows, stops every child process (ping, arp, ...) from flashing a
   black console window.
3. A safety-net socket timeout so one unreachable host can never hang a check.
4. Makes SimpleMonitor's version lookup work inside a PyInstaller bundle.
"""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import socket
import subprocess
import sys
import types

_STUB_ROOTS = {
    "pyaarlo", "ring_doorbell", "oauthlib", "paramiko",
    "boto3", "botocore", "twilio", "paho",
}


class _StubModule(types.ModuleType):
    """A module whose every attribute is a dummy class (usable as an exception too)."""

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        value = type(name, (Exception,), {"__module__": self.__name__})
        setattr(self, name, value)
        return value


class _StubFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path, target=None):
        if fullname.split(".")[0] in _STUB_ROOTS:
            return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        module = _StubModule(spec.name)
        module.__path__ = []  # behave like a package so sub-imports work
        module.__netbeacon_stub__ = True
        return module

    def exec_module(self, module):
        return None


_installed = False


def apply() -> None:
    global _installed
    if _installed:
        return
    _installed = True

    # 0. windowed apps have no console: make print()/stderr writes harmless
    import os
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    # 1. stubs (appended LAST so real packages always win)
    sys.meta_path.append(_StubFinder())

    # 2. no console windows on Windows
    if sys.platform == "win32":
        _orig_init = subprocess.Popen.__init__

        def _init(self, *args, **kwargs):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x08000000  # CREATE_NO_WINDOW
            _orig_init(self, *args, **kwargs)

        subprocess.Popen.__init__ = _init  # type: ignore[method-assign]

    # 3. never let a socket block forever
    socket.setdefaulttimeout(20)

    # 4. version lookup inside frozen apps
    try:
        import importlib.metadata as md

        _orig_version = md.version

        def _version(name):
            try:
                return _orig_version(name)
            except md.PackageNotFoundError:
                if name.lower() == "simplemonitor":
                    return "1.15.0"
                raise

        md.version = _version  # type: ignore[assignment]
    except Exception:  # pragma: no cover
        pass


apply()
