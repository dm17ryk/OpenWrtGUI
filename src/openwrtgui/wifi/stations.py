"""Stations on a router's SSIDs (iwinfo assoclist + luci-rpc host hints) and the hostapd actions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from openwrtgui.transport.base import Transport, ubus_call, ubus_command
from openwrtgui.wifi.model import CCK_KBPS

DEAUTH_REASON = 3  # "deauthenticated because sending station is leaving"


@dataclass(frozen=True)
class Station:
    mac: str
    ifname: str
    ssid: str
    name: str | None
    ip: str | None
    signal_dbm: int | None
    tx_mbps: float | None
    tx_mcs: int | None
    rx_mbps: float | None
    mode: str
    connected_s: int | None
    inactive_ms: int | None


def mode_label(rate: Mapping[str, Any]) -> str:
    """The 802.11 mode a rate belongs to, from an iwinfo rate record (rate in kb/s)."""
    if rate.get("ht"):
        return "802.11n 40" if rate.get("40mhz") else "802.11n 20"
    kbps = rate.get("rate")
    if kbps is None:
        return "unknown"
    return "802.11b" if int(kbps) in CCK_KBPS else "802.11g"


def _mbps(rate: Mapping[str, Any]) -> float | None:
    return int(rate["rate"]) / 1000 if "rate" in rate else None


async def read_stations(t: Transport, ifaces: Sequence[tuple[str, str]]) -> list[Station]:
    """Stations on each (ifname, SSID); names and IPv4 from the router's host hints."""
    hints = {k.lower(): v for k, v in (await ubus_call(t, "luci-rpc", "getHostHints") or {}).items()}
    out: list[Station] = []
    for ifname, ssid in ifaces:
        result = await ubus_call(t, "iwinfo", "assoclist", {"device": ifname}) or {}
        for entry in result.get("results", []):
            mac = str(entry.get("mac", "")).lower()
            hint = hints.get(mac, {})
            tx, rx = entry.get("tx", {}), entry.get("rx", {})
            ipv4 = [a for a in hint.get("ipaddrs", []) if ":" not in a]
            out.append(
                Station(
                    mac=mac,
                    ifname=ifname,
                    ssid=ssid,
                    name=hint.get("name"),
                    ip=ipv4[0] if ipv4 else None,
                    signal_dbm=entry.get("signal"),
                    tx_mbps=_mbps(tx),
                    tx_mcs=tx.get("mcs") if tx.get("ht") else None,
                    rx_mbps=_mbps(rx),
                    mode=mode_label(tx or rx),
                    connected_s=entry.get("connected_time"),
                    inactive_ms=entry.get("inactive"),
                )
            )
    return out


def del_client_command(ifname: str, mac: str, ban_ms: int) -> str:
    """Deauthenticate a station; with ban_ms > 0 it may not rejoin for that long."""
    args = {"addr": mac.lower(), "ban_time": ban_ms, "deauth": True, "reason": DEAUTH_REASON}
    return ubus_command(f"hostapd.{ifname}", "del_client", args)
