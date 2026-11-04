from __future__ import annotations

import pytest

from openwrtgui.wifi.compile import (
    UciOp,
    apply_script,
    compile_channels,
    compile_modes,
    compile_ssid,
    compile_txpower,
    drop_unchanged,
    lowest_basic_mbps,
    mask_command,
    render_uci,
    shell_quote,
    tx_mask_args,
)
from openwrtgui.wifi.model import (
    ChannelSelection,
    ModeSelection,
    RadioLimits,
    SsidRequest,
    TxPowerSetting,
)

LIMITS = RadioLimits(
    band="2g",
    phy="phy0",
    max_htmode="HT40",
    channels=tuple(range(1, 14)),
    txpower_dbm=tuple(range(0, 21)),
    mcs=tuple(range(8)),
    country="IL",
    sae=True,
)
PSK = {"wireless.default_radio0.encryption": "psk2", "wireless.default_radio0.ssid": "OpenWrt"}
OPEN = {"wireless.default_radio0.encryption": "none", "wireless.default_radio0.ssid": "OpenWrt"}


def test_b_plus_n20_matches_the_mockup() -> None:
    sel = ModeSelection.of("b", "n20")
    assert render_uci(compile_modes("radio0", sel, LIMITS)) == [
        "uci set wireless.radio0.htmode='HT20'",
        "uci -q delete wireless.radio0.noscan",
        "uci set wireless.radio0.legacy_rates='1'",
        "uci set wireless.radio0.supported_rates='1000 2000 5500 11000'",
        "uci set wireless.radio0.basic_rate='1000 2000'",
    ]
    assert tx_mask_args(sel, LIMITS.mcs) == "legacy-2.4 1 2 5.5 11 ht-mcs-2.4 0 1 2 3 4 5 6 7"


def test_pure_modes_match_the_harness_masks() -> None:
    assert tx_mask_args(ModeSelection.of("g"), LIMITS.mcs) == "legacy-2.4 6 9 12 18 24 36 48 54"
    assert tx_mask_args(ModeSelection.of("n20"), LIMITS.mcs) == "legacy-2.4 6 ht-mcs-2.4 0 1 2 3 4 5 6 7"
    assert tx_mask_args(ModeSelection.of("b"), LIMITS.mcs) == "legacy-2.4 1 2 5.5 11"
    n40 = render_uci(compile_modes("radio0", ModeSelection.of("n40"), LIMITS))
    assert "uci set wireless.radio0.htmode='HT40'" in n40
    assert "uci set wireless.radio0.noscan='1'" in n40
    assert "uci set wireless.radio0.legacy_rates='0'" in n40
    assert "uci set wireless.radio0.supported_rates='6000 12000 24000'" in n40
    assert "uci set wireless.radio0.basic_rate='6000 12000 24000'" in n40
    g = render_uci(compile_modes("radio0", ModeSelection.of("g"), LIMITS))
    assert "uci set wireless.radio0.htmode='NOHT'" in g
    assert "uci set wireless.radio0.legacy_rates='0'" in g
    assert "uci set wireless.radio0.supported_rates='6000 9000 12000 18000 24000 36000 48000 54000'" in g


def test_n40_with_n20_lets_the_router_fall_back() -> None:
    lines = render_uci(compile_modes("radio0", ModeSelection.of("n20", "n40"), LIMITS))
    assert "uci set wireless.radio0.htmode='HT40'" in lines
    assert "uci -q delete wireless.radio0.noscan" in lines


def test_auto_clears_overrides_and_keeps_legacy_rates() -> None:
    assert render_uci(compile_modes("radio0", ModeSelection.auto(), LIMITS)) == [
        "uci set wireless.radio0.htmode='HT40'",
        "uci -q delete wireless.radio0.noscan",
        "uci -q delete wireless.radio0.supported_rates",
        "uci -q delete wireless.radio0.basic_rate",
    ]
    assert tx_mask_args(ModeSelection.auto(), LIMITS.mcs) == ""
    assert lowest_basic_mbps(ModeSelection.auto(), legacy_rates=True) == 1.0
    assert lowest_basic_mbps(ModeSelection.auto(), legacy_rates=False) == 6.0
    assert lowest_basic_mbps(ModeSelection.of("n20"), legacy_rates=True) == 6.0
    assert lowest_basic_mbps(ModeSelection.of("b", "g"), legacy_rates=False) == 1.0


def test_auto_on_a_20_mhz_board_uses_ht20() -> None:
    narrow = RadioLimits(**{**LIMITS.__dict__, "max_htmode": "HT20"})
    assert render_uci(compile_modes("radio0", ModeSelection.auto(), narrow))[0] == (
        "uci set wireless.radio0.htmode='HT20'"
    )


def test_all_is_every_mode() -> None:
    sel = ModeSelection.all()
    assert sel.modes == frozenset({"b", "g", "n20", "n40"})
    lines = render_uci(compile_modes("radio0", sel, LIMITS))
    assert (
        "uci set wireless.radio0.supported_rates="
        "'1000 2000 5500 11000 6000 9000 12000 18000 24000 36000 48000 54000'"
    ) in lines
    assert "uci set wireless.radio0.basic_rate='1000 2000'" in lines
    assert tx_mask_args(sel, LIMITS.mcs) == (
        "legacy-2.4 1 2 5.5 11 6 9 12 18 24 36 48 54 ht-mcs-2.4 0 1 2 3 4 5 6 7"
    )


def test_empty_selections_are_refused() -> None:
    with pytest.raises(ValueError, match="Tick at least one mode, or choose Auto or All."):
        ModeSelection.of()
    with pytest.raises(ValueError, match="Tick at least one channel, or choose Auto, All or None."):
        ChannelSelection.of()


def test_channels() -> None:
    def r(sel: ChannelSelection) -> list[str]:
        return render_uci(compile_channels("radio0", sel, LIMITS))

    assert r(ChannelSelection.of(6)) == [
        "uci set wireless.radio0.channel='6'",
        "uci -q delete wireless.radio0.channels",
        "uci set wireless.radio0.disabled='0'",
    ]
    assert r(ChannelSelection.of(11, 1, 6)) == [
        "uci set wireless.radio0.channel='auto'",
        "uci set wireless.radio0.channels='1 6 11'",
        "uci set wireless.radio0.disabled='0'",
    ]
    assert r(ChannelSelection.all())[1] == "uci set wireless.radio0.channels='1-13'"
    assert r(ChannelSelection.auto()) == [
        "uci set wireless.radio0.channel='auto'",
        "uci -q delete wireless.radio0.channels",
        "uci set wireless.radio0.disabled='0'",
    ]
    assert r(ChannelSelection.none()) == ["uci set wireless.radio0.disabled='1'"]
    with pytest.raises(ValueError, match="Channel 14 is not allowed in country IL"):
        compile_channels("radio0", ChannelSelection.of(1, 14), LIMITS)


def test_txpower() -> None:
    assert render_uci(compile_txpower("radio0", TxPowerSetting("fixed", 17), LIMITS)) == [
        "uci set wireless.radio0.txpower='17'"
    ]
    assert render_uci(compile_txpower("radio0", TxPowerSetting("auto"), LIMITS)) == [
        "uci -q delete wireless.radio0.txpower"
    ]
    with pytest.raises(ValueError, match="25 dBm is above this radio's maximum of 20 dBm"):
        compile_txpower("radio0", TxPowerSetting("fixed", 25), LIMITS)
    with pytest.raises(ValueError, match="TX power cap is not available on this radio"):
        compile_txpower("radio0", TxPowerSetting("cap", 10), LIMITS)


def test_security_and_ssid_rules() -> None:
    sec = "wireless.default_radio0"
    assert render_uci(compile_ssid(SsidRequest("default_radio0", security="open"), "2g", True, PSK)) == [
        f"uci set {sec}.encryption='none'",
        f"uci -q delete {sec}.key",
    ]
    assert render_uci(
        compile_ssid(SsidRequest("default_radio0", ssid="Lab", security="wpa3"), "2g", True, PSK)
    ) == [f"uci set {sec}.ssid='Lab'", f"uci set {sec}.encryption='sae'"]
    assert render_uci(compile_ssid(SsidRequest("default_radio0", security="wpa2_wpa3"), "2g", True, PSK)) == [
        f"uci set {sec}.encryption='sae-mixed'"
    ]
    with pytest.raises(ValueError, match="WPA3 needs SAE, which this router's hostapd does not have"):
        compile_ssid(SsidRequest("default_radio0", security="wpa3"), "2g", False, PSK)
    with pytest.raises(ValueError, match="6 GHz allows only WPA3-SAE"):
        compile_ssid(SsidRequest("default_radio0", security="wpa2"), "6g", True, PSK)
    with pytest.raises(ValueError, match="A Wi-Fi key needs 8 to 63 characters, or 64 hex digits"):
        compile_ssid(SsidRequest("default_radio0", key="short12"), "2g", True, PSK)
    with pytest.raises(ValueError, match="A Wi-Fi key needs 8 to 63 characters, or 64 hex digits"):
        compile_ssid(SsidRequest("default_radio0", key="x" * 64), "2g", True, PSK)
    hex64 = "ab" * 32
    assert render_uci(compile_ssid(SsidRequest("default_radio0", key=hex64), "2g", True, PSK)) == [
        f"uci set {sec}.key='{hex64}'"
    ]
    with pytest.raises(ValueError, match="An SSID is 1 to 32 bytes"):
        compile_ssid(SsidRequest("default_radio0", ssid="é" * 17), "2g", True, PSK)
    with pytest.raises(ValueError, match="An SSID is 1 to 32 bytes"):
        compile_ssid(SsidRequest("default_radio0", ssid=""), "2g", True, PSK)
    with pytest.raises(ValueError, match="Enter a key for OpenWrt"):
        compile_ssid(SsidRequest("default_radio0", security="wpa2"), "2g", True, OPEN)
    assert render_uci(
        compile_ssid(SsidRequest("default_radio0", security="wpa2", key="lab-key-123"), "2g", True, OPEN)
    ) == [f"uci set {sec}.encryption='psk2'", f"uci set {sec}.key='lab-key-123'"]


def test_key_with_shell_metacharacters_is_quoted() -> None:
    ops = compile_ssid(SsidRequest("default_radio0", key="it's $x `y` z"), "2g", True, PSK)
    assert render_uci(ops) == ["uci set wireless.default_radio0.key='it'\\''s $x `y` z'"]
    assert shell_quote("a'b") == "'a'\\''b'"


def test_non_ascii_key_is_refused() -> None:
    # A WPA passphrase is 8 to 63 printable ASCII characters (IEEE 802.11i).
    with pytest.raises(ValueError, match="A Wi-Fi key needs 8 to 63 characters, or 64 hex digits"):
        compile_ssid(SsidRequest("default_radio0", key="clé-du-labo"), "2g", True, PSK)


def test_only_changes_are_written() -> None:
    current = {"wireless.radio0.htmode": "HT20", "wireless.radio0.legacy_rates": "1"}
    ops = drop_unchanged(compile_modes("radio0", ModeSelection.of("b", "n20"), LIMITS), current)
    assert [o.path for o in ops] == ["wireless.radio0.supported_rates", "wireless.radio0.basic_rate"]
    kept = drop_unchanged([UciOp("delete", "wireless.radio0.noscan")], {"wireless.radio0.noscan": "1"})
    assert kept == [UciOp("delete", "wireless.radio0.noscan")]


def test_add_list_is_rendered() -> None:
    assert render_uci([UciOp("add_list", "wireless.radio0.channels", "6")]) == [
        "uci add_list wireless.radio0.channels='6'"
    ]


def test_apply_script_and_mask_command() -> None:
    script = apply_script("radio0", [UciOp("set", "wireless.radio0.channel", "6")])
    assert script.splitlines() == [
        "uci set wireless.radio0.channel='6'",
        "uci commit wireless",
        "wifi down radio0; wifi up radio0",
    ]
    assert mask_command("phy0-ap0", "") == "iw dev phy0-ap0 set bitrates"
    assert mask_command("phy0-ap0", "legacy-2.4 6") == "iw dev phy0-ap0 set bitrates legacy-2.4 6"
