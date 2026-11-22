"""AP2 window, 1.3a Part 2: Recover waits out netifd's LTE setup on a link that keeps failing (#93, plan C7).

    uv run pytest -m hardware tests/hardware/test_ap2_lte_setup_guard.py --router 192.168.1.2 \
        --identity <key> --known-hosts <file> --allow-writes --txctl-told -v -s

Run it only in a window Dmitry OK'd at the time, Bench Guard clear, the txctl session told. It applies the APN
`owg-wrong` through the app so the link fails and netifd retries qmi.sh's setup, runs Recover with no saved
setup (rungs 2-5 each wait or skip), then always puts the APN back. LTE must work again within 90 s, with no
new "Failed to connect to service" or "Unable to obtain client ID" in the log: the QMI channel was not wedged.
If LTE does not come back, the test fails and says so. It never reboots the router: that needs Dmitry's OK.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from test_ap2_lte import lte  # noqa: F401 - the window's fixture: AP2 as found at the end
from test_ap2_lte_recover import _recover, _run

from openwrtgui.lte import commands as c
from openwrtgui.lte.recover import SETUP_BUSY, SETUP_S, WAITED
from openwrtgui.lte.service import LteService
from openwrtgui.lte.settings import LteSettings
from openwrtgui.transport.ssh import SshTransport

pytestmark = pytest.mark.hardware

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ap2" / "lte_setup_guard.json"
WRONG_APN = "owg-wrong"
RETRY_WAIT_S = 60.0
BACK_S = 90.0
WEDGE = "logread | grep -c -e 'Failed to connect to service' -e 'Unable to obtain client ID'"
NOT_BACK = (
    "LTE did not come back after the APN was put back: QMI may be wedged; a router reboot needs Dmitry's OK"
)


async def _apn(service: LteService, apn: str) -> None:
    settings = LteSettings(apn=apn)
    plan = await service.plan_settings("ap2", settings)
    result = await service.apply_settings("ap2", settings, plan.digest)
    assert result.applied, result


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
    try:
        await _apn(lte, WRONG_APN)
        reads: list[tuple[float, str]] = []
        start = time.monotonic()
        while time.monotonic() - start < RETRY_WAIT_S:
            reads.append(
                (round(time.monotonic() - start, 1), (await ap2_rw.run(c.SETUP_RUNNING)).stdout.strip())
            )
            if any(v != "0" for _, v in reads) and reads[-1][1] == "0":
                break  # a setup was seen, then a gap: netifd retries
            await asyncio.sleep(1.0)
        recorded["setup_reads"] = reads
        assert any(v != "0" for _, v in reads), "the wrong APN did not make netifd retry: no setup was seen"
        job = await _run(_recover(lte, tmp_path))
        recorded["rungs"] = [[r.name, r.outcome, r.detail] for r in job.rungs]
        recorded["phase"] = job.phase
        for rung in job.rungs[1:]:
            detail = rung.detail or ""
            assert rung.outcome in ("not yet", "skipped", "failed", "works"), rung
            if rung.outcome == "skipped":
                assert detail == SETUP_BUSY.format(s=SETUP_S), rung
            elif detail.startswith("waited "):
                assert detail.split(";")[0].endswith(WAITED.split("}", 1)[1]), rung
    finally:
        await _apn(lte, original or "")
        back_at = time.monotonic()
        while not await lte.works_now(ap2_rw):
            assert time.monotonic() - back_at < BACK_S, NOT_BACK
            await asyncio.sleep(3.0)
        recorded["lte_back_s"] = round(time.monotonic() - back_at, 1)
        recorded["wedge_lines_new"] = await _wedge_lines(ap2_rw) - wedges_before
        FIXTURE.write_text(json.dumps(recorded, indent=2) + "\n", encoding="utf-8")
        print(f"\nrecorded the setup guard window to {FIXTURE}: {recorded}")
    assert recorded["wedge_lines_new"] == 0, "the log shows a wedged QMI channel: stop and tell Dmitry"
