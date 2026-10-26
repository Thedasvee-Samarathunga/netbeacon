"""Entry script used by PyInstaller (and handy for `python run_netbeacon.py`)."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from netbeacon.app import main

    sys.exit(main())
