import pytest

from openwrtgui.guard.readonly import is_read_only_command

ALLOWED = [
    "uci show wireless",
    "iw dev",
    "iw phy phy0 info",
    "ubus call system board",
    "ubus -v list",
    "nft list ruleset",
    "logread | tail -n 50",
    "ip addr show br-lan",
    "cat /etc/board.json",
    "tc -s qdisc show dev br-lan",
    "swconfig dev switch0 show",
    "iwinfo phy0-ap0 assoclist",
    "ps w",
    'ubus call network.wireless get_validate \'{"device":"radio0"}\'',
    "top -bn1",
    "uci get dhcp.lan.ignore",
    "awk -F: '{print $1}' /etc/passwd",
    "find /etc -name '*.json'",
]
REFUSED = [
    "awk 'BEGIN{system(\"reboot\")}'",
    "awk '{ \"reboot\" | getline x }' /etc/passwd",
    "sed 'e reboot' /etc/hosts",
    "sed -n 'w /tmp/x' /etc/hosts",
    "find / -fprint /tmp/x",
    "uci set wireless.radio0.channel=6",
    "wifi up",
    "reboot",
    "ip link set eth0 down",
    "iw dev phy0-ap0 set txpower fixed 1000",
    "ubus call network.interface.lan down",
    "nft flush ruleset",
    "echo x > /etc/config/x",
    "cat a; reboot",
    "logread | sh",
    "sed -i s/a/b/ f",
    "$(reboot)",
    "tc qdisc add dev br-lan root netem delay 10ms",
    "find / -delete",
    "cat a && reboot",
    "cat `reboot`",
    "top",
    "",
]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_allowed(cmd: str) -> None:
    assert is_read_only_command(cmd)


@pytest.mark.parametrize("cmd", REFUSED)
def test_refused(cmd: str) -> None:
    assert not is_read_only_command(cmd)
