from openwrtgui.probe.describe import describe_router, propose_port_labels, summarize
from openwrtgui.transport.fake import ReplayTransport


async def test_ap2_self_description(ap2_transport: ReplayTransport) -> None:
    d = await describe_router(ap2_transport)
    assert d.identity.board_name == "dlink,dwr-921-c3-uboot"
    assert d.identity.revision == "r35692-b8bffeefdf"
    assert d.identity.target == "ramips/mt7620"
    assert d.board and d.board.model_name == "D-Link DWR-921 C3 (U-Boot)"
    assert propose_port_labels(d.board) == {
        0: "LAN4",
        1: "LAN3",
        2: "LAN2",
        3: "LAN1",
        4: "WAN",
        6: "CPU (eth0)",
    }
    assert d.board.radios[0].modes == ("NOHT", "HT20", "HT40") and d.board.radios[0].max_width == 40
    assert {
        "network.wireless",
        "iwinfo",
        "luci",
        "luci-rpc",
        "hostapd",
        "system",
        "uci",
        "file",
        "session",
    } <= (d.services.keys())
    assert d.services["network.wireless"]["get_validate"] == {"device": "String"}
    assert set(d.protocols) == {"dhcp", "dhcpv6", "ppp", "pppoe", "qmi", "static", "wwan"}
    assert len(d.protocols["qmi"]) == 25 and len(d.protocols["static"]) == 9
    assert {k: len(v) for k, v in d.wireless_options["radio0"].items()} == {
        "device": 155,
        "interface": 289,
        "station": 4,
        "vlan": 9,
    }
    assert d.features and d.features["hostapd"]["sae"] is True
    assert d.luci and set(d.luci.packages) == {
        "luci-app-firewall",
        "luci-base",
        "luci-mod-network",
        "luci-mod-status",
        "luci-mod-system",
    }
    assert d.luci.menu_entries == 62
    assert d.root_password == "set"


async def test_summary_counts(ap2_transport: ReplayTransport) -> None:
    s = summarize(await describe_router(ap2_transport))
    assert s.wireless_options == {"radio0": {"device": 155, "interface": 289, "station": 4, "vlan": 9}}
    assert s.protocols["qmi"] == 25
    assert s.luci_packages == 5 and s.luci_menu_entries == 62
    assert s.model == "D-Link DWR-921 C3 (U-Boot)"
    assert s.features_on["sae"] is True and s.features_on["swconfig"] is True
