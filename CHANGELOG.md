# Changelog

All notable changes to OpenWrtGUI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-11-08

Image import and Discovery.

### Added

- Settings › Images: import a router's sysupgrade image (uImage, squashfs and fwtool metadata are read on this
  PC; nothing goes to a router) into a profile per board and revision with its packages, default configs and
  the bench's own packages with their usage text; delete a profile. A router without an imported image can
  build a profile from its own `/rom`.
- Discovery screen per router: the matched image and a firmware check (the router's firmware partition hashed
  against the image), files and packages added after flashing with whether a flash keeps them, configs changed
  from the image's defaults (configs made at first boot are named, not read), copy files to another router with
  each copy proven by its sha256, and reflash checklists that keep the files a flash would lose.
- The bench's own packages and programs added after flashing, with their usage text: **Run --help** (previewed
  and audited), **Promote** to a card of named commands with checked parameters (kept per board; every card
  command waits while Bench Guard shows a run), and Start, Stop and Restart for custom services, proven by
  reading the state back.
- Flash from an imported image: exact preview, the image validated on the router (`validate_firmware_image`,
  `sysupgrade -T`), `sysupgrade` started by a router-side timer, progress through the reboot, and done only when
  the router answers with the new board and revision. Keep settings, or flash without them after confirming the
  router is isolated; the Add-router wizard then accepts the new host key only when the board and revision it
  reads match the image. **Copy back lost files** restores what the checklist saved.
- Needs attention: "N files added after flashing" and "Reflashed without settings: add it again".

### Changed

- Router cards show the owners of other tools' nftables tables and tc hooks (for example
  `BENCHSIPGUARD · dima_night`).
- Ports › Wi-Fi mirror points to Discovery › Custom services for Start, Stop and Restart.

## [0.4.0] - 2026-11-07

Firewall and faults.

### Added

- Firewall screen for fw4 routers: per zone and direction **Allow all** or **Block all** (rejected or
  dropped), with each rule's effect in the model and the rules that would no longer do anything flagged. On
  the zone that carries this app's SSH, Block all keeps "Allow SSH from this PC" (and "Allow DHCP and DNS"
  where the router serves DHCP there) open; a pin is removed only after a warning. Every firewall change
  applies with the 60 s rollback.
- Zones (networks, policies, masquerade, MSS clamp, forwardings), traffic rules with live packet counters,
  port forwards, NAT rules, IP sets and custom rule files in `/etc/nftables.d` (checked by fw4 with `nft -c`
  before it reloads), as LuCI's Network › Firewall pages have them, and the raw ruleset.
- Every other nftables table and traffic-control hook with its owner (fw4, this app, a known harness such as
  `BENCHSIPGUARD` or `voipdscp`, or unknown). Tables owned by someone else are locked: **Unlock** says who
  relies on them, and the override is audited. Edit rules and chains, delete a table or add one, runtime only
  or saved as an fw4 include; applied atomically with `nft -f` under a router-side restore timer. The faults
  table `benchfault` is changed only on the Faults screen.
- Faults and capture screen: link down (switch port), isolate (L2), block flows (`rtp_in`, `sip_in`,
  `rtp_out`, `all_in`, `all_out`, `blackout`, with loss), netem impair scoped to the target, and Wi-Fi deauth,
  block for N s and AP down. A fault is held until cleared or for N s, cleared by a timer on the router itself;
  armed faults are listed from their records on the router, also after a restart of the app, and the router
  card shows "N faults armed". A fault still there after Clear stays listed, with what is left. Clear
  everything works during a run.
- Capture on a router interface (`br-lan`, Wi-Fi, `mon0`, LTE) to a `.pcap` in Documents or live in
  Wireshark; the app's own SSH is never captured.
- Settings: known devices (a name and all its MACs) and known tables (who writes which nft table).

### Fixed

- All options no longer edits options that have their own control on the screen; they show read-only (#26).
- A change saved just as a harness run starts is reloaded too, not left saved but not live, and the result
  says the run started (#27).
- A changed host key after a rollback reads as a host key problem, and a new address that belongs to another
  router is warned about (#28).
- A timed Wi-Fi block is reported as proven only when hostapd lists the ban (#29).
- Name checks no longer accept a trailing newline (#30); an unknown protocol is refused (#31).
- The plan and its digest are checked under the router's write lock (#32).
- Background reads wait while a rollback apply reconnects (#33).
- The restore check retries, and a failed read is no longer reported as "differs" (#34).
- Network and Ports: every rollback card says it is waiting for the router, a new interface links the
  Firewall zones, and the State column shows the uptime (#35).

## [0.3.0] - 2026-11-06

Network, DHCP, ports and VLANs.

### Added

- Network and DHCP screen: every interface with its protocol, address, gateway, DNS and state (the one
  carrying this app is marked; interfaces the router makes at run time are read-only). Edit an interface's
  protocol, static address, gateway, DNS, MTU, bridge members and every other option its protocol handler
  knows, or add one.
- Changes that can cut the app off (addresses, bridges, routes, rules, VLANs, the switch mirror) apply with a
  60 s rollback, as LuCI does: the router restores its previous network settings by itself unless the app
  reaches it again, sees the change in effect and confirms. The app then follows the router to its new
  address.
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

### Fixed

- Bench Guard no longer counts a harness's leftover `.own` lock file (for example `voip.lock.own` after a
  finished `dima_night` run) as a live run, which left every router read-only. A `.own` file now counts
  only while a running harness holds its lock; the guard checks without changing the file. Other lock
  files still count while they exist.

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

[Unreleased]: https://github.com/dm17ryk/OpenWrtGUI/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.5.0
[0.4.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.4.0
[0.3.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.3.0
[0.2.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.2.0
[0.1.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.1.0
