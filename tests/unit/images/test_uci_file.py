"""images/uci_file.py: a /etc/config file read into the form `uci show <config>` gives (parse_uci_show)."""

from __future__ import annotations

from openwrtgui.images.uci_file import parse_uci_file
from openwrtgui.uci import parse_uci_show

DHCP_FILE = """
# a comment
config dnsmasq
\toption domainneeded '1'
\toption local '/lan/'
\tlist server '/bench/192.168.1.1'
\tlist server '8.8.8.8'

config dhcp 'lan'
\toption interface 'lan'
\toption ignore 1

config dhcp
\toption interface "wan"

config host
\toption name 'panel'
\toption comment 'it'\\''s the panel'
"""

# what `uci show dhcp` prints for the same file on a router
DHCP_SHOW = """dhcp.@dnsmasq[0]=dnsmasq
dhcp.@dnsmasq[0].domainneeded='1'
dhcp.@dnsmasq[0].local='/lan/'
dhcp.@dnsmasq[0].server='/bench/192.168.1.1' '8.8.8.8'
dhcp.lan=dhcp
dhcp.lan.interface='lan'
dhcp.lan.ignore='1'
dhcp.@dhcp[1]=dhcp
dhcp.@dhcp[1].interface='wan'
dhcp.@host[0]=host
dhcp.@host[0].name='panel'
dhcp.@host[0].comment='it'\\''s the panel'
"""


def test_uci_file_matches_uci_show() -> None:
    assert parse_uci_file("dhcp", DHCP_FILE) == parse_uci_show(DHCP_SHOW)


def test_quote_inside_a_value() -> None:
    got = parse_uci_file("led", "config internet_led 'main'\n\toption comment 'it'\\''s the green LED'\n")
    assert got == {"led.main": "internet_led", "led.main.comment": "it's the green LED"}


def test_lines_that_are_not_uci_are_skipped() -> None:
    text = (
        "config x 'a'\n\toption good 'yes'\n\toption broken 'unterminated\nnonsense line\n\toption next '2'\n"
    )
    assert parse_uci_file("c", text) == {"c.a": "x", "c.a.good": "yes", "c.a.next": "2"}


def test_option_before_any_section_is_skipped() -> None:
    assert parse_uci_file("c", "option stray '1'\nconfig t\n\toption a 'b'\n") == {
        "c.@t[0]": "t",
        "c.@t[0].a": "b",
    }
