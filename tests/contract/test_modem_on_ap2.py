"""The 1.3a AP2 window's recordings (2026-11-22): what the BM806C says about its SIM, SMS and USSD
(modem_sim.json, read only), and Recover on a link made to fail (lte_setup_guard.json)."""

from __future__ import annotations

import json
from pathlib import Path

from openwrtgui.lte import commands as c

AP2 = Path(__file__).resolve().parents[1] / "fixtures" / "ap2"
MODEM = json.loads((AP2 / "modem_sim.json").read_text("utf-8"))
GUARD = json.loads((AP2 / "lte_setup_guard.json").read_text("utf-8"))
PIN_STATUS = "uqmi -s -d /dev/cdc-wdm0 -t 2000 --get-pin-status"
PIN_STATES = {"disabled", "enabled", "not_verified", "verified", "blocked", "permanently_blocked"}


def test_setup_read_is_zero_on_a_working_link() -> None:
    """Plan C2: the guard's read sees no setup when none runs (nothing on AP2's image keeps it above 0)."""
    assert MODEM[c.SETUP_RUNNING]["stdout"].strip() == "0"


def test_the_setup_guard_window_left_no_wedge() -> None:
    """Plan C7, attempt 2: on a link that really failed, every step ran, the setting went back in a gap
    between setups, and LTE came back with no wedged QMI channel."""
    assert GUARD["link_failing"] is True
    assert [r[1] for r in GUARD["rungs"][1:]] == ["not yet"] * 4
    assert GUARD["restore_in_a_gap"] is True
    assert GUARD["lte_back_s"] < 90 and GUARD["wedge_lines_new"] == 0


def test_the_modem_answers_its_pin_state() -> None:
    """1.3b reads the SIM's PIN state over QMI: the keys and values AP2's modem answers."""
    status = json.loads(MODEM[PIN_STATUS]["stdout"])
    assert set(status) == {
        "pin1_status",
        "pin1_verify_tries",
        "pin1_unblock_tries",
        "pin2_status",
        "pin2_verify_tries",
        "pin2_unblock_tries",
    }
    assert status["pin1_status"] in PIN_STATES and status["pin2_status"] in PIN_STATES
    assert isinstance(status["pin1_verify_tries"], int) and isinstance(status["pin1_unblock_tries"], int)


def test_uqmi_has_no_ussd_so_ussd_goes_over_at() -> None:
    """1.3b D3: uqmi on AP2's image lists SMS and PIN actions but no USSD; the modem takes AT+CUSD."""
    usage = MODEM["uqmi --help 2>&1"]["stdout"]
    for action in ("--get-pin-status", "--list-messages", "--get-message", "--send-message"):
        assert action in usage, action
    assert "ussd" not in usage.lower()
    cusd = next(v for k, v in MODEM.items() if "'AT+CUSD=?'" in k)
    assert "+CUSD: (0-2)" in cusd["stdout"]
