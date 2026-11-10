"""What the System screen shows (v0.6b plan, "Rules"): the overview, log entries in one shape for both logs,
the process list. A read that does not answer is named in `missing`; the rest still shows."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.system import commands as s
from openwrtgui.system.parse import ProcessRow, parse_board, parse_dmesg, parse_info, parse_logread
from openwrtgui.transport.base import Transport

KERNEL_LEVELS = ("emerg", "alert", "crit", "err", "warning", "notice", "info", "debug")
LogKind = Literal["system", "kernel"]


class SystemOverview(BaseModel):
    model_config = ConfigDict(frozen=True)

    router_id: str
    read_at: datetime
    model: str | None = None
    board_name: str | None = None
    kernel: str | None = None
    hostname: str | None = None
    system: str | None = None
    release: str | None = None
    revision: str | None = None
    localtime: int | None = None
    uptime_s: int | None = None
    load: tuple[float, float, float] | None = None
    memory_total: int | None = None
    memory_available: int | None = None
    root_total_kib: int | None = None
    root_free_kib: int | None = None
    tmp_total_kib: int | None = None
    tmp_free_kib: int | None = None
    missing: tuple[str, ...] = ()


class LogEntry(BaseModel):
    """One line of the system log or the kernel log, in the same shape (the screen filters both alike)."""

    model_config = ConfigDict(frozen=True)

    time: str | None = None
    seconds: float | None = None
    facility: str | None = None
    level: str | None = None
    source: str | None = None
    pid: int | None = None
    message: str


class ProcessList(BaseModel):
    model_config = ConfigDict(frozen=True)

    rows: list[ProcessRow]
    cpu: str | None
    column: str | None  # the memory column the router prints: RSS (AP2) or VSZ


async def _stdout(t: Transport, command: str) -> str | None:
    result = await t.run(command)
    return result.stdout if result.ok else None


async def read_overview(t: Transport, *, router_id: str, now: datetime) -> SystemOverview:
    board_text = await _stdout(t, s.BOARD)
    info_text = await _stdout(t, s.INFO)
    board = parse_board(board_text) if board_text is not None else None
    info = parse_info(info_text) if info_text is not None else None
    missing = tuple(part for part, value in (("board", board), ("system info", info)) if value is None)
    fields: dict[str, object] = {}
    if board is not None:
        fields |= {k: getattr(board, k) for k in ("model", "board_name", "kernel", "hostname", "system")}
        fields |= {"release": board.release, "revision": board.revision}
    if info is not None:
        fields |= {
            k: getattr(info, k)
            for k in (
                "localtime",
                "uptime_s",
                "load",
                "memory_total",
                "memory_available",
                "root_total_kib",
                "root_free_kib",
                "tmp_total_kib",
                "tmp_free_kib",
            )
        }
    return SystemOverview(router_id=router_id, read_at=now, missing=missing, **fields)  # type: ignore[arg-type]


def log_entries(text: str, kind: LogKind) -> list[LogEntry]:
    if kind == "system":
        return [
            LogEntry(
                time=e.time, facility=e.facility, level=e.level, source=e.source, pid=e.pid, message=e.message
            )
            for e in parse_logread(text)
        ]
    return [
        LogEntry(
            seconds=e.seconds,
            facility="kern",
            level=KERNEL_LEVELS[e.level] if e.level is not None and e.level < len(KERNEL_LEVELS) else None,
            source="kernel",
            message=e.message,
        )
        for e in parse_dmesg(text)
    ]
