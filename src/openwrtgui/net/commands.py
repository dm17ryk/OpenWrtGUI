"""The reads of the Network & DHCP and Ports screens (plan v0.3, "Reads"): one exec each, exact text.

Recordings key on the text, so the recorder and the app take these strings from here.
"""

from __future__ import annotations

from openwrtgui.net.model import Family
from openwrtgui.transport.base import ubus_command

UCI_NETWORK = "uci -X show network"
UCI_DHCP = "uci -X show dhcp"
INTERFACE_DUMP = "ubus call network.interface dump"
DEVICE_STATUS = "ubus call network.device status"
LEASES = "ubus call luci-rpc getDHCPLeases"
HOST_HINTS = "ubus call luci-rpc getHostHints"
SSH_CONNECTION = 'echo "$SSH_CONNECTION"'
ARP = "cat /proc/net/arp"
SERVICES = ("dnsmasq", "odhcpd", "wifi-mirror")


def ip_routes(family: Family) -> str:
    return f"ip -j -{family} route show table all"


def ip_rules(family: Family) -> str:
    return f"ip -j -{family} rule show"


def swconfig_show(switch: str) -> str:
    return f"swconfig dev {switch} show"


def swconfig_help(switch: str) -> str:
    return f"swconfig dev {switch} help"


def swconfig_arl(switch: str) -> str:
    return f"swconfig dev {switch} get arl_table"


def switch_features(switch: str) -> str:
    return ubus_command("luci", "getSwconfigFeatures", {"switch": switch})


def service_list(name: str) -> str:
    return ubus_command("service", "list", {"name": name})


def network_reads(switch: str) -> tuple[str, ...]:
    return (
        UCI_NETWORK,
        UCI_DHCP,
        INTERFACE_DUMP,
        DEVICE_STATUS,
        LEASES,
        HOST_HINTS,
        SSH_CONNECTION,
        ARP,
        ip_routes(4),
        ip_routes(6),
        ip_rules(4),
        ip_rules(6),
        swconfig_show(switch),
        swconfig_help(switch),
        swconfig_arl(switch),
        switch_features(switch),
        *(service_list(name) for name in SERVICES),
    )
