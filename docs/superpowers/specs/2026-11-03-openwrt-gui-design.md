# OpenWrtGUI: design spec

| | |
|---|---|
| Date | 2026-11-03 |
| Status | Draft for review |
| Owner | Dmitry Kokotov |
| Repository | https://github.com/dm17ryk/OpenWrtGUI (public, GPL-3.0, default branch `master`) |
| Screen mockups | Design canvas "OpenWrtGUI screens" (private claude.ai artifact); source in `docs/design/canvas/project/` |

## 1. Purpose

The Wi-Fi test bench uses OpenWrt routers as access points. Everything on them is done today over SSH: by hand, or through
Python harness scripts (`bench_net.py`, `aps.py`, `dima_night.py`, `txlab_*.py`). The routers' own web UI (LuCI) is hard
to use, and it does not cover the custom tools added to the bench image.

OpenWrtGUI is a Windows desktop app that lets one engineer see and operate every bench router from one window. It covers
everything LuCI does, the bench's custom tools, and the test-specific controls a Wi-Fi test needs: pure-mode and channel
selection, RF readings, fault injection, MAC blocking and packet capture.

Success means:

1. Any setting LuCI offers on these routers can be made in OpenWrtGUI, and so can anything else that is routinely done over SSH today.
2. A standard OpenWrt router works on first connect, because the app reads the same self-description LuCI uses. Importing its firmware image adds the custom tools and what changed since flashing. No code change is needed unless the router brings a new mechanism.
3. The app never disturbs a running test harness.
4. It installs and updates itself from GitHub Releases, with nothing preinstalled on the PC.

## 2. Context and constraints (measured, 2026-11-03)

| Fact | Source |
|---|---|
| 3 routers: D-Link DWR-921 C3 (U-Boot), OpenWrt SNAPSHOT r35692-b8bffeefdf, ramips/mt7620, kernel 6.18.41, `apk` | `/etc/openwrt_release` on AP2 |
| AP1 192.168.1.1 (bench, LAN DHCP server, `wifi-mirror`, BENCHSIPGUARD, plink + password); AP2 .1.2 and AP3 .1.3 (DHCP off, radio parked, OpenSSH key) | `aps.py`, txctl session |
| 55 MB RAM (≈12 MB free), 4.5 MB free overlay flash, no python3 / lua / curl / base64 / openssl CLI | AP2 probe |
| Present: uhttpd + LuCI + ubus over HTTP, rpcd, dropbear 2026.92 (ed25519, `scp`, no sftp-server), `iw`, `iwinfo`, `hostapd_cli`, `tcpdump`, `iperf3`, `socat`, `nft`, `tc`/netem, `ifb`, `conntrack`, `swconfig`, `uqmi`, `microcom`, `jsonfilter` | AP2 probe |
| Radio: `rt2800_wmac`, 2.4 GHz only, ch 1–13 (14 disabled in IL), HT20/HT40, 20 dBm max, monitor mode. No STA_TX_PWR and no ACK-signal feature. debugfs `phy0/statistics` present (`dot11ACKFailureCount` etc.) | `iw phy`, debugfs |
| TX power: uci `txpower` set → `iw phy phy0 set txpower fixed N00`; unset → `auto` (regulatory max) | `/lib/netifd/wireless/mac80211.sh:98-109` |
| MAC ACL: `hostapd_cli deny_acl/accept_acl`; ubus `hostapd.<if>` `del_client` with `ban_time`, `list_bans`; uci `macfilter` + `maclist` | `hostapd_cli`/`wpad` strings, `hostapd.sh:360-1049` |
| Your custom packages in the image: `dwr921-portctl` v2, `dwr921-diag` v2, `dwr921-internet-led` v4 | `/lib/apk/db/installed` |
| LTE modem: BroadMobi BM806C (USB 2020:2033), firmware M1.2.0_E1.0.3_A1.1.8, QMI on `/dev/cdc-wdm0`, AT on `ttyUSB1`/`ttyUSB2`. QMI signal gives rssi, rsrq, rsrp, snr. `AT+BMMODODR?` → 17. `AT%SYSCMD` → ERROR | AP2 probe |
| The BM806C is the DHCP server on its 802.3 link. `lte_4` must stay DHCP: a static address stops downlink | Dmitry's port notes |
| Firmware image: `D:\Essence_SC\DWR_921-c3-uboot\…squashfs-sysupgrade.bin` (sha256 d340a53f…), GitHub release dm17ryk/openwrt v25.12.5 | memory, release |
| Harness rules: while `dima_night` / `rh_soak` / `overnight_wifi` runs, every router is read-only. AP1 is the only DHCP server. Only one radio on air per SSID. BENCHSIPGUARD, `voipdscp` and `wifi-mirror` stay untouched | txctl session |
| `dima_night` sets `country=IL`, `cell_density=0`, `legacy_rates=1` on each AP turn (`dima_night.py:265`) and restores only the mode keys | txctl session |
| What LuCI reads on AP2: `/etc/board.json` (model; switch ports with printed labels, internal 0–3 = LAN4–LAN1, 4 = WAN, 6 = CPU `eth0`; LED `green:lan`; radio band 2G with NOHT/HT20/HT40, max width 40; default network including `lte`). ubus objects incl. `luci`, `luci-rpc`, `network.*`, `hostapd`, `iwinfo`, `uci`, `file`, `system`, `session`. Typed option lists: `network get_proto_handlers` (dhcp, dhcpv6, ppp, pppoe, qmi, static, wwan; `qmi` has 25 options) and `network.wireless get_validate` (radio 155, SSID 289, station 4, VLAN 9 options). `luci getFeatures` (SAE, OWE, WPS, 802.11r, swconfig, firewall4, apk). LuCI menu files with `depends` conditions: base, firewall, network, status, system | AP2 probe |
| PC: Windows 11, WebView2 156 present. SentinelOne kills scripts that run outside `C:\Essence_SC` or `D:\Essence_SC` | probe, Dmitry's rule |

## 3. Decisions

| # | Decision | By |
|---|---|---|
| D1 | Scope: routers/APs only, but everything doable over SSH, plus discovery and a dashboard. Test-run orchestration stays in the harness | Dmitry |
| D2 | PC-hosted, localhost, single user | Dmitry |
| D3 | Installable Windows app with bundled Python; nothing needs to be installed on the PC | Dmitry |
| D4 | Independent engine: the harness (`aps.py`, `bench_net.py`) stays untouched | Dmitry |
| D5 | Capability model "C": typed drivers for stateful and risky operations, a generic prober, and a panel for discovered unknown tools | agreed |
| D6 | New router families: the live probe (D18) covers standard OpenWrt; importing the firmware image adds the custom tools and the difference since flashing (image profiles) | Dmitry |
| D7 | Radio model is multi-band from day one (2.4 / 5 / 6 GHz); switch model covers swconfig and DSA | Dmitry |
| D8 | Mode and channel selectors: Auto / All (plus None for channels) or checkboxes; ticked = auto restricted to the ticked set. A selection is either applied (router picks within it) or stepped through (one pure mode × one channel per step) | Dmitry |
| D9 | MAC access control lives on Network & DHCP | Dmitry |
| D10 | Light and dark themes; follow Windows by default, with a manual toggle | Dmitry |
| D11 | Firewall supports both models: allow-all + block rules, and block-all + allow rules | Dmitry |
| D12 | Tables owned by other programs (harness) can be unlocked and then edited, deleted or added | Dmitry |
| D13 | LuCI parity: every LuCI page on the image has an equivalent | Dmitry |
| D14 | LTE modem management, including the modem reset that the D-Link firmware had | Dmitry |
| D15 | Self-update from GitHub Releases; stable and pre-release (CI) channels | Dmitry |
| D16 | Run as a professional open project: README with screenshots, user manual, wiki, issue templates, CI, release pipeline, roadmap | Dmitry |
| D17 | Phase 2: one page per tool listed under "What this router can do" | Dmitry |
| D18 | Discovery and control follow LuCI: on connect, read the router's self-description (board.json, ubus methods, typed option lists, feature flags, LuCI menu conditions); call ubus over SSH wherever LuCI does; typed option lists generate an "All options" section; a LuCI page with no native screen opens inside the app as a fallback | Dmitry |

## 4. Architecture

```
OpenWrtGUI.exe  (PyInstaller onedir, bundled CPython 3.13)
├─ Window: pywebview → Edge WebView2 (falls back to the default browser if WebView2 is missing)
├─ Web UI: React + TypeScript (built at release time; static files at runtime)
├─ Local API: FastAPI + uvicorn on 127.0.0.1:<random port>, per-launch bearer token, WebSocket for live data
├─ Guard: Bench Guard · write lock per router · command preview · 60 s rollback · audit log
├─ Drivers: radio · wifi_acl · rf · network · dhcp · dns · routes · switch_swconfig · switch_dsa · mirror ·
│           firewall · faults · capture · lte · system · services · tools
├─ Prober: router self-description (board.json, ubus, option schemas, LuCI menus) + image profiles (pure-Python squashfs reader)
├─ Forms: typed option lists → "All options" editors
├─ LuCI bridge: SSH tunnel to the router's web server + rpcd session (fallback pages)
└─ Transport: asyncssh, one pooled session per router, host keys pinned; ubus calls and shell commands over it
```

- **Nothing is installed on the routers.** The only change the app makes for itself is one line added to `/etc/dropbear/authorized_keys` (D4, and the 4.5 MB flash limit). LuCI fallback sessions live in rpcd's memory only.
- **Transport.** All routers use asyncssh, so the app depends on neither plink nor Windows OpenSSH. File transfer goes through `scp` (Dropbear has no sftp-server) or `cat >` over an exec channel. The app sends the exact command text it shows in the preview.
- **ubus first** (D18). Drivers call `ubus call <object> <method> <json>` over the SSH exec channel and get JSON back. These are the calls LuCI makes, so the app reads and changes things the way LuCI does: `network.interface.* status`, `iwinfo`, `hostapd.*`, `luci-rpc getDHCPLeases` / `getHostHints`, `luci getRealtimeStats`, `system board`, `uci` and others. Shell commands are used only where no ubus method exists: `iw`, `tc`, `nft -j`, `swconfig`, `hostapd_cli`, `uqmi`, AT commands. The app does not use LuCI's HTTP `/ubus` endpoint for its own work: that needs a password login, while SSH with the app key already runs as root.
- **LuCI fallback bridge** (D18, section 7.14). For a LuCI page with no native screen, the app opens an SSH port forward to the router's web server and creates an rpcd session over SSH (`ubus call session create`, `session grant` for that page's access groups, `session set` user root). The page loads in an app tab with that session, so no password is typed. The session is read-only while Bench Guard sees a run, expires after 5 minutes idle, and is destroyed when the tab closes. Still to be confirmed on AP2 (O13).
- **Local API security.** The API listens on loopback only, on a random port, and every request needs the per-launch token. This stops other local programs and web pages from driving routers.
- **Packaging.** Inno Setup installer, per-user, no admin. Install folder is chosen at install time. On the bench PC it must be inside `C:\Essence_SC\` (SentinelOne rule), e.g. `C:\Essence_SC\apps\OpenWrtGUI`. PyInstaller "onefile" is not used: it unpacks to `%TEMP%` on every launch.
- **Data folder** (chosen at install, default `%LOCALAPPDATA%\OpenWrtGUI`, bench PC `C:\Essence_SC\apps\OpenWrtGUI-data`): `routers.json`, `known_hosts`, `keys/` (the app's ed25519 key, readable by the user only), `profiles/`, `baselines/`, `audit/`, `updates/`. Captures and RF recordings go to `Documents\OpenWrtGUI\`. Updates and uninstall leave the data folder alone (uninstall asks).
- **Secrets.** Router passwords are used once and never stored or logged. Wi-Fi keys are never shown in previews or logs (`<hidden>`). The IMEI is hidden until the user reveals it.

Source layout:

```
src/openwrtgui/  main.py (launcher) · app.py (FastAPI) · transport/ · probe/ · profiles/ · drivers/ · forms/ · luci_bridge/ · guard/ · api/ · store/ · update/
frontend/        React app (Vite)
installer/       OpenWrtGUI.iss
tests/           unit · contract (recorded router outputs) · e2e (Playwright) · hardware (opt-in)
docs/            manual/ (user manual, synced to the wiki) · design/ · superpowers/specs, plans
.github/         workflows · ISSUE_TEMPLATE · PULL_REQUEST_TEMPLATE.md · dependabot.yml
```

## 5. Routers, discovery and image profiles

**Adding a router** (wizard, screen 7):
1. Enter the address.
2. Accept the host key; it is pinned. A changed host key blocks the connection with an explanation (a reflash regenerates it).
3. Log in once with the root password. A fresh OpenWrt has no password, and the wizard offers to set one.
4. The app generates its own ed25519 key once per PC and appends it to `authorized_keys` only if it is not already there. Existing keys and password login stay as they are.
5. The app reconnects with the key only and confirms it works.
6. Read the router's self-description, identify it, and match it to a profile if one was imported.
7. Confirm the port map proposed from `board.json`, then run the self-test.

**Router self-description** (D18). On every connect the app reads what LuCI reads. Most of it is part of every OpenWrt image; only the `luci` / `luci-rpc` objects and the menu files need LuCI installed, and without them the app falls back to plain commands.

| Source | Drives |
|---|---|
| `/etc/board.json` | Model; switch ports with their printed labels (`index`), CPU port and default VLAN roles; LEDs; radio bands, modes and maximum width; default network. The front panel and the port map start from here |
| `ubus -v list` | Which services exist and their method signatures; a driver is available only when the methods it calls are there |
| `ubus call network get_proto_handlers` | Interface protocols and each one's typed options (forms for Router addresses and LTE) |
| `ubus call network.wireless get_validate` | Every radio, SSID, station and VLAN option with its type (forms for Wi-Fi) |
| `ubus call luci getFeatures` | Feature flags: SAE, OWE, WPS, 802.11r, swconfig, firewall4, package manager, dnsmasq features |
| `iwinfo` (`info`, `freqlist`, `txpowerlist`, `countrylist`) | Channels, TX power steps, modes per radio for the current country |
| `/usr/share/luci/menu.d/*.json`, `/usr/share/rpcd/acl.d/*.json` | Which LuCI pages exist, when they apply, and which configs and ubus methods each touches: the parity check (section 8) and the fallback list (7.14) |

`board.json` is written at first boot, so it is not in the image; the live read is the only source for it.

**Image profile.**
- Importing the image adds what the live read cannot see: what came with the image versus what was added later, the custom packages with their usage text, and the defaults. It also works while the router is offline.
- Import a sysupgrade `.bin`. The app finds the squashfs and reads `lib/apk/db/installed` (packages, versions, descriptions), the kernel modules (which qdiscs, which switch framework), binaries on `PATH`, custom packages with their usage text, and the `/etc/config` defaults.
- The profile is keyed by board name, `DISTRIB_REVISION` and image SHA-256.
- If an image cannot be parsed, the same profile is built from a connected router's `/rom`.

**On connect**, the app reads identity (`/etc/openwrt_release`, `ubus call system board`), reads the self-description above, and matches a profile. Live probing then adds:
- **Added after flashing**: `/overlay/upper` files and packages that are not in the profile.
- **Config changed**: `/etc/config` compared with `/rom/etc/config`.
- **Runtime state**: nft tables, qdiscs, monitor interfaces, mirror hooks, radio state.
- **Firmware match**: the firmware partition hash compared with the image.

**Capabilities.** Each feature declares what it needs in the same form as LuCI's menu `depends` (`fs`: file present or executable; `uci`: config section present), plus three kinds of its own: `ubus` (object and method), `feature` (`luci getFeatures` flag) and `board` (`board.json` key). Examples: Switch needs `fs /sbin/swconfig` and `board switch`; LTE needs protocol `qmi` among the proto handlers and `fs /sbin/uqmi`; WPA3 needs `feature hostapd.sae`. The UI shows a feature only when its conditions hold, and greys it out with the reason otherwise.

**Forms from typed options.** A typed option list becomes an editor: `bool` → switch, `uinteger` / `integer` → number, `string` → text, `list(…)` → list editor, `device` → device picker. Options with a hand-made control elsewhere on the screen link to it instead of being repeated. Each option shows its current value, the image default, and the known writer that set it, if any (e.g. `cell_density` by `dima_night`). Writes go through the normal preview, guard and audit. Unknown custom executables appear on the Discovery screen with "Run `--help`" and "Promote to a card". Promotion takes a small descriptor (name, commands, arguments, read-only or write), shown as a card with the same preview, guard and audit as built-in features.

**Port map and self-test.** The port map starts from `board.json` (printed label per switch port; on the DWR-921 C3 internal ports 0–3 are LAN4–LAN1). It is confirmed read-only (switch MAC table and link state), and by unplugging and replugging sockets only where that is not enough. The app never disables the port that carries its own SSH. The self-test checks monitor mode, port-disable carrier drop (on a free port), netem effect and nft insert/readback. Radio checks run only with explicit consent. Results are saved per router model.

**Baselines and known writers.**
- A baseline is a per-router snapshot of uci plus runtime state. Differences from it are shown on the dashboard.
- A difference that matches a known writer's signature is labelled with that writer instead of raised as an error. Example: `dima_night` lab options `country`, `cell_density`, `legacy_rates`.
- Known-writer signatures are kept in a small registry in Settings.

**Future routers.**
- 5 and 6 GHz radios use the same uci `wireless` and `iw` model. Bands and widths come from `board.json`; channel and power lists from `iwinfo` / `iw phy` for the country code.
- DFS channels show the radar-check wait (CAC: 60 s, or 10 min on channels 120–128).
- On 6 GHz only SAE or OWE with PMF can be selected.
- The DSA switch backend implements the same interface as swconfig. It is built when the first DSA router and its image are on the bench.

## 6. Safety

| Mechanism | Behaviour |
|---|---|
| Bench Guard | Detects a live harness run: lock files (e.g. `iperf_txsweep/voip.lock.own`), processes (`dima_night.py`, `rh_soak.py`, `overnight_wifi`, `txlab_*.py`, `voip_chain.py`, `mem04_bench.py`), router markers (run SSIDs `OpenWrtB` / `OpenWrtC`, armed radio dead-man jobs). While one is live, every router is read-only and a banner names the run. Reading, RF, capture and read-only terminal commands keep working. The watch list is editable in Settings |
| Write lock | One write at a time per router. Reads run in parallel |
| Preview | Every write shows the exact commands before Apply. Secrets are masked |
| Verify by effect | A write is reported as done only when the effect is proven. Radio park: uci committed + netifd settled + no AP in `iw dev`. Link up: polled for up to 20 s. nft rule: present, ahead of `ct state established accept`, counter readable |
| Rollback | Changes that can cut the app's own path (lan address, VLAN 1, firewall input on the app's zone, bridge members) arm a router-side 60 s restore timer first. The app reconnects, confirms and cancels the timer; otherwise the router restores itself. The timer is rpcd's own, as LuCI uses it: changes staged in an rpcd session (`uci -P /var/run/rpcd/uci-<session>`), `ubus call uci apply` with rollback, then `ubus call uci confirm` from the reconnected session (O14) |
| Own path | The PC's switch port and the app's SSH rule cannot be disabled from the UI |
| Ownership | Every nft table and tc hook has an owner: fw4, the app, the harness, or unknown. Tables owned by someone else are locked by default. **Unlock** names the owner and what depends on it (e.g. "dima_night expects BENCHSIPGUARD") and asks for confirmation; after that edit, delete and add are allowed (D12). Bench Guard still wins during a run |
| Timed faults | A timer on the router clears them, so they end on time even if the PC goes away |
| DHCP conflict | Before enabling a DHCP server, the app checks the other routers on the same subnet |
| Audit log | Every command sent: time, router, screen, command (masked), exit code, verify result. Exportable for bug reports |
| Dev router | Development and hardware tests use AP2 only. Tell the txctl session before any wifi or network reload on AP2. AP1 and AP3 are not touched |

## 7. Screens

Mockups for screens 1–12 are on the canvas (`docs/design/canvas/project/`). Screen 14 (a LuCI page inside the app) is on the canvas too; screen 13 (terminal and audit log) is specified here only. The D18 parts are drawn on Wi-Fi, Network, LTE and Discovery; the "All options" lists in the mockups are AP2's real ones. Every screen works in light and dark.

### 7.1 Dashboard (1)
- Shows: routers with state; the 2.4 / 5 / 6 GHz air map (on air vs parked/staged); per-router cards (radio, RF summary, stations, network, faults, login type, ownership tags); "Needs attention" (drift with known-writer attribution, password-only login, files added after flashing).
- Header: Bench Guard status and the theme toggle.

### 7.2 Wi-Fi (2)
- **Per radio tab**: band, channel, width, TX power, country, SSID(s), security (Open / WPA2-PSK / WPA3-SAE / WPA2+WPA3; on 6 GHz only SAE/OWE).
- **Mode selector**: Auto / All, or checkboxes b · g · n20 · n40 (ac/ax/be added for 5/6 GHz radios). Ticked modes are compiled to:
  - `htmode` (NOHT / HT20 / HT40)
  - `legacy_rates`, `supported_rates` and `basic_rate` (kb/s)
  - `noscan=1` only when n40 is ticked without n20
  - a runtime TX mask `iw dev <if> set bitrates legacy-2.4 … ht-mcs-2.4 …`, re-applied after every Wi-Fi reload

  Auto removes all overrides. On this image Auto means no 802.11b rates unless `legacy_rates=1`. n-only still beacons at 6 Mb/s OFDM; the UI says so.
- **Channel selector**: Auto / All / None, or checkboxes 1–13. Rules:
  - one ticked: `channel=N`
  - several ticked: `channel=auto` + `channels='…'`
  - All: `channels='1-13'`
  - None: radio parked (`disabled=1`)
- **TX power**: Auto (shows the actual maximum) / Fixed N / Cap N. Cap is shown only when the driver can use it. The actual value from `iw dev … info` is shown next to the requested one.
- **Apply**: the router picks within the selection. The result is verified on air: radio up, channel, width, and beacon rates read through a temporary monitor interface (`owgmon0`, see O4).
- **Step-through**: every ticked mode × ticked channel × (optional) ticked power, one pure mode per step. Each step is proven on air before its dwell. Advance on a timer, manually, or when a station re-joins. AP restored at the end or on Stop. Blocked by Bench Guard.
- **Stations**: MAC, name/IP (leases), signal, TX/RX rate, mode, connected time; actions: RF, Block, Deauth.
- **Who may join**: one-line summary linking to Network & DHCP.
- **All options** (collapsed, per radio and per SSID): every option from `network.wireless get_validate`, as a typed editor (section 5, "Forms from typed options"). On AP2 that is 155 radio and 289 SSID options, so anything hostapd or the driver accepts can be set without a dedicated control. Security choices offered above follow `luci getFeatures` (e.g. SAE only when hostapd has it).
- *v0.7 note* (plan `2026-11-12-v0.7-test-helpers.md`, D2-D10): a step-through step is a Wi-Fi Apply of one pure mode, one channel and optionally one TX power, in the order mode (b, g, n20, n40) → channel → power, at most 200 steps; the whole run is previewed (each step's lines and the restore) and every step is planned again and compared before it runs. A step whose proof fails is recorded "not proven" and the run goes on; a refused change stops it and restores. Advance on a timer (10-3600 s), by Next, or when a station is associated and authorized again (re-join limit 30-600 s, the time recorded). The radio's mode, channel and power options are saved in the data folder before step 1 and applied back at the end, on Stop and at shutdown; a saved copy left behind offers Restore at the next start. A harness run stops it at once without the restore (a reload would disturb the run). While it runs, the radio's Apply, All options, the saved MAC lists, a scan, System jobs and a flash of that router wait (409); it does not start while one of its SSIDs is on air on another router. Results per step go to a CSV in Documents.

### 7.3 RF live (8)
- **Colours**: blue = RX at AP (station → AP), orange = TX from AP (AP → station), used the same way everywhere.
- **Radio**: channel/width/frequency, TX power set vs actual, air busy % (survey), noise floor (shown "not reported" where the driver gives none, as on rt2800), ACK failures/s (debugfs).
- **Per station, RX**: signal now/avg, per antenna, RX rate and mode, packets, drops, last frame.
- **Per station, TX**: TX rate, MCS, width and GI, retry %, failed/s, expected throughput, ACK signal (where supported).
- **Charts**: signal over time and TX vs RX rate, with hover readout. Window: 1 min / 5 min / 1 h.
- **"Which rates reach the station"**: minstrel `rc_stats` (attempts, success %, in-use rate).
- **Frame analysis via `mon0`** (off by default; costs router CPU): rate mix per direction, signal histogram, retry-flag share, bad-FCS share.
- **Record to CSV** (1 s samples).
- **Channel analysis** (LuCI parity): scan of nearby networks and channel survey per channel.
- *v0.7 note* (D11-D13): `owgmon0` is shared by the beacon check, Capture on mon0 and frame analysis (the last holder removes it; a Wi-Fi reload removes it and a holder adds it again). Frame analysis samples 3 s of every 5 s with `tcpdump -e -v` on the monitor, parsed on the PC, direction by the radio's BSSIDs; it stops after 30 minutes, when the last RF viewer leaves and when a run starts. Channel analysis is one passive scan on demand: `iw dev <ap> scan ap-force passive` on air, a temporary managed `owgscan0` when parked, with survey dumps before and after for each channel's busy share; a scan is a write (previewed, refused during a run or a step-through, audited).

### 7.4 Network & DHCP (9)
- **Router addresses**: every interface (lan, wan, lte, VLAN interfaces) as Static / DHCP client / No address / LTE (QMI) / PPP. Address is always written as `address/prefix` (a bare address becomes /32 on this image). Also gateway, DNS, MTU and bridge members. Changes to the app's own path apply with rollback, and the app follows a changed address. The protocol list and each protocol's fields come from `network get_proto_handlers`: the common fields are laid out by hand, the rest appear under **All options**, so a protocol added by a new package (e.g. WireGuard) is editable at once.
- **DHCP server** per interface: on/off with conflict check; pool start/size, lease time; options by code (3, 6, 15, 42, any); IPv6 DHCPv6/RA.
- **Fixed addresses by MAC**: name, MAC, IP, lease time, and **Gets an address** (off = `ignore=1`: the device joins but gets no IP).
- **Active leases**, with Make fixed.
- **Wi-Fi access by MAC**: Everyone / Block listed / Only listed, for all SSIDs or ticked ones. Per device, three ways to block:
  - Now, no Wi-Fi restart: `hostapd_cli deny_acl ADD_MAC`.
  - For N s: ubus `del_client` with `ban_time`.
  - Saved: uci `macfilter` / `maclist` plus a reload.
- **DNS** (LuCI DNS page): forwarders, local domain, rebind protection, per-domain overrides (`address=/host/ip`), and similar options.
- **Static routes and rules** (LuCI Routing page): IPv4/IPv6 routes, policy rules, live routing table.

### 7.5 Ports, VLANs, mirroring (3)
- **Front panel**: printed labels ↔ internal ports (from `board.json`), link/speed, per-port enable via `dwr921-portctl` or `swconfig … enable`. The SSH port is locked. "Enable all ports" button.
- **VLAN matrix** (— / U / T per port, CPU included). Changes to VLAN 1 apply with rollback.
- **Switch port mirror**: monitor port, sources with RX/TX.
- **Wi-Fi mirror** (`wifi-mirror` where present): status, stop/restart, excluded MACs, warning before iperf.
  v0.3 shows the status only (present, running or stopped, from `ubus call service list`); stop/restart, the
  excluded MACs and the iperf warning come with image import (v0.5), which reads how `wifi-mirror` is set up.
  *v0.5 note* (plan D7): `wifi-mirror` is not in the bench image (AP1 added it after flashing), so how it is set
  up cannot be read; its service gets Start, Stop and Restart on Discovery › Custom services where a router has
  it, and the excluded MACs and the iperf warning stay deferred.

### 7.6 Firewall (4)

- **Filtering model per zone and direction** (D11):
  - **Allow all, block by rules**: zone policy ACCEPT, user rules drop/reject.
  - **Block all, allow by rules**: zone policy REJECT/DROP, user rules accept.

  Switching model keeps the existing rules and flags any that no longer do anything. In "Block all" on the zone that carries the app's SSH, the app pins "allow SSH from this PC" and, where this router serves DHCP/DNS there, "allow DHCP + DNS". Pins can be removed after a warning. Changes apply with rollback.
- **Zones**: networks, input/output/forward policy, masquerade, MSS clamp, forwardings.
- **Tabs (LuCI parity)**: Traffic rules (with live counters), Port forwards, NAT rules, IP sets, Custom rules (`/etc/nftables.d` includes), All nftables tables, Raw ruleset.
- **Other tables** (BENCHSIPGUARD, `voipdscp`, the app's `benchfault`, unknown): owner badge, **Unlock**, then edit rules, delete table, or add a table (D12). Each change can be runtime-only or persisted as an fw4 include, and is applied atomically with `nft -f` and rollback.
- *v0.4 note*: every `firewall` uci change applies with rpcd's 60 s rollback, not only input on the app's zone: a rule on any zone can match this PC. Changes that are not uci (other nft tables, `/etc/nftables.d` files) use a router-side timer instead (`/tmp/owg`, started before the change, cancelled after the app reconnects and confirms), because rpcd rolls back uci configs only. The pins are not editable as traffic rules; they are removed only from the pins box, after the warning. fw4 routers only; a router without `firewall4` shows LuCI's pages instead.

### 7.7 Faults and capture (5)
- **Target**: a known device or any IP/MAC. Panel ETH and Wi-Fi MACs differ, so matching is by remembered MAC or lease hostname, never by vendor prefix.
- **Layers**:
  - L1 link down (Ethernet only)
  - L2 isolate
  - L3 block flows (`rtp_in`, `sip_in`, `rtp_out`, `all_in`, `all_out`, `blackout`), with loss %; RTP ports come from conntrack
  - netem impair (delay, jitter, distribution, loss, reorder, duplicate, direction; scoped to the target)
  - Wi-Fi (deauth, Block for N s, AP down)
- **Duration**: until cleared, or hold N s (cleared by a router-side timer).
- **Capture**: br-lan / Wi-Fi interface / `mon0` (created on demand) / wwan0. Filter, duration, Live in Wireshark (if installed) or save `.pcap`.
- *v0.4 note*: faults live in `table netdev benchfault`, chains bound to the target's device (`bridge benchfault` where the router has no netdev egress hook), not in an `inet` forward chain: traffic between a Wi-Fi panel and a wired peer is bridged and never reaches inet forward. Each armed fault leaves a record in `/tmp/owg`, so the app (and the dashboard) lists it after the app or the PC restarts; a reboot ends both. Arming is refused during a run; **Clear** is allowed, since it only removes what the app armed and a fault left in place disturbs the run more. Capture keeps working during a run, except on `mon0`, which needs a monitor interface on the radio (a write). The app's own SSH stream is always filtered out of a capture.

### 7.8 Discovery and tools (6)
- **What the router says about itself** (section 5): model and board file, services found, feature flags, LuCI pages installed. LuCI pages without a native screen are listed with **Open in LuCI** (7.14) and a note that they have no native screen yet.
- Image match and firmware hash; capability map (in image / added after flashing / missing); your custom packages (card, service, or "no card yet" with `--help` and Promote); files added after flashing (copy to another router, save as a reflash checklist); config changed vs image defaults, with diff.
- *v0.5 note*: "What the router says about itself" stays on the router's Overview; Discovery is its own screen
  per router. **Run `--help`** counts as a write (plan D3): previewed, refused during a run, audited, run with
  `timeout 5` and cut at 8 KB; the usage text read from the image is shown first, without running anything (an
  unknown program such as `dwr921-internet-led` would start its loop). The **firmware check** (D4) hashes the
  firmware partition (11 MB through `sha256sum`) only when asked and not during a run. A custom package is an apk
  entry with neither a license nor a URL; promoted cards are kept per board; custom services (an init script from
  a custom package or added after flashing) get Start, Stop and Restart now, other services wait for System ›
  Services. Configs created at first boot (`network`, `wireless`) have no image default and are named, not read.
  **Flash lives on Discovery** (D11), next to the image match; System › Backup and firmware (7.11) will link to it.
- **Phase 2** (D17): each capability chip links to its own tool page. Planned pages:
  - Throughput: iperf3 / iperf 2, router as server or client.
  - Air survey: `iw` scan and survey.
  - Station management: `hostapd_cli` (802.11v BSS transition, 802.11k neighbour reports).
  - Traffic generator: `socat`.
  - Port statistics: `ethtool` and switch MIB counters.
  - Connections: `conntrack`, SIP ALG toggle.

### 7.9 Add router (7)
The wizard described in section 5.

### 7.10 LTE modem (10; LuCI `luci-proto-qmi` parity plus what the D-Link UI had)
- **Status**:
  - registration, radio type, roaming, operator
  - RSSI / RSRP / RSRQ / SNR, each with a quality label and history chart
  - session uptime, IPv4, data counters
- **Settings** (uci `network.lte`): APN, auth (none/PAP/CHAP/both) with user/password, PIN, PDP type (`ipv4` / `ipv6` / `ipv4v6`), MTU (1420 on AP2), metric, bring up at boot, default route. The `qmi` option `autoconnect` is the modem's own autoconnect: this image's `qmi.sh` (custom `dwr921_qmi_*` functions) writes it into the modem's memory, so the UI keeps it apart from "bring up at boot". `lte_4` stays DHCP; the UI explains why. The other options of the `qmi` handler (25 in all, e.g. `modes`, `plmn`, `delay`, `profile`, `v6apn`) appear under **All options**.
- **Modem**:
  - info: manufacturer, model, firmware (ATI); IMEI hidden until revealed
  - network mode order (`AT+BMMODODR`; code names still to map)
- **Actions**:
  - connect / disconnect (`ifup`/`ifdown lte`)
  - reboot modem (QMI operating mode reset, or AT; to be verified)
  - **Reset modem to defaults** (D14; command still to be found, open item O1)
  - AT console with history
- **Phase 2**: SIM PIN management, SMS, USSD (the D-Link UI had these).

> **v0.6 note** (plan `docs/superpowers/plans/2026-11-08-v0.6a-lte.md`, decisions D1-D12):
> - Status comes from the bench's own reads (`uqmi --get-serving-system`, `--get-signal-info`, netifd's status);
>   the live chart samples every 10 s only while the screen is open, and a lost answer is a missed sample, not
>   a state change (D1).
> - Modem info comes from `AT+CGMI`, `AT+CGMM`, `AT+CGMR`, not `ATI`; the IMEI from `uqmi --get-imei` only on
>   Reveal, never stored or audited (D3).
> - The AT port is found per router by sending `AT` to each `/dev/ttyUSB*` in order; the first `OK` is used
>   (D4). On AP2 it is `/dev/ttyUSB1` (2026-11-09; `/dev/ttyUSB3` never takes bytes, so no port after the
>   AT port is opened); the simulator answers on ttyUSB2.
> - Reboot modem is operating mode `low_power`, then `online`, each read back, then `ifup lte`; never `reset`,
>   which wedges the BM806C until a power cycle (D6).
> - Correction to Settings above: this image's `qmi.sh` ignores the uci `autoconnect` option and turns the
>   modem's autoconnect off at every connect, so the UI shows the option locked with that reason (D7).
> - `dhcp=0` on the qmi interface is refused: lte_4 must stay DHCP (D8). Bring up at boot is netifd's `auto`
>   (D9).

### 7.11 System (11; LuCI System and Status parity)
- System: hostname, time zone, NTP client/server, log buffer, remote syslog.
- Access: root password; SSH (port, interface, password auth, root login); SSH keys (each labelled: app, harness, other); HTTP(S) (LuCI on/off, redirect to HTTPS).
- Services: init scripts (enabled, running, start/stop/restart/enable/disable), `rc.local`.
- Scheduled tasks (crontab), LED configuration, mount points.
- **Backup and firmware**:
  - backup download (`sysupgrade -b`), restore
  - reset to defaults (`firstboot`), with a warning that the LAN address returns to 192.168.1.1 and would clash with AP1
  - **Flash firmware from an imported image**: board and hash checked, keep-settings option, upload over scp, `sysupgrade -T` on the router, flash, reconnect, verify the new revision. Files added after flashing can be copied back afterwards (list from Discovery). Without keep settings the router returns like `firstboot` (192.168.1.1, no password, no key), so the app asks for the router to be isolated first; the expected host-key change is accepted only after the board and revision check.
  - *v0.5 note*: built on Discovery (plan D11). The image goes up over the SSH channel's stdin (`cat > /tmp/owg/…`)
    instead of scp, through the same audited write path as every other change; its sha256 is checked, then `validate_firmware_image` and `sysupgrade -T`;
    `sysupgrade` is started 2 s later by a router-side timer (O15), so the app's connection dropping does not
    matter. A flash that keeps settings also keeps `/etc/owg/` (D5) by adding that line to `/etc/sysupgrade.conf`
    when it is missing. Done means the router answered again with a fresh uptime, the image's board and its
    revision. A reflash checklist is saved before every flash. Without keep settings (D6) the router entry shows
    "Reflashed without settings: add it again" and the wizard reads the board and revision over one unchecked,
    unpinned connection before accepting the new key; built and tested in the simulator only (O17).
  - reboot
- Status: overview, routes, system log, kernel log, processes, realtime load/bandwidth/connections, diagnostics (ping, traceroute, nslookup run on the router).
- *v0.6b note* (plan `docs/superpowers/plans/2026-11-09-v0.6b-system.md`, D1-D12): one System screen with a
  tab per LuCI page (`?tab=`). Reads are LuCI's own (`ubus call system board|info`, `logread -l`, `dmesg -r`,
  `top -bn1`, `ubus call rc list`, `luci getTimezones`, `/proc`), each its own exec, a part that fails named.
  Live load, bandwidth and connection count every 3 s; the connection table on request (500 rows at most).
  Diagnostics are audited, not previewed, and wait for a harness run. System settings go through the plain
  uci apply with `system reload`, `sysntpd restart` or `log restart` and are proven by the saved config, the
  live host name and `/tmp/TZ`; UTC is offered as `GMT0` (the router's list has no UTC). Services are proven
  by re-reading `rc list` within 10 s (a one-shot by its exit status); dropbear, rpcd, uhttpd, network,
  firewall and log are restart only. `rc.local` (must end with `exit 0`) and the crontab (every field
  checked) are written whole through the audited heredoc, 8 KiB at most. The reboot is armed by the
  router-side timer and done only on a fresh uptime (300 s limit). The backup is `sysupgrade -b -` saved
  user-only in the data folder; the audit log names the file, never its content. Processes are read-only.
  Access, SSH keys, HTTP(S), LEDs, mount points, restore and reset to defaults are v0.6c.
- *v0.6c note* (plan `docs/superpowers/plans/2026-11-10-v0.6c-system.md`, D1-D15): three new tabs (Access,
  LEDs, Mount points) and a bigger Backup tab; LuCI's `admin/system/admin` pages and `leds` open natively,
  `mounts` stays LuCI's. The root password goes on `passwd root`'s stdin, never in a command line, plan,
  audit line or answer, checked first against LuCI's `rpcd.policy`; proof is a digest of root's shadow field
  that changed, the hash never leaving the router (D2; on AP2 only with a router-side restore timer, D3).
  Every dropbear change applies with the rpcd rollback and is confirmed from a new connection; the app's own
  instance cannot be disabled, removed or moved off the app's interface, and a port change is followed (D4).
  `authorized_keys` is written whole, each key labelled App, Harness (named in `Settings.known_keys`) or
  Other; the app's key cannot be removed and a new login proves the app still gets in (D5). HTTP(S) is two
  switches, `redirect_https` (refused while nothing serves HTTPS) and LuCI on the network or loopback only;
  loopback always stays for the bridge, which follows the redirect over TLS (D6). Repository keys and mount
  points are read only (D7, D8; fstab waits for block-mount). LED actions follow LuCI's trigger plugins and
  are proven by the active trigger (D9). `/etc/sysupgrade.conf` is edited as text beside `sysupgrade -l`
  (D10). A restore takes only a backup from the app's list (its own or an imported one, checked on the PC)
  and is refused before anything is sent when the archive's host key is not the pinned one, it moves the
  router off its address, it lacks the app's key, or its dropbear config leaves nothing on the app's port;
  proof is a fresh uptime and every file's sha256 (D11).
  Reset to defaults is `firstboot -r -y` through the router-side timer, needs the router's name and an
  "alone on this PC's network" tick, ends when the router stops answering and marks it to be added again;
  simulator only, never on AP2 (D12). Signals, the rpcd user's password, uhttpd's other options and fstab
  editing are not in v0.6c (D13). The seven v0.6b deferred minors are fixed test-first (D14). Two AP2
  windows: a read-only recording and, with Dmitry's OK, the writes of O20 (D15).

### 7.12 App settings and updates (12)
- Updates (section 9), theme (System / Light / Dark), data folder, known devices (name ↔ MACs: the panel's ETH and Wi-Fi MACs are unrelated).
- Bench Guard watch list, known-writer signatures.
- App SSH key: fingerprint, export public key, rotate (re-deploys to every router, then removes the old key).
- Audit log retention and export.

### 7.13 Terminal and audit log
- An xterm.js terminal per router over the same session. During a run it accepts read-only commands only.
- Audit log viewer with filters and export.

### 7.14 LuCI pages (fallback, D18)
- For LuCI pages with no native screen yet, typically from a LuCI app that a newer image brings (e.g. SQM, WireGuard, statistics). Native screens stay the main way to work; this is the safety net for the long tail.
- Listed on Discovery and in the router's section list as "LuCI: <page>". Opening one shows the real LuCI page in an app tab, through the bridge in section 4: no password, and the app's theme is not applied (it is LuCI's own look).
- Access: the rpcd session gets only that page's access groups. While Bench Guard sees a run, it gets read access only, and LuCI shows its read-only view.
- Changes made inside a LuCI page do not go through the app's preview. LuCI's own apply with rollback still works. The app records in the audit log that the page was opened, and shows what changed afterwards as a difference labelled "changed via LuCI".

## 8. LuCI parity (every LuCI page installed on the image)

| LuCI page | OpenWrtGUI |
|---|---|
| Status › Overview | Dashboard; System › Status |
| Status › Routing | Network › Static routes (live table) |
| Status › Firewall (nftables) | Firewall › Raw ruleset |
| Status › System log, Kernel log | System › Status |
| Status › Processes | System › Status |
| Status › Channel analysis | RF live › Channel analysis |
| Status › Realtime graphs (load, bandwidth, wireless, connections) | System › Status (load, bandwidth, connections); RF live (wireless) |
| System › System | System › System |
| System › Administration (router password, password policy, SSH access, SSH keys, HTTP(S) access, repo public keys) | System › Access (repo keys: read-only list) |
| System › Plugins | not applicable (LuCI's internal plugin switches) |
| System › Startup | System › Services |
| System › Scheduled tasks | System › Scheduled tasks |
| System › Mount points | System › Mount points |
| System › LED configuration | System › LEDs |
| System › Backup / Flash firmware | System › Backup and firmware |
| System › Reboot | System › Reboot |
| Network › Interfaces (incl. protocols qmi, ppp, ipv6) | Network & DHCP › Router addresses; LTE modem |
| Network › Wireless | Wi-Fi; Network & DHCP › Wi-Fi access by MAC |
| Network › Switch, Switch/VLAN config | Ports, VLANs, mirroring |
| Network › Routing | Network & DHCP › Static routes and rules |
| Network › DHCP, DNS | Network & DHCP › DHCP server, Fixed addresses, DNS |
| Network › Diagnostics | System › Status › Diagnostics |
| Network › Firewall (zones, port forwards, traffic rules, NAT rules, IP sets, custom rules) | Firewall (all tabs) |
| Services, VPN | empty on this image; an app installed later shows up under Discovery |

New router images may bring more LuCI apps. The prober compares the router's LuCI menu files with this table: a page with no native screen shows up as a Discovery finding and opens through the LuCI fallback (7.14) until it gets one. So parity holds from day one, and native screens replace fallback pages over time.

## 9. Updates from GitHub Releases

- **Check**: at start-up and daily, `GET https://api.github.com/repos/dm17ryk/OpenWrtGUI/releases`. Anonymous, since the repo is public.
  - Stable channel: the latest release that is not a pre-release.
  - Pre-release channel: also CI pre-releases.
- **Offer**: version, release notes, size; Update now / Skip this version / Later. Auto-check can be switched off.
- **Install**:
  1. Download `OpenWrtGUI-Setup-<ver>.exe` and `SHA256SUMS.txt` into `<data>\updates\`.
  2. Verify SHA-256.
  3. Stop live operations; if a step-through or capture is running, ask first.
  4. Start the installer silently into the current install folder (`/VERYSILENT /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS /DIR=…`) and exit.
  5. The installer relaunches the app. The previous installer is kept for "Reinstall previous version".
- **Trust**: HTTPS to GitHub plus the SHA-256 match. Authenticode signing is open item O7.

## 10. Project and repository (D16)

- **README**: what it is, hero screenshot, feature tour with screenshots, install, quick start (add a router), safety model, supported routers (any standard OpenWrt; image profiles add custom tools), roadmap link, contributing, license. Screenshots are generated in CI by Playwright against the router simulator (section 11), so they stay current.
- **User manual** in `docs/manual/`, published to the GitHub wiki by a workflow on every push to `master`; the repo is the single source.
  - Pages: Install, Updating, First router, each screen, Bench Guard, Adding a router family (image import), Troubleshooting, FAQ.
- **Issues**: issue forms for Bug (version, router model and image, audit-log export, steps), Feature request, and **New router support** (image link, `ubus call system board` output, `/etc/board.json`, `iw phy` output). `config.yml` turns off blank issues and points questions to Discussions. Labels: `type:*`, `area:*`, `router-support`, `good first issue`, `needs-hardware`.
- **Pull requests**: template with checklist (tests, screenshots for UI, docs, CHANGELOG). Conventional commits.
- **Agents**:
  - `AGENTS.md`: repo conventions for AI coding agents (layout, commands, safety rules: never touch AP1/AP3, AP2 only with the guard), with `CLAUDE.md` pointing to it.
  - Optional Claude Code GitHub Action for `@claude` on issues and PRs; needs an `ANTHROPIC_API_KEY` secret, Dmitry's call (O12).
- **GitHub Actions**:
  - `ci.yml` on push and PR: ruff + mypy + pytest (coverage ≥ 80 % on `transport`, `probe`, `drivers`, `guard`, `update`); eslint + tsc + vitest; Playwright e2e and screenshots; a Windows job that builds the frontend, PyInstaller onedir and the Inno Setup installer and uploads it as a workflow artifact.
  - `prerelease.yml` after CI succeeds on `master`: publishes a pre-release `vX.Y.Z-ci.<run>` with the installer and `SHA256SUMS.txt` (the CI update channel); keeps the last 10.
  - `release.yml` on tag `vX.Y.Z`: version stamped from the tag; build, checksums; GitHub Release with notes from `CHANGELOG.md`; stable channel.
  - `wiki.yml`: syncs `docs/manual/` to the wiki.
  - Dependabot (pip, npm, actions) and CodeQL.
- **Versioning**: SemVer, `CHANGELOG.md` in Keep a Changelog format.
- **Roadmap**: `ROADMAP.md`, plus GitHub milestones matching section 12 and a GitHub Project board.
- **Repo files**: `CONTRIBUTING.md` (dev setup, tests, hardware-test rules), `SECURITY.md` (private reporting; what the app stores locally), `CODE_OF_CONDUCT.md`, `LICENSE` (GPL-3.0, already in the repo).

## 11. Testing

- **Unit**: the command compilers (mode/channel → uci + iw; firewall model → fw4; ACL methods; DHCP), parsers (`iw`, `iwinfo`, `ubus`, `uci show`, `nft -j`, `tc`, `uqmi`, `ATI`), the self-description reader (`board.json`, `ubus -v list`, option lists, feature flags, LuCI menu `depends`), the typed-option form builder, the profile reader, the guard and the updater. Written test-first.
- **Contract**: real router outputs recorded from AP2 (sanitized: no keys, no IMEI) and replayed through a fake transport. They include the self-description set: `board.json`, `ubus -v list`, `get_proto_handlers`, `get_validate`, `getFeatures` and the LuCI menu and ACL files.
- **Router simulator**: the fake transport plus state. Serves the UI for e2e tests, screenshots and demos without hardware.
- **E2E**: Playwright drives the built UI against the simulator, in light and dark, at 1440 and 375 px widths.
- **Hardware** (opt-in, `pytest -m hardware --router 192.168.1.2`): runs only when Bench Guard is clear and the txctl session has been told. Restores the router afterwards and checks it matches its baseline.
- **Release check**: the installer installs, starts and updates on a clean Windows VM (manual for v0.1, automated later).

## 12. Roadmap (milestones; the order can change)

| Milestone | Content |
|---|---|
| v0.1 Foundation | Repo setup (README, templates, AGENTS.md, CI, pre-release and release workflows, wiki sync), installer, update check, app shell with themes, Add-router wizard (password → key), router self-description probe, router list, read-only dashboard, Bench Guard, audit log, terminal |
| v0.2 Wi-Fi and LuCI fallback | Wi-Fi screen (selectors, TX power, security, apply + verify on air, All options from the typed list), stations, RF live (radio and stations, charts, CSV); LuCI fallback pages (after O13), so every LuCI page is reachable from here on |
| v0.3 Network | Router addresses with rollback (fields from the proto handlers), DHCP, fixed addresses, Wi-Fi access by MAC, DNS, routes; ports/VLANs/mirroring (swconfig, labels from `board.json`) |
| v0.4 Firewall and faults | Both filtering models, zones, rules, port forwards, NAT, IP sets, custom rules, other tables with unlock; faults and capture |
| v0.5 Discovery and images | Image import and profiles, overlay difference, custom tools panel, flash firmware from image |
| v0.6 LTE and System | LTE screen (status, settings, actions, AT console), System screen (all LuCI System and Status pages) |
| v0.7 Test helpers | Step-through runner, `mon0` frame analysis, channel analysis |
| v1.0 | Native screens for every LuCI page on the bench image (the fallback stays for pages that later images bring), manual complete, hardening |
| 1.x (phase 2) | Tool pages, SIM PIN / SMS / USSD, DSA backend and 5/6 GHz checked on real hardware |

Each milestone gets its own implementation plan. The first plan covers v0.1 Foundation.

## 13. Open items

| # | Item | How to close it |
|---|---|---|
| O1 | BM806C "reset to defaults" command. The D-Link firmware's `libusbmodem.so` resets its DWP-812 modem profile with `AT%SYSCMD="/etc/sysconfig/script/cus_restore_default.sh"`, but the BM806C answers `AT%SYSCMD=?` with ERROR. `usbmodem_set_defaults` references `AT+BMMODODR=17`. An earlier Claude Code session reportedly reset this modem over SSH; the command is not in the local transcripts | Ask Dmitry for the command, or disassemble `usbmodem_set_defaults`; then test on AP2's modem with Dmitry's OK |
| O2 | Names for the `AT+BMMODODR` codes (17 now) | BroadMobi AT manual. v0.6 shows the code read-only ("names not mapped yet") |
| O3 | Operator name from QMI comes back garbled (encoding) | v0.6: the operator comes from `AT+COPS?`; QMI's name only when no AT port answers, marked "(from QMI, may be garbled)" |
| O4 | rt2800 noise floor and RX/TX air-time split are expected missing; confirm with the radio up | **Done 2026-11-05 on AP2 (on air, ch 6):** `survey dump` has no `noise` line and no RX/TX time on any channel, only active, busy and extension busy time. rt2800 also marks every channel `[in use]`, so the RF sampler takes the entry of the radio's own frequency (`current_survey`). The radio's own beacons, read on a monitor interface of the same radio, come from the TX path: `6.0 Mb/s [bit 15] BSSID:…`, with no `<freq> MHz` (the beacon parser reads the rate after the timestamp). So the beacon check reads the rate the driver reports for the beacons it sent, not beacons heard over the air. The monitor interface goes only with `iw dev owgmon0 del`; `ip link del` answers "Not supported" |
| O5 | `txpower limit` on rt2800 is expected to equal fixed | Open: not measured in the 2026-11-05 window |
| O6 | minstrel `rc_stats` path with a station associated | Done 2026-11-13 09:38 in the HW-2 window (O21): with the bench phone associated to `OwgTest` and pinging AP2, `rc_stats` read through the minstrel path: HT20, LGI and SGI rows for 1 and 2 streams; best throughput MCS15 LGI (A), MCS14 LGI (B), MCS12 SGI (C), best probability MCS12 SGI (P); one frame per A-MPDU on average |
| O7 | Authenticode signing certificate (SmartScreen, SentinelOne) | Dmitry / IT |
| O8 | Runtime `deny_acl` combined with a saved `maclist` across reloads | Test on AP2 |
| O9 | What the panel sees for each block method (auth reject vs no probe response) | `mon0` capture on AP2 |
| O10 | Known-writer signatures for each harness | Collect from the harness sources |
| O11 | Installing the app key on AP1 (live bench router) | Dmitry's go |
| O12 | Claude Code GitHub Action (needs an API key secret) | Dmitry's call |
| O13 | LuCI fallback login: LuCI accepts an rpcd session created over SSH (`session create` + `grant` + `set` user root) through its `sysauth` cookie; a read-only grant gives LuCI's read-only view; the session expires and is destroyed as planned | **Done 2026-11-05 on AP2:** a read-only session with only the page's own access groups (from acl.d) opened `admin/network/wireless` through the SSH forward: HTTP 200, no login form; the page's ubus calls (`iwinfo assoclist`, `uci get`) were allowed; `session destroy` left no session behind (`tests/hardware/test_ap2_luci.py`). No password and no "every group" retry needed |
| O14 | rpcd `uci apply` with rollback and `uci confirm` work from SSH, with the confirm sent over a second SSH connection | **Done 2026-11-05 on AP2** (`tools/rollback_spike.py`, throwaway config `owgprobe`, nothing reloaded): a value staged in an rpcd session and applied with a 10 s rollback was committed, then restored by rpcd 10 s later with no confirm; with a 30 s rollback and `uci confirm` sent from a new SSH connection it stayed. `session destroy` also removes the session's staging folder. **2026-11-06 on AP2 with real `network` changes** (`tests/hardware/test_ap2_network.py`): lan `192.168.1.2/30` (cuts the PC off at the same address) and lan `192.168.77.2/24` were never confirmed and AP2 restored itself, back at `.2` with its previous config; a free port off and on, the switch mirror on and off and a `/32` route were applied, proven and undone. The address follow to `.12` was not confirmed because the app compared a host key of another type than the one pinned (fixed: it asks for the pinned type), and the DNS check looked before procd had restarted dnsmasq (fixed: it waits). **Re-run 2026-11-06 with both fixes: 7 of 7 passed** — the follow to `.12` reconnected, proved and confirmed in 11.7 s; the two cuts were never confirmed and restored in 70 s and 75 s; the DNS change was proven after dnsmasq's restart; AP2 was left as found |
| O15 | A router-side timer that outlives the SSH connection (`start-stop-daemon -b` shell in `/tmp/owg`), for rollback of non-uci firewall changes and for held faults | **Done 2026-11-07 on AP2** (`tools/timer_spike.py`, `build/o15.json`): a 10 s timer fired after the SSH connection closed, and a 30 s timer was cancelled from a new connection; nothing was left in `/tmp`. In the firewall and faults window that followed (`tests/hardware/test_ap2_firewall.py`, `test_ap2_faults.py`, 15:24-15:31): an `all_in` block held 15 s was cleared on time by the router's timer after the app dropped its connection, LAN2 held down 10 s came back by the timer, and an app table add/edit/delete ran under the timer rollback and was confirmed. Also proven there: lan input Block all with the SSH pin confirmed in 8 s; without the pin AP2 rolled back by itself in 66 s; a 5 s br-lan capture held none of the app's own SSH packets. Two failures found and fixed test-first: a new traffic rule was refused (uci exits 1 on `-q delete` of an option the new section lacks), and the netem check read `tc qdisc show dev X`, which leaves out `dev X` (netem itself, on `ets`, was set). Both passed when re-run on AP2 the same day (21:59-22:01, `test_rule_add_and_delete` and `test_netem_to_target_and_clear`); the run left only an empty `/tmp/owg`, removed by hand. AP2 ended as found. **Re-run 2026-11-08 on master (0.4.0 with the Codex fixes), 10:31-10:35: the other six passed** — Block all with the pin confirmed in 8.8 s and undone in 7.9 s, the unpinned one restored by AP2 in 69.9 s, the app table add/edit/delete confirmed, the held `all_in` block cleared by the router's timer, LAN2 held down 10 s and back, a br-lan capture with none of the app's SSH; AP2 ended as found (again only an empty `/tmp/owg`, removed) |
| O16 | Wi-Fi faults on air: deauth, ban for N s, AP down | **Done 2026-11-09 on AP2** (`tests/hardware/test_ap2_wifi_faults.py`). The station is the Android phone: it joins `OwgTest`, put on air with a key made for the run, through a shell network suggestion over adb (`--adb-station`), which its owner allowed once on the phone; its user build has no `cmd wifi connect-network`. The run was 10:37-10:39 on channel 11 (`--o16-channel`, because an A/B run held AP1 on channel 6), and 1 test passed in 101 s. Block for 30 s kept the phone out (not associated for 20 s), and hostapd lifted the ban on time. Deauth sent the phone off (`left phy0-ap0`). AP down held 10 s stopped the BSS; the router's timer started it again after the app had dropped its connection, and the phone joined again. AP2 ended as found: the exact wireless file was written back and the radio parked, and the only leftover was an empty `/tmp/owg`, removed. The night runs (00:29-00:58) proved the ban and found three app bugs, fixed in #45. First, the verify read the AP interface while hostapd was still in COUNTRY_UPDATE (no channel yet, and `set bitrates` failed), so it now waits for a channel. Second, hostapd keeps a deauthenticated station listed, no longer associated, for about a second, and the phone joined again by the next look, so a station listed but not associated now counts as gone. Third, iwinfo's freqlist marked usable channels 6 and 9 restricted while the kernel's `iw phy` list had them usable, so channel limits now come from the kernel's list (Dmitry's call). The PC's own Wi-Fi cannot be the station: it carries the PC's network |
| O17 | Flash from the app on AP2: upload and validate in `/tmp/owg`, then a flash that keeps settings, the come-back and the revision proof, and flashing back. Flash without keeping settings is simulator-only (AP2 would return as 192.168.1.1, clashing with AP1) | Open: built and tested in the simulator (unit tests and the e2e flash of the simulated AP2); needs Dmitry's OK for an AP2 write window, the txctl session told and its run over. **2026-11-08 read-only recording on AP2** (`tests/fixtures/ap2/discovery.json`): AP2 runs exactly the bench image (its firmware partition's first 11 255 254 bytes hash to the image's, read in 13.8 s; no package added, removed or changed); `validate_firmware_image` and `sysupgrade` are there; /tmp has 27 012 kB free, but **MemAvailable is 8 148 kB** (MemFree 12 224 kB, file cache 14 508 kB), below the flash rule's image + 4 MiB (15 104 kB), so the app refuses to flash AP2 as it stands. Deciding the rule (for example counting clean file cache, or stopping services first) is the owner's call before the window |
| O18 | LTE actions on AP2: connect, disconnect, the modem reboot (low_power, online), a settings change through the interface plan, an AT query | Done 2026-11-09 (`tests/hardware/test_ap2_lte.py`, 4/4, AP2 as found): disconnect 3.6 s, connect 14.4 s, modem reboot 25.4 s, metric 20 → 21 and back about 14 s each with the rollback confirmed, `AT+CSQ` OK. The read-only recording before it (`tests/fixtures/ap2/lte.json`) found and fixed three things: QMI's operator name is not valid UTF-8 (it closed the SSH connection; the transport now reads it as U+FFFD), the AT port is `/dev/ttyUSB1` and `/dev/ttyUSB3` never takes bytes (microcom needs `timeout -s KILL`; the image's `dwr921-at-probe` hangs there), and the BM806C drops the third of a burst of AT commands (identity reads go one each). lte_4 has no DHCP lease on AP2 (pending), so LTE shows no IPv4 address |
| O19 | System writes on AP2: the hostname and back, a scheduled task added and removed, a service restart, a backup; the reboot and back | Done 2026-11-09 22:41-22:44 except the reboot (`tests/hardware/test_ap2_system.py`, 4/4, AP2 as found after each test: `uci -X show system`, `/etc/rc.local`, the crontab, every service's enabled and running state, the live hostname, `/tmp/TZ`, radio0 disabled; nothing on air). Hostname `OpenWrt` → `owg-test` and back in 0.3 s each, saved and live hostname proven. A `*/30` task added in 7.7 s (file read back, cron running), removed in 4.2 s. AP2 had no `/etc/crontabs/root`; removing the last task leaves an empty file (as LuCI does), which keeps crond running idle, so the test put the absence back by hand. `sysntpd` restarted in 8.1 s (proven running). Backup 7 428 bytes in 4.8 s (gzip), deleted after. **The reboot done 2026-11-13 12:37-12:40** with Dmitry's own OK, Bench Guard clear and txctl told (`test_reboot_and_back`, `--allow-reboot`): passed; AP2 back after 157 s (uptime 131 s at the check), the system config, rc.local, crontab, services, hostname, TZ and the parked radio as found |
| O20 | System access writes on AP2 (v0.6c D15): an LED trigger and back, the HTTPS redirect and LuCI off the network and back (a bridged LuCI page opened each way), a throwaway SSH key added and removed, the SSH port 22 → 2222 followed and back, a kept-files line, the policy section, the password (D3, `--allow-password`) and a restore of AP2's own fresh backup (`--allow-reboot`, its own OK). Reset to defaults never runs on AP2 | Done 2026-11-11 12:56-13:05 on AP2 with Dmitry's OK, Bench Guard clear and txctl told; restore skipped by his choice. HW-1 redone first (`--set access`, 15 reads, 12:58:30-35): the same values as the unaccepted 12:38 run apart from uptimes, disk use and one TCP line, so the fixture is no longer provisional. `tests/hardware/test_ap2_access.py` (`--allow-writes --txctl-told --allow-password`): 7 passed, 2 skipped (the restore; the HTTPS redirect, since AP2 serves no HTTPS). led_lan to none and back 0.4 s each, the active trigger proven; LuCI loopback-only 1.7 s and back 0.9 s, a bridged LuCI page HTTP 200 each way; a throwaway ed25519 key added 0.6 s and removed 0.7 s, the app still logging in; SSH 22 to 2222 7.4 s and back 5.8 s, reconnected and confirmed each way; a kept-files line 0.1 s each way; the rpcd.policy section created and removed; the password (D3) changed and proven in 0.8 s, then AP2's own shadow copy written back and its digest as found. One teardown error found a bug: rewriting authorized_keys turned AP2's CRLF key line (pasted from a Windows .pub) into LF; the CR was put back by hand at 13:03:56 (fresh key login proven) and the parser now keeps each line as written. An empty /tmp/owg the password test left was removed. AP2 ended as found (dropbear on 22, the same root password digest, `uci changes` only the boot-time lte staging, radio parked: disabled 1, country IL, legacy_rates 1, cell_density 0, no AP interface), except that uhttpd's listen_http and listen_https now sit at the end of its main section (same values: uci re-appends a rewritten list, as LuCI's page does). **The restore done 2026-11-13 12:42-12:45** with Dmitry's own OK (`test_a_fresh_backup_restored_and_back`, `--allow-reboot`): a fresh 7 360-byte backup of AP2 restored, AP2 back after 143 s (uptime 119 s). The proof then flagged `/etc/uci-defaults/10_disable_services` (`sysupgrade -b` adds it so that disabled services stay disabled; the first boot runs and deletes it) and `/etc/config/firewall` (`uci_apply_defaults` ends in a blanket `uci commit`, which kept the boot staging `network+='lte'`). A false alarm: AP2's effective config equalled its recordings. The proof now skips uci-defaults and proves each config by its settings in `uci show`, other files by sha256. The as-found check differed only by dnsmasq listening on the carrier's new LTE address; it now keeps listeners on any, loopback and the network config's fixed addresses. AP2 was left with the lte item committed and nothing staged; on Dmitry's "Put it back" one item was committed and the boot staging restored uncommitted, without a reload. The HTTPS redirect stays open (AP2 serves no HTTPS) |
| O21 | v0.7 air on AP2: a passive scan and its survey both ways (temporary `owgscan0` on the parked radio, `ap-force` on air), the monitor's `fcsfail` flag and the frame lines' format, whether `owgmon0` survives a Wi-Fi reload, the step-through on air with a station re-joining, frame analysis on AP2's own BSS (plan D16 HW-1, HW-2) | HW-1 done 2026-11-12 16:52:14-28 on AP2 with Dmitry's OK, Bench Guard clear and txctl told (`tests/hardware/test_ap2_air.py`, radio parked, nothing transmitted; `uci -q show wireless` and `iw dev` read exactly as found, then `test_ap2_at_rest`: no `owgscan0`/`owgmon0`, radio0 disabled, IL, `legacy_rates 1`, `cell_density 0`, `uci changes` only the boot firewall staging, `/tmp/owg` absent). The passive scan works on the parked phy through the temporary managed `owgscan0`: exit 0 in 1.65 s, 33 BSSes on channels 1, 2, 4, 6, 8, 10 and 11. The survey (phy-wide counters, 13 channels) grew by about 115 ms of active time per channel during the scan (219 ms on channel 1) and 8-93 ms of busy time, so the busy share per channel reads 7-79 %. `iw dev owgmon0 set monitor fcsfail control otherbss` is accepted (exit 0, no output); in 3 s on channel 6 tcpdump printed 343 frame lines, 132 of them `bad-fcs`, and 0 dropped by the kernel. Frame lines read `HH:MM:SS.us [bad-fcs] <rate> Mb/s <MHz> MHz 11b|11g -NNdBm signal antenna N [Retry] NNus <addresses> <type> [(SSID)]` with no `tsft` field; the addresses come in tcpdump's label orders (`BSSID DA SA` management, `RA`/`TA RA` control); stderr has tcpdump's listening line and its packet counts. A bad-FCS frame's addresses are corrupted and may carry the group bit, so the sanitizer replaces every address in a bad-FCS line but broadcast (air.json re-sanitized offline). AP2's clock read 07:24 at 16:52 local (no time source on the bench LAN). **HW-2 done 2026-11-13 09:32-09:39** on AP2 (`tests/hardware/test_ap2_on_air.py`, `OwgTest` on channel 11 with a key made for the run, the bench phone over adb checked as its owner left it before and after): 4 passed, 1 failed, 1 teardown error. The step-through g then n20 on channel 11: both steps proven, beacons at 6.0 Mb/s, the CSV written; with the phone re-joining: g in 25.0 s, n20 in 8.1 s. **`owgmon0` survives a Wi-Fi reload** (`wifi down radio0; wifi up radio0`); `MonitorLeases.ensure` handles both cases. The `ap-force` scan on air heard 58 BSSes in 1.7 s but not AP2's own: a radio does not receive its own beacons, so `own` marks only what another radio of the same router hears; the test now records it instead of requiring it. Frame analysis on AP2's own BSS with the phone pinging (17.1 ms average): 3 windows, 866 frames received (6 and 24 Mb/s, MCS 12-15) and 508 sent; `rc_stats` in O6. After the owgmon0 test, the restore's reload left the AP interface up for more than 20 s (the next test's fixture parked it); the park now prints netifd's radio0 state and reloads once more. AP2 and the phone ended as found, read by hand. The owgmon0 and scan tests are re-run only in a later window with a new OK |

## 14. Out of scope

- Running or orchestrating board tests (relays, flashing, serial). The harness keeps that.
- Remote or multi-user access; the app is bound to localhost.
- Managing routers that are not OpenWrt.
- Building router firmware. The app imports images; it does not build them.
