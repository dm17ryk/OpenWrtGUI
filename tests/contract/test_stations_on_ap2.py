"""Station management against AP2's recorded hostapd (wifi_on.json): its ubus methods (v1.2b R8, R11). The
window's recorded notifications join this file (Task 12) and settle R10."""

from pathlib import Path

from openwrtgui.tools.stations import HOSTAPD_LIST, METHODS, hostapd_methods
from openwrtgui.transport.fake import load_commands

AP2 = Path(__file__).resolve().parents[1] / "fixtures" / "ap2"


def test_hostapd_has_the_five_methods_on_ap2() -> None:
    text = load_commands(AP2 / "wifi_on.json")[HOSTAPD_LIST].stdout
    assert hostapd_methods(text) == {"phy0-ap0": list(METHODS)}
