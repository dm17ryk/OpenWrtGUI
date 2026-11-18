"""Every write without an HTTP Bench Guard test so far (v1.0b2 D13): previewed while clear, a harness run
starts, the apply answers 423, the audit log gains no line and the router hears nothing. And the second
layer: a run that starts while the planner reads is refused by run_audited."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import asyncssh
import httpx
import pytest
from test_v10a2_guard_api import WRITES as V10A2_WRITES
from test_v10a2_guard_api import _entries, add_ap4

from openwrtgui.context import AppContext
from openwrtgui.discovery.tools import ToolCard, ToolCommand
from openwrtgui.flash.plan import FlashRequest
from openwrtgui.simulator import SIM_GUARD_ENV
from openwrtgui.transport.base import CommandResult

IMAGES = Path(__file__).resolve().parents[2] / "fixtures" / "images"
MINI = (IMAGES / "mini-r35692.bin").read_bytes()
NEWER = (IMAGES / "mini-r35700.bin").read_bytes()
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
BOARD = "dlink,dwr-921-c3-uboot"
MIRROR = ToolCard(
    board=BOARD,
    path="/usr/sbin/wifi-mirror",
    name="wifi-mirror",
    commands=(
        ToolCommand(label="status", args=("status",), write=False),
        ToolCommand(label="stop", args=("stop",), write=True),
    ),
)
Body = Callable[[AppContext, httpx.AsyncClient], Awaitable[dict[str, object]]]


@dataclass(frozen=True)
class Write:
    router: str
    preview: str | None  # path under /api/routers/<router>/; None: the write has no preview
    apply: str
    body: Body
    first: bool = True  # the guard is checked before any router command: nothing reaches the router


def fixed(body: dict[str, object]) -> Body:
    async def build(ctx: AppContext, authed: httpx.AsyncClient) -> dict[str, object]:
        return body

    return build


async def _restore(ctx: AppContext, authed: httpx.AsyncClient) -> dict[str, object]:
    return {"name": (await ctx.system.create_backup("ap2")).name}


async def _kept(ctx: AppContext, authed: httpx.AsyncClient) -> dict[str, object]:
    text = (await authed.get("/api/routers/ap2/system/kept-files")).json()["text"]
    return {"text": f"{text}/etc/owg-test.conf\n"}


async def _key(ctx: AppContext, authed: httpx.AsyncClient) -> dict[str, object]:
    key = asyncssh.generate_private_key("ssh-ed25519", comment="ci@lab")
    return {"add": [key.export_public_key("openssh").decode().strip()], "remove": []}


async def _leds(ctx: AppContext, authed: httpx.AsyncClient) -> dict[str, object]:
    rows = (await authed.get("/api/routers/ap2/system/leds")).json()["rows"]
    lan = next(r for r in rows if r["section"] == "led_lan")
    return {"rows": [{**lan, "trigger": "heartbeat", "port_mask": None, "inverted": True}]}


async def _flash(ctx: AppContext, authed: httpx.AsyncClient) -> dict[str, object]:
    ctx.profiles.import_image(MINI, "mini-r35692.bin", NOW)
    ctx.profiles.import_image(NEWER, "mini-r35700.bin", NOW)
    req = FlashRequest(board=BOARD, revision="r35700-0c0ffee000", sha256=hashlib.sha256(NEWER).hexdigest())
    return req.model_dump()


def _mini(body: dict[str, object], card: bool = False) -> Body:
    async def build(ctx: AppContext, authed: httpx.AsyncClient) -> dict[str, object]:
        ctx.profiles.import_image(MINI, "mini-r35692.bin", NOW)
        if card:
            put = await authed.put(f"/api/tools/{BOARD}", json=MIRROR.model_dump())
            assert put.status_code == 200, put.text
        return body

    return build


async def _entries_body(ctx: AppContext, authed: httpx.AsyncClient) -> dict[str, object]:
    return await _entries(authed)  # ap4's mount points as read, the first one disabled


SSH = {
    "instances": [
        {
            "section": "main",
            "enable": True,
            "interface": "",
            "port": 22,
            "password_auth": True,
            "root_password_auth": True,
            "gateway_ports": True,
        }
    ],
    "remove": [],
}
S = "system"
WRITES = [
    Write("ap2", f"{S}/settings/preview", f"{S}/settings/apply", fixed({"hostname": "bench-ap2"})),
    Write(
        "ap2", f"{S}/service/preview", f"{S}/service/apply", fixed({"name": "sysntpd", "action": "restart"})
    ),
    Write(
        "ap2",
        f"{S}/rc-local/preview",
        f"{S}/rc-local/apply",
        fixed({"text": "# boot\nlogger owg-boot\nexit 0\n"}),
    ),
    Write(
        "ap2", f"{S}/crontab/preview", f"{S}/crontab/apply", fixed({"text": "*/5 * * * * logger owg-test"})
    ),
    Write("ap2", f"{S}/reboot/preview", f"{S}/reboot/start", fixed({})),
    Write(
        "ap2",
        f"{S}/reset/preview",
        f"{S}/reset/start",
        fixed({"confirm_name": "AP2 · office", "alone": True}),
    ),
    Write("ap2", f"{S}/restore/preview", f"{S}/restore/start", _restore),
    Write("ap2", f"{S}/kept-files/preview", f"{S}/kept-files/apply", _kept),
    Write("ap2", f"{S}/password/preview", f"{S}/password/apply", fixed({"password": "Zq7-Secret-77"})),
    Write(
        "ap2",
        f"{S}/password-policy/preview",
        f"{S}/password-policy/apply",
        fixed({"enabled": True, "pw_length": 8, "digits": True}),
    ),
    Write("ap2", f"{S}/ssh-keys/preview", f"{S}/ssh-keys/apply", _key),
    Write("ap2", f"{S}/leds/preview", f"{S}/leds/apply", _leds),
    Write("ap2", f"{S}/http/preview", f"{S}/http/apply", fixed({"luci_on_network": False})),
    Write("ap2", f"{S}/ssh/preview", f"{S}/ssh/apply", fixed(SSH)),
    Write("ap2", "lte/action/preview", "lte/action/apply", fixed({"action": "disconnect"})),
    Write("ap2", "lte/settings/preview", "lte/settings/apply", fixed({"apn": "internet"}), first=False),
    Write("ap2", None, "lte/at", fixed({"command": "AT+CFUN=0", "confirmed": True})),
    Write("ap2", "flash/preview", "flash/start", _flash),
    Write(
        "ap2",
        "discovery/copy/preview",
        "discovery/copy/apply",
        fixed({"paths": ["/root/notes.txt"], "target": "ap1"}),
    ),
    Write("ap1", "discovery/help/preview", "discovery/help/apply", _mini({"path": "/usr/sbin/wifi-mirror"})),
    Write(
        "ap1",
        "discovery/tool/preview",
        "discovery/tool/apply",
        _mini({"path": "/usr/sbin/wifi-mirror", "label": "stop", "values": {}}, card=True),
        first=False,
    ),
    Write(
        "ap1",
        "discovery/service/preview",
        "discovery/service/apply",
        _mini({"name": "dwr921-internet-led", "action": "restart"}),
    ),
]
# the writes whose service plans inside ApplyRunner.run_planned with no read before it (LTE settings reads the
# network first, so a run starting there meets the first layer, not run_audited)
RUNNER_APPLIES = {
    f"{S}/{name}/apply"
    for name in (
        "settings",
        "service",
        "rc-local",
        "crontab",
        "kept-files",
        "password-policy",
        "ssh-keys",
        "leds",
        "http",
        "ssh",
    )
}
RUNNER = [w for w in WRITES if w.apply in RUNNER_APPLIES]
V10A2 = [
    Write("ap4", f"{p}/preview", f"{p}/apply", fixed(b) if b is not None else _entries_body)
    for p, b in V10A2_WRITES
]


def _recorded(
    original: Callable[..., Awaitable[CommandResult]], sent: list[str]
) -> Callable[..., Awaitable[CommandResult]]:
    async def call(command: str, *args: object, **kw: object) -> CommandResult:
        sent.append(command)
        return await original(command, *args, **kw)

    return call


async def _record(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every command sent to ap1 or ap2 from now on: plain, with stdin or as an upload."""
    sent: list[str] = []
    for router_id in ("ap1", "ap2"):
        rec = ctx.routers.get(router_id)
        assert rec is not None
        t = await ctx.pool.get(rec)
        for name in ("run", "run_stdin", "upload"):
            original = getattr(t, name, None)
            if original is not None:
                monkeypatch.setattr(t, name, _recorded(original, sent))
    return sent


def _write_lines(commands: list[str]) -> set[str]:
    """Every line of the commands, trimmed: a write sent as a multi-line script still meets its preview line
    (the v1.0b2 final review: whole strings were compared). `set -e` alone says nothing."""
    return {s for c in commands for line in c.splitlines() if (s := line.strip()) and s != "set -e"}


def test_the_sweep_compares_line_by_line() -> None:
    writes = ["set -e", "uci set network.lan.ipaddr='10.0.0.1'"]
    sent = ["uci show network", "set -e\n  uci set network.lan.ipaddr='10.0.0.1'\nuci commit network"]
    assert not set(sent) & set(writes)  # what the whole-string compare saw
    assert _write_lines(sent) & _write_lines(writes) == {"uci set network.lan.ipaddr='10.0.0.1'"}


async def _previewed(
    write: Write, ctx: AppContext, authed: httpx.AsyncClient
) -> tuple[dict[str, object], list[str]]:
    """The apply's body with the preview's digest, and the preview's lines: the writes it would send."""
    body = await write.body(ctx, authed)
    if write.preview is None:
        return body, []
    preview = await authed.post(f"/api/routers/{write.router}/{write.preview}", json=body)
    assert preview.status_code == 200, preview.text
    return {**body, "digest": preview.json()["digest"]}, list(preview.json()["lines"])


@pytest.mark.parametrize("write", WRITES, ids=[f"{w.router}/{w.apply}" for w in WRITES])
async def test_a_previewed_write_is_refused_once_a_run_starts(
    ctx: AppContext, authed: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, write: Write
) -> None:
    body, writes = await _previewed(write, ctx, authed)
    sent = await _record(ctx, monkeypatch)
    monkeypatch.setenv(SIM_GUARD_ENV, "live")
    assert ctx.guard.check_local().live
    before = len(ctx.audit.query())
    applied = await authed.post(f"/api/routers/{write.router}/{write.apply}", json=body)
    assert applied.status_code == 423, applied.text
    assert len(ctx.audit.query()) == before  # nothing audited: nothing was written
    if write.first:
        assert sent == [], sent  # the guard came first: the router heard nothing at all
    else:  # it reads before its guard (the network state, the tool card): never one of the preview's writes
        assert writes and not _write_lines(sent) & _write_lines(writes), sent


@pytest.mark.parametrize("write", [*RUNNER, *V10A2], ids=lambda w: f"{w.router}/{w.apply}")
async def test_run_audited_refuses_when_the_run_starts_during_the_planner(
    ctx: AppContext, authed: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, write: Write
) -> None:
    """v1.0b1 final review minor: run_planned's early check has passed, so the write layer must refuse."""
    add_ap4(ctx)
    body, _ = await _previewed(write, ctx, authed)
    rec = ctx.routers.get(write.router)
    assert rec is not None
    t = await ctx.pool.get(rec)
    original = t.run
    flipped: list[str] = []

    async def live_on_first_read(command: str, *, timeout: float = 15.0) -> CommandResult:
        if not flipped:
            flipped.append(command)
            monkeypatch.setenv(SIM_GUARD_ENV, "live")
            ctx.guard.check_local()
        return await original(command, timeout=timeout)

    monkeypatch.setattr(t, "run", live_on_first_read)
    before = len(ctx.audit.query())
    applied = await authed.post(f"/api/routers/{write.router}/{write.apply}", json=body)
    assert flipped, "the planner read nothing"
    assert applied.status_code == 423, applied.text
    assert len(ctx.audit.query()) == before
