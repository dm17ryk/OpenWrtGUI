"""Reading a router's Wi-Fi back into the selectors: what is set, what is on air, what may be chosen."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from typing import Literal

from openwrtgui.probe.board import BoardInfo
from openwrtgui.probe.describe import SelfDescription
from openwrtgui.transport.base import Transport, ubus_call
from openwrtgui.wifi.compile import UciOp, compile_modes
from openwrtgui.wifi.model import (
    ENCRYPTION,
    MODES,
    ChannelSelection,
    ModeSelection,
    RadioLimits,
    Security,
    TxPowerSetting,
)
from openwrtgui.wifi.parse import (
    IwDevInfo,
    parse_freqlist,
    parse_ht_mcs,
    parse_iw_dev_info,
    parse_txpowerlist,
    parse_uci_show,
)
from openwrtgui.wifi.writers import writer_of

MaskState = Literal["none", "active", "missing"]
UCI_SHOW = "uci -q show wireless"
_SECURITY: dict[str, Security] = {v: k for k, v in ENCRYPTION.items()}
_MODE_OPTIONS = ("htmode", "noscan", "legacy_rates", "supported_rates", "basic_rate")


@dataclass(frozen=True)
class SsidState:
    section: str
    ifname: str | None
    ssid: str
    security: Security | Literal["other"]
    encryption: str
    key_set: bool


@dataclass(frozen=True)
class RadioState:
    name: str
    band: str
    up: bool
    disabled: bool
    limits: RadioLimits
    modes: ModeSelection
    channels: ChannelSelection
    txpower: TxPowerSetting
    legacy_rates: bool
    actual: IwDevInfo | None
    mask: MaskState
    ssids: tuple[SsidState, ...]
    writers: dict[str, str]


@dataclass(frozen=True)
class WifiState:
    router_id: str
    read_at: datetime
    radios: tuple[RadioState, ...]


def _expected(ops: Sequence[UciOp]) -> dict[str, str | None]:
    return {op.path: op.value if op.op == "set" else None for op in ops}


def modes_from_uci(opts: Mapping[str, str], radio: str, max_htmode: Literal["HT20", "HT40"]) -> ModeSelection:
    p = f"wireless.{radio}."
    overrides = [opts.get(p + n) for n in ("noscan", "supported_rates", "basic_rate")]
    if all(v is None for v in overrides) and opts.get(p + "htmode", max_htmode) == max_htmode:
        return ModeSelection.auto()
    limits = RadioLimits("2g", "", max_htmode, (), (), (), "", False)
    for size in range(1, len(MODES) + 1):
        for subset in combinations(MODES, size):
            sel = ModeSelection.of(*subset)
            want = _expected(compile_modes(radio, sel, limits))
            if all(opts.get(path) == value for path, value in want.items()):
                return sel
    return ModeSelection("custom")


def channels_from_uci(opts: Mapping[str, str], radio: str, allowed: Sequence[int]) -> ChannelSelection:
    p = f"wireless.{radio}."
    if opts.get(p + "disabled") == "1":
        return ChannelSelection.none()
    channel = opts.get(p + "channel", "auto")
    if channel.isdigit():
        return ChannelSelection.of(int(channel))
    listed = opts.get(p + "channels")
    if not listed:
        return ChannelSelection.auto()
    if allowed and listed == f"{min(allowed)}-{max(allowed)}":
        return ChannelSelection.all()
    chosen: set[int] = set()
    for token in listed.split():
        if m := re.fullmatch(r"(\d+)-(\d+)", token):
            chosen.update(range(int(m.group(1)), int(m.group(2)) + 1))
        elif token.isdigit():
            chosen.add(int(token))
    return ChannelSelection("set", frozenset(chosen)) if chosen else ChannelSelection.auto()


def txpower_from_uci(opts: Mapping[str, str], radio: str) -> TxPowerSetting:
    value = opts.get(f"wireless.{radio}.txpower")
    return TxPowerSetting("fixed", int(value)) if value and value.isdigit() else TxPowerSetting("auto")


def max_htmode(board: BoardInfo | None, phy: str, band: str) -> Literal["HT20", "HT40"]:
    bands = [b for b in (board.radios if board else ()) if b.band.lower() == band.lower()]
    best = next((b for b in bands if b.phy == phy), bands[0] if bands else None)
    if best is None:
        return "HT20"
    return "HT40" if (best.max_width or 0) >= 40 or "HT40" in best.modes else "HT20"


def ssid_sections(uci: Mapping[str, str], radio: str) -> list[str]:
    return [
        path.split(".")[1]
        for path, value in uci.items()
        if path.count(".") == 1 and value == "wifi-iface" and uci.get(f"{path}.device") == radio
    ]


async def read_uci(t: Transport) -> dict[str, str]:
    return parse_uci_show((await t.run(UCI_SHOW)).stdout)


async def read_wifi(
    t: Transport,
    router_id: str,
    desc: SelfDescription,
    mask_marks: Mapping[tuple[str, str], int],
    clock: Callable[[], datetime],
    uci: Mapping[str, str] | None = None,
) -> WifiState:
    uci = uci if uci is not None else await read_uci(t)
    status = await ubus_call(t, "network.wireless", "status") or {}
    sae = bool((desc.features or {}).get("hostapd", {}).get("sae"))
    radios = []
    for name, st in status.items():
        p = f"wireless.{name}."
        phy = str((await ubus_call(t, "iwinfo", "phyname", {"section": name}) or {}).get("phyname", "phy0"))
        band = uci.get(p + "band") or str(st.get("config", {}).get("band", "2g"))
        allowed = parse_freqlist(await ubus_call(t, "iwinfo", "freqlist", {"device": name}) or {})
        limits = RadioLimits(
            band=band,
            phy=phy,
            max_htmode=max_htmode(desc.board, phy, band),
            channels=allowed,
            txpower_dbm=parse_txpowerlist(
                await ubus_call(t, "iwinfo", "txpowerlist", {"device": name}) or {}
            ),
            mcs=parse_ht_mcs((await t.run(f"iw phy {phy} info")).stdout),
            country=uci.get(p + "country", "00"),
            sae=sae,
        )
        up = bool(st.get("up"))
        ifnames = {i.get("section"): i.get("ifname") for i in st.get("interfaces", []) if i.get("ifname")}
        actual = None
        first = next(iter(ifnames.values()), None)
        if up and first:
            actual = parse_iw_dev_info((await t.run(f"iw dev {first} info")).stdout)
        modes = modes_from_uci(uci, name, limits.max_htmode)
        mask: MaskState = "none"
        if modes.kind == "set" and up:
            marked = mask_marks.get((router_id, first or ""))
            mask = (
                "active"
                if actual is not None and marked is not None and actual.ifindex == marked
                else "missing"
            )
        ssids = tuple(
            SsidState(
                section=s,
                ifname=ifnames.get(s),
                ssid=uci.get(f"wireless.{s}.ssid", ""),
                security=_SECURITY.get(uci.get(f"wireless.{s}.encryption", "none"), "other"),
                encryption=uci.get(f"wireless.{s}.encryption", "none"),
                key_set=f"wireless.{s}.key" in uci,
            )
            for s in ssid_sections(uci, name)
        )
        writers = {
            path[len(p) :]: w
            for path in uci
            if path.startswith(p) and (w := writer_of(path[len(p) :])) is not None
        }
        radios.append(
            RadioState(
                name=name,
                band=band,
                up=up,
                disabled=uci.get(p + "disabled") == "1",
                limits=limits,
                modes=modes,
                channels=channels_from_uci(uci, name, allowed),
                txpower=txpower_from_uci(uci, name),
                legacy_rates=uci.get(p + "legacy_rates") == "1",
                actual=actual,
                mask=mask,
                ssids=ssids,
                writers=writers,
            )
        )
    return WifiState(router_id=router_id, read_at=clock(), radios=tuple(radios))
