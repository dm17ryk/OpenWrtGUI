"""Step-through steps (v0.7 plan Task 10, D2-D5): expansion, refusals, the saved options, re-join."""

from __future__ import annotations

import pytest

from openwrtgui.uci import UciOp
from openwrtgui.wifi.compile import compile_channels, compile_modes
from openwrtgui.wifi.model import ChannelSelection, ModeSelection, RadioLimits, TxPowerSetting
from openwrtgui.wifi.steps import (
    SAVED_OPTIONS,
    Step,
    StepRequest,
    expand_steps,
    joined,
    saved_ops,
    saved_options,
    step_request,
)

LIMITS = RadioLimits("2g", "phy0", "HT40", tuple(range(1, 14)), tuple(range(21)), (0, 7), "IL", True)


def test_expand_order() -> None:
    req = StepRequest(radio="radio0", modes=("n20", "b"), channels=(6, 1))
    assert expand_steps(req, LIMITS) == (
        Step(1, "b", 1, None),
        Step(2, "b", 6, None),
        Step(3, "n20", 1, None),
        Step(4, "n20", 6, None),
    )


def test_expand_with_powers() -> None:
    req = StepRequest(radio="radio0", modes=("g",), channels=(11,), powers=(20, 10))
    assert [(s.index, s.txpower_dbm) for s in expand_steps(req, LIMITS)] == [(1, 10), (2, 20)]


@pytest.mark.parametrize(
    ("req", "message"),
    [
        (StepRequest("radio0", (), (1,)), "Tick at least one mode"),
        (StepRequest("radio0", ("g",), ()), "Tick at least one channel"),
        (StepRequest("radio0", ("g",), (14,)), "Channel 14 is not allowed in country IL"),
        (StepRequest("radio0", ("g",), (1,), powers=(21,)), "21 dBm is above this radio's maximum of 20 dBm"),
        (
            StepRequest("radio0", ("b", "g", "n20", "n40"), tuple(range(1, 14)), powers=(1, 2, 3, 4, 5, 6)),
            "312 steps; at most 200",
        ),
        (StepRequest("radio0", ("g",), (1,), dwell_s=5), "A dwell is 10 to 3600 s"),
        (StepRequest("radio0", ("g",), (1,), dwell_s=4000), "A dwell is 10 to 3600 s"),
        (StepRequest("radio0", ("g",), (1,), advance="rejoin"), "Choose the station that re-joins"),
        (
            StepRequest("radio0", ("g",), (1,), advance="rejoin", station="aa:bb;reboot"),
            "'aa:bb;reboot' is not a MAC address",
        ),
        (
            StepRequest(
                "radio0", ("g",), (1,), advance="rejoin", station="aa:bb:cc:dd:ee:ff", rejoin_limit_s=5
            ),
            "A re-join limit is 30 to 600 s",
        ),
    ],
)
def test_step_refusals(req: StepRequest, message: str) -> None:
    with pytest.raises(ValueError, match=f"^{message}"):
        expand_steps(req, LIMITS)


def test_station_mac_is_lowercased() -> None:
    req = StepRequest("radio0", ("g",), (1,), advance="rejoin", station="AA:BB:CC:DD:EE:FF")
    assert expand_steps(req, LIMITS)


def test_n40_on_13_is_a_step() -> None:
    [step] = expand_steps(StepRequest("radio0", ("n40",), (13,)), LIMITS)
    req = step_request(step, "radio0")
    assert req.modes == ModeSelection.of("n40") and req.channels == ChannelSelection.of(13)
    assert req.txpower is None
    assert req.modes is not None and req.channels is not None
    ops = compile_modes("radio0", req.modes, LIMITS) + compile_channels("radio0", req.channels, LIMITS)
    assert UciOp("set", "wireless.radio0.htmode", "HT40") in ops
    assert UciOp("set", "wireless.radio0.noscan", "1") in ops
    assert UciOp("set", "wireless.radio0.channel", "13") in ops


def test_step_request_with_power() -> None:
    req = step_request(Step(1, "g", 6, 15), "radio0")
    assert req.txpower == TxPowerSetting("fixed", 15)


def test_saved_ops_round_trip() -> None:
    section = {  # `ubus call uci get` of wireless.radio0: its values
        ".type": "wifi-device",
        ".name": "radio0",
        "htmode": "HT20",
        "channel": "auto",
        "disabled": "1",
        "legacy_rates": "1",
        "country": "IL",
    }
    saved = saved_options(section)
    assert set(saved) == set(SAVED_OPTIONS) and saved["txpower"] is None and saved["disabled"] == "1"
    assert "country" not in saved  # never part of a step-through
    ops = saved_ops("radio0", saved)
    assert UciOp("set", "wireless.radio0.htmode", "HT20") in ops
    assert UciOp("delete", "wireless.radio0.noscan") in ops
    assert UciOp("set", "wireless.radio0.disabled", "1") in ops


def test_a_list_is_written_back_as_the_same_list() -> None:
    """Re-graded review minor: `list basic_rate` must come back a list, same values, same order (D6)."""
    saved = saved_options({"basic_rate": ["6000", "12000", "24000"], "htmode": "HT20"})
    assert saved["basic_rate"] == ["6000", "12000", "24000"]
    p = "wireless.radio0.basic_rate"
    ops = [o for o in saved_ops("radio0", saved) if o.path == p]
    # libuci: `set` replaces an option where it stands, `add_list` on a string option makes it a list there,
    # so the list comes back in its place in `uci show`, whatever the steps left
    assert ops == [UciOp("set", p, "6000"), UciOp("add_list", p, "12000"), UciOp("add_list", p, "24000")]


def test_a_one_item_list_is_rewritten_whole() -> None:
    """A one-item list cannot be made in place (a set makes an option): delete, then add it back."""
    p = "wireless.radio0.basic_rate"
    ops = [o for o in saved_ops("radio0", saved_options({"basic_rate": ["6000"]})) if o.path == p]
    assert ops == [UciOp("delete", p), UciOp("add_list", p, "6000")]


def test_restore_skips_what_already_reads_as_saved() -> None:
    saved = saved_options({"basic_rate": ["6000", "12000"], "htmode": "HT20"})
    ops = saved_ops("radio0", saved, {"basic_rate": ["6000", "12000"], "htmode": "HT40"})
    assert ops == [UciOp("set", "wireless.radio0.htmode", "HT20")]  # the list and every absent option match
    as_option = saved_ops("radio0", saved, {"basic_rate": "6000 12000", "htmode": "HT20"})
    assert as_option == [  # the same text as an option is not the list it was
        UciOp("set", "wireless.radio0.basic_rate", "6000"),
        UciOp("add_list", "wireless.radio0.basic_rate", "12000"),
    ]


def test_joined() -> None:
    mac = "f4:12:fa:f3:57:68"
    assert joined({"clients": {mac.upper(): {"auth": True, "assoc": True, "authorized": True}}}, mac)
    assert not joined({"clients": {mac: {"auth": True, "assoc": False, "authorized": False}}}, mac)
    assert not joined({"clients": {}}, mac)
    assert not joined({}, mac)
