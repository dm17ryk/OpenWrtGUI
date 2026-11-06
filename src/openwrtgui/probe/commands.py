"""Exact read-only commands the probe and the status reader send (also the recording set)."""

from __future__ import annotations

from openwrtgui.transport.base import ubus_command

RELEASE = "cat /etc/openwrt_release"
BOARD_JSON = "cat /etc/board.json"
UBUS_LIST = "ubus -v list"
SYSTEM_BOARD = ubus_command("system", "board")
SYSTEM_INFO = ubus_command("system", "info")
FEATURES = ubus_command("luci", "getFeatures")
PROTO_HANDLERS = ubus_command("network", "get_proto_handlers")
WIRELESS_STATUS = ubus_command("network.wireless", "status")
IFACE_DUMP = ubus_command("network.interface", "dump")
DHCP_LAN = ubus_command("uci", "get", {"config": "dhcp", "section": "lan"})
LUCI_MENU = 'for f in /usr/share/luci/menu.d/*.json; do [ -e "$f" ] && { echo "=== $f"; cat "$f"; }; done'
LUCI_ACL = 'for f in /usr/share/rpcd/acl.d/*.json; do [ -e "$f" ] && { echo "=== $f"; cat "$f"; }; done'
# The app's fault records (spec 7.7): one JSON line per armed fault, gone at reboot like the faults
FAULT_RECORDS = "cat /tmp/owg/fault-*.json 2>/dev/null"
ROOT_PASSWORD_STATE = 'awk -F: \'$1=="root"{print ($2=="" ? "none" : "set")}\' /etc/shadow'


def wireless_validate(radio: str) -> str:
    return ubus_command("network.wireless", "get_validate", {"device": radio})


def iwinfo_info(ifname: str) -> str:
    return ubus_command("iwinfo", "info", {"device": ifname})


def iwinfo_assoclist(ifname: str) -> str:
    return ubus_command("iwinfo", "assoclist", {"device": ifname})


DESCRIBE_COMMANDS: tuple[str, ...] = (
    RELEASE,
    BOARD_JSON,
    UBUS_LIST,
    SYSTEM_BOARD,
    FEATURES,
    PROTO_HANDLERS,
    LUCI_MENU,
    LUCI_ACL,
    ROOT_PASSWORD_STATE,
)
STATUS_COMMANDS: tuple[str, ...] = (SYSTEM_INFO, WIRELESS_STATUS, IFACE_DUMP, DHCP_LAN)
