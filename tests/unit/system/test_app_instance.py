"""Which dropbear instance the app came in through, also when the interface list cannot be read
(v1.0b2 D9)."""

from __future__ import annotations

import pytest

from openwrtgui.system.access import SshInstance
from openwrtgui.system.access_service import app_instance, app_instance_for_change


def _inst(section: str, interface: str = "", port: int = 22) -> SshInstance:
    return SshInstance(
        section=section,
        enable=True,
        interface=interface,
        direct_interface="",
        port=port,
        password_auth=True,
        root_password_auth=True,
        gateway_ports=False,
    )


def test_with_the_interface_unknown_the_only_instance_on_the_port_is_the_apps() -> None:
    """v0.6c minor (#34): an instance bound to `lan` is still the app's when the interface dump failed."""
    lan = _inst("main", interface="lan")
    assert app_instance([lan, _inst("alt", port=2222)], 22, None, listed=False) == lan
    assert app_instance([lan], 22, "lan") == lan


def test_with_the_interface_unknown_and_two_on_the_port_an_ssh_change_is_refused() -> None:
    both = [_inst("main", interface="lan"), _inst("wan_ssh", interface="wan")]
    assert app_instance(both, 22, None, listed=False) is None
    with pytest.raises(ValueError, match="^Cannot tell which SSH instance this app uses on AP2"):
        app_instance_for_change(both, 22, None, "AP2", listed=False)
    assert app_instance_for_change(both, 22, "lan", "AP2") == both[0]


def test_an_address_on_no_interface_is_not_a_failed_read() -> None:
    """Final review: the dump was read but no interface has the router's address (a hostname, an alias):
    the old rule stands, the instance on every interface is the app's, and nothing is refused."""
    everywhere, wan = _inst("main"), _inst("wan_ssh", interface="wan")
    assert app_instance([everywhere, wan], 22, None) == everywhere
    assert app_instance_for_change([everywhere, wan], 22, None, "AP2") == everywhere
