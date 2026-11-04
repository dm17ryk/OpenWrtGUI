# Contributing to OpenWrtGUI

Thanks for helping. Bug reports, router support requests and pull requests are all welcome. Please
use the issue forms; for questions, use Discussions.

## Development setup

You need [uv](https://docs.astral.sh/uv/), Node.js 24 and Git. Windows is the target platform; the
backend and the tests also run on Linux.

```bash
uv python install 3.13
uv sync --extra dev
cd frontend
npm ci
npm run build
```

Run the app against the built-in router simulator (no hardware needed):

```bash
uv run python -m openwrtgui --simulator tests/fixtures/sim --data-dir build/dev-data
```

For UI work, start the backend with `--port 8765 --token dev --no-window` added, run `npm run dev` in
`frontend/`, and open `http://localhost:5173/#token=dev`. Vite serves the UI with hot reload and proxies
`/api` to the backend.

**On the Essence bench PC**, keep the checkout and every script you run inside `C:\Essence_SC\` or
`D:\Essence_SC\`. SentinelOne silently stops programs started from anywhere else.

## Layout

| Path | What lives there |
|---|---|
| `src/openwrtgui/` | Backend: FastAPI app, SSH transport, probes, Bench Guard, updater |
| `frontend/` | React + TypeScript UI (Vite), unit tests (Vitest), e2e tests (Playwright) |
| `tests/` | Backend unit and contract tests; `tests/fixtures/` holds recorded router output and the simulator data |
| `tests/hardware/` | Opt-in tests against a real router |
| `packaging/`, `installer/`, `tools/` | PyInstaller spec, Inno Setup script, build and release helpers |
| `docs/manual/` | The user manual, published to the wiki |

## Tests

| What | Command |
|---|---|
| Backend lint, types, unit and contract tests | `uv run ruff check src tests tools` · `uv run ruff format --check src tests tools` · `uv run mypy` · `uv run pytest` |
| Frontend lint, types and unit tests | `cd frontend` · `npm run lint` · `npx tsc -b` · `npm test` |
| End-to-end, light and dark, 1440 and 375 px | `cd frontend` · `npm run build` · `npm run e2e` |
| Windows build with self-check | `pwsh -File tools/build_windows.ps1` |
| Hardware (opt-in) | `uv run pytest -m hardware --router 192.168.1.2 --identity <your key>` |

New behaviour comes with a test that failed first. CI runs everything except the hardware tests and
requires 80 % backend coverage. When the API changes, regenerate the UI types with
`uv run python tools/dump_openapi.py` and `npm run gen:api`; CI fails if they drift.

## Hardware tests: rules for the Essence bench

The bench routers carry other people's tests. These rules are not optional:

- **AP2 (192.168.1.2) only.** Never touch AP1 (192.168.1.1, the live bench router) or AP3 (192.168.1.3).
  The hardware tests refuse any other address unless you pass `--allow-other`.
- **Bench Guard must be clear.** The tests skip themselves while a harness run is live. Do not work around that.
- **Read-only by default.** Anything that reloads Wi-Fi or the network on AP2 (for example `wifi reload`,
  `/etc/init.d/network restart`, a uci commit that triggers either) needs a heads-up to the txctl session
  first.
- Leave AP2's lab options (`country`, `legacy_rates`, `cell_density`) as they are.
- Installing the app key on AP2 is fine: it adds one line to `authorized_keys` and restarts nothing.

## Commits and pull requests

- [Conventional commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `refactor:`, `docs:`,
  `test:`, `chore:`, `perf:`, `ci:`, `build:`.
- One topic per pull request. Fill in the template's checklist: tests, screenshots for UI changes (light
  and dark), docs and `CHANGELOG.md` under `[Unreleased]`.
- By contributing you agree that your contribution is licensed under GPL-3.0.

## Versions and releases

`BASE_VERSION` in `src/openwrtgui/version.py` is the version being worked on. Every green build of
`master` is published as the pre-release `BASE_VERSION-ci.N`, and pushing the tag `vBASE_VERSION`
publishes the stable release.

1. Give the `[Unreleased]` section of `CHANGELOG.md` its version and date, merge that, then tag the merge
   commit `vX.Y.Z` and push the tag.
2. Right after a release, move to the next version so CI builds sort above it: set `BASE_VERSION` and
   `APP_VERSION` (`X.Y.Z-dev`) in `version.py`, the `version` in `pyproject.toml` and the two defaults at
   the top of `installer/OpenWrtGUI.iss`; run `uv lock`, and in `frontend` run
   `npm version X.Y.Z --no-git-tag-version`. `tests/unit/test_version.py` fails if one of them is missed.
