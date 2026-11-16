"""One snapshot of the LTE modem (v0.6a plan, "State shown"): what uqmi, netifd and the AT port say. A part
that does not answer is named in `missing`; the rest still shows."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.lte import commands as c
from openwrtgui.lte.at import ModemIdentity, ModemInfo, modem_info, operator_answer, read_identity
from openwrtgui.lte.parse import Signal, parse_cops, parse_opmode, parse_serving, parse_signal
from openwrtgui.lte.quality import Metric, Quality, label
from openwrtgui.net.interfaces import QMI_LOCKED
from openwrtgui.transport.base import Transport

NO_LTE = "This router has no LTE interface (no qmi interface in its network config)"
AUTOCONNECT_NOTE = QMI_LOCKED["autoconnect"]


class Measure(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: float
    label: Quality | None


class LteState(BaseModel):
    model_config = ConfigDict(frozen=True)

    router_id: str
    read_at: datetime
    available: bool
    note: str | None = None
    device: str | None = None
    up: bool | None = None
    pending: bool | None = None
    uptime_s: int | None = None
    ipv4: str | None = None
    rx_bytes: int | None = None
    tx_bytes: int | None = None
    registration: str | None = None
    radio: str | None = None
    roaming: bool | None = None
    operator: str | None = None
    operator_source: Literal["at", "qmi"] | None = None
    mcc: int | None = None
    mnc: int | None = None
    rssi: Measure | None = None
    rsrp: Measure | None = None
    rsrq: Measure | None = None
    snr: Measure | None = None
    opmode: str | None = None
    modem: ModemInfo = ModemInfo()
    autoconnect_note: str = AUTOCONNECT_NOTE
    missing: tuple[str, ...] = ()


async def _stdout(t: Transport, command: str) -> str | None:
    result = await t.run(command)
    return result.stdout if result.ok else None


async def _json(t: Transport, command: str) -> Any:
    text = await _stdout(t, command)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def measures(signal: Signal | None) -> dict[Metric, Measure | None]:
    """The four LTE values with their labels; other radios' values get no label (D11 is for LTE)."""
    out: dict[Metric, Measure | None] = {}
    for metric in ("rssi", "rsrp", "rsrq", "snr"):
        value = getattr(signal, metric) if signal is not None else None
        labelled = signal is not None and signal.type == "lte"
        if value is None:
            out[metric] = None
        else:
            out[metric] = Measure(value=value, label=label(metric, value) if labelled else None)
    return out


@dataclass(frozen=True)
class _Netifd:
    """What uqmi and netifd say, read alongside the AT exchange (v1.0c D3)."""

    serving: Any
    signal: Signal | None
    opmode: str | None
    session: dict[str, Any] | None
    ipv4: str | None
    stats: dict[str, Any] | None


async def _read_netifd(t: Transport, name: str, dev: str | None) -> _Netifd:
    serving = parse_serving(await _stdout(t, c.SERVING(dev)) or "") if dev else None
    signal = parse_signal(await _stdout(t, c.SIGNAL(dev)) or "") if dev else None
    opmode = parse_opmode(await _stdout(t, c.OPMODE(dev)) or "") if dev else None
    session = await _json(t, c.iface_status(name))
    session = session if isinstance(session, dict) else None
    lease = await _json(t, c.iface_status(f"{name}_4")) if len(name) <= 13 else None  # qmi.sh's dynamic one
    addresses = lease.get("ipv4-address") if isinstance(lease, dict) else None
    ipv4 = addresses[0].get("address") if isinstance(addresses, list) and addresses else None
    l3 = session.get("l3_device") if session else None
    counters = await _json(t, c.device_status(l3)) if isinstance(l3, str) and c.NETDEV.fullmatch(l3) else None
    stats = counters.get("statistics") if isinstance(counters, dict) else None
    return _Netifd(
        serving=serving,
        signal=signal,
        opmode=opmode,
        session=session,
        ipv4=ipv4 if isinstance(ipv4, str) else None,
        stats=stats if isinstance(stats, dict) else None,
    )


async def _read_at(
    t: Transport, port: str | None, identity: ModemIdentity | None
) -> tuple[ModemInfo, ModemIdentity | None]:
    """The operator every time; the identity only when none is kept for this connection (v1.0c D2)."""
    if port is None:
        return ModemInfo(), None
    known = identity if identity is not None else await read_identity(t, port)
    answer = await operator_answer(t, port)
    if answer is None and (identity is not None or known.silent):
        # the port answered once and is silent now: the modem re-enumerated, so nothing is kept for it
        return ModemInfo(), None
    info = modem_info(known, parse_cops(answer.lines) if answer else None, port)
    return info, (None if known.silent else known)  # an identity that never answered is asked again


async def read_lte(
    t: Transport,
    *,
    router_id: str,
    qmi: tuple[str, str | None] | None,
    at_port: str | None,
    now: datetime,
    identity: ModemIdentity | None = None,
) -> tuple[LteState, ModemIdentity | None]:
    """`qmi` is the qmi interface's name and device from the network config; None: no LTE here. The second
    item is the identity read or reused, None when the AT port gave nothing (nothing to keep)."""
    if qmi is None:
        return LteState(router_id=router_id, read_at=now, available=False, note=NO_LTE), None
    name, device = qmi
    dev = device if device is not None and c.MODEM_DEVICE.fullmatch(device) else None
    # both halves end before an error goes on: a lost connection leaves nothing running (v1.0c D3)
    n, at_half = await asyncio.gather(
        _read_netifd(t, name, dev), _read_at(t, at_port, identity), return_exceptions=True
    )
    if isinstance(n, BaseException):
        raise n
    if isinstance(at_half, BaseException):
        raise at_half
    modem, kept = at_half
    serving, signal, opmode, session, stats = n.serving, n.signal, n.opmode, n.session, n.stats
    missing: list[str] = []
    for part, value in (("serving system", serving), ("signal", signal), ("operating mode", opmode)):
        if value is None:
            missing.append(part)
    if session is None:
        missing.append("session")
    ipv4 = n.ipv4
    if modem.at_port is None:
        missing.append("AT")
    operator = modem.operator
    source: Literal["at", "qmi"] | None = "at" if operator else None
    if not operator and serving is not None and serving.qmi_name:  # D2: QMI's name may come back garbled
        operator, source = serving.qmi_name, "qmi"
    values = measures(signal)
    state = LteState(
        router_id=router_id,
        read_at=now,
        available=True,
        device=dev,
        up=session.get("up") if session else None,
        pending=session.get("pending") if session else None,
        uptime_s=session.get("uptime") if session else None,
        ipv4=ipv4,
        rx_bytes=stats.get("rx_bytes") if stats else None,
        tx_bytes=stats.get("tx_bytes") if stats else None,
        registration=serving.registration if serving else None,
        radio=serving.radio if serving else None,
        roaming=serving.roaming if serving else None,
        operator=operator,
        operator_source=source,
        mcc=serving.mcc if serving else None,
        mnc=serving.mnc if serving else None,
        rssi=values["rssi"],
        rsrp=values["rsrp"],
        rsrq=values["rsrq"],
        snr=values["snr"],
        opmode=opmode,
        modem=modem,
        missing=tuple(missing),
    )
    return state, kept
