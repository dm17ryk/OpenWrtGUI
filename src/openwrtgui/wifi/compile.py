"""The Wi-Fi selectors compiled to uci changes and the runtime TX mask (plan: "Wi-Fi rules").

Pure modes use only their own rates in both directions. mac80211 refuses a bitrate mask without one
basic rate of the BSS, so an HT-only mask keeps the lowest basic rate 6 (proven on AP2, 2026-10-25).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from openwrtgui.wifi.model import (
    CCK_BASIC_KBPS,
    CCK_KBPS,
    ENCRYPTION,
    OFDM_BASIC_KBPS,
    OFDM_KBPS,
    ChannelSelection,
    ModeSelection,
    RadioLimits,
    SsidRequest,
    TxPowerSetting,
)

PSK_MODES = ("wpa2", "wpa3", "wpa2_wpa3")


@dataclass(frozen=True)
class UciOp:
    op: Literal["set", "delete", "add_list"]
    path: str
    value: str | None = None


def _kbps(rates: Sequence[int]) -> str:
    return " ".join(str(r) for r in rates)


def _mbps(rates: Sequence[int]) -> str:
    return " ".join(f"{r / 1000:g}" for r in rates)


def compile_modes(radio: str, sel: ModeSelection, limits: RadioLimits) -> list[UciOp]:
    p = f"wireless.{radio}"
    if sel.kind == "auto":
        return [
            UciOp("set", f"{p}.htmode", limits.max_htmode),
            UciOp("delete", f"{p}.noscan"),
            UciOp("delete", f"{p}.supported_rates"),
            UciOp("delete", f"{p}.basic_rate"),
        ]
    if sel.kind != "set":
        raise ValueError("Set outside the selector; see All options")
    m = sel.modes
    htmode = "HT40" if "n40" in m else "HT20" if "n20" in m else "NOHT"
    supported = (CCK_KBPS if "b" in m else ()) + (OFDM_KBPS if "g" in m else ())
    return [
        UciOp("set", f"{p}.htmode", htmode),
        UciOp("set", f"{p}.noscan", "1") if "n40" in m and "n20" not in m else UciOp("delete", f"{p}.noscan"),
        UciOp("set", f"{p}.legacy_rates", "1" if "b" in m else "0"),
        UciOp("set", f"{p}.supported_rates", _kbps(supported or OFDM_BASIC_KBPS)),
        UciOp("set", f"{p}.basic_rate", _kbps(CCK_BASIC_KBPS if "b" in m else OFDM_BASIC_KBPS)),
    ]


def tx_mask_args(sel: ModeSelection, mcs: Sequence[int]) -> str:
    """Arguments for `iw dev <if> set bitrates`; empty clears the mask (Auto)."""
    if sel.kind != "set":
        return ""
    m = sel.modes
    legacy = (CCK_KBPS if "b" in m else ()) + (OFDM_KBPS if "g" in m else ())
    args = f"legacy-2.4 {_mbps(legacy or OFDM_BASIC_KBPS[:1])}"
    if ("n20" in m or "n40" in m) and mcs:
        args += " ht-mcs-2.4 " + " ".join(str(i) for i in mcs)
    return args


def lowest_basic_mbps(sel: ModeSelection, legacy_rates: bool) -> float:
    """The beacon rate: the lowest basic rate of the BSS."""
    has_b = "b" in sel.modes if sel.kind == "set" else legacy_rates
    return CCK_BASIC_KBPS[0] / 1000 if has_b else OFDM_BASIC_KBPS[0] / 1000


def compile_channels(radio: str, sel: ChannelSelection, limits: RadioLimits) -> list[UciOp]:
    p = f"wireless.{radio}"
    if sel.kind == "none":
        return [UciOp("set", f"{p}.disabled", "1")]
    if sel.kind == "auto":
        ops = [UciOp("set", f"{p}.channel", "auto"), UciOp("delete", f"{p}.channels")]
    elif sel.kind == "all":
        span = f"{min(limits.channels)}-{max(limits.channels)}"
        ops = [UciOp("set", f"{p}.channel", "auto"), UciOp("set", f"{p}.channels", span)]
    else:
        for ch in sorted(sel.channels):
            if ch not in limits.channels:
                raise ValueError(f"Channel {ch} is not allowed in country {limits.country}")
        chans = sorted(sel.channels)
        if len(chans) == 1:
            ops = [UciOp("set", f"{p}.channel", str(chans[0])), UciOp("delete", f"{p}.channels")]
        else:
            ops = [
                UciOp("set", f"{p}.channel", "auto"),
                UciOp("set", f"{p}.channels", " ".join(str(c) for c in chans)),
            ]
    return [*ops, UciOp("set", f"{p}.disabled", "0")]


def compile_txpower(radio: str, setting: TxPowerSetting, limits: RadioLimits) -> list[UciOp]:
    path = f"wireless.{radio}.txpower"
    if setting.kind == "auto":
        return [UciOp("delete", path)]
    if setting.kind == "cap":
        raise ValueError("TX power cap is not available on this radio")
    if setting.dbm is None:
        raise ValueError("Choose a TX power in dBm")
    top = max(limits.txpower_dbm)
    if setting.dbm > top:
        raise ValueError(f"{setting.dbm} dBm is above this radio's maximum of {top} dBm")
    if setting.dbm not in limits.txpower_dbm:
        raise ValueError(f"{setting.dbm} dBm is not a TX power this radio offers")
    return [UciOp("set", path, str(setting.dbm))]


def _valid_key(key: str) -> bool:
    if len(key) == 64:
        return all(c in "0123456789abcdefABCDEF" for c in key)
    return 8 <= len(key) <= 63 and all(" " <= c <= "~" for c in key)


def compile_ssid(req: SsidRequest, band: str, sae: bool, current: Mapping[str, str]) -> list[UciOp]:
    p = f"wireless.{req.section}"
    ops: list[UciOp] = []
    if req.ssid is not None:
        if not 1 <= len(req.ssid.encode()) <= 32:
            raise ValueError("An SSID is 1 to 32 bytes")
        ops.append(UciOp("set", f"{p}.ssid", req.ssid))
    security = req.security
    if security is not None:
        if band == "6g" and security != "wpa3":
            raise ValueError("6 GHz allows only WPA3-SAE")
        if security in ("wpa3", "wpa2_wpa3") and not sae:
            raise ValueError("WPA3 needs SAE, which this router's hostapd does not have")
        ops.append(UciOp("set", f"{p}.encryption", ENCRYPTION[security]))
        if security == "open":
            return [*ops, UciOp("delete", f"{p}.key")]
        was_open = current.get(f"{p}.encryption", "none") == "none"
        if was_open and not req.key:
            name = req.ssid or current.get(f"{p}.ssid", req.section)
            raise ValueError(f"Enter a key for {name}")
    if req.key:
        if not _valid_key(req.key):
            raise ValueError("A Wi-Fi key needs 8 to 63 characters, or 64 hex digits")
        ops.append(UciOp("set", f"{p}.key", req.key))
    return ops


def drop_unchanged(ops: Sequence[UciOp], current: Mapping[str, str]) -> list[UciOp]:
    """Only changes are written: a set to the current value or a delete of an absent option goes."""
    kept: list[UciOp] = []
    for op in ops:
        if op.op == "set" and current.get(op.path) == op.value:
            continue
        if op.op == "delete" and op.path not in current:
            continue
        kept.append(op)
    return kept


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def render_uci(ops: Sequence[UciOp]) -> list[str]:
    lines = []
    for op in ops:
        if op.op == "delete":
            lines.append(f"uci -q delete {op.path}")
        else:
            verb = "set" if op.op == "set" else "add_list"
            lines.append(f"uci {verb} {op.path}={shell_quote(op.value or '')}")
    return lines


def apply_script(radio: str, ops: Sequence[UciOp]) -> str:
    """The change: `set -e` stops at the first failing line, so a half-done change is never committed."""
    return "\n".join(["set -e", *render_uci(ops), "uci commit wireless"])


def reload_command(radio: str) -> str:
    """Sent on its own after the commit, so a failed reload is told apart from a refused change."""
    return f"wifi down {radio}; wifi up {radio}"


def mask_command(ifname: str, args: str) -> str:
    return f"iw dev {ifname} set bitrates {args}".rstrip()
