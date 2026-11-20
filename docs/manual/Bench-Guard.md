# Bench Guard

Test harnesses on the bench (for example `dima_night`, `rh_soak`, `overnight_wifi`) reconfigure the
routers for hours. A change made by hand in the middle of a run spoils it. Bench Guard prevents that:
**while a run is live, every router is read-only in OpenWrtGUI.**

![A live run: the red banner names it, and every router is read-only](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/guard-banner.png)

## What it watches

The watch list is in [Settings](Settings) → Bench Guard. A run counts as live when any of these is true:

| Watch | Default entries | Live when |
|---|---|---|
| **Lock files** | `D:\Essence_SC\wifi_ref\iperf_txsweep\voip.lock.own` | a `.own` file: a running harness holds its lock; any other file: it exists |
| **Processes on this PC** | `dima_night.py`, `rh_soak.py`, `overnight_wifi*`, `txlab_*.py`, `voip_chain.py`, `mem04_bench.py` | a running process matches (`*` is a wildcard) |
| **SSIDs on air on a router** | `OpenWrtB`, `OpenWrtC` | a router broadcasts that SSID |

A file ending in `.own` (for example `voip.lock.own`, `dima_night.lock.own`) is a harness's lock sidecar. It
stays on disk after a run on purpose, and the next run opens it again, so its being there says nothing. A
live run holds a lock on its first byte, and Windows drops that lock when the run's process ends. The guard
tries to take the lock and gives it back at once: when it is refused, a run is live and the banner says
"Lock file … held by a live run". When the guard gets the lock, the file is a leftover and does not count.
The guard only opens the file for reading: it never writes, creates or deletes a harness's file. A `.own`
file it cannot open still counts as a run. Any other lock file, such as a PID file like `voip.lock`, counts
while it exists.

Add or remove entries with the fields and the **×** on each chip. Changes are saved at once; the guard
checks every 2 seconds. The default entries are this bench's own harnesses: on another bench, remove them and add
your harnesses' lock files, processes and run SSIDs.

## What you see

The top bar always shows the guard's state:

- Green: **No harness running · writes allowed**.
- Red banner: the run it found, for example "dima_night.py started 21:04 (PID 18244)". Routers show
  "running · read-only".

## What still works during a run

- Everything that only reads: the dashboard, router overviews, every screen's state, RF live's samples, the
  audit log.
- LTE: AT queries and the LTE screen's readings.
- Faults: **Clear everything** for the faults this app armed (a fault left in place disturbs a run more).
- A capture on a wired or Wi-Fi interface (not `mon0`, which adds a monitor interface).
- System: reads, logs, the live charts and a backup (it changes nothing on the router).
- LuCI pages open read-only.
- The [terminal](Terminal-and-audit-log), in read-only mode: commands such as `cat`, `logread`,
  `iw dev`, `ubus call … status` run; anything that changes the router is refused with the reason.

## What is refused

Every write to a router. Each refusal names the run, so you know what to wait for, and nothing is sent to the
router. In detail:

- Each screen's **Apply**, including every change that applies with the 60 s rollback (addresses, VLANs, the
  firewall).
- On the Network screen, Wi-Fi access by MAC too.
- LTE actions (connect, disconnect, modem reboot, settings, Reconfigure) and AT commands that are not queries.
- LTE **Recover**: starting it, and its next step. A run that starts while Recover or Reboot modem has the
  modem in low power or LTE down still gets two lines, sent past the guard and marked in the audit log as
  "put back during a harness run": the modem back online, then `ifup lte`. Then it stops and says so.
- On the System screen:
  - a reboot, a restore or a reset;
  - a new router password;
  - diagnostics (ping and traceroute send traffic from a router under test).
- On Discovery:
  - Run --help;
  - a tool card's command that writes;
  - starting or stopping a custom service;
  - copying files to a router.
- A flash or a firmware check.
- Arming a fault, and a capture on `mon0`.
- RF live's channel scan and frame analysis (each adds an interface on the radio).
- Starting a step-through, or its **Restore**.
- On the Tools screen: starting **Throughput** or a **Traffic generator** listen, the Traffic generator's
  **Send**, and Station management's requests. A Throughput or listen that is running stops within a second
  of a run starting, and says "Stopped by Bench Guard".
- Installing the app key, and setting a root password in the wizard.
- Settings › **Rotate key**: starting it, a Retry, and its next router. A router it was moving keeps the old key
  and is listed with Retry.
- Terminal commands that change something.

**Clear everything** on the Faults screen still works: it only removes what this app armed.

## The test helpers when a run starts

- A **step-through** stops at once and leaves the radio at its step: putting it back is a Wi-Fi reload, which
  would disturb the run. The Wi-Fi screen offers **Restore** once the run is over.
- **Frame analysis** stops and removes its monitor interface (that only undoes what the app added).
- A **channel scan** and starting frame analysis or a step-through are refused while the run lasts.
