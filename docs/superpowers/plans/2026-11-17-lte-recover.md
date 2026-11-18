# LTE Recover, Saved Good Setups and Modem Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** The LTE screen gets a one-button Recover job, saved good setups with Reconfigure, a "no packet-data
handle" status, and a specific AT-console warning, so a person can bring a bench router's LTE back without SSH.

**Architecture:**
- **Recover** is a per-router background job (`lte/recover.py`, modelled on `StepService`). It runs a ladder of
  rungs through `LteService`'s audited commands and checks "LTE works" (`lte/state.py`) after each rung. The UI
  polls it.
- **Saved setups** are JSON files in a new data folder (`lte/setups.py`). Reconfigure turns a setup into one
  `LteSettings` change through the existing settings path with rollback.
- **The simulator's modem** learns to be wedged and to have stale QMI state, so the whole thing is tested
  without a router.

**Tech Stack:** Python 3.13, FastAPI, pydantic, asyncio, pytest; React + TypeScript, TanStack Query, Vitest,
Playwright.

**Spec:** `docs/superpowers/specs/2026-11-17-lte-recover-design.md` (approved by Dmitry, 2026-11-17: "Approve,
write plan"). Read it first; section numbers below are its own.

**Base:** branch `feat/lte-recover` from master c3b94c2, worktree `.claude/worktrees/lte-recover`, local. If PR #81
(1.1a) has merged by the time execution starts, rebase onto master first. 1.1a changes `remove_router` (its D4
busy check) and the AT console's copied constants (#29, a contract test): Tasks 4, 6 and 10 then build on its
versions.

## Global Constraints

- **Test first** (AGENTS.md): every change starts with a test that fails before it.
- **Never sent:** QMI `--set-device-operating-mode reset`, `--reset-wds`, `--set-autoconnect` with any value but
  `disabled`, `AT&F`, `AT&W` or `AT+CFUN` (spec section 2, anti-goals). `commands.set_opmode` keeps refusing
  every mode but `low_power` and `online`; `commands.autoconnect_off` takes no value.
- **uqmi:** every command is built through `commands.uqmi()`.
- **Writes:** use `run_audited` (`guard/writes.py`) or `ApplyRunner`, under `pool.write_lock`, refused during a
  harness run. The only exception is the put-back of 4.2: `online` after `low_power`, and `ifup lte` after
  `ifdown lte`. They are sent with `require_guard=False` and audited with screen `"LTE (put back during a harness
  run)"`.
- **Reads:** background reads use `t.run`, and every new read passes `is_read_only_command`. Recorded AP2 commands
  replay by exact string, so no existing command text changes.
- **Secrets:** `password` and `pincode` are never in an API model, a preview line (masked by `net_plan`), a log
  line or the audit log (masked by `secrets=`). Keep them out of `repr` (`Field(repr=False)`).
- **"LTE works"** (4.1) means `up is True`, `data_handle is True` and `ipv4` set. An invalid handle is
  `0xffffffff` (any case) or `4294967295`.
- **The UI words** are the spec's (4.2, 4.3, 4.5) where the spec quotes them.
- **Public repo:** no real APN credentials, PINs, IMEIs or names in fixtures, tests or docs. Use `test-apn`,
  `secret-pw` and `1234`.
- **No router access** except Task 13, which needs Dmitry's OK at the time. AP2 only, never AP1 or AP3. Agents
  never type router passwords.
- **Nothing is pushed** without Dmitry's go. Branches are never deleted.

## Review Focus

1. **A setup file that cannot be read** (hand-edited or cut off). It is listed as unreadable, Reconfigure refuses
   it with its file name, and nothing crashes. Test in Task 4.
2. **Recover pressed twice quickly.** One job starts; the second call gets 409 naming it. Test in Task 6.
3. **An app update while Recover runs.** The update asks first, naming "LTE recovery on <router>", and `stop_all`
   ends the job after putting back what it took down. Test in Task 6.
4. **The router stops answering mid-job** (TransportError). The job ends "failed", naming the command and saying
   the router did not answer. It is never left "running". Test in Task 6.
5. **A setup from a router with an option the target has no row for.** The option is not written, and the preview
   names it. Test in Task 5.

---

### Task 1: The simulator's modem can be wedged and can have stale QMI state

**Files:**
- Modify: `src/openwrtgui/simmodem.py` (the `SimModem` state and its uqmi and ifup handling)
- Modify: `src/openwrtgui/simnet.py` (`_dump`: the lte entry gets `data.pdh_4`)
- Test: `tests/unit/test_simmodem_faults.py` (new)

**Interfaces:**
- Produces:
  - `SimModem.wedged: bool` (default False). While it is set, `ifup lte` sets `connected=True` but the lte status
    has `"data": {"pdh_4": "0xffffffff"}`. A `low_power` then `online` cycle clears it.
  - `SimModem.stale_qmi: bool` (default False). While it is set, `ifup lte` leaves `connected=False`.
    `uqmi ... --sync` clears it.
  - `SimModem` answers `uqmi -s -d /dev/cdc-wdm0 -t 5000 --sync` with exit 0 and empty output.
  - When connected and not wedged, the lte status carries `"data": {"cid_4": "11", "pdh_4": "90215808"}`, the
    shape AP2 recorded.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_wedged_modem_comes_up_without_a_handle`: set `wedged`, run `ifup lte`, read
    `ubus call network.interface.lte status`. Assert `up` is true and `data.pdh_4 == "0xffffffff"`.
  - `test_a_modem_restart_clears_the_wedge`: set `wedged`, then `low_power`, `online`, `ifup lte`. Assert
    `pdh_4 == "90215808"` and `wedged` is false.
  - `test_stale_qmi_blocks_ifup_until_sync`: set `stale_qmi`, `ifup lte`, assert `up` is false; then `--sync` and
    `ifup lte`, assert `up` is true.
  - `test_a_healthy_session_has_the_ap2_handle`: no flags, `ifup lte`. Assert `data == {"cid_4": "11",
    "pdh_4": "90215808"}`.

  Drive them through the fake transport as `tests/unit/api/test_lte_actions.py` does (`await _modem(ctx)`).
- [ ] **Step 2:** Run `uv run pytest tests/unit/test_simmodem_faults.py -q`. Expected: 4 failed.
- [ ] **Step 3:** Implement the two flags, the `--sync` branch and the `data` entry.
- [ ] **Step 4:** Run the new tests and `uv run pytest tests/unit/api/test_lte_actions.py tests/unit/api/test_lte_state.py -q`.
  Expected: all pass. The existing LTE tests do not change.
- [ ] **Step 5:** Commit: `test: the simulated modem can be wedged and hold stale QMI state`.

### Task 2: "LTE works" and the packet-data handle

**Files:**
- Modify: `src/openwrtgui/lte/state.py` (`LteState`, `read_lte`)
- Modify: `frontend/src/screens/lte/StatusCard.tsx`
- Test: `tests/unit/lte/test_lte_health.py` (new); `frontend/src/screens/lte/StatusCard.test.tsx`

**Interfaces:**
- Produces:
  - `LteState.data_handle: bool | None = None` and `LteState.works: bool = False`.
  - `def handle_ok(session: Mapping[str, Any] | None) -> bool | None` in `lte/state.py`: None when the session is
    None or not `up`; True for a `data.pdh_4` that is not invalid; False when it is missing or invalid.
  - `def lte_works(state: LteState) -> bool`: `state.up is True and state.data_handle is True and
    bool(state.ipv4)`. `read_lte` sets `works` with it.
- Consumes: Task 1's simulator handle.

- [ ] **Step 1: Write the failing tests:**
  - `test_handle_ok` parametrized: `{"up": True, "data": {"pdh_4": "90215808"}}` gives True;
    `"0xffffffff"`, `"0xFFFFFFFF"` and `"4294967295"` give False; `{"up": True}` (no data) gives False;
    `{"up": False, ...}` and None give None.
  - `test_works_needs_up_handle_and_address`: True only when all three hold.
  - `test_a_wedged_simulated_modem_reads_as_not_working`: through `GET /api/routers/ap2/lte` with the modem
    wedged and connected. Assert `data_handle is False`, `works is False`, `up is True`.
  - Frontend `StatusCard.test.tsx`: with `data_handle: false` it shows "Session up but no packet-data handle: the
    modem carries no data. Use Recover."; with true or null it does not.
- [ ] **Step 2:** Run `uv run pytest tests/unit/lte/test_lte_health.py -q` and
  `npx vitest run src/screens/lte/StatusCard.test.tsx`. Expected: FAIL (names not defined, text missing).
- [ ] **Step 3:** Implement `handle_ok`, `lte_works`, the two fields, and the StatusCard line. Run
  `uv run python tools/dump_openapi.py` and `npm run gen:api` (frontend) for the new fields.
- [ ] **Step 4:** Run both test files and `uv run pytest tests/unit/api/test_lte_state.py tests/contract -q`.
  Expected: pass. No recorded AP2 command text changes, because the handle is in the status read already made.
- [ ] **Step 5:** Commit: `feat: LTE status says when the session has no packet-data handle`.

### Task 3: `--sync`, and Reboot modem puts the modem back during a harness run

**Files:**
- Modify: `src/openwrtgui/lte/commands.py`
- Modify: `src/openwrtgui/lte/service.py` (`_run_action`, plus a put-back helper)
- Test: `tests/unit/lte/test_lte_commands.py`, `tests/unit/api/test_lte_actions.py`

**Interfaces:**
- Produces:
  - `def sync(device: str) -> str` in `commands.py`. It returns `uqmi(device, "--sync", timeout_ms=5000)`, i.e.
    `"uqmi -s -d /dev/cdc-wdm0 -t 5000 --sync"`.
  - `PUT_BACK_SCREEN = "LTE (put back during a harness run)"` in `lte/service.py`.
  - `async def _put_back(self, rec: RouterRecord, t: Transport, command: str) -> CommandResult` on
    `LteService`. It calls `run_audited(..., screen=PUT_BACK_SCREEN, require_guard=False)`.
  - `HARNESS_STOPPED = "Stopped: a harness run started; the modem was put back online and LTE reconnected."`

- [ ] **Step 1: Write the failing tests:**
  - `test_sync_command_text`: `sync("/dev/cdc-wdm0") == "uqmi -s -d /dev/cdc-wdm0 -t 5000 --sync"`.
    `sync("/dev/x")` raises ValueError.
  - `test_reboot_puts_the_modem_back_when_a_run_starts_after_low_power`: Bench Guard goes live right after the
    `low_power` line is sent (wrap the guard as the guard test at test_lte_actions.py:120 does). Assert:
    - the result's `error == HARNESS_STOPPED`;
    - the sim modem's `opmode == "online"` and it is connected;
    - the audit log holds the `online` and `ifup lte` lines with screen `PUT_BACK_SCREEN`;
    - no line after `ifup lte` was sent.
  - `test_reboot_put_back_failure_names_where_the_modem_was_left`: as above, but the `online` line fails.
    Assert the error names the `online` command and says the modem is in low power.
- [ ] **Step 2:** Run the two test files. Expected: FAIL.
- [ ] **Step 3:** Implement `sync`, `_put_back`, and in `_run_action` catch `GuardLocked` after `low_power` ran.
  Then put back `online` and `ifup lte`, and return `NetApplyResult(..., error=HARNESS_STOPPED)`, or the failure
  text.
- [ ] **Step 4:** Run `uv run pytest tests/unit/lte tests/unit/api/test_lte_actions.py -q`. Expected: pass.
- [ ] **Step 5:** Commit: `fix: Reboot modem puts the modem back online when a harness run starts`.

**Added 2026-11-17 (spec 4.9, Dmitry: "Add a Recover step"), a second commit in this task:**
- Produces:
  - `def autoconnect_off(device: str) -> str` in `commands.py`: `uqmi(device, "--set-autoconnect", "disabled",
    timeout_ms=5000)`, i.e. `"uqmi -s -d /dev/cdc-wdm0 -t 5000 --set-autoconnect disabled"`. It takes no value.
  - `SimModem.autoconnect_on: bool` (default False): while set, `ifup lte` leaves `connected=False`.
    `SimModem.autoconnect_refusals: int` (default 0): that many `--set-autoconnect disabled` calls fail first
    (exit 1, "Request failed"); the next one clears `autoconnect_on` and exits 0.
- Tests:
  - `test_autoconnect_off_command_text`: the text above; `autoconnect_off("/dev/x")` raises ValueError; it is
    not a read.
  - `test_modem_autoconnect_blocks_ifup_until_turned_off` (tests/unit/api/test_simmodem_faults.py), with one
    refusal first.
- Commit: `test: the simulated modem's own autoconnect can hold the bearer`.

### Task 4: Saved good setups: the store, Save, and their life cycle

**Files:**
- Create: `src/openwrtgui/lte/setups.py`
- Modify:
  - `src/openwrtgui/paths.py` (`DataDir.lte_setups_dir = root / "lte-setups"`, created with the others)
  - `src/openwrtgui/net/service.py` (a public read of an interface's raw values)
  - `src/openwrtgui/lte/service.py` (Save)
  - `src/openwrtgui/api/lte_api.py` and a new `src/openwrtgui/api/lte_setups_api.py` (`GET /api/lte-setups`)
  - `src/openwrtgui/context.py`
  - `src/openwrtgui/api/routers_api.py` (Remove deletes the setup)
  - `installer/OpenWrtGUI.iss` (DeleteAppData and its "left behind" message)
- Test: `tests/unit/lte/test_lte_setups.py` (new), `tests/unit/api/test_lte_setups_api.py` (new),
  `tests/unit/test_installer_text.py` (or whichever existing test pins the .iss DelTree list; extend it)

**Interfaces:**
- Produces:
  - In `lte/setups.py`:
    - `class LteSetup(BaseModel)` (frozen): `router_id: str`, `router_name: str`, `saved_at: datetime`,
      `modem: ModemInfo`, `options: dict[str, str] = Field(repr=False)`.
    - `class LteSetupSummary(BaseModel)` (frozen): `router_id`, `router_name`, `saved_at: datetime | None`,
      `apn: str | None`, `pdptype: str | None`, `readable: bool`.
    - `class SetupUnreadable(ValueError)`.
    - `class SetupStore`, constructed as `SetupStore(folder: Path)`, with these methods:
      - `get(router_id) -> LteSetup | None`, which raises `SetupUnreadable(f"{path.name} cannot be read")`;
      - `save(setup: LteSetup) -> None`, using `write_atomic`, after `restrict_to_user` on the folder;
      - `delete(router_id) -> None`;
      - `summaries() -> list[LteSetupSummary]`, where an unreadable file shows with `readable=False` and its
        router id taken from the file name.
  - In `net/service.py`: `async def interface_values(self, router_id: str, name: str) -> tuple[list[OptionRow],
    dict[str, str]]`. It returns the rows `interface_options` gives, plus the raw values of `network.<name>` with
    secrets included. Use `options(uci, "network", name)` on the read `_read` already makes.
  - In `lte/service.py`: `async def save_setup(self, router_id: str, setups: SetupStore) -> LteSetupSummary`.
    - It refuses with `LteNotWorking(ValueError)` unless `lte_works(await self.state(router_id))`.
    - It stores every row that is not control-locked (`row.control` is None) plus `password` and `pincode`, with
      the raw values.
    - It audits one line `"LTE good setup saved"` with `secrets=` set to the password and PIN values.
  - API:
    - `GET /api/lte-setups` returns `list[LteSetupSummary]`.
    - `POST /api/routers/{id}/lte/setup` returns `LteSetupSummary`. A router whose LTE does not work gets 422
      with "LTE does not work on <name> right now; save a good setup while it works".
- Ruling: the spec writes the source router as `{from: ...}`. The API field is named `source`, because `from` is
  a Python keyword. Cost if wrong: one alias.

- [ ] **Step 1: Write the failing tests:**
  - `test_save_then_get_round_trips_without_secrets_in_repr`: `"secret-pw" not in repr(setup)`, and the summary
    has no `options`.
  - `test_an_unreadable_file_is_listed_and_refused` (Review Focus 1): write `{"router_id":` to `ap2.json`.
    `summaries()` has `readable=False`, and `get("ap2")` raises `SetupUnreadable` naming `ap2.json`.
  - `test_save_refuses_when_lte_does_not_work`: the sim modem is wedged, so the API answers 422 with the text
    above.
  - `test_save_stores_the_editable_options_and_the_secrets`: the sim router's lte section has `apn=test-apn`,
    `password=secret-pw` and `pincode=1234`. The saved `options` include those values and leave out the
    control-locked rows.
  - `test_the_audit_line_hides_the_secrets`: the audit record for the save contains neither `secret-pw` nor
    `1234`.
  - `test_removing_a_router_deletes_its_setup`: `DELETE /api/routers/ap2`, then `lte-setups/ap2.json` is gone.
  - Installer: the DeleteAppData DelTree list includes `lte-setups`, and the left-behind message names it.
- [ ] **Step 2:** Run the new tests. Expected: FAIL.
- [ ] **Step 3:** Implement the store, `interface_values`, `save_setup`, the two endpoints, the `DataDir` field,
  the Remove hook and the installer lines. Context: `ctx.lte_setups = SetupStore(data.lte_setups_dir)`.
- [ ] **Step 4:** Run `uv run pytest tests/unit/lte tests/unit/api -q -k "setup or remove"` and the installer
  test. Expected: pass.
- [ ] **Step 5:** Commit: `feat: save a router's working LTE settings as its good setup`.

### Task 5: Reconfigure from a saved setup

**Files:**
- Modify: `src/openwrtgui/lte/setups.py` (building the change), `src/openwrtgui/lte/service.py`,
  `src/openwrtgui/api/lte_api.py`
- Test: `tests/unit/lte/test_lte_reconfigure.py` (new), `tests/unit/api/test_lte_setups_api.py`

**Interfaces:**
- Consumes: Task 4's `SetupStore`, `LteSetup` and `interface_values`.
- Produces:
  - `def setup_change(setup: LteSetup, rows: list[OptionRow], values: Mapping[str, str], *, same_router: bool)
    -> tuple[LteSettings, list[str]]` in `lte/setups.py`. It returns the settings change and the names of saved
    options the target has no row for. Rules:
    - Each named field (`apn`, `auth`, `username`, `password`, `pincode`, `pdptype`, `mtu`, `metric`, `auto`,
      `defaultroute`) goes through `LteSettings`' own field. It is set only when the saved value differs, and
      removed (`""`) when the setup lacks it but the router has it.
    - Every other editable row goes through `edits`, with `OptionEdit("lte", name, value)` to set and
      `OptionEdit("lte", name, None)` to remove.
    - `device` is never in the change.
    - When `same_router` is false, `pincode` is never in the change.
    - Names with no row on the target are skipped and returned.
  - `LteService.plan_setup(router_id: str, source: str, setups: SetupStore) -> NetPlan`. The plan's warnings
    include "Not restored (no such option on <name>): <names>" when the list is not empty.
  - `LteService.apply_setup(router_id: str, source: str, setups: SetupStore, digest: str) -> NetApplyResult`.
  - API:
    - `POST /api/routers/{id}/lte/setup/preview` takes `{"source": "<router id>"}` and returns `NetPlanOut`.
    - `POST /api/routers/{id}/lte/setup/apply` takes `{"source", "digest"}` and returns `NetApplyResultOut`.
    - A missing setup gets 404 "No good setup saved for <id>"; an unreadable one gets 422 with its file name.

- [ ] **Step 1: Write the failing tests:**
  - `test_same_router_restores_only_what_differs`: the router has `apn=other` and the setup has `apn=test-apn`.
    The change sets `apn` only.
  - `test_an_option_the_setup_lacks_is_removed`: the router has `mtu=1500` and the setup has no `mtu`, so the
    change removes `mtu`.
  - `test_another_routers_setup_keeps_the_target_pin`: `same_router=False`, and the setup has `pincode=1234`. The
    change has no `pincode`.
  - `test_device_is_never_changed`.
  - `test_an_option_without_a_row_is_named_not_written` (Review Focus 5).
  - `test_the_preview_masks_the_password`: the plan lines contain `<hidden>` and not `secret-pw`.
  - `test_a_restore_that_matches_changes_nothing`: the preview has no uci lines, only the reload-free "no change"
    plan that `plan_interface` gives for an empty request. Check that shape in `net_plan`, and assert on it.
  - API: preview and apply on the simulator round-trip; apply with a stale digest gets 409 (`PreviewChanged`).
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement `setup_change`, `plan_setup`, `apply_setup` and the two endpoints.
- [ ] **Step 4:** Run `uv run pytest tests/unit/lte tests/unit/api/test_lte_setups_api.py tests/unit/api/test_lte_settings.py -q`.
  Expected: pass.
- [ ] **Step 5:** Commit: `feat: Reconfigure puts a saved good setup back, with rollback`.

### Task 6: The Recover job

**Files:**
- Create: `src/openwrtgui/lte/recover.py`
- Modify:
  - `src/openwrtgui/lte/service.py` (an `extra_busy` check on actions, settings, setups and AT writes)
  - `src/openwrtgui/context.py` (build `LteRecover`; cross-busy both ways)
  - `src/openwrtgui/api/update_api.py` (`_live` and `_stop_live`)
  - `src/openwrtgui/api/routers_api.py` (if #81 merged: Remove's busy list names the recovery)
- Test: `tests/unit/lte/test_lte_recover.py` (new)

**Interfaces:**
- Consumes:
  - Task 2's `lte_works`;
  - Task 3's `sync`, `_put_back` and `HARNESS_STOPPED`;
  - Task 5's `setup_change`;
  - `LteService._cmd`, `_readback`, `_wait_up`, `_address`, `state`, `apply_settings`.

  Make the private ones public, or pass them in, whichever keeps `recover.py` free of `LteService` internals.
  That is the builder's call (spec section 7).
- Produces:
  - `RecoverPhase = Literal["running", "works", "recovered", "not recovered", "stopped", "failed"]`.
  - `RungOutcome = Literal["skipped", "not needed", "works", "not yet", "failed"]`.
  - `RUNGS = ("Put back the saved setup", "Reconnect", "Clear QMI state", "Turn off the modem's autoconnect",
    "Restart the modem")` (spec 4.9 added the fourth). Rung 4 sends `autoconnect_off` up to
    `AUTOCONNECT_TRIES = 10` times, `AUTOCONNECT_GAP_S = 1.0` apart, until one exits 0; each try is audited.
  - `class RungResult(BaseModel)` (frozen): `name: str`, `outcome: RungOutcome`, `detail: str | None`.
  - `class LteRecoverJob(BaseModel)` (frozen): `router_id`, `phase: RecoverPhase`, `diagnosis: list[str]`,
    `rungs: list[RungResult]`, `current: int | None`, `started_at: datetime`, `ended_at: datetime | None`,
    `detail: str | None`, `error: str | None`.
  - `class RecoverPreview` (frozen dataclass): `router_id`, `lines: tuple[str, ...]`, `warnings:
    tuple[str, ...]`, `digest: str`. Lines that run only if needed end with
    `"  # only if LTE does not work after the step before"`.
  - `class LteRecoverBusy(RouterBusy)`.
  - `class LteRecover`, constructed as `LteRecover(*, lte: LteService, setups: SetupStore, routers: RouterStore,
    guard: BenchGuard, busy: Sequence[Callable[[str], str | None]] = (), clock=datetime.now,
    sleep=asyncio.sleep)`. Its methods:
    - `async preview(router_id) -> RecoverPreview`;
    - `async start(router_id, digest) -> LteRecoverJob`;
    - `job(router_id) -> LteRecoverJob | None`;
    - `busy(router_id) -> str | None` (the text "LTE recovery runs on <name>");
    - `live() -> list[str]` (each item "LTE recovery on <name>");
    - `async stop(router_id) -> LteRecoverJob | None`;
    - `async stop_all(limit_s: float) -> None`.
  - **The ladder and its texts are spec section 4.2.** The texts to use:
    - diagnosis items: "not registered", "no session", "session up but no packet-data handle", "no address", and
      "settings differ from the good setup saved <YYYY-MM-DD>: <names>";
    - works: "LTE works; nothing to do.", plus, when the settings differ, "Its settings differ from the good
      setup saved <date>: use Reconfigure to put them back.";
    - recovered: "LTE works again after: <rung name>.";
    - not recovered: "LTE did not come back. Reboot the router (System › Reboot), then power-cycle it if that
      does not help.";
    - Stop: "Stopped; LTE works." or "Stopped; LTE does not work.";
    - a harness run: `HARNESS_STOPPED`;
    - failed: "<command>: <reason>; the modem was left <where>." (where is "online", "in low power" or "with LTE
      down").
  - **Behaviour:**
    - A failed command in rungs 1-4 records the rung as "failed" and goes on to the next rung, after `ifup lte` if
      the rung ran `ifdown lte`. Rung 4 fails only when all 10 tries fail. A failed command in rung 5 ends the
      job "failed".
    - Stop and a harness run put back what the running rung took down (`_put_back` for the harness case), then
      end.
    - A TransportError ends the job "failed", with "<router> did not answer".

- [ ] **Step 1: Write the failing tests.** Use the simulator modem from Task 1; set `ctx` `poll_s`, `readback_s`
  and the job sleep to 0.
  - `test_a_working_modem_ends_at_once_with_nothing_written`: phase "works", and no write in the audit log.
  - `test_works_but_settings_differ_writes_nothing_and_says_so`.
  - `test_a_dropped_session_is_back_after_reconnect`: disconnect first. Phase "recovered", rung 2 "works", and
    rungs 3-5 "not needed".
  - `test_stale_qmi_needs_the_sync_rung`: phase "recovered" at "Clear QMI state". The audit log has
    `ifdown lte`, then `--sync`, then `ifup lte`, in that order.
  - `test_modem_autoconnect_needs_the_autoconnect_rung`: `autoconnect_on` with 2 refusals. Phase "recovered" at
    "Turn off the modem's autoconnect"; the audit log has three `--set-autoconnect disabled` lines between
    `ifdown lte` and `ifup lte`.
  - `test_autoconnect_that_never_takes_goes_on_to_the_restart`: 10 refusals. Rung 4 "failed" naming the
    command; rung 5 runs.
  - `test_a_wedged_modem_needs_the_restart_rung`: phase "recovered" at "Restart the modem".
  - `test_a_failing_sync_goes_on_to_the_next_rung` (the sim `--sync` fails once).
  - `test_differing_settings_are_put_back_first`: rung 1 "works", and the apn is restored with rollback and
    confirm.
  - `test_nothing_helps_ends_not_recovered_with_the_reboot_advice`: the modem stays low power.
  - `test_stop_finishes_the_put_back`: stop while rung 5 is between `low_power` and `online`. Phase "stopped",
    and the modem is online.
  - `test_a_harness_run_mid_rung_puts_back_and_stops`: phase "stopped", detail `HARNESS_STOPPED`, and the
    put-back lines are audited with `PUT_BACK_SCREEN`.
  - `test_two_starts_one_job` (Review Focus 2): two concurrent `start` calls give one job and one
    `LteRecoverBusy`.
  - `test_an_update_asks_and_stops_the_job` (Review Focus 3): `POST /api/update/install` without force gets 409
    with "LTE recovery on AP2 · office" in `live`, and `stop_all` ends it "stopped".
  - `test_an_unreachable_router_fails_the_job` (Review Focus 4).
  - `test_other_writes_are_refused_while_it_runs`: Connect, settings apply and a non-query AT command get 409
    naming the job.
  - `test_a_step_through_blocks_recover_and_recover_blocks_a_step_through`.
  - `test_never_sends_reset_or_risky_at`: across all the tests above, no audit line contains `mode reset`,
    `--reset-wds`, `--set-autoconnect enabled`, `--set-autoconnect paused`, `AT&F`, `AT&W` or `AT+CFUN`.
- [ ] **Step 2:** Run `uv run pytest tests/unit/lte/test_lte_recover.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement `lte/recover.py` and the wiring:
  - `ctx.lte_recover`;
  - `LteService.extra_busy`;
  - steps, system and flash cross-busy;
  - update `_live` and `_stop_live`;
  - Remove's list.
- [ ] **Step 4:** Run `uv run pytest tests/unit -q -k "lte or step or flash or reboot or update or remove"`.
  Expected: pass.
- [ ] **Step 5:** Commit: `feat: Recover, an LTE recovery job that stops when LTE works`.

### Task 7: The Recover API

**Files:**
- Modify: `src/openwrtgui/api/lte_api.py`; regenerate `frontend/src/api/schema.ts`
- Test: `tests/unit/api/test_lte_recover_api.py` (new)

**Interfaces:**
- Consumes: Task 6's `LteRecover`, `LteRecoverJob` and `RecoverPreview`.
- Produces, under `/api/routers/{id}/lte`:
  - `POST /recover/preview` returns `{lines, warnings, digest}`;
  - `POST /recover` takes `{"digest"}` and returns `LteRecoverJob`. It answers 409 when busy or the digest is
    stale, and 423 when the guard is live;
  - `GET /recover` returns `LteRecoverJob | null`;
  - `POST /recover/stop` returns `LteRecoverJob | null`.

- [ ] **Step 1: Write the failing tests:** the four endpoints round-trip on the simulator, plus the 409, 423 and
  stale-digest answers.
- [ ] **Step 2:** Run them. Expected: FAIL (404s).
- [ ] **Step 3:** Implement the routes. Then run `uv run python tools/dump_openapi.py` and, in `frontend`,
  `npm run gen:api`.
- [ ] **Step 4:** Run the tests and `git diff --stat frontend/src/api/schema.ts`. Expected: pass, and
  schema.ts gains the Recover types.
- [ ] **Step 5:** Commit: `feat: the Recover endpoints`.

### Task 8: Recover on the LTE screen

**Files:**
- Create: `frontend/src/screens/lte/useLteRecover.ts`, `frontend/src/screens/lte/RecoverPanel.tsx`
- Modify: `frontend/src/screens/lte/ActionsCard.tsx`
- Test: `frontend/src/screens/lte/RecoverPanel.test.tsx` (new), `frontend/src/screens/lte/ActionsCard.test.tsx`

**Interfaces:**
- Consumes: Task 7's endpoints and types.
- Produces:
  - `useLteRecover(routerId: string)`, using query key `['lte-recover', routerId]`. It refetches every 2000 ms
    while `phase === 'running'`, as `wifi/useStepJob.ts` does.
  - `RecoverPanel({ routerId, job })`.

- [ ] **Step 1: Write the failing tests:**
  - **ActionsCard:** a **Recover** button. A click shows the preview lines, including a line ending "# only if LTE
    does not work after the step before", and a Start button.
  - **RecoverPanel:**
    - it lists the diagnosis and the five rungs with their outcomes;
    - it shows **Stop** while running;
    - a "not recovered" end shows a **Reboot router** link to the router's System screen, and the power-cycle
      line;
    - a "works" end shows "LTE works; nothing to do.".
- [ ] **Step 2:** Run `npx vitest run src/screens/lte`. Expected: FAIL.
- [ ] **Step 3:** Implement the hook, the panel, and the button in ActionsCard. Grey Recover while another LTE
  action or a job runs, with the busy text as its title.
- [ ] **Step 4:** Run `npx vitest run src/screens/lte`, `npx tsc -b` and `npm run lint`. Expected: pass, 0 errors.
- [ ] **Step 5:** Commit: `feat: Recover on the LTE screen, with live progress`.

### Task 9: Save good setup and Reconfigure on the Settings card

**Files:**
- Modify: `frontend/src/screens/lte/SettingsCard.tsx`
- Test: `frontend/src/screens/lte/SettingsCard.test.tsx`

**Interfaces:**
- Consumes:
  - Task 4's `GET /api/lte-setups` and `POST .../lte/setup`;
  - Task 5's `.../setup/preview` and `.../setup/apply`;
  - Task 2's `LteState.works`.

- [ ] **Step 1: Write the failing tests:**
  - **Save good setup:**
    - it is disabled with the title "Save a good setup while LTE works" when `works` is false;
    - when `works` is true, a click posts the save;
    - when a setup exists, it first asks "Replace the good setup saved <YYYY-MM-DD>?".
  - **Reconfigure:**
    - a source choice lists this router's setup first, then the other routers' setups by name and date;
    - an unreadable one shows as "(cannot be read)" and cannot be chosen;
    - choosing one shows the settings preview through `NetChange`, and Apply posts the digest.
- [ ] **Step 2:** Run `npx vitest run src/screens/lte/SettingsCard.test.tsx`. Expected: FAIL.
- [ ] **Step 3:** Implement both, with `usePlanApply` as the card's settings change does today.
- [ ] **Step 4:** Run the lte vitest files, `npx tsc -b` and `npm run lint`. Expected: pass.
- [ ] **Step 5:** Commit: `feat: Save good setup and Reconfigure on the LTE settings card`.

### Task 10: The AT console warns before risky commands

**Files:**
- Modify: `src/openwrtgui/lte/at.py`, `src/openwrtgui/lte/service.py` (`AtNeedsConfirm` carries `risky`),
  `src/openwrtgui/api/lte_api.py` (the 428 body), `frontend/src/screens/lte/AtConsole.tsx`
- Test: `tests/unit/lte/test_lte_at.py`, `tests/unit/api/test_lte_at_console.py`,
  `frontend/src/screens/lte/AtConsole.test.tsx`

**Interfaces:**
- Produces:
  - `def is_risky(text: str) -> bool` in `lte/at.py`.
  - The 428 body is `{"detail": ..., "risky": bool}`.
  - `RISKY_QUESTION = "This command can erase the modem's saved profiles or leave it unusable until the router is
    power-cycled. Use Recover instead. Send it anyway?"` in AtConsole.tsx.

- [ ] **Step 1: Write the failing tests:**
  - `is_risky` parametrized:
    - true for `AT&F`, `at&f0`, `AT&W`, `AT+CFUN=1,1`, `AT+CFUN = 0` and ` at+cfun=4 `;
    - false for `AT+CFUN?`, `AT+CFUN=?`, `AT+CSQ`, `ATI` and `AT+COPS=0`.
  - API: `POST /lte/at {"command": "AT&F"}` without `confirmed` gets 428 with `risky: true`;
    `{"command": "AT+COPS=0"}` gets 428 with `risky: false`.
  - **AtConsole:**
    - a non-query is sent without `confirmed` first;
    - on a 428 with `risky: true`, `window.confirm` is called with `RISKY_QUESTION`; with `risky: false`, with
      "This command may change the modem. Send it?";
    - on OK it is sent again with `confirmed: true`;
    - a query is sent once, with no question.
- [ ] **Step 2:** Run the three test files. Expected: FAIL.
- [ ] **Step 3:** Implement. If 1.1a's contract test (#29) pins the console's copy of the query pattern, keep it
  in step. The console now uses the server's 428 rather than its own copy for the question.
- [ ] **Step 4:** Run them plus `uv run pytest tests/contract -q`. Expected: pass.
- [ ] **Step 5:** Commit: `feat: the AT console warns before commands that can wipe or wedge the modem`.

### Task 11: The manual, the CHANGELOG and the browser test

**Files:**
- Modify:
  - `docs/manual/LTE-modem.md`: a new "Recovering the modem" section; Recover; Save good setup and Reconfigure
    under Settings; the status line; the AT warning under AT console. Replace the reset-to-defaults line with
    what the stock firmware's "Restore modem defaults" does (it turns the modem's autoconnect off) and that
    Recover's fourth step does the same. The Actions card's reset-to-defaults note changes to match.
  - `docs/manual/Files-and-data.md`: a `lte-setups\` row ("the APN password and SIM PIN of each router's good
    setup"), and the uninstall text.
  - `docs/manual/Troubleshooting.md`: "LTE does not connect" points to Recover.
  - `CHANGELOG.md`, under `[Unreleased]`: Added (Recover, saved setups and Reconfigure, the handle status, the AT
    warning) and Fixed (Reboot modem's put-back during a harness run).
  - `frontend/e2e/lte.spec.ts`.
- Test: `tests/unit/test_docs.py` (extend), `frontend/e2e/lte.spec.ts`

- [ ] **Step 1: Write the failing tests:**
  - `test_docs`: LTE-modem.md has a "## Recovering the modem" heading that names the five rungs. Files-and-data
    names `lte-setups`.
  - e2e "Recover on a working modem says nothing to do": open AP2's LTE screen, Recover, Start, then see
    "LTE works; nothing to do.".
  - e2e "Save good setup, then Reconfigure from it changes nothing".
- [ ] **Step 2:** Run `uv run pytest tests/unit/test_docs.py -q` and
  `npx playwright test e2e/lte.spec.ts --project=desktop-light`. Expected: FAIL.
- [ ] **Step 3:** Write the docs, the CHANGELOG lines and the two browser tests.
- [ ] **Step 4:** Run them again. Expected: pass.
- [ ] **Step 5:** Commit: `docs: recovering the LTE modem, saved setups, the AT warning`.

Ruling: the spec (4.6) allows the e2e simulator to start a router wedged through an environment variable. The
wedged and stale-QMI ladders are covered by the API tests on the simulator's modem (Task 6), so no new Playwright
project is added. Cost if wrong: one environment variable and one browser test.

### Task 12: The gate, a fresh review, the hand-over

- [ ] **Step 1:** Full gate:
  - `uv run ruff check src tests tools packaging/make_icon.py` and `uv run ruff format --check` on the same;
  - `uv run mypy`;
  - `uv run pytest --cov=openwrtgui --cov-fail-under=80`;
  - `uv run python tools/dump_openapi.py`, then `npm run gen:api` with no schema.ts diff;
  - `npm run lint`, `npx tsc -b`, `npm test`, `npm run build`;
  - `npm run e2e`, with no other Playwright run going.

  Expected: all green.
- [ ] **Step 2:** A key and name scan of `origin/master..HEAD` (no keys, PINs, IMEIs, real SSIDs or MACs).
- [ ] **Step 3:** A fresh whole-branch reviewer on the most capable model, given the spec, this plan and the
  ledger. Then one fix pass, test first, and the gate again.
- [ ] **Step 4:** Hand-over `lte-recover-done.md` in the parent's `.claude/notes`: commits, gate counts, rulings,
  deferred minors. Nothing is pushed until Dmitry's go.

### Task 13: The AP2 proof (only with Dmitry's OK at the time)

Spec 4.8. Before it starts: Dmitry's own OK in the orchestrator, Bench Guard clear, and the txctl session told.

- [ ] **Step 1:** Record `ifdown lte`, `uqmi -s -d /dev/cdc-wdm0 -t 5000 --sync` and `ifup lte` on AP2. Record
  the lte status with its `pdh_4` into the AP2 LTE fixtures, the way the existing AP2 LTE recording writes them.
  Real APN credentials and IMEIs are replaced as the recorder does.
- [ ] **Step 2:** Recover on the working modem gives "LTE works; nothing to do.".
- [ ] **Step 3:** Disconnect, then Recover, gives "recovered" at "Reconnect".
- [ ] **Step 4:** Run rungs 3, 4 and 5 once each, through a test hook or by forcing the earlier rungs to not
  settle. Each must end with LTE working. If `--sync` or `--set-autoconnect disabled` answers differently from
  the simulator (for example a QMI error printed with exit 0), fix the simulator test first and record a
  ruling.
- [ ] **Step 5:** Save good setup on AP2, then Reconfigure from it gives no change.
- [ ] **Step 6:** Commit the fixtures and results: `test: LTE recover proven on AP2`.

Nothing in the window breaks the modem on purpose: no `AT&F`, no QMI reset. If the modem ends in any state but
working, stop and tell Dmitry.
