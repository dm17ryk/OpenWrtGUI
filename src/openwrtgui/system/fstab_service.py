"""Mount points with block-mount (v1.0a2 D5): read fstab and the block devices; apply edits, Generate Config,
Unmount and Mount attached devices through the plain apply."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from openwrtgui.net.apply import (
    ApplyRunner,
    NetApplyResult,
    NetCheck,
    NetPlan,
    Planned,
    net_plan,
    saved_check,
)
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.system import commands as s
from openwrtgui.system.fstab import (
    MOUNT_PATH,
    PROTECTED,
    FstabChange,
    FstabState,
    fstab_ops,
    generate_ops,
    parse_block_devices,
    parse_detect,
    parse_fstab,
    present,
)
from openwrtgui.system.mounts import parse_mounts
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.uci import UciOp, parse_uci_show, shell_quote

SCREEN = "System"
GENERATE_WARNING = (
    "Replaces every fstab section with what block detect finds now; the mounts it finds start disabled."
)
Build = Callable[[Transport], Awaitable[tuple[NetPlan, dict[str, str]]]]


class FstabService:
    def __init__(self, *, pool: ConnectionPool, routers: RouterStore, runner: ApplyRunner) -> None:
        self._pool = pool
        self._routers = routers
        self._runner = runner

    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    async def _read(self, t: Transport) -> tuple[FstabState, dict[str, str]]:
        if (await t.run(s.HAS_BLOCK)).exit_status != 0:
            return FstabState(block=False), {}
        shown = await t.run(s.UCI_FSTAB)
        uci = parse_uci_show(shown.stdout) if shown.ok else {}
        name, settings, entries = parse_fstab(uci)
        devices = await t.run(s.BLOCK_DEVICES)
        missing = (() if shown.ok else ("fstab config",)) + (() if devices.ok else ("block devices",))
        state = FstabState(
            block=True,
            settings=settings,
            global_section=name,
            entries=entries,
            devices=parse_block_devices(devices.stdout) if devices.ok else [],
            missing=missing,
        )
        return state, uci

    async def state(self, router_id: str) -> FstabState:
        return (await self._read(await self._pool.get(self._record(router_id))))[0]

    def _usable(self, rec: RouterRecord, state: FstabState) -> None:
        if not state.block:
            raise ValueError(f"{rec.name} has no block-mount: LuCI's Mount Points page is not on this image")
        if "fstab config" in state.missing:
            raise ValueError(
                f"{rec.name} has no /etc/config/fstab: create it in the terminal with `block detect`"
            )

    def _uci_plan(
        self,
        rec: RouterRecord,
        current: dict[str, str],
        ops: Sequence[UciOp],
        *,
        mount: bool,
        warnings: Sequence[str] = (),
    ) -> NetPlan:
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config="fstab",
            ops=ops,
            current=current,
            reloads=[s.BLOCK_MOUNT] if mount else [],
            warnings=warnings,
        )

    async def _change_plan(
        self, rec: RouterRecord, t: Transport, change: FstabChange
    ) -> tuple[NetPlan, dict[str, str]]:
        state, current = await self._read(t)
        self._usable(rec, state)
        ops = fstab_ops(state.global_section, state.entries, change)
        return self._uci_plan(rec, current, ops, mount=True), current

    async def _generate_plan(self, rec: RouterRecord, t: Transport) -> tuple[NetPlan, str]:
        state, current = await self._read(t)
        self._usable(rec, state)
        detected = await t.run(s.BLOCK_DETECT)
        if not detected.ok:
            why = (detected.stderr or detected.stdout).strip()
            raise ValueError(f"block detect failed on {rec.name}: {why}")
        ops = generate_ops(state.global_section, state.entries, detected.stdout)
        return self._uci_plan(rec, current, ops, mount=False, warnings=[GENERATE_WARNING]), detected.stdout

    async def plan(self, router_id: str, change: FstabChange) -> NetPlan:
        rec = self._record(router_id)
        return (await self._change_plan(rec, await self._pool.get(rec), change))[0]

    async def plan_generate(self, router_id: str) -> NetPlan:
        rec = self._record(router_id)
        return (await self._generate_plan(rec, await self._pool.get(rec)))[0]

    async def _apply_uci(self, rec: RouterRecord, digest: str | None, build: Build) -> NetApplyResult:
        async def make(t: Transport) -> Planned:
            plan, current = await build(t)

            async def verify(t2: Transport) -> list[NetCheck]:
                return [await saved_check(t2, s.UCI_FSTAB, plan.ops, current)]

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, digest)

    async def apply(self, router_id: str, change: FstabChange, digest: str | None) -> NetApplyResult:
        rec = self._record(router_id)
        return await self._apply_uci(rec, digest, lambda t: self._change_plan(rec, t, change))

    async def apply_generate(self, router_id: str, digest: str | None) -> NetApplyResult:
        """Proven by content: fstab read back is what block detect printed. (saved_check cannot prove it: a
        deleted unnamed section whose twin is added again, such as an unchanged `global`, looks kept.)"""
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            plan, detected = await self._generate_plan(rec, t)
            want = parse_detect(detected)

            async def verify(t2: Transport) -> list[NetCheck]:
                _name, settings, entries = parse_fstab(parse_uci_show((await t2.run(s.UCI_FSTAB)).stdout))
                same = (settings, [e.model_copy(update={"section": None}) for e in entries]) == want
                detail = "holds" if same else "differs from"
                return [NetCheck("saved", same, f"fstab {detail} what block detect found")]

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, digest)

    # ---------------------------------------------------------------- Unmount, Mount attached devices
    async def _mounted(self, t: Transport) -> set[str]:
        return {m.target for m in parse_mounts((await t.run(s.MOUNTS)).stdout)}

    async def _unmount_plan(self, rec: RouterRecord, t: Transport, target: str) -> NetPlan:
        if not MOUNT_PATH.fullmatch(target):
            raise ValueError(f"{target!r} is not a mount point")
        if PROTECTED.fullmatch(target):
            raise ValueError(f"{target} is not unmounted here (LuCI offers no Unmount for it)")
        self._usable(rec, (await self._read(t))[0])
        if target not in await self._mounted(t):
            raise ValueError(f"Nothing is mounted at {target}")
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config=None,
            ops=[],
            current={},
            commands=[f"umount {shell_quote(target)}"],
        )

    async def plan_unmount(self, router_id: str, target: str) -> NetPlan:
        rec = self._record(router_id)
        return await self._unmount_plan(rec, await self._pool.get(rec), target)

    async def apply_unmount(self, router_id: str, target: str, digest: str | None) -> NetApplyResult:
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            plan = await self._unmount_plan(rec, t, target)

            async def verify(t2: Transport) -> list[NetCheck]:
                gone = target not in await self._mounted(t2)
                detail = "no longer in /proc/mounts" if gone else "still mounted"
                return [NetCheck(f"{target} unmounted", gone, detail)]

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, digest)

    async def _mount_plan(self, rec: RouterRecord, t: Transport) -> tuple[NetPlan, FstabState]:
        state = (await self._read(t))[0]
        self._usable(rec, state)
        plan = net_plan(
            router_id=rec.id, screen=SCREEN, config=None, ops=[], current={}, commands=[s.BLOCK_MOUNT]
        )
        return plan, state

    async def plan_mount(self, router_id: str) -> NetPlan:
        rec = self._record(router_id)
        return (await self._mount_plan(rec, await self._pool.get(rec)))[0]

    async def apply_mount(self, router_id: str, digest: str | None) -> NetApplyResult:
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            plan, state = await self._mount_plan(rec, t)
            wanted = [
                e.target
                for e in state.entries
                if e.kind == "mount" and e.enabled and e.target and present(e, state.devices)
            ]

            async def verify(t2: Transport) -> list[NetCheck]:
                mounted = await self._mounted(t2)
                checks = [NetCheck(f"{target} mounted", target in mounted, "") for target in wanted]
                return checks or [NetCheck("block mount", True, "no enabled mount has its device here")]

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, digest)
