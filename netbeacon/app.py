"""Program entry point."""
from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback


def _setup_logging() -> None:
    from . import paths

    handler = logging.handlers.RotatingFileHandler(paths.log_dir() / "netbeacon.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logging.getLogger("netbeacon").setLevel(logging.INFO)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        i = argv.index("--selftest")
        from .selftest import run
        return run(argv[i + 1] if i + 1 < len(argv) else "netbeacon-selftest.json")

    from . import compat  # noqa: F401  (must precede simplemonitor imports)
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox

    from . import paths
    from .engine import EngineCore
    from .store import History, Store
    from .ui import theme
    from .ui.context import AppContext
    from .ui.main_window import MainWindow
    from .ui.widgets import hub

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NetBeacon.Desktop")
        except Exception:
            pass

    _setup_logging()
    log = logging.getLogger("netbeacon")

    def excepthook(exc_type, exc, tb):
        log.error("Unhandled exception:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))

    sys.excepthook = excepthook

    app = QApplication([sys.argv[0]] + argv)
    app.setApplicationName("NetBeacon")
    app.setOrganizationName("NetBeacon")
    app.setStyle("Fusion")
    app.setWindowIcon(theme.app_icon())
    app.setQuitOnLastWindowClosed(False)

    lock = QLockFile(str(paths.data_dir() / "netbeacon.lock"))
    lock.setStaleLockTime(30000)
    if not lock.tryLock(300):
        QMessageBox.information(None, "NetBeacon", "NetBeacon is already running.\nLook for its icon in the system tray (near the clock).")
        return 0

    store = Store()
    theme.set_current(store.get("theme", "light"), store.get("accent", ""))
    theme.apply_palette(app, theme._current)
    app.setStyleSheet(theme.stylesheet(theme._current))
    hub.set(bool(store.get("teaching_mode", True)))

    history = History()
    core = EngineCore(store, history)
    ctx = AppContext(store, history, core)
    window = MainWindow(ctx, start_minimized="--minimized" in argv)
    app._window = window  # keep a reference
    core.start()
    code = app.exec()
    core.stop()
    history.close()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
