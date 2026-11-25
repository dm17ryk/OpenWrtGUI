"""AP2's recorded SIM, SMS and mode-name reads (tests/fixtures/ap2/modem_sms.json, 2026-11-25; shapes only).
The recording found two things the simulator did not show: real messages carry their body as UTF-16BE hex
under "ucs-2" (no "text" key), and the modem names its network mode orders itself. The SMS send and USSD
were skipped on the owner's choice, so they stay unproven on hardware."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

from openwrtgui.lte.parse import MODE_NAMES, parse_mode_names
from openwrtgui.lte.sim import PinState
from openwrtgui.lte.sms import parse_cpms

RECORDED: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "ap2" / "modem_sms.json").read_text(encoding="utf-8")
)


def test_the_sim_matches_the_1_3a_recording() -> None:
    sim = RECORDED["sim"]
    assert sim["pin"] in get_args(PinState)
    assert isinstance(sim["tries_left"], int) and isinstance(sim["puk_tries_left"], int)
    assert (sim["pin"], sim["tries_left"], sim["can_enter_pin"]) == ("off", 3, False)


def test_a_real_message_has_the_keys_parse_message_reads() -> None:
    keys = set(RECORDED["message_keys"])
    assert {"sender", "timestamp"} <= keys
    assert keys & {"text", "ucs-2"}


def test_the_storage_use() -> None:
    assert parse_cpms(RECORDED["cpms"]) == {"me": (0, 23), "sim": (20, 20)}


def test_the_modem_names_its_mode_orders() -> None:
    assert parse_mode_names(RECORDED["bmmododr_test"]) == MODE_NAMES
    assert MODE_NAMES[17] == "AUTO (LTE>WCDMA>GSM>TDS>HDR>CDMA)"


def test_the_window_deleted_the_sim_messages_and_skipped_send_and_ussd() -> None:
    assert RECORDED["deleted"] == 20
    assert "sent" not in RECORDED and "ussd" not in RECORDED
