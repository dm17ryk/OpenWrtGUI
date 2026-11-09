from __future__ import annotations

import json

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
        "set -e",
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
    assert lines[0][0].startswith("set -e\nuci set wireless.radio0.htmode='HT20'\n") and lines[0][1] == "user"
    assert lines[1:] == [
        ("wifi down radio0; wifi up radio0", "user"),
        (f"iw dev phy0-ap0 set bitrates legacy-2.4 6 ht-mcs-2.4 {MCS16}", "app"),
        (
            "iw dev owgmon0 del 2>/dev/null; "
            "iw phy phy0 interface add owgmon0 type monitor && ip link set owgmon0 up",
            "app",
        ),
        (
            "timeout 5 tcpdump -i owgmon0 -e -n -c 5 -l "
            "'type mgt subtype beacon and wlan addr2 02:00:00:00:00:02'",
            "app",
        ),
        ("iw dev owgmon0 del", "app"),
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
        if "uci commit wireless" in command:
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
    assert env.audit_lines()[0][0].startswith("set -e\nuci set wireless.radio0.htmode='HT20'")


class _OnCommand:
    """Wraps a transport and changes what one command does."""

    def __init__(
        self, inner: Transport, match: str, do: str, env: WifiEnv | None = None, *, exact: bool = False
    ) -> None:
        self._inner, self._match, self._do, self._env, self._exact = inner, match, do, env, exact
        self.sent: list[str] = []

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        self.sent.append(command)
        if command == self._match if self._exact else self._match in command:
            if self._do == "drop":
                raise Unreachable("192.168.1.2: no answer within 60 s")
            if self._do == "fail":
                return CommandResult(command, "", "Command failed: Not found", 1)
            if self._do == "guard" and self._env is not None:
                result = await self._inner.run(command, timeout=timeout)
                self._env.go_live()
                return result
        return await self._inner.run(command, timeout=timeout)

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


class _CountryUpdate:
    """AP2, 2026-11-09: netifd reported radio0 up while hostapd was still in COUNTRY_UPDATE. Until the AP
    interface operates, `iw dev X info` shows no channel and `set bitrates` fails."""

    def __init__(self, inner: Transport, polls: int) -> None:
        self._inner, self._polls = inner, polls

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        if self._polls and "set bitrates" in command:
            return CommandResult(command, "", "command failed: Network is down (-100)", 1)
        done = await self._inner.run(command, timeout=timeout)
        if self._polls and command == "iw dev phy0-ap0 info":
            self._polls -= 1
            shown = "\n".join(line for line in done.stdout.splitlines() if "channel" not in line)
            return CommandResult(command, shown, "", 0)
        return done

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


class _RestrictedByIwinfo:
    """AP2, 2026-11-09: iwinfo's freqlist marked channels 6 and 9 restricted (no_ir, indoor_only) while the
    kernel's own list (`iw phy phy0 info`) had them usable."""

    def __init__(self, inner: Transport) -> None:
        self._inner = inner

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        done = await self._inner.run(command, timeout=timeout)
        if command.startswith("ubus call iwinfo freqlist"):
            data = json.loads(done.stdout)
            for f in data["results"]:
                f["restricted"] = f["channel"] in (6, 9)
            return CommandResult(command, json.dumps(data), "", 0)
        return done

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


async def test_the_kernels_channel_list_wins_over_iwinfos_flags(env: WifiEnv) -> None:
    env.wrap.append(lambda t: _RestrictedByIwinfo(t))  # type: ignore[arg-type, return-value]
    [radio] = (await env.service.state("ap2")).radios
    assert radio.limits.channels == tuple(range(1, 14))
    plan = await env.service.plan("ap2", N20_CH6)
    assert "uci set wireless.radio0.channel='6'" in plan.lines


async def test_apply_waits_for_the_ap_interface_to_operate(env: WifiEnv) -> None:
    env.wrap.append(lambda t: _CountryUpdate(t, polls=2))  # type: ignore[arg-type, return-value]
    result = await env.service.apply("ap2", N20_CH6)
    assert result.applied and result.verified, [(c.name, c.detail) for c in result.checks]
    assert next(c for c in result.checks if c.name == "channel").detail == "channel 6"


async def test_the_change_and_the_reload_run_apart_and_a_failing_line_stops_the_commit(env: WifiEnv) -> None:
    plan = await env.service.plan("ap2", N20_CH6)
    assert plan.lines[0] == "set -e"  # a failing uci line stops the script before `uci commit`
    await env.service.apply("ap2", N20_CH6)
    sent = [c for c, _ in env.audit_lines()[:2]]
    assert sent[0].startswith("set -e\nuci set wireless.radio0.htmode='HT20'") and sent[0].endswith(
        "uci commit wireless"
    )
    assert sent[1] == "wifi down radio0; wifi up radio0"


async def test_connection_lost_while_the_change_runs_may_have_committed(env: WifiEnv) -> None:
    env.wrap.append(lambda t: _OnCommand(t, "uci commit wireless", "drop"))  # type: ignore[arg-type, return-value]
    result = await env.service.apply("ap2", N20_CH6)
    assert result.applied and not result.verified
    assert result.error == (
        "Lost the connection to AP2 · office while the change ran; it may have been committed: "
        "192.168.1.2: no answer within 60 s"
    )
    assert env.audit.query()[0].command == "verify radio0" and env.audit.query()[0].verify.startswith("fail")


async def test_a_failed_reload_is_applied_but_not_verified(env: WifiEnv) -> None:
    env.wrap.append(lambda t: _OnCommand(t, "wifi down radio0", "fail"))  # type: ignore[arg-type, return-value]
    result = await env.service.apply("ap2", N20_CH6)
    assert result.applied and not result.verified
    assert result.error == "The radio reload failed after the change was committed: Command failed: Not found"


async def test_monitor_interface_is_removed_even_when_a_run_starts(env: WifiEnv) -> None:
    env.wrap.append(lambda t: _OnCommand(t, "tcpdump", "guard", env))  # type: ignore[arg-type, return-value]
    await env.service.apply("ap2", N20_CH6)
    commands = [c for c, _ in env.audit_lines()]
    assert "iw dev owgmon0 del" in commands


async def test_a_monitor_that_cannot_be_removed_fails_the_beacon_check(env: WifiEnv) -> None:
    # AP2, 2026-11-05: the cleanup failed unnoticed and owgmon0 stayed on the radio.
    env.wrap.append(
        lambda t: _OnCommand(t, "iw dev owgmon0 del", "fail", exact=True)  # type: ignore[arg-type, return-value]
    )
    result = await env.service.apply("ap2", N20_CH6)
    beacon = next(c for c in result.checks if c.name == "beacon rate")
    assert not beacon.ok and beacon.detail == "owgmon0 is still on the radio: Command failed: Not found"
    assert result.applied and not result.verified


async def test_the_monitor_is_removed_when_the_connection_drops_while_adding_it(env: WifiEnv) -> None:
    wrappers: list[_OnCommand] = []

    def wrap(t: Transport) -> _OnCommand:
        wrappers.append(_OnCommand(t, "interface add owgmon0", "drop"))
        return wrappers[-1]

    env.wrap.append(wrap)  # type: ignore[arg-type]
    await env.service.apply("ap2", N20_CH6)
    assert "iw dev owgmon0 del" in wrappers[0].sent


async def test_a_stale_monitor_interface_is_cleared_before_adding_one(env: WifiEnv) -> None:
    await env.service.apply("ap2", N20_CH6)
    commands = [c for c, _ in env.audit_lines()]
    add = "iw phy phy0 interface add owgmon0 type monitor && ip link set owgmon0 up"
    assert f"iw dev owgmon0 del 2>/dev/null; {add}" in commands


async def test_an_options_apply_restores_the_tx_mask(env: WifiEnv) -> None:
    from openwrtgui.wifi.compile import UciOp

    await env.service.apply("ap2", N20_CH6)
    plan = await env.service.plan_ops("ap2", "radio0", [UciOp("set", "wireless.radio0.beacon_int", "200")])
    assert plan.lines[-1] == f"iw dev phy0-ap0 set bitrates legacy-2.4 6 ht-mcs-2.4 {MCS16}"
    result = await env.service.apply_ops("ap2", "radio0", [UciOp("set", "wireless.radio0.beacon_int", "200")])
    assert result.verified and (await env.service.state("ap2")).radios[0].mask == "active"


async def test_only_this_radios_ssids_can_be_changed(env: WifiEnv) -> None:
    req = RadioRequest("radio0", ssids=(SsidRequest("x; reboot; #", ssid="a"),))
    with pytest.raises(ValueError, match="x; reboot; # is not an SSID of radio0"):
        await env.service.plan("ap2", req)
    with pytest.raises(ValueError, match="radio0 is not an SSID of radio0"):
        await env.service.plan("ap2", RadioRequest("radio0", ssids=(SsidRequest("radio0", ssid="a"),)))


async def test_apply_sends_only_what_was_previewed(env: WifiEnv) -> None:
    from openwrtgui.wifi.service import PreviewChanged

    preview = await env.service.plan("ap2", N20_CH6)
    t = await env.pool.get(env.routers.get("ap2"))  # type: ignore[arg-type]
    await t.run("uci set wireless.radio0.channel='6'\nuci commit wireless")  # someone else, meanwhile
    with pytest.raises(PreviewChanged, match="AP2 · office changed since the preview"):
        await env.service.apply("ap2", N20_CH6, digest=preview.digest)
    assert env.audit.query() == []  # nothing was sent
    fresh = await env.service.plan("ap2", N20_CH6)
    assert fresh.digest != preview.digest
    assert (await env.service.apply("ap2", N20_CH6, digest=fresh.digest)).verified


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
    assert plan.lines[1] == "uci set wireless.default_radio0.key='<hidden>'"
    assert all("it's" not in line and "$x" not in line for line in plan.lines)
    result = await env.service.apply("ap1", req)
    assert result.applied
    assert all("$x" not in command for command, _ in env.audit_lines())
    shown = (await (await env.sim("ap1")).run("uci -q show wireless")).stdout
    assert "wireless.default_radio0.key='it'\\''s $x `y` z'" in shown
