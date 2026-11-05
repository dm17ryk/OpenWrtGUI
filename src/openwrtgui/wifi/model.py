"""What the Wi-Fi screen asks for, independent of how it is written to the router."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Mode = Literal["b", "g", "n20", "n40"]
MODES: tuple[Mode, ...] = ("b", "g", "n20", "n40")

# Rates in kb/s, as uci's supported_rates / basic_rate take them.
CCK_KBPS = (1000, 2000, 5500, 11000)
OFDM_KBPS = (6000, 9000, 12000, 18000, 24000, 36000, 48000, 54000)
CCK_BASIC_KBPS = (1000, 2000)
OFDM_BASIC_KBPS = (6000, 12000, 24000)

NO_MODE = "Tick at least one mode, or choose Auto or All."
NO_CHANNEL = "Tick at least one channel, or choose Auto, All or None."


@dataclass(frozen=True)
class ModeSelection:
    kind: Literal["auto", "set", "custom"]
    modes: frozenset[Mode] = frozenset()

    @classmethod
    def auto(cls) -> ModeSelection:
        return cls("auto")

    @classmethod
    def of(cls, *modes: Mode) -> ModeSelection:
        if not modes:
            raise ValueError(NO_MODE)
        return cls("set", frozenset(modes))

    @classmethod
    def all(cls) -> ModeSelection:
        return cls.of(*MODES)


@dataclass(frozen=True)
class ChannelSelection:
    kind: Literal["auto", "all", "none", "set"]
    channels: frozenset[int] = frozenset()

    @classmethod
    def auto(cls) -> ChannelSelection:
        return cls("auto")

    @classmethod
    def all(cls) -> ChannelSelection:
        return cls("all")

    @classmethod
    def none(cls) -> ChannelSelection:
        return cls("none")

    @classmethod
    def of(cls, *channels: int) -> ChannelSelection:
        if not channels:
            raise ValueError(NO_CHANNEL)
        return cls("set", frozenset(channels))


@dataclass(frozen=True)
class TxPowerSetting:
    kind: Literal["auto", "fixed", "cap"]
    dbm: int | None = None


Security = Literal["open", "wpa2", "wpa3", "wpa2_wpa3"]
ENCRYPTION: dict[Security, str] = {
    "open": "none",
    "wpa2": "psk2",
    "wpa3": "sae",
    "wpa2_wpa3": "sae-mixed",
}


@dataclass(frozen=True)
class SsidRequest:
    """One SSID section; None means leave that field as it is (an empty key keeps the key)."""

    section: str
    ssid: str | None = None
    security: Security | None = None
    key: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class RadioRequest:
    radio: str
    modes: ModeSelection | None = None
    channels: ChannelSelection | None = None
    txpower: TxPowerSetting | None = None
    ssids: tuple[SsidRequest, ...] = ()


@dataclass(frozen=True)
class RadioLimits:
    """What this radio allows here: from board.json, iwinfo and iw phy for the current country."""

    band: str
    phy: str
    max_htmode: Literal["HT20", "HT40"]
    channels: tuple[int, ...]
    txpower_dbm: tuple[int, ...]
    mcs: tuple[int, ...]
    country: str
    sae: bool
