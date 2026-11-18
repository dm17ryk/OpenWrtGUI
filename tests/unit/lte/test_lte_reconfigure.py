"""Reconfigure (spec 4.4): a saved setup becomes one LTE settings change, only for what differs."""

from __future__ import annotations

from datetime import UTC, datetime

from openwrtgui.forms import OptionEdit, OptionRow
from openwrtgui.lte.at import ModemInfo
from openwrtgui.lte.setups import LteSetup, setup_change

SAVED = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
NAMES = (
    "device",
    "apn",
    "auth",
    "username",
    "password",
    "pincode",
    "pdptype",
    "mtu",
    "metric",
    "defaultroute",
)
CONTROLS = {"device": "Device", "mtu": "MTU", "dhcp": "LTE screen", "autoconnect": "LTE screen"}


def _row(name: str) -> OptionRow:
    return OptionRow(
        config="network",
        group="general",
        section="lte",
        name=name,
        type="string",
        editor="secret" if name in ("password", "pincode") else "text",
        value=None,
        set_in_config=False,
        control=CONTROLS.get(name),
        writer=None,
    )


ROWS = [_row(n) for n in (*NAMES, "dhcp", "autoconnect", "delay")]
ROUTER = {"device": "/dev/cdc-wdm0", "apn": "test-apn", "auth": "none", "pdptype": "ipv4", "mtu": "1420"}


def _setup(**options: str) -> LteSetup:
    return LteSetup(
        router_id="ap2", router_name="AP2 · office", saved_at=SAVED, modem=ModemInfo(), options=options
    )


def test_same_router_restores_only_what_differs() -> None:
    change = setup_change(
        _setup(**{**ROUTER, "apn": "test-apn"}), ROWS, {**ROUTER, "apn": "other"}, same_router=True
    )
    assert change.settings.apn == "test-apn"
    assert (change.settings.auth, change.settings.pdptype, change.settings.mtu) == (None, None, None)
    assert change.settings.edits == ()
    assert (change.skipped, change.kept) == ((), ())


def test_an_option_the_setup_lacks_is_removed() -> None:
    change = setup_change(_setup(**ROUTER), ROWS, {**ROUTER, "metric": "20", "delay": "5"}, same_router=True)
    assert set(change.settings.edits) == {OptionEdit("lte", "metric", None), OptionEdit("lte", "delay", None)}


def test_a_named_text_option_the_setup_lacks_is_removed() -> None:
    change = setup_change(_setup(**ROUTER), ROWS, {**ROUTER, "username": "someone"}, same_router=True)
    assert change.settings.username == ""


def test_an_mtu_the_setup_lacks_stays_and_is_named() -> None:
    """The Settings card sets the MTU but cannot remove it, so neither can Reconfigure (ledger ruling)."""
    lacking = {k: v for k, v in ROUTER.items() if k != "mtu"}
    change = setup_change(_setup(**lacking), ROWS, ROUTER, same_router=True)
    assert change.settings.mtu is None and change.kept == ("mtu",)


def test_another_routers_setup_keeps_the_target_pin() -> None:
    change = setup_change(
        _setup(**ROUTER, pincode="1234"), ROWS, {**ROUTER, "pincode": "5678"}, same_router=False
    )
    assert change.settings.pincode is None


def test_the_same_routers_setup_puts_its_pin_back() -> None:
    change = setup_change(_setup(**ROUTER, pincode="1234"), ROWS, ROUTER, same_router=True)
    assert change.settings.pincode == "1234"


def test_device_is_never_changed() -> None:
    change = setup_change(_setup(**{**ROUTER, "device": "/dev/cdc-wdm1"}), ROWS, ROUTER, same_router=True)
    assert (
        change.settings.edits == ()
        and change.settings == setup_change(_setup(**ROUTER), ROWS, ROUTER, same_router=True).settings
    )


def test_an_option_without_a_row_is_named_not_written() -> None:
    change = setup_change(_setup(**ROUTER, v6apn="test-apn6"), ROWS, ROUTER, same_router=True)
    assert change.skipped == ("v6apn",)
    assert all(e.name != "v6apn" for e in change.settings.edits)


def test_numbers_and_switches_go_through_their_fields() -> None:
    change = setup_change(
        _setup(**{**ROUTER, "mtu": "1400", "metric": "10", "auto": "0", "defaultroute": "0"}),
        ROWS,
        {**ROUTER, "metric": "20"},
        same_router=True,
    )
    s = change.settings
    assert (s.mtu, s.metric, s.auto, s.defaultroute) == (1400, 10, False, False)
