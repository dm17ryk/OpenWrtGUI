from __future__ import annotations

import pytest

from conftest import WifiEnv
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.transport.base import CommandResult, Transport, Unreachable
from openwrtgui.wifi.model import ChannelSelection, ModeSelection, RadioRequest, SsidRequest, TxPowerSetting

N20_CH6 = RadioRequest("radio0", modes=ModeSelection.of("n20"), channels=ChannelSelection.of(6))
MCS16 = " ".join(str(i) for i in range(16))


async def test_state_reads_ap2_as_parked_ht40_auto_with_dima_night_badges(env: WifiEnv) -> None:
    state = await env.service.state("ap2")
    [radio] = state.radios
    assert radio.name == "radio0" and radio.band == "2g" and not radio.up and radio.disabled
    assert radio.channels.kind == "none" and radio.modes.kind == "auto" and radio.txpower.kind == "auto"
    assert radio.limits.channels == tuple(range(1, 14)) and radio.limits.max_htmode == "HT40"
    assert radio.limits.txpower_dbm[-1] == 20 and radio.limits.mcs == tuple(range(16))
    assert radio.limits.phy == "phy0" and radio.limits.country == "IL" and radio.legacy_rates
    assert radio.writers == {
        "country": "dima_night",
        "cell_density": "dima_night",
        "legacy_rates": "dima_night",
    }
    assert radio.mask == "none" and radio.actual is None
    [ssid] = radio.ssids
    assert ssid.section == "default_radio0" and ssid.ssid == "OpenWrt" and ssid.security == "wpa2"
    assert ssid.key_set and ssid.ifname is None


async def test_state_of_ap1_on_air(env: WifiEnv) -> None:
    [radio] = (await env.service.state("ap1")).radios
    assert (
        radio.up and radio.channels == ChannelSelection.of(1) and radio.txpower == TxPowerSetting("fixed", 20)
    )
    assert radio.actual is not None and radio.actual.channel == 1 and radio.ssids[0].ifname == "phy0-ap0"


async def test_plan_shows_exact_lines_and_unpark_warning(env: WifiEnv) -> None:
    plan = await env.service.plan("ap2", N20_CH6)
    assert list(plan.lines) == [
        "uci set wireless.radio0.htmode='HT20'",
        "uci set wireless.radio0.legacy_rates='0'",
        "uci set wireless.radio0.supported_rates='6000 12000 24000'",
        "uci set wireless.radio0.basic_rate='6000 12000 24000'",
        "uci set wireless.radio0.channel='6'",
        "uci set wireless.radio0.disabled='0'",
        "uci commit wireless",
        "wifi down radio0; wifi up radio0",
        f"iw dev <AP interface of radio0> set bitrates legacy-2.4 6 ht-mcs-2.4 {MCS16}",
    ]
    assert plan.warnings == (
        "OpenWrt is already on air on AP1 · bench. The bench rule is one radio on air per SSID.",
    )
    assert (
        plan.expect.radio_up
        and plan.expect.channels == frozenset({6})
        and plan.expect.widths == frozenset({20})
    )
    assert plan.expect.beacon_mbps == 6.0


async def test_apply_verifies_on_air_and_audits(env: WifiEnv) -> None:
    result = await env.service.apply("ap2", N20_CH6)
    assert result.applied and result.verified and result.error is None
    assert [(c.name, c.ok) for c in result.checks] == [
        ("radio", True),
        ("channel", True),
        ("width", True),
        ("TX power", True),
        ("TX mask", True),
        ("beacon rate", True),
    ]
    assert next(c for c in result.checks if c.name == "beacon rate").detail == "6.0 Mb/s ×5"
    lines = env.audit_lines()
    assert lines[0][0].startswith("uci set wireless.radio0.htmode='HT20'\n") and lines[0][1] == "user"
    assert lines[1:] == [
        (f"iw dev phy0-ap0 set bitrates legacy-2.4 6 ht-mcs-2.4 {MCS16}", "app"),
        ("iw phy phy0 interface add owgmon0 type monitor && ip link set owgmon0 up", "app"),
        (
            "timeout 5 tcpdump -i owgmon0 -e -n -c 5 -l "
            "'type mgt subtype beacon and wlan addr2 02:00:00:00:00:02'",
            "app",
        ),
        ("ip link del owgmon0", "app"),
        ("verify radio0", "app"),
    ]
    assert env.audit.query()[0].verify == "pass"


async def test_apply_none_parks_and_checks_only_radio(env: WifiEnv) -> None:
    result = await env.service.apply("ap1", RadioRequest("radio0", channels=ChannelSelection.none()))
    assert result.applied and result.verified
    assert [(c.name, c.ok) for c in result.checks] == [
        ("radio", True),
        ("channel", None),
        ("width", None),
        ("TX power", None),
        ("TX mask", None),
        ("beacon rate", None),
    ]
    assert result.checks[1].detail == "not run: radio parked"


async def test_nothing_to_apply_is_a_value_error(env: WifiEnv) -> None:
    with pytest.raises(ValueError, match="Nothing to apply: the router already has these settings."):
        await env.service.plan("ap2", RadioRequest("radio0", channels=ChannelSelection.none()))


async def test_guard_live_refuses_before_any_command(env: WifiEnv) -> None:
    env.go_live()
    with pytest.raises(GuardLocked):
        await env.service.apply("ap2", N20_CH6)
    assert env.audit.query() == []


class _AfterScript:
    """Wraps a transport and does something once the uci script has run."""

    def __init__(self, inner: Transport, env: WifiEnv, mode: str) -> None:
        self._inner, self._env, self._mode, self._done = inner, env, mode, False

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        if self._done and self._mode == "drop" and command.startswith("ubus call network.wireless status"):
            raise Unreachable("192.168.1.2:22: connection lost")
        result = await self._inner.run(command, timeout=timeout)
        if command.startswith("uci set") and "uci commit wireless" in command:
            self._done = True
            if self._mode == "guard":
                self._env.go_live()
        return result

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        (
            "drop",
            "Lost the connection to AP2 · office after the change was committed: "
            "192.168.1.2:22: connection lost",
        ),
        ("guard", "Bench Guard went live after the change was committed: "),
    ],
)
async def test_apply_interrupted_after_commit_is_not_verified(env: WifiEnv, mode: str, error: str) -> None:
    env.wrap.append(lambda t: _AfterScript(t, env, mode))  # type: ignore[arg-type, return-value]
    result = await env.service.apply("ap2", N20_CH6)
    assert result.applied and not result.verified
    assert result.error is not None and result.error.startswith(error)
    assert env.audit_lines()[0][0].startswith("uci set wireless.radio0.htmode='HT20'")


async def test_mask_reported_missing_after_interface_recreated(env: WifiEnv) -> None:
    await env.service.apply("ap2", N20_CH6)
    assert (await env.service.state("ap2")).radios[0].mask == "active"
    t = await env.pool.get(env.routers.get("ap2"))  # type: ignore[arg-type]
    await t.run("wifi down radio0; wifi up radio0")
    assert (await env.service.state("ap2")).radios[0].mask == "missing"
    again = await env.service.plan("ap2", N20_CH6)
    assert list(again.lines) == [f"iw dev phy0-ap0 set bitrates legacy-2.4 6 ht-mcs-2.4 {MCS16}"]
    result = await env.service.apply("ap2", N20_CH6)
    assert result.verified and (await env.service.state("ap2")).radios[0].mask == "active"


async def test_key_never_reaches_preview_or_audit(env: WifiEnv) -> None:
    key = "it's $x `y` z"
    req = RadioRequest("radio0", ssids=(SsidRequest("default_radio0", key=key),))
    plan = await env.service.plan("ap1", req)
    assert plan.lines[0] == "uci set wireless.default_radio0.key='<hidden>'"
    assert all("it's" not in line and "$x" not in line for line in plan.lines)
    result = await env.service.apply("ap1", req)
    assert result.applied
    assert all("$x" not in command for command, _ in env.audit_lines())
    shown = (await (await env.sim("ap1")).run("uci -q show wireless")).stdout
    assert "wireless.default_radio0.key='it'\\''s $x `y` z'" in shown
