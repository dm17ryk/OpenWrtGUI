"""AP2 window, 1.3a Part 2: Recover waits out netifd's LTE setup on a link that keeps failing (#93, plan C7).

    uv run pytest -m hardware tests/hardware/test_ap2_lte_setup_guard.py --router 192.168.1.2 \
        --identity <key> --known-hosts <file> --allow-writes --txctl-told -v -s

Run it only in a window Dmitry OK'd at the time, Bench Guard clear, the txctl session told. It applies the APN
`owg-wrong` through the app so the link fails and netifd retries qmi.sh's setup, samples the setup processes
every 0.25 s for 60 s to measure the gaps between retries, runs Recover with no saved setup (rungs 2-5 each
wait or skip), then puts the APN back, itself only in a gap between setups (final review I1). LTE must work
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
from openwrtgui.transport.ssh import SshTransport

pytestmark = pytest.mark.hardware

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ap2" / "lte_setup_guard.json"
WRONG_APN = "owg-wrong"
SAMPLE_S = 60.0  # about three retry cycles
RESTORE_GAP_S = 120.0
BACK_S = 90.0
WEDGE = "logread | grep -c -e 'Failed to connect to service' -e 'Unable to obtain client ID'"
NOT_BACK = (
    "LTE did not come back after the APN was put back: QMI may be wedged; a router reboot needs Dmitry's OK"
)
STILL_WRONG = (
    "AP2's APN is still owg-wrong: {why}; put it back by hand (LTE > Settings) in a quiet moment "
    "and tell Dmitry"
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
    original = next((r.value for r in rows if r.name == "apn"), None)
    assert original is None or isinstance(original, str)
    recorded: dict[str, object] = {}
    wedges_before = await _wedge_lines(ap2_rw)
    wrong = LteSettings(apn=WRONG_APN)
    plan = await lte.plan_settings("ap2", wrong)
    applied = await lte.apply_settings("ap2", wrong, plan.digest)
    assert applied.applied, applied
    ran: list[str] = []
    try:
        n = int(SAMPLE_S / SAMPLE_STEP_S)
        samples = parse_samples((await ap2_rw.run(SAMPLE_LOOP.format(n=n), timeout=SAMPLE_S * 2)).stdout)
        recorded["setup_gaps_s"] = gap_widths([(at, q + u) for at, q, u in samples])
        recorded["uqmi_gaps_s"] = gap_widths([(at, u) for at, _, u in samples])
        recorded["samples"] = len(samples)
        assert any(q + u for _, q, u in samples), "the wrong APN did not make netifd retry: no setup was seen"
        job = await _run(_recover(lte, tmp_path))
        recorded["rungs"] = [[r.name, r.outcome, r.detail] for r in job.rungs]
        recorded["phase"] = job.phase
        for rung in job.rungs[1:]:
            detail = rung.detail or ""
            if rung.outcome == "skipped":
                assert detail == SETUP_BUSY.format(s=SETUP_S), rung
            elif rung.outcome is not None and rung.outcome != "not needed":
                ran.append(rung.name)
                if detail.startswith("waited "):
                    assert detail.split(";")[0].endswith(WAITED.split("}", 1)[1]), rung
    finally:
        restore = LteSettings(apn=original or "")
        back = await lte.plan_settings("ap2", restore)  # its reads now; the reload only in a gap
        gap = await wait_for_gap(lambda: lte.setup_idle(ap2_rw), limit_s=RESTORE_GAP_S, step_s=SAMPLE_STEP_S)
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
    assert ran, (
        "Recover skipped every step: the guard saw no gap in 20 s. Measured gaps (s): "
        f"setup {recorded['setup_gaps_s']}, uqmi only {recorded['uqmi_gaps_s']}: C2/C3 need a ruling"
    )
