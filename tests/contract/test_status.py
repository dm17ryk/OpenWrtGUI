from collections.abc import Callable

from openwrtgui.probe.status import StationInfo, read_status, ssids_on_air
from openwrtgui.transport.fake import ReplayTransport


async def test_ap2_parked(ap2_transport: ReplayTransport) -> None:
    s = await read_status(ap2_transport)
    r = s.radios[0]
    assert (r.name, r.band, r.up, r.disabled, r.channel, r.htmode, r.stations) == (
        "radio0",
        "2g",
        False,
        True,
        "1",
        "HT40",
        (),
    )
    assert next(i for i in s.interfaces if i.name == "lan").ipv4 == ("192.168.1.2/24",)
    assert s.dhcp_server_on is False
    assert ssids_on_air(s) == []
    assert s.uptime_s == 1786118
    assert s.load == (0.16, 0.03, 0.01)
    assert s.mem_total_kb == 55104 and s.mem_available_kb == 7484


async def test_sim_ap1_on_air(sim_transport: Callable[[str], ReplayTransport]) -> None:
    s = await read_status(sim_transport("ap1"))
    r = s.radios[0]
    assert (r.up, r.channel, r.htmode, r.txpower_dbm) == (True, "1", "HT20", 20)
    assert (
        r.ssids[0].name == "OpenWrt" and r.ssids[0].encryption == "psk2" and r.ssids[0].ifname == "phy0-ap0"
    )
    assert r.stations == (StationInfo("f4:12:fa:f3:57:68", -52, 65.0, 54.0, 11520),)
    assert ssids_on_air(s) == ["OpenWrt"]
    assert s.dhcp_server_on is True
    assert next(i for i in s.interfaces if i.name == "lan").ipv4 == ("192.168.1.1/24",)


async def test_interfaces_include_down_ones(ap2_transport: ReplayTransport) -> None:
    s = await read_status(ap2_transport)
    by_name = {i.name: i for i in s.interfaces}
    assert by_name["wan"].up is False and by_name["wan"].proto == "dhcp" and by_name["wan"].ipv4 == ()
    assert by_name["lte"].proto == "qmi"
