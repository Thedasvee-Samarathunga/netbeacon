# NetBeacon user guide

## 1. First five minutes

1. Start NetBeacon. The **Quick Start wizard** looks around and suggests checks (router, internet, DNS, disk...). Accept the ones you like.
2. Watch the **Dashboard**. Green = working, red = DOWN, amber = *Retrying* (failed, but not yet often enough to count as down).
3. Open **Alerts**, keep *Desktop pop-up* on, and add a phone channel (ntfy is the quickest: pick a long random topic and subscribe to it in the ntfy app). Press **Send a test alert**.
4. Open **Learn > Practice** and press *Create the practice check* to watch a whole outage and recovery in 2 minutes.

## 2. The pages

| Page | Use it to... |
|---|---|
| **Dashboard** | See everything at once, filter by group/status, glance at the latest events. **What's wrong?** runs the step-by-step diagnosis; right-click a check for *What's wrong with this?* |
| **Checks** | Add, edit, duplicate, pause or delete checks. *Pause* during maintenance. |
| **Devices** | Scan your network, name devices, mark the ones you recognise as *known*, get told about newcomers. |
| **Network map** | The router in the middle and every device around it, coloured by health. Click a device for actions. |
| **Port scanner** | See which TCP ports are open on a device, with plain-English risk advice; add a check for ports that *should* be open. |
| **Services & programs** | Browse Windows services, running programs and listening ports on this PC and turn them into checks. |
| **Wi-Fi** | This PC's signal, channel and link speed, signal history, nearby networks and channel crowding, with advice. |
| **Internet speed** | Run or schedule speed tests and compare them with the speed you pay for. |
| **Uptime & history** | Availability, downtime, incidents, response-time chart; export CSV or an HTML report. |
| **Weekly summary** | The week in plain sentences; prepared automatically, optionally emailed. |
| **Alerts** | Channels, rules (how many failures, repeat, recovery, quiet hours) and test buttons. |
| **Activity & logs** | Event diary, the SimpleMonitor engine log, and the generated config files. |
| **Learn** | 15 short lessons, glossary and guided practice. |
| **Settings** | Interval, history length, theme, teaching mode, tray/startup, status web page, backup/export. |

## 3. Choosing good settings

* **Interval 30 s** is fine. Faster rarely helps and generates more traffic.
* **Forgive (tolerance):** 1-2 for LAN devices, 2-3 for internet/websites, 3-5 for CPU/memory, 0 for things that must alert instantly.
* **Depends on:** make everything behind the router depend on the router; servers on a switch depend on the switch.
* **Backups:** a *File or backup is fresh* check on the backup folder (`D:\Backups\*.zip`, newer than 26 hours) is the most valuable check a small business can add.
* **Certificates:** one *Certificate expiry* check per public website; 14 days warning is a good start.
* **Combine channels:** pop-up (works when the internet is down) + phone push (reaches you when you're away).

## 4. What "uptime" means here

Availability = share of **checks** that succeeded (retries inside tolerance count as up), so time when NetBeacon wasn't running doesn't distort the numbers.
An **incident** starts at the first failed check of an outage and ends at the first success afterwards. If NetBeacon is closed during an incident, the incident is ended
at the last moment it was watching and marked as approximate.

## 5. Keeping it running

* *Settings > Start NetBeacon when I sign in to Windows* and *Keep running in the system tray*.
* The tray icon changes colour: green = all OK, amber = something retrying, red = problems, grey = paused.
* Quit from the tray icon's menu.

## 6. When you outgrow it

Use **Settings > Export for stock SimpleMonitor**, copy the folder to an always-on machine (a Raspberry Pi is plenty) and run
`pip install simplemonitor` then `simplemonitor -f monitor.ini`. Read **Learn > 15** for the next-step tools and a translation table
of NetBeacon words into Zabbix/PRTG/Checkmk/Nagios words.

## 7. When something breaks: "What's wrong?"

Press **What's wrong?** (Dashboard, the sidebar or the tray menu). NetBeacon tests, in order: this PC's network adapter, the Wi-Fi link,
the router, the internet by number (1.1.1.1), DNS, and real web pages - and, if you started it from a check, that check's device and the check itself.
The first step that fails is the cause; the window says what to do and what it ruled out. **Copy report** gives you a text version to email to your IT person or provider.

## 8. Speed, Wi-Fi and the weekly summary

* **Internet speed:** enter what your plan promises, tick *Test automatically*, and let a week of tests build up. Test from a PC on a cable for fair numbers.
* **Wi-Fi:** below about 40% signal (-80 dBm) calls stutter. On 2.4 GHz use channel 1, 6 or 11. Add the *Wi-Fi signal* check to be told when it degrades.
* **Weekly summary:** prepared every week at the time you choose (if NetBeacon was off, the next time it starts). Tick *Also email it* after setting up the Email channel.
* **Wake-on-LAN:** right-click a device (Devices page) or click it on the map and choose *Wake it up*. Enable Wake-on-LAN in that PC's BIOS first.

## 9. Troubleshooting

| Problem | What to try |
|---|---|
| A check says *Problem* | Open *Activity > Events* or *Engine log*; the message says what's wrong with its settings. Use *Test this check now* in the editor. |
| Everything is red at once | The router (or this PC's network) is down. Set up *Depends on* so you get one alert instead of many. |
| Ping fails but the device works | The device blocks ping. Use a port or web check. |
| No pop-ups | *Alerts* page: tick Desktop, press the test button; make sure Windows *Focus assist / Do not disturb* is off. |
| Email test fails | The test shows the server's error. For Microsoft 365 / Gmail you normally need an *app password* and port 587 with STARTTLS. |
| Device scan finds few devices | Choose the right network; try *Deep scan*; guest Wi-Fi/VLANs are separate networks. |
| Service list is empty | Windows services only exist on Windows. |
| Windows SmartScreen warning | The exe is unsigned: *More info -> Run anyway*, or sign it. |
| "What's wrong?" blames the router, but it's fine | Some routers ignore ping; NetBeacon also tries ports 53/80/443. If they're all closed too, add a check on a device behind the router instead. |
| Wi-Fi page shows no nearby networks | Windows 11: Settings > Privacy & security > Location > allow desktop apps. Then press Refresh. |
| Speed test fails | A firewall or proxy may block the test server. Try another server on the Internet speed page. |
| Wake-on-LAN does nothing | Enable it in the target PC's BIOS/UEFI and in its network adapter's Power Management tab; Windows "Fast startup" can also block it. |
| Something odd | `%APPDATA%\NetBeacon\logs\netbeacon.log`, and `NetBeacon.exe --selftest out.json`. |
