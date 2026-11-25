# Architecture and how to extend NetBeacon

## Data flow

```
                +--------------------+        edits         +--------------------+
   GUI pages -> | AppContext (Qt)    | -------------------> | Store (JSON)       |
                +----------+---------+                       +---------+----------+
                           ^ signals (queued across threads)           | config_writer.build()
                           |                                           v
                +----------+---------+   loads        +----------------------------------+
                | EngineCore (thread)| -------------> | monitor.ini  +  monitors.ini     |
                |  run_loop() every  |                +----------------------------------+
                |  N seconds         |                         |
                +----------+---------+                         v
                           |                     +---------------------------+
                           +-------------------> | SimpleMonitor (the engine)|
                                                 |  run_tests()   - parallel |
                                                 |  do_recovery()            |
                                                 |  do_alerts()   -> Alerters|
                                                 |  do_logs()     -> Loggers |
                                                 +---------------------------+
                                                   |                |
                                  netbeacon_desktop alerter     netbeacon_gui logger
                                   (pop-ups via Bridge)    -> Recorder -> History (SQLite) + events
```

* **Every edit** rewrites the two INI files and creates a *new* `SimpleMonitor` object. The state of unchanged checks (failure counts, up-since, alert history)
  is copied over, so editing one check never re-sends alerts for another.
* `config_writer.build()` **test-constructs** every check and alert channel with SimpleMonitor's own classes before writing. One broken entry is skipped and reported
  (toast + *Activity*), instead of stopping the engine.
* `EngineCore` never touches Qt; `ui/context.py` converts its callbacks into queued Qt signals. Anything slow in the GUI (scans, test buttons, service lists) runs in a `Task` (QThread).
* Status words: *up*, *retry* (error count > 0 but within tolerance), *down* (virtual fail count > 0), *skipped* (a dependency is down), *paused*, *error* (bad configuration), *pending*.

## 1.1 modules (all Qt-free and unit-tested)

| Module | What it does | GUI |
|---|---|---|
| `diagnose.py` | Ordered probes (PC, Wi-Fi, router, internet, DNS, web, target). `Probes` holds every network call so tests inject failures. `_finish()` picks the first failing *relevant* step (LAN targets ignore internet failures) and writes the verdict. | `ui/diagnose_dialog.py` (steps stream in through `Task.item`) |
| `speedtest.py` | Median TCP-connect latency + jitter; parallel streamed download / upload, capped by bytes and time. | `ui/pages/speed.py` (schedule timer, history table `speedtests`) |
| `wifi.py` | Parses `netsh wlan show interfaces` / `show networks mode=bssid` by value shape (%, GHz, 802.11, MAC) so localised Windows works; crowding + advice. | `ui/pages/wifi_page.py` (sampling timer, history table `wifi`), check type `lan_wifi` in `sm_ext.py` |
| `digest.py` | Sentences from history; merges overlapping internet outages; linear-regression disk forecast; `last_slot()/is_due()` schedule. | `ui/pages/digest_page.py` |
| `notify.py` | `broadcast()` through SimpleMonitor's alerter classes (time rules stripped), `send_email()` with smtplib. | used by the device watch and the summary |

The network map (`ui/pages/netmap.py`) combines the Devices page's rows, the remembered devices and the dashboard's check statuses, matched by IP / host name.

## Adding a check type

1. **Engine side** - subclass `Monitor` in `netbeacon/sm_ext.py` and decorate it with `@register_monitor`:

   ```python
   @register_monitor
   class LanSomething(Monitor):
       monitor_type = "lan_something"
       def __init__(self, name, config_options):
           super().__init__(name, config_options)
           self.thing = self.get_config_option("thing", required=True)
       def run_test(self):
           ok = do_the_check(self.thing)
           return self.record_success("fine") if ok else self.record_fail("not fine")
       def describe(self): return f"Checking {self.thing}"
       def get_params(self): return (self.thing,)
   ```
   (Set `self.response_ms` if you measure a time; the GUI graphs it.)
2. **GUI side** - add a `CheckType(...)` to `netbeacon/checks.py` with its form `Field`s, help texts (`what`, `why`, `how`) and, if a stock SimpleMonitor equivalent exists, a `standalone_type`/`standalone_fn`.
3. Add a sample to `test_every_check_type_builds_valid_options` in `tests/test_engine_e2e.py`. The check dialog, test button, INI preview, export and self-test pick it up automatically.

## Adding an alert channel

Add the SimpleMonitor alerter options to `config_writer.alerter_sections()`, a default block in `store.DEFAULT_SETTINGS["channels"]`, and a spec in `ui/pages/alerts.py::CHANNELS`.

## The stand-ins in `compat.py`

SimpleMonitor imports `boto3`, `twilio`, `paramiko`, `pyaarlo`, `ring_doorbell`, `paho-mqtt` at module level although NetBeacon never uses the monitors/alerters that need them.
`compat.py` adds a *last-resort* import hook that fabricates empty modules for those names **only if the real package is absent**. If you want e.g. the SES alerter,
`pip install boto3` and it will be used instead (and PyInstaller will bundle it if you remove it from `excludes` in `netbeacon.spec`).

## Tests

* `tests/test_engine_e2e.py` - starts local TCP/HTTP/DNS servers and runs the *real* SimpleMonitor through up, down, retry, dependency-skip, recovery, reload-keeps-state, export, alert testing.
* `tests/test_gui.py` - builds the real window off-screen: dialogs, validation, rename, dependency loops, live engine -> dashboard -> notification, alerts/settings pages, wizard, devices merge.
* `python -m netbeacon --selftest out.json` - the same idea packaged for a finished `.exe` (used by the workflow).

## Packaging notes

* `netbeacon.spec` collects every `simplemonitor` sub-module (it loads monitors by name), its `html/` templates and its package metadata (it reads its own version at import time).
* The workflow installs SimpleMonitor with `--no-deps` and excludes the unused heavy libraries, which keeps the single-file `.exe` small (a Linux test build of the same recipe came to about 66 MB).
* The icon (`assets/netbeacon.ico`) uses classic 32-bit bitmap frames (not PNG-compressed) for maximum tool compatibility. Regenerate with `python tools/make_icon.py`.
