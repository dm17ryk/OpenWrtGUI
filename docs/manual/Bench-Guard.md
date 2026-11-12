# Bench Guard

Test harnesses on the bench (for example `dima_night`, `rh_soak`, `overnight_wifi`) reconfigure the
routers for hours. A change made by hand in the middle of a run spoils it. Bench Guard prevents that:
**while a run is live, every router is read-only in OpenWrtGUI.**

![Settings, with the Bench Guard watch list](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/settings.png)

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
checks every 2 seconds.

## What you see

The top bar always shows the guard's state:

- Green: **No harness running · writes allowed**.
- Red banner: the run it found, for example "dima_night.py started 21:04 (PID 18244)". Routers show
  "running · read-only".

## What still works during a run

- Everything that only reads: the dashboard, router overviews, the audit log, RF live's samples.
- The [terminal](Terminal-and-audit-log), in read-only mode: commands such as `cat`, `logread`,
  `iw dev`, `ubus call … status` run; anything that changes the router is refused with the reason.

## What is refused

Every write to a router: installing the app key, setting a root password in the wizard, and terminal
commands that change something. The refusal names the run, so you know what to wait for.

## The test helpers when a run starts

- A **step-through** stops at once and leaves the radio at its step: putting it back is a Wi-Fi reload, which
  would disturb the run. The Wi-Fi screen offers **Restore** once the run is over.
- **Frame analysis** stops and removes its monitor interface (that only undoes what the app added).
- A **channel scan** and starting frame analysis or a step-through are refused while the run lasts.
