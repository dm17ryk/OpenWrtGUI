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
| `frontend/src/` | React screens (`screens/`), shell (`shell/`), API client and generated types (`api/`) |
| `tests/` | `unit/`, `contract/` (recorded AP2 output replayed), `hardware/` (opt-in), `fixtures/` |

## Commands

```bash
uv sync --extra dev                       # backend deps
uv run ruff check src tests tools && uv run ruff format --check src tests tools
uv run mypy
uv run pytest                             # unit + contract; hardware tests are deselected
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
- While Bench Guard reports a live run (`dima_night`, `rh_soak`, `overnight_wifi`, `txlab_*`,
  `voip_chain`, lock files, run SSIDs), every router is read-only. Do not work around it.
- Agents **never type router passwords**. Where a password is needed, the owner types it.
- **Nothing is pushed** to GitHub, and no issues, labels, milestones, releases or wiki pages are created,
  without the owner's explicit go in the conversation.
- On the bench PC, run every script from inside `C:\Essence_SC\` or `D:\Essence_SC\` (SentinelOne stops
  anything started elsewhere, silently). Keep needed files out of temp folders.
