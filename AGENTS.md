# AGENTS.md

Instructions for AI coding agents (Claude Code, Codex and others) working in this repository.
Humans: see [CONTRIBUTING.md](CONTRIBUTING.md); the rules below apply to you too.

## What this is

OpenWrtGUI is a Windows desktop app for operating the OpenWrt routers of a Wi-Fi test bench. A Python
backend (FastAPI on `127.0.0.1`, asyncssh) talks to the routers; a React UI runs in a WebView2 window.
The design spec is `docs/superpowers/specs/2026-11-03-openwrt-gui-design.md`; implementation plans are
in `docs/superpowers/plans/`.

## Layout

| Path | Contents |
|---|---|
| `src/openwrtgui/transport/` | `Transport` protocol, `SshTransport` with pinned host keys, `ReplayTransport` (simulator), connection pool |
| `src/openwrtgui/probe/` | Read-only probes: exact command strings, board/ubus/identity parsers, self-description, live status |
| `src/openwrtgui/guard/` | Bench Guard, the read-only command check, `perform_write`, the audit log |
| `src/openwrtgui/onboard/` | Add-router wizard (host key → login → key install → identify → port map) |
| `src/openwrtgui/update/` | GitHub Releases check, download, SHA-256 check, silent installer launch |
| `src/openwrtgui/api/` | FastAPI routers and pydantic API models |
| `src/openwrtgui/store/` | Persisted data: routers, settings, the app key |
| `src/openwrtgui/fw/` | Firewall: fw4 config and `nft -j` / `nft -a` parsers, the filtering model and pins, zones and sections compiled to uci ops, other nft tables and custom rule files (router-side timer rollback), owners |
| `src/openwrtgui/faults/` | Fault targets, the `benchfault` chains, netem, port and hostapd faults, records in `/tmp/owg`, held faults cleared by the router's timer |
| `src/openwrtgui/capture/` | `tcpdump -w -` over a binary SSH channel to a `.pcap` or Wireshark, the app's own SSH filtered out |
| `src/openwrtgui/images/` | Sysupgrade images read on this PC (uImage, squashfs via PySquashfsImage, fwtool metadata), apk/opkg databases, profiles; kept in `<data>/profiles/<board>/<revision>-<sha12>/` (`profile.json`, and `image.bin` for an imported image) |
| `src/openwrtgui/discovery/` | Overlay, package and config diffs against the image, capabilities, copies, reflash checklists (`<data>/reflash/<router>-<stamp>.json`), promoted tool cards (`<data>/tools/<board>.json`), custom services |
| `src/openwrtgui/flash/` | Flash plan (board, hash, RAM and isolation checks), upload to `/tmp/owg`, router-side timer for `sysupgrade`, come-back and revision proof |
| `frontend/src/` | React screens (`screens/`), shell (`shell/`), API client and generated types (`api/`) |
| `tests/` | `unit/`, `contract/` (recorded AP2 output replayed), `hardware/` (opt-in), `fixtures/` |

## Commands

```bash
uv sync --extra dev                       # backend deps
uv run ruff check src tests tools && uv run ruff format --check src tests tools
uv run mypy
uv run pytest                             # unit + contract; hardware tests are deselected
uv run pytest tests/hardware -m hardware --router 192.168.1.2 --identity <key>   # AP2 only: reads (+ LuCI rpcd sessions)
uv run pytest -m hardware tests/hardware/test_ap2_wifi.py --router 192.168.1.2 --identity <key> \
    --allow-writes --txctl-told           # radio on air and restored: only in a window the txctl session agreed to
OWG_TEST_IMAGE=<bench .bin> uv run pytest -m hardware tests/hardware/test_ap2_images.py --router 192.168.1.2 \
    --identity <key> --allow-writes --txctl-told -s   # upload + validate in /tmp/owg; add --allow-flash to flash AP2
# Hardware tests and tools/record_fixtures.py, tools/luci_spike.py trust only --known-hosts
# (default ~/.ssh/known_hosts): AP2's host key must be there already; nothing pins a key on its own.
cd frontend && npm ci && npm run lint && npx tsc -b && npm test
npm run build && npm run e2e              # Playwright against the simulator
uv run python tools/dump_openapi.py && npm run gen:api   # after any API change
pwsh -File tools/build_windows.ps1        # PyInstaller build + self-check (version BASE_VERSION-dev)
```

## Conventions

- Test first. A change without a test that failed before it is not done.
- Domain values are frozen dataclasses; persisted and API data are pydantic models.
- Talk to routers **ubus first** (`ubus call …`, as LuCI does); fall back to files and CLI tools only
  where LuCI does too. Command strings live in `probe/commands.py` and are replayed by contract tests.
- **Every write goes through `perform_write`**: it checks Bench Guard, takes the per-router write lock and
  writes the masked audit entry. Never send a changing command any other way.
- Reads must pass `is_read_only_command` when they come from a user (terminal during a run).
- Never auto-accept an SSH host key.
- Keep the UI working at 375 px and in both themes; e2e checks for horizontal scroll.
- In-app help comes from the manual: `frontend/src/help/topics.ts` maps each `?` and button tooltip to a
  `docs/manual` section (`Page#anchor`, as the wiki names it). Renaming a manual heading means updating
  that file; `manual.test.ts` fails otherwise. New screens get help the same way.

## Safety rules (the bench is shared and runs long tests)

- **AP2 (192.168.1.2) is the only router you may touch.** Never connect to AP1 (192.168.1.1) or AP3
  (192.168.1.3), not even read-only.
- **Read-only unless the owner told you otherwise** in this session. Installing the app key on AP2 is
  allowed (one `authorized_keys` line, nothing restarts).
- **Tell the txctl session before any Wi-Fi or network reload on AP2** (`wifi`, `wifi reload`, network
  restart, a uci commit that triggers either). Do not change AP2's `country`, `legacy_rates` or `cell_density`.
- **A network change on AP2** (its address, a VLAN, a route, a port) runs only in a window the owner
  approved in this session and the txctl session agreed to, never while a harness run is live, and always
  with the 60 s rollback. AP2 ends as found: lan `192.168.1.2/24`, radio parked, its DHCP server off (AP1
  is the only DHCP server), every port on.
- **A firewall change or a fault on AP2** (a zone, a rule, an nft table, a custom rule file, an armed fault,
  anything in `/tmp/owg`) runs only in a window the owner approved in this session and the txctl session
  agreed to (an fw4 reload counts as a network reload), never while a harness run is live, and with the 60 s
  rollback or the router-side timer. AP2 ends as found: `uci -X show firewall` and `nft list tables` as
  before, `tc qdisc show` as before, `/tmp/owg` gone, every port on. Wi-Fi faults wait for a radio window.
- **An image upload or a flash on AP2** is a write window: only with the owner's OK in this session, the txctl
  session told and its run over, Bench Guard clear. An upload and validate writes only `/tmp/owg` (RAM) and
  ends with it removed; a flash keeps settings, AP2 ends on the image it started on (flash it back) with the
  checks above as before. Never flash without keeping settings on the bench: that is tested in the simulator
  only (AP2 would come back as 192.168.1.1, clashing with AP1).
- **An LTE action on AP2** (connect, disconnect, reboot modem, an LTE settings change, an AT command that is
  not a query) is a write window: only with the owner's OK in this session, the txctl session told (AP2's LTE
  session drops), Bench Guard clear. Never set the modem's operating mode to `reset` (it wedges the BM806C
  until a power cycle). AP2 ends as found: `uci show network` as before and lte up as before. Never type a
  SIM PIN or an APN password, and never write the IMEI to a log, a file or the audit log. AT queries and the
  LTE screen's reads are reads.
- **A System write on AP2** (host name, time zone, NTP or log settings, a service action, an `rc.local` or
  crontab edit, a diagnostic) is a write window: only with the owner's OK in this session, the txctl session
  told (a network, firewall, wpad or dnsmasq restart reloads AP2's network), Bench Guard clear. **A reboot**
  needs its own OK. AP2 ends as found: `uci -X show system`, `/etc/rc.local`, `/etc/crontabs/root` (or its
  absence) and every service's enabled and running state as before. The System screen's reads are reads. A
  backup is a read too, but the archive holds secrets (password hash, host keys, the app's key line, Wi-Fi
  keys): never put one in a fixture, a log, the audit log or a commit, and remove a test backup afterwards.
- **An Access, LED or kept-files write on AP2** (an SSH instance or port, an SSH key, the HTTP(S) switches, an
  LED action, the password policy, `/etc/sysupgrade.conf`) is a write window: only with the owner's OK in this
  session, Bench Guard clear. SSH and HTTP(S) changes reload dropbear and uhttpd, so the txctl session is told
  first. AP2 ends as found: `uci -X show dropbear`, `uhttpd`, `system` and `rpcd`, `authorized_keys` and
  `/etc/sysupgrade.conf` as before. A key added on AP2 is a throwaway made for the test, never a real one, and
  a recording never keeps a real public key or a person's name (the repository is public). **The root
  password** is changed only as the plan's D3 test does it (`--allow-password`, the shadow copy and its
  restore timer), with its own OK. **A restore** reboots AP2 and needs its own OK, like a reboot. **Reset to
  defaults never runs on AP2**: it is tested in the simulator only (AP2 would come back as 192.168.1.1).
- While Bench Guard reports a live run (`dima_night`, `rh_soak`, `overnight_wifi`, `txlab_*`,
  `voip_chain`, `mem04_bench`, lock files, run SSIDs), every router is read-only. Do not work around it.
- Agents **never type router passwords**. Where a password is needed, the owner types it.
- **Nothing is pushed** to GitHub, and no issues, labels, milestones, releases or wiki pages are created,
  without the owner's explicit go in the conversation.
- On the bench PC, run every script from inside `C:\Essence_SC\` or `D:\Essence_SC\` (SentinelOne stops
  anything started elsewhere, silently). Keep needed files out of temp folders.
