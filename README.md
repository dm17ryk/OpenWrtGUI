# OpenWrtGUI

**Operate the OpenWrt routers of a Wi-Fi test bench from one Windows window, without SSH.**

[![CI](https://github.com/dm17ryk/OpenWrtGUI/actions/workflows/ci.yml/badge.svg)](https://github.com/dm17ryk/OpenWrtGUI/actions/workflows/ci.yml)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)

A Wi-Fi test bench uses OpenWrt routers as access points. Until now every change on them meant an SSH
session or a harness script, and the routers' own web UI (LuCI) is slow to use and knows nothing about
the bench's custom tools. OpenWrtGUI shows every bench router in one desktop app: what is on air, who
is connected, and how each router describes itself. It never disturbs a test run that is in progress.

![Dashboard: three routers, the 2.4 GHz air map and one station](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/dashboard.png)

> v0.1 is the foundation: install, update, add routers, a read-only dashboard, Bench Guard, the
> terminal and the audit log. Wi-Fi, network, firewall and LTE screens follow; see the [roadmap](ROADMAP.md).

## What v0.1 does

| Screen | What you get |
|---|---|
| **Dashboard** | Every router at a glance: radio channel, width and power, stations with signal and rates, LAN and DHCP state, login state. An air map shows which channels each radio occupies (on air, or parked on a staged channel). Refreshed every 5 s over SSH. |
| **Add router** | A wizard: check and pin the host key, log in once with the root password, install the app's own SSH key (one line in `authorized_keys`), read what the router says about itself, label its sockets. |
| **Router overview** | The router's self-description, read the way LuCI reads it: board file, ubus services, typed option lists, feature flags, LuCI pages, and the port map. |
| **Terminal** | A real shell on any router that has the app key. During a harness run it accepts read-only commands only. |
| **Audit log** | Every command the app sent: time, router, screen, command with secrets masked, exit code. Filter it, and export it for a bug report. |
| **Settings** | Updates (stable or CI pre-release channel), light / dark / system theme, data folder, the Bench Guard watch list, the app's SSH key, audit-log retention. |

| Add router | Terminal | Settings |
|---|---|---|
| ![Add router](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/add-router.png) | ![Terminal](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/terminal.png) | ![Settings](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/settings.png) |

The screenshots are produced in CI by Playwright against the built-in router simulator, so they show
the current build.

## Install

1. Download `OpenWrtGUI-Setup-<version>.exe` from [Releases](https://github.com/dm17ryk/OpenWrtGUI/releases).
2. Run it. It installs for your user only and needs no admin rights. Python and everything else is
   bundled; the window uses Microsoft Edge WebView2, which Windows 11 already has.
3. Pick a data folder. That is where the router list, the pinned host keys, the app's SSH key and the
   audit log live.

On PCs with SentinelOne (the Essence bench PCs), install the app **and** its data folder inside
`C:\Essence_SC\`, for example `C:\Essence_SC\apps\OpenWrtGUI`. Programs started from elsewhere are
stopped without a message.

The app checks GitHub for a new version at start-up and once a day and offers it in Settings. Each
download is checked against the release's `SHA256SUMS.txt` before it runs.

## Quick start: add a router

1. **Add router** → type the router's address (for example `192.168.1.2`) → **Connect**.
2. Compare the host key fingerprint with the router, then **Accept and pin**.
3. Enter the root password once → **Log in**. The app does not store it.
4. Read the exact command that installs the app key → **Install key**. The app checks that the key works.
5. Check the model and services the router reported, name it, confirm the socket labels → **Save port map**.

The router now appears on the dashboard. The [user manual](https://github.com/dm17ryk/OpenWrtGUI/wiki)
walks through each screen.

## Safety model

The app was built for a bench where test harnesses run for hours. It must never break one.

- **Bench Guard.** The app watches for a live run: lock files, harness processes on this PC (for example
  `dima_night.py`, `rh_soak.py`, `txlab_*.py`), and run SSIDs on air. While one is live, every router is
  read-only. A banner names the run, and any write is refused with that reason. The watch list is
  editable in Settings.
- **Write lock.** One write at a time per router; reads run in parallel.
- **Preview.** A write shows the exact commands before it runs (for example the key-install command).
- **Audit log.** Every command is recorded with secrets masked.
- **Host key pinning.** A router's SSH host key is pinned when you add it. If the key changes (for
  example after a reflash), the app refuses to connect. You re-pin it through Add router, which shows
  the key that was pinned before.
- **Local only.** The UI talks to a server on `127.0.0.1` with a per-launch token. Nothing listens on
  the network.

## Supported routers

Any standard OpenWrt router that you can reach over SSH. On first connect the app reads the router's
self-description (the same files and ubus methods LuCI uses), so a new model needs no code change.
Firmware image profiles, which add a bench image's custom tools, arrive in v0.5.

Developed and tested on the D-Link DWR-921 C3 with OpenWrt SNAPSHOT r35692.

## Contributing, roadmap, license

- [ROADMAP.md](ROADMAP.md): what comes after v0.1.
- [CONTRIBUTING.md](CONTRIBUTING.md): development setup, tests, and the rules for hardware tests.
- [SECURITY.md](SECURITY.md): how to report a vulnerability and what the app stores.
- [CHANGELOG.md](CHANGELOG.md): what changed in each release.

OpenWrtGUI is free software under the GNU General Public License v3.0; see [LICENSE](LICENSE).
