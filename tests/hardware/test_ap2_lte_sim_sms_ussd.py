"""AP2 window, 1.3b: the SIM, SMS and USSD cards against the real modem, shapes only (plan C-window, E13).

    uv run pytest -m hardware tests/hardware/test_ap2_lte_sim_sms_ussd.py --router 192.168.1.2 \
        --identity <key> --known-hosts <file> --allow-writes --txctl-told \
        [--sms-read sim:0] [--sms-delete sim:0,1] [--sms-to <number> --sms-text <text>] [--ussd <code>] -v -s

Run it only in a window Dmitry OK'd at the time, Bench Guard clear, the txctl session told. The parts run
through the app's own ModemService. Part 1 (reads) always runs: the SIM state, both message lists, AT+CPMS?,
one message and AT+BMMODODR=?. It needs ap2_rw because --get-message is not in the read-only grammar.
Part 2 (--sms-delete), part 3 (--sms-to with --sms-text) and part 4 (--ussd) run only when named, and each
is a write Dmitry named for this window. --sms-to without --sms-text, or the reverse, is a usage error that
fails the test before anything is sent.

E13: tests/fixtures/ap2/modem_sms.json is public, so it holds shapes only: counts, key names, string lengths,
a send's ok, a USSD reply's status and length. Never a number, an SMS text, a USSD code or a reply. The
file is written in a `finally`, with every key read until a part failed; an answer that does not parse is
recorded as {"error": ...} and the window goes on. The PIN is never entered here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sim_sms_ussd_window as w
from test_ap2_lte import lte  # noqa: F401 - the window's fixture: AP2 as found at the end
from test_ap2_wifi import _recorder

from openwrtgui.lte.modem import ModemService
from openwrtgui.lte.service import LteService
from openwrtgui.transport.ssh import SshTransport

pytestmark = pytest.mark.hardware

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ap2" / "modem_sms.json"


async def test_record_the_modems_sim_sms_and_ussd_shapes(
    lte: LteService,  # noqa: F811
    ap2_rw: SshTransport,
    request: pytest.FixtureRequest,
) -> None:
    get = request.config.getoption
    opts = w.Options(
        read=w.parse_read(get("--sms-read")),
        delete=w.parse_delete(get("--sms-delete")),
        to=get("--sms-to"),
        text=get("--sms-text"),
        ussd=get("--ussd"),
    )
    guard, audit = lte._guard, lte._audit  # noqa: SLF001 - the service's own, so the audit holds every line
    window = w.Window(
        modem=ModemService(lte=lte, guard=guard, audit=audit),
        lte=lte,
        guard=guard,
        audit=audit,
        router_id="ap2",
    )
    recorded = await w.run_window(window, _recorder(), opts, FIXTURE)
    print(f"\nrecorded the 1.3b window to {FIXTURE}: {sorted(recorded)}")
    if opts.delete is not None:
        assert recorded["deleted"] == len(opts.delete[1]), recorded
    if opts.to is not None and opts.text is not None:
        assert recorded["sent"] == {"ok": True}, recorded
