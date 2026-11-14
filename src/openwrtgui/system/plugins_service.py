"""System › Plugins (v1.0a2 D4): read the plugins and their switches; apply a change with the plain uci
apply."""

from __future__ import annotations

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
from openwrtgui.system.plugins import (
    LOGIN_WARNING,
    PLUGIN_FILE,
    PluginChange,
    PluginHeader,
    PluginState,
    parse_header,
    plugin_ops,
    plugin_state,
    read_plugin_command,
)
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.uci import parse_uci_show

SCREEN = "System"


class PluginsService:
    def __init__(self, *, pool: ConnectionPool, routers: RouterStore, runner: ApplyRunner) -> None:
        self._pool = pool
        self._routers = routers
        self._runner = runner

    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    async def _read(self, t: Transport) -> tuple[PluginState, dict[str, str]]:
        shown = await t.run(s.UCI_PLUGINS)
        uci = parse_uci_show(shown.stdout) if shown.ok else {}
        headers: list[PluginHeader] = []
        listed = await t.run(s.LIST_PLUGINS)  # no such folder: no plugins installed
        if listed.ok:
            for name in listed.stdout.split():
                if m := PLUGIN_FILE.fullmatch(name):
                    text = await t.run(read_plugin_command(m.group(1)))
                    header = parse_header(m.group(1), text.stdout) if text.ok else None
                    if header is not None:
                        headers.append(header)
        state = plugin_state(uci, headers)
        if not shown.ok:
            state = state.model_copy(update={"missing": ("luci_plugins config",)})
        return state, uci

    async def state(self, router_id: str) -> PluginState:
        rec = self._record(router_id)
        return (await self._read(await self._pool.get(rec)))[0]

    def _plan(
        self, rec: RouterRecord, state: PluginState, current: dict[str, str], change: PluginChange
    ) -> NetPlan:
        if state.missing:
            raise ValueError(
                f"{rec.name} has no /etc/config/luci_plugins: LuCI's Plugins page is not on this image"
            )
        login_on = any(on and k.startswith("auth_") for k, on in change.groups.items()) or any(
            change.plugins.get(r.id) and r.group.startswith("auth_") for r in state.plugins
        )
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config="luci_plugins",
            ops=plugin_ops(state, change),
            current=current,
            warnings=[LOGIN_WARNING] if login_on else [],
        )

    async def plan(self, router_id: str, change: PluginChange) -> NetPlan:
        rec = self._record(router_id)
        state, current = await self._read(await self._pool.get(rec))
        return self._plan(rec, state, current, change)

    async def apply(self, router_id: str, change: PluginChange, digest: str | None) -> NetApplyResult:
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            state, current = await self._read(t)
            plan = self._plan(rec, state, current, change)

            async def verify(t2: Transport) -> list[NetCheck]:
                return [await saved_check(t2, s.UCI_PLUGINS, plan.ops, current)]

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, digest)
