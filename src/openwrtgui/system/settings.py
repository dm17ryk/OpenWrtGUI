"""System and time (v0.6b plan D5): hostname, time zone, NTP client and server, log buffer and remote
syslog as uci ops on the `system` section `uci -X show system` names and on `system.ntp`, plus the init
scripts that put each in effect (LuCI writes the same options and calls the same scripts)."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from openwrtgui.system import commands as s
from openwrtgui.uci import UciOp, drop_unchanged

LogProto = Literal["udp", "tcp"]
NTP = "system.ntp"
SYSTEM_RELOAD = s.init("system", "reload")
NTP_RESTART = s.init("sysntpd", "restart")
LOG_RESTART = s.init("log", "restart")
HOSTNAME_MESSAGE = "A hostname is 1 to 63 letters, digits or -, not starting or ending with -"
LOG_SIZE = (16, 1024)


@dataclass(frozen=True)
class SystemSettings:
    """None leaves a field as it is; log_ip "" removes the remote syslog (log_ip, log_port, log_proto)."""

    hostname: str | None = None
    zonename: str | None = None
    ntp_client: bool | None = None
    ntp_server: bool | None = None
    ntp_servers: tuple[str, ...] | None = None
    log_size: int | None = None
    log_ip: str | None = None
    log_port: int | None = None
    log_proto: LogProto | None = None


def system_section(current: Mapping[str, str]) -> str:
    section = next(
        (k for k, v in current.items() if k.count(".") == 1 and k.startswith("system.") and v == "system"),
        None,
    )
    if section is None:
        raise ValueError("This router's system config has no system section")
    return section


def current_settings(current: Mapping[str, str]) -> SystemSettings:
    sec = system_section(current)
    port = current.get(f"{sec}.log_port", "")
    size = current.get(f"{sec}.log_size", "")
    proto = current.get(f"{sec}.log_proto")
    return SystemSettings(
        hostname=current.get(f"{sec}.hostname", "OpenWrt"),
        zonename=current.get(f"{sec}.zonename", "UTC"),
        ntp_client=current.get(f"{NTP}.enabled", "1") == "1",
        ntp_server=current.get(f"{NTP}.enable_server", "0") == "1",
        ntp_servers=tuple(current.get(f"{NTP}.server", "").split()),
        log_size=int(size) if size.isdigit() else None,
        log_ip=current.get(f"{sec}.log_ip", ""),
        log_port=int(port) if port.isdigit() else None,
        log_proto=proto if proto in ("udp", "tcp") else None,  # type: ignore[arg-type]
    )


def _system_ops(
    sec: str, current: Mapping[str, str], req: SystemSettings, zones: Mapping[str, str]
) -> list[UciOp]:
    ops: list[UciOp] = []
    if req.hostname is not None:
        if not s.HOSTNAME.fullmatch(req.hostname):
            raise ValueError(HOSTNAME_MESSAGE)
        ops.append(UciOp("set", f"{sec}.hostname", req.hostname))
    if req.zonename is not None:
        if req.zonename not in zones:
            raise ValueError(f"{req.zonename} is not a time zone this router knows")
        ops += [
            UciOp("set", f"{sec}.zonename", req.zonename),
            UciOp("set", f"{sec}.timezone", zones[req.zonename]),
        ]
    if req.log_size is not None:
        if not LOG_SIZE[0] <= req.log_size <= LOG_SIZE[1]:
            raise ValueError(f"The log buffer is {LOG_SIZE[0]} to {LOG_SIZE[1]} KiB")
        ops.append(UciOp("set", f"{sec}.log_size", str(req.log_size)))
    return ops


def _syslog_ops(sec: str, req: SystemSettings) -> list[UciOp]:
    if req.log_ip == "":
        return [UciOp("delete", f"{sec}.{option}") for option in ("log_ip", "log_port", "log_proto")]
    ops: list[UciOp] = []
    if req.log_ip is not None:
        try:
            ipaddress.IPv4Address(req.log_ip)
        except ValueError:
            raise ValueError(f"{req.log_ip} is not an IPv4 address") from None
        ops.append(UciOp("set", f"{sec}.log_ip", req.log_ip))
    if req.log_port is not None:
        if not 1 <= req.log_port <= 65535:
            raise ValueError("The remote syslog port is 1 to 65535")
        ops.append(UciOp("set", f"{sec}.log_port", str(req.log_port)))
    if req.log_proto is not None:
        ops.append(UciOp("set", f"{sec}.log_proto", req.log_proto))
    return ops


def _ntp_ops(current: Mapping[str, str], req: SystemSettings) -> list[UciOp]:
    ops: list[UciOp] = []
    if NTP not in current and any(v is not None for v in (req.ntp_client, req.ntp_server, req.ntp_servers)):
        ops.append(UciOp("set", NTP, "timeserver"))
    if req.ntp_client is not None:
        ops.append(UciOp("set", f"{NTP}.enabled", "1" if req.ntp_client else "0"))
    if req.ntp_server is not None:
        ops.append(UciOp("set", f"{NTP}.enable_server", "1" if req.ntp_server else "0"))
    if req.ntp_servers is not None and list(req.ntp_servers) != current.get(f"{NTP}.server", "").split():
        for server in req.ntp_servers:
            if not s.NTP_SERVER.fullmatch(server):
                raise ValueError(f"{server!r} is not an NTP server name or address")
        ops.append(UciOp("delete", f"{NTP}.server"))
        ops += [UciOp("add_list", f"{NTP}.server", server) for server in req.ntp_servers]
    return ops


def settings_ops(
    current: Mapping[str, str], req: SystemSettings, zones: Mapping[str, str]
) -> tuple[list[UciOp], list[str]]:
    """The changes (unchanged values dropped) and the init scripts that put them in effect, in order."""
    sec = system_section(current)
    ops = drop_unchanged(
        [*_system_ops(sec, current, req, zones), *_syslog_ops(sec, req), *_ntp_ops(current, req)], current
    )
    names = {op.path.rsplit(".", 1)[1] for op in ops if op.path.count(".") == 2}
    reloads: list[str] = []
    if names & {"hostname", "zonename", "timezone", "log_size"}:
        reloads.append(SYSTEM_RELOAD)
    if names & {"log_ip", "log_port", "log_proto", "log_size"}:
        reloads.append(LOG_RESTART)
    if any(op.path.startswith(NTP) for op in ops):
        reloads.append(NTP_RESTART)
    return ops, reloads
