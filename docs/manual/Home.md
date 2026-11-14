# OpenWrtGUI user manual

OpenWrtGUI lets you see and operate the OpenWrt routers of a Wi-Fi test bench from one Windows window,
instead of SSH sessions. This manual covers the current release: install, update, add routers, the dashboard,
[Discovery](Discovery), the [Wi-Fi](Wi-Fi) screen and its step-through, [RF live](RF-live),
[Network and DHCP](Network-and-DHCP), the [LTE modem](LTE-modem), [Ports, VLANs, mirroring](Ports-and-VLANs),
[Firewall](Firewall), [Faults and capture](Faults-and-capture), [System](System), [LuCI pages](LuCI-pages), Bench
Guard, the terminal and the audit log. What comes next is on the
[roadmap](https://github.com/dm17ryk/OpenWrtGUI/blob/master/ROADMAP.md).

![The dashboard with three routers](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/dashboard.png)

## Start here

1. [Install](Install) the app, and choose where it keeps its data.
2. Add your [first router](First-router).
3. Read the [Dashboard](Dashboard) at a glance.
4. Learn what [Bench Guard](Bench-Guard) does while a test runs.

## All pages

- [Install](Install) · [Updating](Updating)
- [First router](First-router) · [Dashboard](Dashboard) · [Discovery](Discovery) ·
  [Adding a router family](Adding-a-router-family)
- [Wi-Fi](Wi-Fi) · [RF live](RF-live) · [LuCI pages](LuCI-pages)
- [Network and DHCP](Network-and-DHCP) · [LTE modem](LTE-modem) · [Ports, VLANs, mirroring](Ports-and-VLANs)
- [Firewall](Firewall) · [Faults and capture](Faults-and-capture) · [System](System)
- [Bench Guard](Bench-Guard) · [Terminal and audit log](Terminal-and-audit-log) · [Settings](Settings)
- [Troubleshooting](Troubleshooting) · [FAQ](FAQ)

## Three things to know

- **The app never stores router passwords.** It logs in with an SSH key: one this PC already has and the
  router trusts, or its own key, which it installs after you log in once (it tries `root` / `root` before
  asking you to type anything).
- **It stays out of a running test's way.** While a harness run is live, every router is read-only.
- **Everything it sends is recorded** in the audit log, with secrets masked.

## Help inside the app

Every page title and section has a **?** next to it, and the main buttons explain themselves when you
rest the pointer on them. The text is the matching part of this manual, built into the app so it works
offline; **More in the manual** opens the page here.

Questions are welcome in [Discussions](https://github.com/dm17ryk/OpenWrtGUI/discussions); bugs and
feature requests go to [Issues](https://github.com/dm17ryk/OpenWrtGUI/issues/new/choose).

This manual lives in the repository under `docs/manual/` and is published here on every change.
