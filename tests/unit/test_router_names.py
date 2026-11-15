"""Router-reported names reach a command only checked, in every builder (v1.0b1 D5, final review)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from openwrtgui.net import commands as net
from openwrtgui.transport.base import ubus_command
from openwrtgui.wifi.compile import reload_command
from openwrtgui.wifi.state import dev_info_command, phy_info_command

BAD = ["phy0;reboot", "-h", "a b", "x$(id)"]
BUILDERS: list[Callable[[str], str]] = [
    net.swconfig_show,
    net.swconfig_help,
    net.swconfig_arl,
    phy_info_command,
    dev_info_command,
]


@pytest.mark.parametrize("bad", BAD)
@pytest.mark.parametrize("build", BUILDERS, ids=lambda b: b.__name__)
def test_an_interface_builder_refuses_a_name_that_is_not_one(build: Callable[[str], str], bad: str) -> None:
    with pytest.raises(ValueError, match="is not an interface name"):
        build(bad)


def test_the_wifi_reload_refuses_a_radio_that_is_not_a_name() -> None:
    with pytest.raises(ValueError, match="is not a radio name"):
        reload_command("radio0; reboot")


@pytest.mark.parametrize("obj", ["hostapd.phy0-ap0;reboot", "hostapd.a b", "-x", "hostapd.$(id)"])
def test_a_ubus_object_that_is_not_a_name_is_refused(obj: str) -> None:
    with pytest.raises(ValueError, match="is not a ubus object"):
        ubus_command(obj, "get_clients")


def test_honest_names_build_the_same_commands() -> None:
    """The recordings replay by exact text: nothing changes for a name that passes."""
    assert net.swconfig_show("switch0") == "swconfig dev switch0 show"
    assert phy_info_command("phy0") == "iw phy phy0 info"
    assert dev_info_command("phy0-ap0") == "iw dev phy0-ap0 info"
    assert reload_command("radio0") == "wifi down radio0; wifi up radio0"
    assert ubus_command("hostapd.phy0-ap0", "get_clients") == "ubus call hostapd.phy0-ap0 get_clients"
    assert ubus_command("network.interface.lan", "status") == "ubus call network.interface.lan status"
