# Changelog

All notable changes to OpenWrtGUI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Network, DHCP, ports and VLANs.

### Added

- Network and DHCP screen: every interface with its protocol, address, gateway, DNS and state (the one
  carrying this app is marked; interfaces the router makes at run time are read-only). Edit an interface's
  protocol, static address, gateway, DNS, MTU, bridge members and every other option its protocol handler
  knows, or add one.
- Changes that can cut the app off (addresses, bridges, routes, rules, VLANs, the switch mirror) apply with a
  60 s rollback, as LuCI does: the router restores its previous network settings by itself unless the app
  reaches it again and confirms. The app then follows the router to its new address.
- DHCP server per interface (pool, lease time, options by code, DHCPv6 and RA), with a warning when another
  router already serves DHCP on the subnet; fixed addresses by MAC; active IPv4 and IPv6 leases with
  **Make fixed**.
- Wi-Fi access by MAC: Everyone, Block listed or Only listed per SSID, and blocking one device now (no Wi-Fi
  restart), for 10 to 3600 s, or saved. The Wi-Fi screen's "Who may join" sums it up per SSID.
- DNS: forwarders, local domain, rebind protection, overrides, dnsmasq's switches and any other option.
- Static routes and policy rules for IPv4 and IPv6, and the live routing table.
- Ports, VLANs, mirroring screen for swconfig switches: the front panel with link and speed and turning a
  socket off or on (the socket carrying this app's SSH is locked), the VLAN matrix, the switch port mirror,
  and the Wi-Fi mirror status.
- LuCI's Network › Interfaces, DHCP and DNS, Routing and Switch pages open the app's own screens.

## [0.2.0] - 2026-11-05

Wi-Fi and the LuCI fallback.

### Added

- Wi-Fi screen per radio: modes and rates on air (802.11b, g, n 20/40 MHz, or Auto), channels (one, a list,
  all, or none to park the radio), TX power, SSIDs with security. Every change shows its commands first;
  after Apply the app checks on air that the radio is up and that channel, width, TX power, the TX rate mask
  and the rate of real beacons are what was asked for.
- Stations list with disconnect and block; every radio and SSID option the router validates, editable with
  the same preview.
- RF live: radio and per-station RX/TX figures once a second, signal and data-rate charts over one minute to
  one hour, and CSV recording to `Documents\OpenWrtGUI\`.
- LuCI pages: a page from the router's LuCI menu that has no screen here opens inside the app over an SSH
  tunnel, logged in with a session that may touch only that page's settings (read-only during a harness
  run). The app lists every option changed through LuCI and records the page in the audit log.
- Router overview lists every LuCI page and where it lives in the app.

### Security

- More secrets are hidden in previews, the audit log and the LuCI change list: WEP keys, Wi-Fi backhaul
  keys, RADIUS and DAE secrets, private key passwords, WPS and AP PINs, 802.11r keys and WireGuard keys.
- Audit entries written by an earlier version are masked the same way when shown and when exported; the
  export now holds what the audit log shows, so an unreadable line is left out instead of copied.

## [0.1.0] - 2026-11-04

The foundation: install, update, add routers, see them, and stay out of a running test's way.

### Added

- Per-user Windows installer (no admin rights) with the data folder chosen at install time; Python is bundled.
- Update check against GitHub Releases at start-up and daily, with a stable and a CI pre-release channel.
  Downloads are verified against `SHA256SUMS.txt`; the previous installer is kept for "Reinstall previous version".
- App shell with light, dark and system themes, usable from 375 px to full-screen widths.
- Add-router wizard: host key check and pinning, then a login with nothing typed (the app key, this PC's own
  `id_ed25519`/`id_ecdsa`/`id_rsa`, then the default `root`/`root`) before it asks for a user and password
  or a key file. A key the router already trusts is used as is, with nothing installed; otherwise the app
  installs its own SSH key with the exact command shown first. Then the router's self-description and socket
  labels proposed from `board.json`.
- Router self-description probe, read the way LuCI reads it: `board.json`, ubus services, typed option lists,
  feature flags and LuCI menu entries.
- Dashboard: router cards (radio, stations, network, login), an air map per band, and a "Needs attention" list.
- In-app help: a "?" next to page titles and sections, and tooltips on the main buttons, with the matching
  section of the user manual (built in, so it works offline) and a link to the full page in the wiki.
- Bench Guard: while a harness run is live (lock files, processes on this PC, run SSIDs on air), every router
  is read-only and a banner names the run. The watch list is editable in Settings.
- Terminal per router: a full shell, or a read-only command line during a harness run.
- Audit log of every command sent, with secrets masked, filters, and a zip export for bug reports.
- Router simulator built from recorded router output, used for e2e tests, screenshots and demos.
- CI, pre-release and release workflows, wiki sync, CodeQL and Dependabot.

[Unreleased]: https://github.com/dm17ryk/OpenWrtGUI/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.2.0
[0.1.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.1.0
