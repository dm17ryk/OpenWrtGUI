"""DNS settings (dnsmasq), static routes and policy rules, with the live routing table (sim ap2)."""

from __future__ import annotations

from dataclasses import replace

import pytest
from netenv import NetEnv

from openwrtgui.net.dns import DnsRequest
from openwrtgui.net.model import Family, LiveRoute, LiveRule, RouteConf, RuleConf
from openwrtgui.net.routes import LiveTables, RouteRequest, RuleRequest, expectations, read_live
from openwrtgui.transport.base import CommandResult

D = "dhcp.cfg01411c"
P = "uci -P /var/run/rpcd/uci-<session>"


async def test_forwarders_and_domain_plan(net: NetEnv) -> None:
    plan = await net.service.plan_dns(
        "ap2", DnsRequest(forwarders=("8.8.8.8", "/bench/192.168.1.1"), domain="bench")
    )
    assert plan.lines == (
        "set -e",
        f"uci set {D}.local='/bench/'",
        f"uci set {D}.domain='bench'",
        f"uci add_list {D}.server='8.8.8.8'",
        f"uci add_list {D}.server='/bench/192.168.1.1'",
        "uci commit dhcp",
        "/etc/init.d/dnsmasq reload",
    )


async def test_override_switches_and_bad_server_refused(net: NetEnv) -> None:
    plan = await net.service.plan_dns(
        "ap2",
        DnsRequest(overrides=(("panel.lan", "192.168.1.30"),), switches={"logqueries": True}, cachesize=500),
    )
    assert f"uci add_list {D}.address='/panel.lan/192.168.1.30'" in plan.lines
    assert f"uci set {D}.logqueries='1'" in plan.lines and f"uci set {D}.cachesize='500'" in plan.lines
    with pytest.raises(ValueError, match=r"8\.8\.8 is not a DNS server \(IP, IP#port or /domain/IP\)"):
        await net.service.plan_dns("ap2", DnsRequest(forwarders=("8.8.8",)))
    with pytest.raises(ValueError, match="nosuchswitch is not a DNS switch"):
        await net.service.plan_dns("ap2", DnsRequest(switches={"nosuchswitch": True}))


async def test_other_option_set_and_delete(net: NetEnv) -> None:
    plan = await net.service.plan_dns(
        "ap2", DnsRequest(others={"ednspacket_max": "1280", "filter_aaaa": None})
    )
    assert (
        f"uci set {D}.ednspacket_max='1280'" in plan.lines and f"uci -q delete {D}.filter_aaaa" in plan.lines
    )
    with pytest.raises(ValueError, match="Use the server control for server"):
        await net.service.plan_dns("ap2", DnsRequest(others={"server": "1.1.1.1"}))


async def test_apply_dns_verifies(net: NetEnv) -> None:
    result = await net.service.apply_dns("ap2", DnsRequest(forwarders=("1.1.1.1",)))
    assert result.verified and [c.name for c in result.checks] == ["saved", "dnsmasq"]


async def test_add_route_plan_rolls_back(net: NetEnv) -> None:
    req = RouteRequest(None, "route", "lan", "10.10.0.0/16", gateway="192.168.1.1")
    plan = await net.service.plan_routes("ap2", [req], [], [], [])
    assert plan.rollback
    assert f"r1=$({P} add network route)" in plan.lines
    assert f"{P} set network.$r1.target='10.10.0.0/16'" in plan.lines
    assert f"{P} set network.$r1.gateway='192.168.1.1'" in plan.lines


async def test_route_verified_in_live_table(net: NetEnv) -> None:
    req = RouteRequest(None, "route", "lan", "10.10.0.0/16", gateway="192.168.1.1", metric=5)
    result = await net.service.apply_routes("ap2", [req], [], [], [])
    assert result.applied and result.verified, result
    assert [c.name for c in result.checks] == ["reconnected", "confirmed", "route 10.10.0.0/16"]
    live = await net.service.live_routes("ap2")
    assert any(r.dst == "10.10.0.0/16" and r.metric == 5 for r in live.routes)
    section = (await net.service.state("ap2")).routes[0].section
    gone = await net.service.apply_routes("ap2", [], [section], [], [])
    assert gone.verified and not any(
        r.dst == "10.10.0.0/16" for r in (await net.service.live_routes("ap2")).routes
    )


async def test_route_refusals(net: NetEnv) -> None:
    with pytest.raises(ValueError, match="10.10.0.0/40 is not an IPv4 network"):
        await net.service.plan_routes("ap2", [RouteRequest(None, "route", "lan", "10.10.0.0/40")], [], [], [])
    with pytest.raises(ValueError, match="There is no interface named lan9"):
        await net.service.plan_routes(
            "ap2", [RouteRequest(None, "route", "lan9", "10.10.0.0/16")], [], [], []
        )
    with pytest.raises(ValueError, match="10.10.0.0/16 is not an IPv6 network"):
        await net.service.plan_routes(
            "ap2", [RouteRequest(None, "route6", "lan", "10.10.0.0/16")], [], [], []
        )
    with pytest.raises(ValueError, match="192.168.1 is not an IPv4 address"):
        await net.service.plan_routes(
            "ap2", [RouteRequest(None, "route", "lan", "10.10.0.0/16", gateway="192.168.1")], [], [], []
        )


async def test_rule_by_priority(net: NetEnv) -> None:
    rule = RuleRequest(None, "rule", src="192.168.5.0/24", lookup="100", priority=90)
    result = await net.service.apply_routes("ap2", [], [], [rule], [])
    assert result.verified and result.checks[-1].name == "rule 90"
    assert any(
        r.priority == 90 and r.src == "192.168.5.0/24" for r in (await net.service.live_routes("ap2")).rules
    )


def _live(*routes: LiveRoute, rules: tuple[LiveRule, ...] = ()) -> LiveTables:
    return LiveTables(routes, rules, None)


def _r(dst: str, gateway: str | None = None, dev: str = "br-lan", family: Family = 4) -> LiveRoute:
    return LiveRoute(family, dst, gateway, dev, "main", "static", None, "unicast")


async def test_route_checks_read_targets_as_ip_prints_them(net: NetEnv) -> None:
    """`ip -j route` prints the default route as "default", a host route without its prefix, a network
    in its network form, and addresses in lower case."""
    state = await net.service.state("ap2")

    def holds(req: RouteRequest, live: LiveTables) -> bool:
        (want,) = expectations(state, [req], [], [], [])
        return want.holds(live)

    gw = "192.168.1.1"
    assert holds(RouteRequest(None, "route", "lan", "0.0.0.0/0", gateway=gw), _live(_r("default", gw)))
    assert holds(RouteRequest(None, "route", "lan", "10.10.0.1/16"), _live(_r("10.10.0.0/16")))
    assert holds(RouteRequest(None, "route", "lan", "10.9.9.9/32"), _live(_r("10.9.9.9")))
    six = RouteRequest(None, "route6", "lan", "fd00:9::/64", gateway="FD00::1")
    assert holds(six, _live(_r("fd00:9::/64", "fd00::1", family=6)))
    assert not holds(RouteRequest(None, "route", "lan", "0.0.0.0/0"), _live(_r("default", family=6)))


async def test_a_deleted_host_route_is_gone_only_when_ip_no_longer_shows_it(net: NetEnv) -> None:
    host = RouteConf("cfgabc123", "route", "lan", "10.9.9.9/32", None, None, None, None, False)
    state = replace(await net.service.state("ap2"), routes=(host,))
    (want,) = expectations(state, [], ["cfgabc123"], [], [])
    assert not want.holds(_live(_r("10.9.9.9")))
    assert want.holds(_live())


async def test_a_route_over_pppoe_is_matched_on_the_kernel_device(net: NetEnv) -> None:
    state = await net.service.state("ap2")
    wan = next(v for v in state.interfaces if v.conf is not None and v.conf.name == "wan")
    assert wan.live is not None
    pppoe = replace(wan, live=replace(wan.live, device="eth0.2", l3_device="pppoe-wan"))
    state = replace(state, interfaces=tuple(pppoe if v is wan else v for v in state.interfaces))
    (want,) = expectations(state, [RouteRequest(None, "route", "wan", "10.20.0.0/16")], [], [], [])
    assert want.holds(_live(_r("10.20.0.0/16", dev="pppoe-wan")))


async def test_a_deleted_rule_is_matched_in_its_own_family(net: NetEnv) -> None:
    rule = RuleConf("cfgdef456", "rule", "10.9.0.0/24", None, None, None, "main", 100, None, False)
    state = replace(await net.service.state("ap2"), rules=(rule,))
    (want,) = expectations(state, [], [], [], ["cfgdef456"])
    assert want.holds(_live(rules=(LiveRule(6, 100, None, "main"),)))  # only an IPv6 rule has 100 now
    assert not want.holds(_live(rules=(LiveRule(4, 100, "10.9.0.0/24", "main"),)))


async def test_live_tables_fallback_to_text(net: NetEnv) -> None:
    class NoJson:
        async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
            if command.startswith("ip -j"):
                return CommandResult(command, "", 'Option "-j" is unknown\n', 255)
            return CommandResult(command, "192.168.1.0/24 dev br-lan scope link\n", "", 0)

    live = await read_live(NoJson())  # type: ignore[arg-type]
    assert live.routes == () and live.raw is not None and "192.168.1.0/24 dev br-lan" in live.raw
