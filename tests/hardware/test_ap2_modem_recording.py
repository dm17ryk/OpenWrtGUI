"""AP2 window, 1.3a Part 1: what the modem says about its SIM, SMS and USSD, read only (plan C9, C10).

    uv run pytest -m hardware tests/hardware/test_ap2_modem_recording.py --router 192.168.1.2 \
        --identity <key> --known-hosts <file> --allow-writes --txctl-told -v -s

Run it only in a window Dmitry OK'd at the time, Bench Guard clear, the txctl session told. It sends reads
only: uqmi's help, the SIM's PIN state, the SIM state and the SMS list when this uqmi has them, at most three
messages, and AT `?`/`=?` queries. Never a PIN write, an SMS or a USSD code. Message bodies and phone numbers
are replaced before anything is written (tests/fixtures/ap2/modem_sim.json is public).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_ap2_lte import lte  # noqa: F401 - the window's fixture: AP2 as found at the end
from test_ap2_wifi import _recorder

from openwrtgui.lte import commands as c
from openwrtgui.lte.at import find_at_port, is_query
from openwrtgui.lte.service import LteService
from openwrtgui.transport.ssh import SshTransport

pytestmark = pytest.mark.hardware

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ap2" / "modem_sim.json"
MESSAGES_READ = 3


def _ids(listing: str) -> list[int]:
    """`uqmi --list-messages` prints a JSON list of message ids; anything else reads as none."""
    try:
        found = json.loads(listing)
    except ValueError:
        return []
    return [i for i in found if isinstance(i, int)] if isinstance(found, list) else []


async def test_record_the_modems_sim_sms_and_ussd_answers(
    lte: LteService,  # noqa: F811
    ap2_rw: SshTransport,
) -> None:
    rf = _recorder()
    device = await lte.lte_device("ap2")
    assert device is not None, "AP2's network.lte.device names no QMI device"
    port = await find_at_port(ap2_rw)  # type: ignore[arg-type]
    assert port is not None, "no AT port answered on AP2"
    assert all(is_query(q) for q in rf.MODEM_AT_QUERIES)
    recorded: dict[str, dict[str, object]] = {}

    async def read(command: str) -> str:
        r = await ap2_rw.run(command, timeout=60.0)
        recorded[command] = {"stdout": rf.sanitize_modem(command, r.stdout), "exit": r.exit_status}
        if r.stderr:
            recorded[command]["stderr"] = rf.sanitize_modem(command, r.stderr)
        return r.stdout

    # the guard's read on a working link: 0 means it sees no setup when none runs (plan C2)
    assert (await read(c.SETUP_RUNNING)).strip() == "0", "SETUP_RUNNING is not 0 on a working link: a ruling"
    uqmi_help = await read(rf.UQMI_HELP)
    reads = rf.modem_reads(device, port, uqmi_help)
    for command in reads[1:]:  # UQMI_HELP was read above
        await read(command)
    listing = next((r for r in reads if "--list-messages" in r), None)
    if listing is not None:
        before = recorded[listing]["stdout"]
        for message in _ids(await read(listing))[:MESSAGES_READ]:
            await read(c.uqmi(device, "--get-message", str(message)))
        recorded[f"{listing}  # after --get-message"] = {
            "stdout": rf.sanitize_modem(listing, (await ap2_rw.run(listing)).stdout),
            "exit": 0,
            "before": before,
        }
    sent = [k.split("  #")[0] for k in recorded]
    assert set(sent) <= {c.SETUP_RUNNING, *reads, *(k for k in sent if "--get-message" in k)}
    FIXTURE.write_text(json.dumps(recorded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nrecorded {len(recorded)} commands to {FIXTURE}")
