"""AP2 window, 1.3a Part 1: what the modem says about its SIM, SMS and USSD, read only (plan C9, C10).

    uv run pytest -m hardware tests/hardware/test_ap2_modem_recording.py --router 192.168.1.2 \
        --identity <key> --known-hosts <file> --allow-writes --txctl-told -v -s

Run it only in a window Dmitry OK'd at the time, Bench Guard clear, the txctl session told. It sends reads
only: uqmi's help, the SIM's PIN state, the SIM state and the SMS list (message ids) when this uqmi has them,
and AT `?`/`=?` queries. No message is read (final review I5: its sender and text are private; 1.3b decides
how), and never a PIN write, an SMS or a USSD code. Anything private that arrives anyway (an unsolicited SMS,
a number) is replaced before the file is written (tests/fixtures/ap2/modem_sim.json is public).
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
    assert set(recorded) == {c.SETUP_RUNNING, *reads}  # nothing else was sent through the recorder
    FIXTURE.write_text(json.dumps(recorded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nrecorded {len(recorded)} commands to {FIXTURE}")
