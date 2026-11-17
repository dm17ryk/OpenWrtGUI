# LTE recover, saved good setups and modem safety: design

Written 2026-11-17 from Dmitry's answers in the orchestrator session. Base: master c3b94c2 (1.1.0-dev),
branch `feat/lte-recover`, worktree `.claude/worktrees/lte-recover`.

Sources:
- Dmitry's BM806C notes, saved as `.claude/notes/lte-modem-recovery.md` in the repo folder (not committed).
  They come from the OpenWrt-port analysis and are not yet proven on AP2 by this project.
- The code as it is at c3b94c2 (the map below).

## 1. Intent

The bench routers' LTE modem (BroadMobi BM806C, QMI) sometimes stops carrying data after experiments. Once, on
the stock firmware, only the stock "restore modem defaults" action brought it back. Today the app can connect,
disconnect and restart the modem, but recovering means knowing the right order and often SSH.

Dmitry's words: "we need to add LTE restart/reconfig/recover options to app". His choices:
1. **One Recover button.** The app finds what is wrong, then steps up, checking after each step whether LTE
   works. It stops as soon as LTE works.
2. **Reconfigure = a saved good setup.** You save a working router's LTE settings once; Reconfigure puts that
   copy back.
3. **Another router's setup may be used, without its PIN.** Each bench router has its own SIM.
4. **Recover is a background job with live progress**, like Flash, router Reboot and the Wi-Fi step-through.

Success: a person at the bench whose router's LTE stopped working presses Recover. Either LTE works again
within a few minutes, or the app says plainly what it tried, where the modem was left, and what is left to do:
Reboot router (asked first), then a power cycle.

## 2. Goals, non-goals, anti-goals

Goals:
- **G1 Recover:** a per-router background job running the ladder in section 4, with live progress on the LTE
  screen.
- **G2 Saved good setups:** Save good setup, and Reconfigure from this router's setup or another router's,
  without the PIN.
- **G3 "No packet-data handle":** the LTE status shows when the session is up but carries no data.
- **G4 AT console:** a specific warning before `AT&F`, `AT&W` or `AT+CFUN=`.
- **G5 Manual:**
  - LTE modem: Recovering the modem, Recover, saved setups, the AT warning.
  - Files and data: the new folder.
  - Troubleshooting: "LTE does not connect".
  - Uninstall: the data-folder delete removes the setups.
- **G6 AP2 proof:** one short AP2 window records the new commands and proves each rung on the real modem.

Non-goals:
- The modem's factory reset. The stock firmware's sequence (`cpe.Execute` in `libusbmodem.so`) is unknown;
  that is open item O1, in 1.3.
- Changing the modem's own autoconnect. The bench image's qmi.sh turns it off at every connect (manual, LTE
  modem › Settings).
- Rebooting the router or power-cycling it automatically.
- Modems other than the qmi interface named `lte` (the only one the LTE screen supports today).

Anti-goals (failure even if it "works"):
- Recover ever sends QMI `--set-device-operating-mode reset`, `AT&F`, `AT&W` or `AT+CFUN`. The first wedges the
  BM806C until a power cycle.
- Anything here writes to a router while a harness run is live, except the two put-back lines Dmitry allowed
  (4.2, Stopping).
- The modem is left in low power without the result saying so.
- A saved password or PIN shows on screen, in the API, in a preview line or in the audit log.
- Another router's PIN is written to a router.
- Recover changes LTE settings that already match the saved setup, or changes them silently.

## 3. How things work today (c3b94c2)

- **LTE service:** `lte/service.py`, `LteService`.
  - `LteAction = Literal["connect","disconnect","reboot"]` (:33). `plan_action` and `apply_action` take a digest.
  - The busy lock per router raises `LteBusy` (409).
  - `guard.require_clear()`; writes go through `run_audited` (`_cmd`) under `pool.write_lock`.
  - Reboot modem = `set_opmode low_power`, readback, `set_opmode online`, readback, `ifup lte`, then
    `_wait_up` (`CONNECT_S` 60 s, `POLL_S` 2 s) and `_address` (lte_4).
  - `commands.set_opmode` refuses every mode but `low_power` and `online`. `commands.uqmi()` is the choke point
    that checks the device. There is no `--sync` helper.
- **LTE state:** `LteState` (`lte/state.py:32`) has `up`, `pending`, `ipv4` and the rest. It does not read the
  packet-data handle. AP2's recorded `ubus call network.interface.lte status` ends with
  `"data": {"cid_4": "11", "pdh_4": "90215808"}`, so the handle is already in an answer the state read gets.
- **LTE settings:** `POST /lte/settings/preview` and `/apply` (api/lte_api.py).
  - `LteSettingsIn` maps to `InterfaceRequest(name="lte", mtu, auto, edits)`.
  - `NetworkService.plan_interface` and `apply_interface` call `ApplyRunner.run_planned`: digest, write lock,
    `ubus uci apply rollback:true`, confirm.
  - `password` and `pincode` are secret rows: masked in the plan, the audit and the API.
  - Edits must name options the interface has rows for; control-locked options are refused.
- **Jobs:** `StepJob` (wifi/step_service.py) is the closest model: a job model per router, a background
  runner, guard checks between steps, `busy()` and `live()`, and `stop_all`.
  - The UI polls the job's GET endpoint every 2 s (`useStepJob.ts`, `useJob.ts`). LiveHub carries no job state.
  - Jobs live in memory only.
  - Cross-busy wiring is in `context.py:343-346`. `update_api._live` and `_stop_live` list the live work an
    update asks about.
- **AT console:** `POST /lte/at` answers 428 (`AtNeedsConfirm`) for a command that is not a query. The UI
  asks "This command may change the modem. Send it?" (`AtConsole.tsx:133`) and resends with `confirmed`.
- **Stores:** `store/__init__.py:write_atomic`, and `restrict_to_user` (`store/keys.py:30`). The backups with
  secrets are in `<data>/backups/<router_id>`. Uninstall's `DeleteAppData` (`installer/OpenWrtGUI.iss:194`)
  DelTrees `keys`, `audit`, `updates`, `logs` and `backups`, and names `backups` in its "left behind" message.
- **Simulator:** `SimModem` (simmodem.py) fakes uqmi reads and the operating-mode write, and ifup/ifdown. It
  fails anything else (so `--sync` fails). `simnet._dump` builds the lte and lte_4 status. It cannot fake "up
  but no handle" or "back only after a modem restart".

## 4. The design

### 4.1 "LTE works"

LTE works when all three hold, read the way `read_lte` reads today (no new command):
- the `lte` interface is `up`;
- its status has `data.pdh_4`, and the value is not `0xffffffff` (in any case) or `4294967295`;
- `lte_4` has an IPv4 address.

`LteState` gains `data_handle: bool | None`: True when there is a valid `pdh_4`, False when it is missing or
invalid while `up` is true, and None when the session is down or the status was not read. The Status card shows
False as "Session up but no packet-data handle: the modem carries no data. Use Recover."

### 4.2 Recover: the ladder

**Which setup Recover uses (my call).** Recover uses this router's own saved setup if it has one, and no
setup otherwise. It never takes another router's setup and offers no picker; Reconfigure (4.4) does that. So
`setup_from` is the router itself or null, chosen by the server.

**Diagnose first (reads only).** Read the state as `read_lte` does, then compare the router's LTE options with
its own saved setup (4.4), if there is one.
- If LTE works, the job ends at once: "LTE works; nothing to do." Nothing is written, even if the settings
  differ from the saved setup (my call: a working session is never dropped, and a difference may be
  intentional). The result then adds "Its settings differ from the good setup saved <date>: use Reconfigure to
  put them back."
- Otherwise the job says what is wrong, one of: not registered, no session, session up but no packet-data
  handle, no address. If settings differ, it also says which.

**Then the rungs, in order. Each runs only if LTE does not work after the one before:**

| # | Rung | Commands | Then |
|---|---|---|---|
| 1 | Put back the saved setup (only if a setup is chosen and differs) | the settings change of 4.4, with rollback and confirm | wait for "works", up to `CONNECT_S` |
| 2 | Reconnect | `ifdown lte`, `ifup lte` | wait for "works", up to `CONNECT_S` |
| 3 | Clear QMI state | `ifdown lte`, `uqmi -s -d DEV -t 5000 --sync`, `ifup lte` | wait for "works", up to `CONNECT_S` |
| 4 | Restart the modem | `ifdown lte`, then the Reboot modem sequence (`low_power`, readback, `online`, readback, `ifup lte`) | wait for "works", up to `CONNECT_S` |

- `--sync` comes only after `ifdown lte`, so it cannot release the client id of a live session.
- **A failed command in rungs 1-3 does not end the job (my call).** A stuck modem is exactly when `--sync` or
  `ifup` may fail. The rung records "failed: <command>: <reason>" (a non-zero exit or no answer within the
  timeout), still runs its `ifup lte` if it ran `ifdown lte`, and the job goes on to the next rung. A refused
  settings change (rung 1) is rolled back by the router as today, then the job goes on.
- **A failed command in rung 4 ends the job ("failed")**, naming the command and where the modem was left. It
  keeps today's rule: if `online` does not take, the result says the modem is in low power.
- After rung 4, if LTE still does not work, the job ends "not recovered". It lists what each rung did and
  offers **Reboot router**: the System reboot, which asks first and is never started by the job. If that does
  not help either, power-cycle the router.

**Stopping.**
- **Stop (my call):** the job finishes putting back what the running rung took down (`online` after
  `low_power`, `ifup lte` after `ifdown lte`), then stops before the next rung. The result says "stopped" and
  whether LTE works.
- **A harness run going live mid-rung (Dmitry, 2026-11-17: "Finish putting back").**
  - The job checks the guard before every command.
  - Once the run is live, it sends no new rung and no new step. It still sends the put-back lines of the running
    rung, past Bench Guard, the way the network rollback's reload does: `online` after `low_power`, then
    `ifup lte` after `ifdown lte`.
  - Then it stops: "stopped: a harness run started; the modem was put back online and LTE reconnected". If a
    put-back line failed, the result names it and says where the modem was left.
  - Only those two put-back lines are exempt from the guard. Each goes to the audit log marked "put back during
    a harness run".
  - **Reboot modem gets the same rule (my call).** Today it has the same hole: `run_audited` refuses `online`
    with `GuardLocked`, and the modem stays in low power with no result saying so.

**Preview.** Recover shows every command it may run before it starts, as every LTE action does. Lines of a
rung that runs only if needed are marked so: "runs only if LTE does not work after the step before". The start
call carries the preview's digest; a changed preview is refused (`PreviewChanged`), as today. The settings
rung's lines are the settings preview's lines, with secrets masked.

**One at a time.**
- One LTE job per router. While it runs, the LTE screen's other writes (Connect, Disconnect, Reboot modem,
  Settings apply, Reconfigure, AT commands that are not queries) answer 409 naming the job.
- Its `busy()` joins the cross-checks with the step-through, Flash and the System jobs (context.py), both ways.
- `live()` adds "LTE recovery on <router>" to the app update's 409 list. `stop_all` stops it at the next safe
  point.

**The job model** (`LteRecoverJob`, frozen, in memory like the others):
- `router_id`, `started_at`, `ended_at`;
- `phase`: running, works, recovered, not recovered, stopped, failed;
- `diagnosis`: what was wrong at the start;
- `rungs`: one entry per rung, with its name, its outcome (skipped, not needed, ran: works, ran: not yet,
  failed) and a detail line;
- `current` (the running rung's index), `detail`, `error`.

**API** (under `/api/routers/{id}/lte`):
- `POST /recover/preview` takes no body and returns the plan; the server picks the router's own setup.
- `POST /recover` takes `digest` and starts the job.
- `GET /recover` returns the job or null.
- `POST /recover/stop`.

The UI polls `GET /recover` every 2 s while the job runs (the `useStepJob` pattern).

### 4.3 The UI

- **Actions card:** **Recover** next to Connect, Disconnect and Reboot modem. While a job runs or after it
  ends, the card shows the job as a list: the diagnosis, each rung with its outcome, a progress line for the
  running rung, and Stop. A "not recovered" end shows **Reboot router** (it goes to the System reboot, which
  asks) and the power-cycle line.
- **Settings card:**
  - **Save good setup**: enabled only while LTE works, with a tooltip saying why otherwise. It asks before it
    overwrites an older setup ("Replace the good setup saved 2026-11-10?").
  - **Reconfigure**: a choice of source, this router's setup or another router's (labelled with the router's
    name and the date), then the usual preview and apply with rollback.
- **Status card:** the "no packet-data handle" line (4.1).
- **AT console:** the stronger question for risky commands (4.5).

### 4.4 Saved good setups

- **Where:** `<data>/lte-setups/<router_id>.json`, one per router, written with `write_atomic`. The folder is
  created with `restrict_to_user`. A new `DataDir` field holds it.
- **What a setup holds:**
  - router id and name, the time it was saved, and the modem (manufacturer, model, firmware);
  - every option of the router's `lte` section that the Settings card can edit: the named fields plus the
    "All options" rows that are not control-locked, `password` and `pincode` included, with their values as the
    router has them.
- **Save** reads the options from the router (the read the Settings card makes, plus the secret values, which
  the app never sends to the browser). It is refused unless LTE works at that moment. It is audited as "LTE
  good setup saved" with the secrets masked.
- **Reconfigure** builds one settings change:
  - every saved option whose value differs is set;
  - every option the router has that the setup lacks is removed;
  - `device` is never changed;
  - from another router's setup, `pincode` is left as the target router has it;
  - options a setup holds that the target has no row for are not written, and the result names them.
  
  It runs through `LteService.plan_settings` and `apply_settings`, so the preview, masking, rollback and
  confirm are today's.
- **API:**
  - `GET /api/lte-setups` lists every saved setup: router id, router name, saved time, APN, PDP type. It never
    returns secrets.
  - `POST /api/routers/{id}/lte/setup` saves the router's setup.
  - `POST /api/routers/{id}/lte/setup/preview` takes `{from: router_id}` and returns the plan.
  - `POST /api/routers/{id}/lte/setup/apply` takes `{from, digest}`.
- **Remove from the app** also deletes that router's setup file.
- **Uninstall:** the data-folder delete DelTrees `lte-setups` and names it in its "left behind" message, like
  `backups`.

### 4.5 AT console: risky commands

- `lte/at.py` gains `is_risky(text)`, true for `AT&F` (with or without a number), `AT&W` and any `AT+CFUN=...`,
  in any case and spacing.
- The 428 answer carries `risky: true` for those. The UI then asks "This command can erase the modem's saved
  profiles or leave it unusable until the router is power-cycled. Use Recover instead. Send it anyway?"
  instead of the generic question.
- The server keeps the rule, so there is no second copy of it in the frontend.
- **Today the console asks before it sends**, using its own copy of the query rule (`AtConsole.tsx:13`), then
  sends with `confirmed: true`, so it never sees the 428. **My call:** a command that is not a query is first
  sent unconfirmed; the console asks when the 428 comes back (generic or risky text), then sends it confirmed.
  The extra round trip is only for commands that change the modem, which are rare. 1.1a (#29) also touches the
  console's copied AT constants: build on whatever master has when this work starts.
- Recover never sends these (anti-goal).

### 4.6 Simulator

- **`SimModem`:**
  - A `wedged` flag. While it is set, `ifup lte` brings the session up without a packet-data handle. It is
    cleared by a `low_power` then `online` cycle.
  - A `stale_qmi` flag. While it is set, `ifup lte` fails to start the session. It is cleared by `--sync`.
  - A `--sync` branch in its uqmi handling.
- **`simnet._dump`:** puts `data.pdh_4` (a valid handle, or `0xffffffff` while wedged) in the lte status.
- **Seeding:** tests set the flags directly. The e2e simulator can start one router wedged through an
  environment variable, like `OPENWRTGUI_SIM_GUARD`.

### 4.7 The manual and the CHANGELOG

- **LTE modem:**
  - **Recovering the modem**: the ladder, what each rung does, what the job shows, when to reboot or
    power-cycle, and what never to send in the AT console.
  - **Save good setup** and **Reconfigure**, and the status line.
- **Files and data:** a row for `lte-setups` (it holds the APN password and SIM PIN), and the uninstall text.
- **Troubleshooting:** "LTE does not connect" points to Recover.
- **CHANGELOG:** lines under `[Unreleased]`.

### 4.8 The AP2 proof

One window with Dmitry's OK at the time, Bench Guard clear, and the txctl session told first:
1. Record `uqmi --sync` (after `ifdown lte`), and the lte status with `pdh_4`, as fixtures.
2. Recover on a working modem: it must end "LTE works; nothing to do".
3. Disconnect, then Recover: it must end "recovered" at rung 2.
4. Run rungs 3 and 4 once each and record their commands. They must come back working.
5. Save good setup, then Reconfigure from it: no change.

Nothing in the window breaks the modem on purpose: no `AT&F`, no QMI reset. Agents never type router
passwords.

## 5. Approaches considered

| Approach | Trade-off | Chosen |
|---|---|---|
| **A background job with live progress** (like StepJob) | More code: a job model, a runner, polling, busy and live hooks. You see every step, it survives closing the window, and it stops cleanly for a harness run or an update. | **Yes** (Dmitry: "Yes, a job") |
| One long request (a fourth `LteAction`) | Less code, but nothing shows until the end (up to about four minutes), and a closed window loses where the modem was left. | No |
| Separate buttons per rung | More control, but the person has to know the order. | No (Dmitry: "One Recover button") |
| Reconfigure from fixed bench values (APN `uinternet` and so on) | No store needed, but it is wrong for any other SIM or carrier, and hard-coded. | No (Dmitry: "A saved good setup") |

## 6. Constraints

- **Test first** (AGENTS.md).
- **Writes:** `run_audited` or `ApplyRunner`; refused during a harness run (`GuardLocked`, 423).
- **Reads:** background reads use `t.run`. Every new read passes `is_read_only_command`. Recorded AP2 commands
  replay by exact string, so no existing command text changes.
- **uqmi:** every command goes through `commands.uqmi()`. `set_opmode` keeps refusing everything but
  `low_power` and `online`.
- **Secrets:** use `guard/secrets.py`, `mask` and `secrets=`. Keep secret fields out of `repr` and out of API
  models.
- **Public repo:** no real APN credentials, PINs, IMEIs or names in fixtures, tests or docs.
- **Routers:** AP2 only, and only in the 4.8 window. Never AP1 or AP3.
- **GitHub:** nothing is pushed without Dmitry's go.

## 7. Left to the builder

- Where the job runner lives (inside `LteService` or a small `lte/recover.py`).
- How the preview marks conditional lines.
- Exact UI layout and texts, beyond those quoted here.
- The job's exact phase and outcome names in code. The UI words above stand.
- Splitting the work into tasks, and the test list.

## 8. Open, for Dmitry

- **A harness run starts mid-rung:** answered "Finish putting back" (4.2, Stopping).
- **Which release ships it (does not block the plan):** with 1.1.0 (1.1a, 1.1b) by default, or a 1.0.2 of its
  own.

## 9. The builder check (2026-11-17)

A fresh reviewer read this design as its builder. Its five questions:
1. A harness run mid-rung: Dmitry answered "Finish putting back" (4.2).
2. Where Recover's setup comes from: settled, the router's own setup only (4.2).
3. LTE works but the settings differ: settled, nothing is written (4.2).
4. A failed `--sync`: settled, the job goes on to the next rung (4.2).
5. The AT console asks before sending: settled, send unconfirmed first, ask on the 428 (4.5).
