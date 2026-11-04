# OpenWrtGUI user manual

OpenWrtGUI lets you see and operate the OpenWrt routers of a Wi-Fi test bench from one Windows window,
instead of SSH sessions. This manual covers **v0.1 (Foundation)**: install, update, add routers, the
dashboard, Bench Guard, the terminal and the audit log. Later versions add Wi-Fi, network, firewall
and LTE screens (see the [roadmap](https://github.com/dm17ryk/OpenWrtGUI/blob/master/ROADMAP.md)).

![The dashboard with three routers](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/dashboard.png)

## Start here

1. [Install](Install) the app, and choose where it keeps its data.
2. Add your [first router](First-router).
3. Read the [Dashboard](Dashboard) at a glance.
4. Learn what [Bench Guard](Bench-Guard) does while a test runs.

## All pages

- [Install](Install) · [Updating](Updating)
- [First router](First-router) · [Dashboard](Dashboard)
- [Bench Guard](Bench-Guard) · [Terminal and audit log](Terminal-and-audit-log) · [Settings](Settings)
- [Troubleshooting](Troubleshooting) · [FAQ](FAQ)

## Three things to know

- **The app never stores router passwords.** You type the root password once, the app installs its own
  SSH key, and logs in with that key from then on.
- **It stays out of a running test's way.** While a harness run is live, every router is read-only.
- **Everything it sends is recorded** in the audit log, with secrets masked.

This manual lives in the repository under `docs/manual/` and is published here on every change.
