"""AP2 window, 1.3a Part 2: Recover waits out netifd's LTE setup on a link that keeps failing (#93, plan C7).

    uv run pytest -m hardware tests/hardware/test_ap2_lte_setup_guard.py --router 192.168.1.2 \
        --identity <key> --known-hosts <file> --allow-writes --txctl-told -v -s

Run it only in a window Dmitry OK'd at the time, Bench Guard clear, the txctl session told. It sets an
IPv6-only PDP type through the app so the link fails and netifd retries qmi.sh's setup (attempt 1's wrong
APN was accepted by the carrier), samples the setup processes every 0.25 s for 60 s to measure the gaps
between retries, checks the link really fails, runs Recover with no saved setup (rungs 2-5 each wait or
skip), then puts the PDP type back, itself only in a gap between setups (final review I1). LTE must work
again within 90 s, with no new "Failed to connect to service" or "Unable to obtain client ID" in the log:
the QMI channel was not wedged. Recover must have run at least one step: a run where every step was skipped
proves nothing (final review I4). It never reboots the router: that needs Dmitry's OK.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from lte_window import SAMPLE_LOOP, SAMPLE_STEP_S, gap_widths, parse_samples, wait_for_gap
from test_ap2_lte import lte  # noqa: F401 - the window's fixture: AP2 as found at the end
from test_ap2_lte_recover import _recover, _run

from openwrtgui.lte.recover import SETUP_BUSY, SETUP_S, WAITED
from openwrtgui.lte.service import LteService
from openwrtgui.lte.settings import LteSettings
from openwrtgui.net.apply import NOTHING
from openwrtgui.transport.ssh import SshTransport

pytestmark = pytest.mark.hardware

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ap2" / "lte_setup_guard.json"
# 2026-11-22 window, attempt 1: the APN owg-wrong did not make the link fail (the carrier accepted it), so the
# link is broken by an IPv6-only PDP type, which the known-good setup (IPv4) suggests the network refuses
BREAK_FIELD = "pdptype"
BREAK_VALUE = "ipv6"
SAMPLE_S = 60.0  # about three retry cycles
RESTORE_GAP_S = 120.0
BACK_S = 90.0
WEDGE = "logread | grep -c -e 'Failed to connect to service' -e 'Unable to obtain client ID'"
NOT_BACK = (
    f"LTE did not come back after {BREAK_FIELD} was put back: QMI may be wedged; a router reboot needs "
    "Dmitry's OK"
)
STILL_WRONG = (
    f"AP2's {BREAK_FIELD} is still {BREAK_VALUE}: {{why}}; put it back by hand (LTE > Settings) in a quiet "
    "moment and tell Dmitry"
)
NOT_FAILING = (
    f"{BREAK_FIELD}={BREAK_VALUE} did not make AP2's link fail (the carrier accepted it): nothing was proven"
)


async def _wedge_lines(t: SshTransport) -> int:
    out = (await t.run(WEDGE)).stdout.strip()
    return int(out) if out.isdigit() else 0


async def test_recover_on_a_retrying_link_leaves_qmi_working(
    lte: LteService,  # noqa: F811
    ap2_rw: SshTransport,
    tmp_path: Path,
) -> None:
    assert await lte.works_now(ap2_rw), "LTE does not work on AP2 before the test: stop and tell Dmitry"
    rows = await lte.settings_options("ap2")
    original = next((r.value for r in rows if r.name == BREAK_FIELD), None)
    assert original is None or isinstance(original, str)
    recorded: dict[str, object] = {"break": f"{BREAK_FIELD}={BREAK_VALUE}", "original": original}
    wedges_before = await _wedge_lines(ap2_rw)
    broken = LteSettings(**{BREAK_FIELD: BREAK_VALUE})  # type: ignore[arg-type]
    recorded["link_failing"] = False
    ran: list[str] = []
    exercised: list[str] = []  # steps that waited for a setup, or were skipped because one still ran
    try:
        # PR #100 Codex P1: the break is applied inside the cleanup scope, so any exit puts it back
        plan = await lte.plan_settings("ap2", broken)
        applied = await lte.apply_settings("ap2", broken, plan.digest)
        assert applied.applied, applied
        n = int(SAMPLE_S / SAMPLE_STEP_S)
        samples = parse_samples((await ap2_rw.run(SAMPLE_LOOP.format(n=n), timeout=SAMPLE_S * 2)).stdout)
        recorded["setup_gaps_s"] = gap_widths([(at, q + u) for at, q, u in samples])
        recorded["uqmi_gaps_s"] = gap_widths([(at, u) for at, _, u in samples])
        recorded["samples"] = len(samples)
        # final review minor M5 (attempt 1): the link must really fail before Recover proves anything; with
        # no `return` here (PR #100 Codex P1), the checks after the cleanup decide
        recorded["link_failing"] = not await lte.works_now(ap2_rw)
        if recorded["link_failing"]:
            assert any(q + u for _, q, u in samples), "the link fails but netifd ran no setup in 60 s"
            job = await _run(_recover(lte, tmp_path))
            recorded["rungs"] = [[r.name, r.outcome, r.detail] for r in job.rungs]
            recorded["phase"] = job.phase
            for rung in job.rungs[1:]:
                detail = rung.detail or ""
                if rung.outcome == "skipped":
                    assert detail == SETUP_BUSY.format(s=SETUP_S), rung
                    exercised.append(rung.name)
                elif rung.outcome is not None and rung.outcome != "not needed":
                    ran.append(rung.name)
                    if detail.startswith("waited "):
                        assert detail.split(";")[0].endswith(WAITED.split("}", 1)[1]), rung
                        exercised.append(rung.name)
    finally:
        restore = LteSettings(**{BREAK_FIELD: original or ""})  # type: ignore[arg-type]
        try:
            back = await lte.plan_settings("ap2", restore)  # its reads now; the reload only in a gap
        except ValueError as exc:
            if not str(exc).startswith(NOTHING):
                raise
            back = None  # the break never reached AP2: nothing to put back
        if back is not None:
            gap = await wait_for_gap(
                lambda: lte.setup_idle(ap2_rw), limit_s=RESTORE_GAP_S, step_s=SAMPLE_STEP_S
            )
            recorded["restore_in_a_gap"] = gap
            if not gap:
                FIXTURE.write_text(json.dumps(recorded, indent=2) + "\n", encoding="utf-8")
                pytest.fail(STILL_WRONG.format(why=f"no gap between LTE setups in {RESTORE_GAP_S:g} s"))
            try:
                restored = await lte.apply_settings("ap2", restore, back.digest)
            except Exception as exc:
                print("\n" + STILL_WRONG.format(why=f"the restore failed: {exc}"))
                raise
            assert restored.applied, STILL_WRONG.format(why=f"the restore was not applied: {restored}")
        back_at = time.monotonic()
        while not await lte.works_now(ap2_rw):
            assert time.monotonic() - back_at < BACK_S, NOT_BACK
            await asyncio.sleep(3.0)
        recorded["lte_back_s"] = round(time.monotonic() - back_at, 1)
        recorded["wedge_lines_new"] = await _wedge_lines(ap2_rw) - wedges_before
        FIXTURE.write_text(json.dumps(recorded, indent=2) + "\n", encoding="utf-8")
        print(f"\nrecorded the setup guard window to {FIXTURE}: {recorded}")
    assert recorded["wedge_lines_new"] == 0, "the log shows a wedged QMI channel: stop and tell Dmitry"
    assert recorded["link_failing"], NOT_FAILING
    assert ran, (
        "Recover skipped every step: the guard saw no gap in 20 s. Measured gaps (s): "
        f"setup {recorded['setup_gaps_s']}, uqmi only {recorded['uqmi_gaps_s']}: C2/C3 need a ruling"
    )
    # PR #100 Codex P1: a run where no step met a setup proves no wedge, not the guard itself
    assert exercised, (
        "the guard was not exercised: no step waited for a setup or was skipped for one (netifd was not "
        "retrying when Recover's steps started); the run shows only that Recover left no wedge"
    )
