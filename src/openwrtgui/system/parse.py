"""What the System screen's reads print, parsed. A part that does not parse is None or an empty list: the
screen names it and shows the rest (v0.6b plan D2)."""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass
from typing import Any

LOAD_SCALE = 65536  # `ubus call system info` gives load averages times 65536


@dataclass(frozen=True)
class Board:
    model: str | None
    board_name: str | None
    kernel: str | None
    hostname: str | None
    system: str | None
    release: str | None
    revision: str | None


@dataclass(frozen=True)
class Info:
    localtime: int | None
    uptime_s: int | None
    load: tuple[float, float, float] | None
    memory_total: int | None
    memory_available: int | None
    root_total_kib: int | None
    root_free_kib: int | None
    tmp_total_kib: int | None
    tmp_free_kib: int | None


@dataclass(frozen=True)
class LogLine:
    time: str | None
    facility: str | None
    level: str | None
    source: str | None
    pid: int | None
    message: str


@dataclass(frozen=True)
class KernelLine:
    level: int | None
    seconds: float | None
    message: str


@dataclass(frozen=True)
class ProcessRow:
    pid: int
    ppid: int
    user: str
    state: str
    mem_kib: int  # RSS or VSZ: `parse_top` says which column this busybox build prints
    mem_pct: float
    cpu_pct: float
    command: str


@dataclass(frozen=True)
class RcService:
    name: str
    start: int | None
    stop: int | None
    enabled: bool
    running: bool
    instance: bool = True  # False: a one-shot (rc list has no "running": procd keeps no instance of it)


@dataclass(frozen=True)
class LiveSample:
    t: float
    load1: float | None
    load5: float | None
    load15: float | None
    interfaces: dict[str, tuple[int, int]]  # name -> (rx bytes, tx bytes)
    connections: int | None


@dataclass(frozen=True)
class Connection:
    proto: str
    src: str | None
    dst: str | None
    sport: int | None
    dport: int | None
    state: str | None
    bytes: int


def _object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def parse_board(text: str) -> Board | None:
    data = _object(text)
    if data is None:
        return None
    raw = data.get("release")
    release: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return Board(
        model=_str(data.get("model")),
        board_name=_str(data.get("board_name")),
        kernel=_str(data.get("kernel")),
        hostname=_str(data.get("hostname")),
        system=_str(data.get("system")),
        release=_str(release.get("description")),
        revision=_str(release.get("revision")),
    )


def _kib(part: object, key: str) -> int | None:
    return _int(part.get(key)) if isinstance(part, dict) else None


def parse_info(text: str) -> Info | None:
    data = _object(text)
    if data is None:
        return None
    load = data.get("load")
    loads = None
    if isinstance(load, list) and len(load) >= 3 and all(_int(x) is not None for x in load[:3]):
        loads = (
            round(load[0] / LOAD_SCALE, 2),
            round(load[1] / LOAD_SCALE, 2),
            round(load[2] / LOAD_SCALE, 2),
        )
    memory = data.get("memory")
    return Info(
        localtime=_int(data.get("localtime")),
        uptime_s=_int(data.get("uptime")),
        load=loads,
        memory_total=_kib(memory, "total"),
        memory_available=_kib(memory, "available"),
        root_total_kib=_kib(data.get("root"), "total"),
        root_free_kib=_kib(data.get("root"), "free"),
        tmp_total_kib=_kib(data.get("tmp"), "total"),
        tmp_free_kib=_kib(data.get("tmp"), "free"),
    )


# Sun Nov  8 15:29:02 2026 authpriv.info dropbear[24543]: message
_LOG = re.compile(
    r"(?P<time>\w{3} \w{3} [ \d]\d \d\d:\d\d:\d\d \d{4}) (?P<facility>\w+)\.(?P<level>\w+) "
    r"(?P<source>[^\s\[:]+)(?:\[(?P<pid>\d+)\])?: ?(?P<message>.*)"
)


def parse_logread(text: str) -> list[LogLine]:
    """Every line kept: one that does not look like logd's format keeps its text with no level."""
    out: list[LogLine] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _LOG.fullmatch(line)
        if m is None:
            out.append(LogLine(None, None, None, None, None, line))
            continue
        pid = m.group("pid")
        out.append(
            LogLine(
                m.group("time"),
                m.group("facility"),
                m.group("level"),
                m.group("source"),
                int(pid) if pid else None,
                m.group("message"),
            )
        )
    return out


_DMESG = re.compile(r"<(?P<level>\d+)>\[\s*(?P<seconds>\d+\.\d+)\] ?(?P<message>.*)")


def parse_dmesg(text: str) -> list[KernelLine]:
    out: list[KernelLine] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _DMESG.fullmatch(line)
        if m is None:
            out.append(KernelLine(None, None, line))
        else:
            out.append(KernelLine(int(m.group("level")), float(m.group("seconds")), m.group("message")))
    return out


def _mem_kib(text: str) -> int:
    """busybox top prints memory in KiB, or with an m/g suffix once it is wide."""
    unit = {"m": 1024, "g": 1024 * 1024}.get(text[-1:].lower())
    return round(float(text[:-1]) * unit) if unit else int(text)


_TOP_ROW = re.compile(
    r"\s*(?P<pid>\d+)\s+(?P<ppid>\d+)\s+(?P<user>\S+)\s+(?P<state>\S+(?: [<N])?)\s+(?P<mem>[\d.]+[mg]?)\s+"
    r"(?P<memp>\d+)%\s+(?P<cpu>\d+)%\s+(?P<command>.*)"
)
_TOP_HEADER = re.compile(r"\s*PID\s+PPID\s+USER\s+STAT\s+(?P<column>RSS|VSZ)\s+%(?:RSS|VSZ)\s+%CPU\s+COMMAND")


def parse_top(text: str) -> tuple[list[ProcessRow], str | None, str | None]:
    """`top -bn1`: the process rows (by CPU, then by memory), the CPU line's figures, and the memory column
    the build prints (AP2's busybox shows RSS; others VSZ)."""
    cpu: str | None = None
    column: str | None = None
    rows: list[ProcessRow] = []
    for line in text.splitlines():
        if line.startswith("CPU:"):
            cpu = line[len("CPU:") :].strip()
            continue
        if header := _TOP_HEADER.fullmatch(line):
            column = header.group("column")
            continue
        m = _TOP_ROW.fullmatch(line)
        if m is None:
            continue
        rows.append(
            ProcessRow(
                pid=int(m.group("pid")),
                ppid=int(m.group("ppid")),
                user=m.group("user"),
                state=m.group("state"),
                mem_kib=_mem_kib(m.group("mem")),
                mem_pct=float(m.group("memp")),
                cpu_pct=float(m.group("cpu")),
                command=m.group("command"),
            )
        )
    rows.sort(key=lambda r: (-r.cpu_pct, -r.mem_kib, r.pid))
    return rows, cpu, column


def parse_rc_list(text: str) -> list[RcService]:
    data = _object(text)
    if data is None:
        return []
    out = [
        RcService(
            name=name,
            start=_int(v.get("start")),
            stop=_int(v.get("stop")),
            enabled=v.get("enabled") is True,
            running=v.get("running") is True,
            instance="running" in v,
        )
        for name, v in data.items()
        if isinstance(v, dict)
    ]
    return sorted(out, key=lambda r: r.name)


def parse_timezones(text: str) -> dict[str, str]:
    """`luci getTimezones`: zone name -> its TZ string."""
    data = _object(text) or {}
    return {
        name: v["tzstring"]
        for name, v in data.items()
        if isinstance(v, dict) and isinstance(v.get("tzstring"), str)
    }


_DEV = re.compile(r"\s*(?P<name>[^\s:]+):\s*(?P<numbers>[\d\s]+)")


def parse_live(text: str, t: float) -> LiveSample:
    """The three files of `LIVE` in one text: /proc/loadavg, /proc/net/dev and nf_conntrack_count (absent
    when the conntrack module is not loaded)."""
    lines = text.splitlines()
    load: list[float | None] = [None, None, None]
    if lines and (parts := lines[0].split()) and len(parts) >= 3:
        with contextlib.suppress(ValueError):
            load = [float(parts[0]), float(parts[1]), float(parts[2])]
    interfaces: dict[str, tuple[int, int]] = {}
    connections: int | None = None
    for line in lines[1:]:
        m = _DEV.fullmatch(line)
        if m is not None:
            numbers = m.group("numbers").split()
            if len(numbers) >= 9 and m.group("name") != "lo":
                interfaces[m.group("name")] = (int(numbers[0]), int(numbers[8]))
        elif line.strip().isdigit():
            connections = int(line.strip())
    return LiveSample(t, load[0], load[1], load[2], interfaces, connections)


def rates(before: LiveSample, now: LiveSample) -> dict[str, tuple[float, float]]:
    """Bytes per second per interface between two samples (a counter that went back is a restart: 0)."""
    dt = now.t - before.t
    if dt <= 0:
        return {}
    out: dict[str, tuple[float, float]] = {}
    for name, (rx, tx) in now.interfaces.items():
        if name in before.interfaces:
            rx0, tx0 = before.interfaces[name]
            out[name] = (max(rx - rx0, 0) / dt, max(tx - tx0, 0) / dt)
    return out


_STATES = frozenset(
    {
        "ESTABLISHED",
        "SYN_SENT",
        "SYN_RECV",
        "FIN_WAIT",
        "CLOSE_WAIT",
        "LAST_ACK",
        "TIME_WAIT",
        "CLOSE",
        "LISTEN",
    }
)


def parse_conntrack(text: str) -> list[Connection]:
    out: list[Connection] = []
    for line in text.splitlines():
        tokens = line.split()
        if len(tokens) < 5:
            continue
        fields: dict[str, str] = {}
        total = 0
        for token in tokens:
            key, _, value = token.partition("=")
            if key == "bytes" and value.isdigit():
                total += int(value)
            elif value and key not in fields:
                fields[key] = value
        state = next((tok for tok in tokens if tok in _STATES), None)
        out.append(
            Connection(
                proto=tokens[2],
                src=fields.get("src"),
                dst=fields.get("dst"),
                sport=int(fields["sport"]) if fields.get("sport", "").isdigit() else None,
                dport=int(fields["dport"]) if fields.get("dport", "").isdigit() else None,
                state=state,
                bytes=total,
            )
        )
    return out
