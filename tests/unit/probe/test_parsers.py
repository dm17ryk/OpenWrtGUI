import json

from openwrtgui.probe.board import parse_board_json
from openwrtgui.probe.identity import parse_release
from openwrtgui.probe.ubus_list import parse_ubus_list

UBUS_LIST = """'network.wireless' @7750b8d7
\t"up":{"device":"String"}
\t"get_validate":{"device":"String"}
'luci-rpc' @03ccfbb3
\t"getBoardJSON":{}
"""


def test_parse_ubus_list() -> None:
    assert parse_ubus_list(UBUS_LIST) == {
        "network.wireless": {"up": {"device": "String"}, "get_validate": {"device": "String"}},
        "luci-rpc": {"getBoardJSON": {}},
    }


def test_parse_release() -> None:
    text = "DISTRIB_ID='OpenWrt'\nDISTRIB_REVISION='r35692-b8bffeefdf'\nDISTRIB_TARGET='ramips/mt7620'\n"
    assert parse_release(text) == {
        "DISTRIB_ID": "OpenWrt",
        "DISTRIB_REVISION": "r35692-b8bffeefdf",
        "DISTRIB_TARGET": "ramips/mt7620",
    }


def test_board_without_switch_or_wlan() -> None:
    b = parse_board_json(json.dumps({"model": {"id": "x,y", "name": "X Y"}}))
    assert (b.model_id, b.model_name, b.switch_name, b.ports, b.radios, b.leds) == (
        "x,y",
        "X Y",
        None,
        (),
        (),
        (),
    )


def test_board_ports_and_leds() -> None:
    board = {
        "model": {"id": "a", "name": "A"},
        "led": {"lan": {"name": "lan", "sysfs": "green:lan"}},
        "switch": {
            "switch0": {
                "ports": [
                    {"num": 0, "role": "lan", "index": 4},
                    {"num": 4, "role": "wan"},
                    {"num": 6, "device": "eth0"},
                ]
            }
        },
    }
    b = parse_board_json(json.dumps(board))
    assert b.switch_name == "switch0"
    assert [(p.num, p.label, p.cpu) for p in b.ports] == [
        (0, "LAN4", False),
        (4, "WAN", False),
        (6, "CPU (eth0)", True),
    ]
    assert b.leds[0].sysfs == "green:lan"
