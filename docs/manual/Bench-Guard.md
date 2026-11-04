# Bench Guard

Test harnesses on the bench (for example `dima_night`, `rh_soak`, `overnight_wifi`) reconfigure the
routers for hours. A change made by hand in the middle of a run spoils it. Bench Guard prevents that:
**while a run is live, every router is read-only in OpenWrtGUI.**

![Settings, with the Bench Guard watch list](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/settings.png)

## What it watches

The watch list is in [Settings](Settings) → Bench Guard. A run counts as live when any of these is true:

| Watch | Default entries | Live when |
|---|---|---|
| **Lock files** | `D:\Essence_SC\wifi_ref\iperf_txsweep\voip.lock.own` | the file exists |
| **Processes on this PC** | `dima_night.py`, `rh_soak.py`, `overnight_wifi*`, `txlab_*.py`, `voip_chain.py` | a running process matches (`*` is a wildcard) |
| **SSIDs on air on a router** | `OpenWrtB`, `OpenWrtC` | a router broadcasts that SSID |

Add or remove entries with the fields and the **×** on each chip. Changes are saved at once; the guard
checks every 2 seconds.

## What you see

The top bar always shows the guard's state:

- Green: **No harness running · writes allowed**.
- Red banner: the run it found, for example "dima_night.py started 21:04 (PID 18244)". Routers show
  "running · read-only".

## What still works during a run

- Everything that only reads: the dashboard, router overviews, the audit log.
- The [terminal](Terminal-and-audit-log), in read-only mode: commands such as `cat`, `logread`,
  `iw dev`, `ubus call … status` run; anything that changes the router is refused with the reason.

## What is refused

Every write to a router: installing the app key, setting a root password in the wizard, and terminal
commands that change something. The refusal names the run, so you know what to wait for.
