# Changelog

All notable changes to OpenWrtGUI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- LTE: the modem's model, firmware and mode order are read once per connection and the rest of the read runs
  alongside the operator query: about 2 s instead of 10-12 s per refresh.
- Firewall › Legacy iptables reads every table in one command instead of nine, every 10 s.
- LuCI pages: two lists asked at the same time read the router once, and a list read during a change is not kept.
- Discovery: Run --help and tool cards check the program in two commands instead of reading the whole page again.
- Faults: a refresh no longer asks the router the same thing twice (19 commands to 16).
- Capture to Wireshark: a Wireshark that falls behind drops packets from its own view and says how many; the app
  never waits for it.

### Fixed

- An unexpected error shows a plain message instead of a blank screen or a bare 500; the details go to the app
  log.
- LTE, RF live and System status reconnect by themselves after a lost connection instead of asking you to open the
  screen again.
- Reset counters is no longer proven by a listing that lost the rule.
- System › reset: a router that goes away just before the 2-minute limit counts as reset.
- RF › scan removes an owgscan0 left by a scan that lost its connection.
- LTE shows unknown for a netifd value of the wrong type instead of failing.
- A table change saved as an fw4 include writes the file before the section that loads it, so a run starting in
  between cannot leave the firewall an include it cannot read.
- Clearer message when Bench Guard stops an fw4 include from being saved; "1 fault record" on the Faults screen.
- igmp_snooping, ping, mapping, passive and key_type are no longer hidden as secrets.
- Faults: an RTP block on a router without conntrack is refused before anything runs; this PC is no longer offered
  as a fault target.
- System: a reboot asked during a restore or a reset says which job is running.
- Wi-Fi step-through: a run that Bench Guard stops names the step the radio is really at.
- Flash is greyed during a harness run and says why; the VLAN editor greys what the router would refuse and says
  why.
- A router can be removed from the app: its overview, Remove from the app (the router itself is not changed).
- A restore's proof no longer reports a setup script the router's first boot removed.
- LuCI's page list is read again after every change the app makes, not only after the apply runner's (Wi-Fi,
  System › Access, LTE, faults and the rest).
- LuCI pages are listed as LuCI itself decides: an unknown depends rule hides nothing, a one-word option no longer
  matches a value that merely contains it, any regular file counts as executable, and an access group with an
  empty read or write part counts.
- Legacy iptables: Reset counters is proven for ip6tables too, and stays proven after an earlier reset with
  traffic since; lines the app cannot read are counted on the tab, not dropped silently.
- Firewall: a run that starts after a confirmed table change is reported ("not saved as an fw4 include"), not
  answered 423; table-level lines such as flags and comment survive an edit; an IP set entry takes one field per
  match; a rule or set of one family refuses an address of the other.
- Faults: a record in /tmp/owg the app cannot read no longer takes the screen and Clear everything down; the
  screen says how many there are.
- Step-through: an error during the restore or a cancelled run ends it as failed with Restore offered, instead of
  leaving the router "restoring"; a proven step is kept when its wait loses the router; Next acts only on the wait
  on screen.
- Step-through: Restore waits for a System job or a flash as Start does; a saved file that lacks options restores
  nothing instead of deleting them; Start checks the radio name before anything else.
- RF and the monitor: owgmon0 serves one radio at a time, so a beacon check on another radio says "not checked"
  instead of reporting beacons from the wrong one; owgscan0 is removed after a dropped connection; an SSID such as
  "MCS 7" no longer counts as a rate.
- System: the app's SSH instance is still recognised when the interface list cannot be read (an SSH change is
  refused when it cannot be told apart); a reset counts the router as gone only after three failed logins in a
  row; the password policy is checked under the write lock.
- Flash: the audit's upload line names the whole image file, "openwrt (1).bin" included; the flash steps are read
  by name. Tool cards: a file that cannot be read is moved aside before a save, not overwritten.
- LTE: the modem's AT port is used by one exchange at a time per router (the state read and the console no longer
  run two microcom at once); the metric is a whole number from 0 to 4294967295.
- VLAN editor: a section deleted and changed, or changed twice, in one apply is refused before the preview.

### Security

- Discovery, Plugins and a LuCI page's change list hide every secret option, including names outside the audit
  log's list. Discovery still lists a secret that differs from the image, with both values hidden.
- The AT console never shows a SIM PIN or an APN password and does not keep the command for Up/Down; the audit
  log hides them too, also when typed with spaces.
- Interface, phy and capture device names a router reports, and the radio names RF live and a step-through
  restore are given, are checked before they go into a command or a file name. LuCI page checks ask the router
  only about absolute paths.
- A backup archive with more than 1,000 entries is refused, and so is an image whose root file system has more
  than 50,000 entries or unpacks to more than 512 MiB.
- Plugin headers are read only from the plugin's declaration; Mount points refuse a negative root delay.
- CI runs ruff's bandit rules, pip-audit and npm audit.

## [0.8.1] - 2026-11-16

A fix for Add router.

### Fixed

- Add router: a profile `.ssh` that Windows will not let the app enter (a junction, "untrusted mount point",
  WinError 448) no longer stops the login. The automatic login skips that folder, and a typed login no longer
  looks in `.ssh` at all (asyncssh's X.509 certificate look-up is off; the app pins host keys).

## [0.8.0] - 2026-11-15

LuCI parity.

Proven on the bench router (2026-11-15, read only): the LuCI page list shows the pages LuCI itself shows there,
and lists the others under **Not on this router** with what each one needs; Realtime Graphs › Wireless opens
RF live; the Plugins, Mount points and Legacy iptables screens read the router (it has no plugins, no
block-mount and no iptables, so they show that).

Proven in the simulator only: switching Plugins, editing Mount points (fstab with block-mount), Legacy
iptables (Reset counters, Restart firewall) and the bridge VLAN editor on a DSA router. No bench router has any
of these.

Not yet proven on a real router: the HTTPS redirect with the LuCI pages behind it (the bench router serves no
HTTPS).

### Added

- LuCI page lists show only the pages LuCI itself shows on each router. The others are listed under **Not on this
  router**, with what they need, such as a program or a configuration.
- Status › Realtime Graphs › Wireless opens RF live.
- System › Plugins: LuCI's plugin switches (the global one, each group's, each plugin's).
- Mount points edits fstab on routers with block-mount: settings, mounts and swap, Mount attached devices,
  Generate config, Unmount.
- Firewall › Legacy iptables: the rules of a router with iptables, Reset counters, Restart firewall.
- A LuCI page with a screen here opens that screen's own tab.
- Ports: the bridge VLAN editor on a DSA router (LuCI's Switch/VLAN config), with the 60 s rollback, the
  management-path rule and a check by netifd's own report. Proven on a simulated DSA router.
- A network change whose rollback does not bring the router back now says how to recover.

### Changed

- The README (with what 0.7 added), the manual's home page, FAQ and Bench Guard page describe the current
  release. SECURITY.md lists every data folder. Flashing a router with too little free memory, such as the
  bench's AP2, is documented: use LuCI or the terminal.

### Fixed

- After the app changes a router's settings, its LuCI page list is read again at once.
- A LuCI page opened in the app gets the access its menu parents grant too.

## [0.7.0] - 2026-11-13

Test helpers.

Proven on the bench router (2026-11-13): the System reboot and a restore of the router's own backup, which
0.6.0 listed as not yet proven; the step-through on air with a phone re-joining; frame analysis on the router's
own network. Channel analysis on air lists the networks around the router but not its own: a radio does not
hear its own beacons.

Not yet proven on a real router: the HTTPS redirect with the LuCI pages behind it (the bench router serves no
HTTPS).

### Added

- Wi-Fi › Step-through: steps a radio through every ticked mode, channel and TX power, one pure mode per step,
  each step proven on air before it waits. Advance on a timer, by hand, or when a chosen station re-joins (its
  re-join time is recorded). The whole run is previewed first; results go to a table and a CSV in Documents.
  The radio is put back at the end, on Stop and when the app closes; a step-through left behind (the app
  ended, or a harness run started) offers Restore on the Wi-Fi screen and the dashboard.
- RF live › Frame analysis: short windows on a monitor interface show the rate mix per direction, the RX
  signal histogram, the retry flag and the bad-FCS share. Off by default; it stops by itself after 30 minutes.
- RF live › Channel analysis (LuCI's Status › Channel analysis opens it): a passive scan of nearby networks
  with each channel's busy share, as a chart and a table.
- An update asks before it stops a step-through, a capture or frame analysis, and puts the radio back first.

### Fixed

- A restore no longer reports files that "differ" when OpenWrt's first boot changed them by design (found on the
  bench router): the script `sysupgrade -b` adds to keep disabled services disabled runs once and is deleted,
  and the boot may add to a config. Each config is now checked by its settings (options exactly, lists by
  every item of the backup), other files by their sha256; a uci-defaults script still there must match.
- An Apply during a Capture on mon0 no longer removes the capture's monitor interface: the beacon check,
  the capture and frame analysis now share it.
- The GitHub release notes keep characters such as "›": since 0.4.0 they showed a replacement character
  instead (the 0.4.0, 0.5.0 and 0.6.0 notes are corrected).

## [0.6.0] - 2026-11-11

LTE and System.

Not yet proven on a real router: the System reboot (O19), a restore from a backup (proven in the simulator
only), and the HTTPS redirect with the LuCI pages behind it (the bench router serves no HTTPS).

### Added

- LTE screen per router with an LTE modem: registration, radio, roaming, the operator (from the modem's AT
  port, or from QMI marked as possibly garbled), the data session with its address and counters, and RSSI,
  RSRP, RSRQ and SNR with quality labels and live charts (one sample every 10 s while the screen is open).
- LTE settings (APN, authentication, user name, password, SIM PIN, PDP type, MTU, metric, bring up at boot,
  default route, and every other option of the interface) through the interface plan with its 60 s rollback;
  the password and PIN show as `<hidden>` in the preview and the audit log. The modem's autoconnect and
  lte_4's DHCP stay as they are, with the reason shown.
- Connect, Disconnect and Reboot modem, each previewed and proven; the reboot goes low power, then online,
  each read back, and never uses the modem's reset mode (it wedges the BM806C until a power cycle).
- AT console: queries run any time, also during a harness run; any other command asks first and waits for the
  run. Modem details from `AT+CGMI`, `AT+CGMM`, `AT+CGMR`; the IMEI only on Reveal, never stored or audited.
- Network and DHCP: the LTE interface's row links to the LTE screen, and **bring up at boot** (`auto`) can be
  set on any interface.
- System screen per router, one tab per LuCI page it replaces: the overview (model, firmware, kernel, host
  name, time, uptime, load, memory, storage); live load, per-interface bandwidth and connection count every
  3 s; the connection table on request; the system and kernel logs with a text and level filter and Follow;
  processes; ping, traceroute and nslookup from the router (audited, waiting for a harness run).
- System and time: host name, time zone from the router's own list (plus UTC), NTP client, server and
  servers, log buffer and remote syslog, previewed and proven by the saved config, the host name the router
  answers with and its time zone.
- Services: every init script with Start, Stop, Restart, Enable and Disable, proven by reading the state
  back; the services the app goes through (dropbear, rpcd, uhttpd, network, firewall, log) offer Restart
  only, with the reason. `rc.local` and the crontab are edited as text, every crontab field checked before
  anything is sent; cron is enabled and restarted when needed.
- Backup: the router's configuration archive saved in the data folder, readable by the user only, listed
  and downloaded. Reboot: armed by a router-side timer, then followed until the router answers with a
  fresh uptime (not back after 5 minutes is reported).
- LuCI's logs, processes, realtime graphs, system, startup, scheduled tasks, reboot, backup and diagnostics
  pages now open the System screen.
- System › Access: the root password (typed twice, sent on `passwd`'s input, never in a command line, log or
  answer; proven by the changed hash) and LuCI's password policy; dropbear's instances with the app's own one
  kept on, kept and kept on its interface, applied with the router's 60 s rollback and followed to a new port;
  the authorized keys, each labelled App, Harness (with the owner you name) or Other, added and removed with
  the app's own key protected and a new login proving the app still gets in; LuCI on or off the network and
  the HTTPS redirect (refused while the router serves no HTTPS); the repository keys, read only.
- System › LEDs: each LED action with its LED, trigger and that trigger's options, proven by the active
  trigger read back. System › Mount points: what is mounted and how full, read only.
- Backup: import a backup file from the PC (checked on the PC first); restore one from the list, refused when
  it is another router's, would move the router off its address or lock the app out, and proven by a fresh
  uptime and every restored file's sha256; the files kept in a backup (`/etc/sysupgrade.conf`) beside what a
  backup holds now; reset to defaults, which needs the router's name typed and an "alone on this PC's
  network" tick, after which the router is to be added again.
- LuCI's administration pages (password, policy, SSH, SSH keys, HTTP(S), repository keys) and LED
  configuration now open the System screen. Its Mount Points page still opens in LuCI, where fstab editing
  lives.

### Changed

- Bench Guard also watches for the C8000 memory soak (`mem04_bench.py`) by default. A watch list saved
  unchanged from an earlier release's default gets it too; a list you edited is kept as saved.

### Fixed

- A list replaced on a named uci section (for example the NTP servers) was reported as not saved although
  the router had it.
- A crontab emptied of every task now removes the file, so the router goes back to having no crontab.
- Two backups started in the same second no longer overwrite each other; two reboots started at once arm one.
- The live System charts idle while the router reboots instead of reporting it unreachable.
- A startup script the router refuses to read is named as such instead of shown empty.
- LuCI pages open on a router whose web server listens on another port than 80 or 443 (8080, 8443).
- A Wi-Fi change waits for the AP interface to come up before it sets the TX mask and checks the channel.
  Before, it could report "not verified" while hostapd was still setting the country (#45).
- A deauth counts as proven once hostapd lists the station as no longer associated, so a phone that joins
  again within a second no longer leaves the deauth unproven (#45).
- The channels a radio offers come from the kernel's list. iwinfo's flags had marked usable channels
  restricted (#45).

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

[Unreleased]: https://github.com/dm17ryk/OpenWrtGUI/compare/v0.8.1...HEAD
[0.8.1]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.8.1
[0.8.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.8.0
[0.7.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.7.0
[0.6.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.6.0
[0.5.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.5.0
[0.4.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.4.0
[0.3.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.3.0
[0.2.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.2.0
[0.1.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.1.0
