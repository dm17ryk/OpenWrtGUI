"""The System screen's endpoints (spec 7.11, v0.6b plan)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.net_api import Digest, NetPlanOut
from openwrtgui.context import AppContext
from openwrtgui.net.apply import NetApplyResult
from openwrtgui.system.commands import ServiceAction
from openwrtgui.system.service import Connections, DiagResult, DiagTool, TimeZones
from openwrtgui.system.services import ServiceRow
from openwrtgui.system.settings import LogProto, SystemSettings
from openwrtgui.system.state import LogEntry, LogKind, ProcessList, SystemOverview

router = APIRouter(
    prefix="/api/routers/{router_id}/system", dependencies=[Depends(require_token)], tags=["system"]
)
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


@router.get("")
async def overview(router_id: str, ctx: Ctx) -> SystemOverview:
    return await ctx.system.overview(_known(ctx, router_id))


@router.get("/logs")
async def logs(router_id: str, ctx: Ctx, kind: LogKind = "system", lines: int = 100) -> list[LogEntry]:
    """`lines` is 100, 500 or 2000 (anything else: 422 from the service)."""
    return await ctx.system.logs(_known(ctx, router_id), kind, lines)  # type: ignore[arg-type]


@router.get("/processes")
async def processes(router_id: str, ctx: Ctx) -> ProcessList:
    return await ctx.system.processes(_known(ctx, router_id))


@router.get("/services")
async def services(router_id: str, ctx: Ctx) -> list[ServiceRow]:
    return await ctx.system.services(_known(ctx, router_id))


class SettingsIn(BaseModel):
    """None leaves a field as it is; log_ip "" removes the remote syslog."""

    hostname: str | None = Field(default=None, max_length=63)
    zonename: str | None = Field(default=None, max_length=64)
    ntp_client: bool | None = None
    ntp_server: bool | None = None
    ntp_servers: list[str] | None = Field(default=None, max_length=16)
    log_size: int | None = None
    log_ip: str | None = Field(default=None, max_length=15)
    log_port: int | None = None
    log_proto: LogProto | None = None

    def to_domain(self) -> SystemSettings:
        servers = tuple(self.ntp_servers) if self.ntp_servers is not None else None
        fields = self.model_dump(exclude={"ntp_servers"})
        return SystemSettings(**fields, ntp_servers=servers)


class SettingsApplyIn(SettingsIn, Digest):
    pass


class SettingsOut(BaseModel):
    hostname: str | None
    zonename: str | None
    ntp_client: bool | None
    ntp_server: bool | None
    ntp_servers: list[str]
    log_size: int | None
    log_ip: str | None
    log_port: int | None
    log_proto: LogProto | None


@router.get("/settings")
async def settings(router_id: str, ctx: Ctx) -> SettingsOut:
    s = await ctx.system.settings(_known(ctx, router_id))
    return SettingsOut(**{**s.__dict__, "ntp_servers": list(s.ntp_servers or ())})


@router.post("/settings/preview")
async def settings_preview(router_id: str, body: SettingsIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.system.plan_settings(_known(ctx, router_id), body.to_domain()))


@router.post("/settings/apply")
async def settings_apply(router_id: str, body: SettingsApplyIn, ctx: Ctx) -> NetApplyResult:
    domain = SettingsIn(**body.model_dump(exclude={"digest"})).to_domain()
    return await ctx.system.apply_settings(_known(ctx, router_id), domain, body.digest)


class ServiceIn(BaseModel):
    name: str = Field(max_length=64)
    action: ServiceAction


class ServiceApplyIn(ServiceIn, Digest):
    pass


@router.post("/service/preview")
async def service_preview(router_id: str, body: ServiceIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.system.plan_service(_known(ctx, router_id), body.name, body.action))


@router.post("/service/apply")
async def service_apply(router_id: str, body: ServiceApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.system.apply_service(_known(ctx, router_id), body.name, body.action, body.digest)


class TextIn(BaseModel):
    text: str = Field(max_length=16 * 1024)  # the service says "at most 8 KiB" in its own words


class TextApplyIn(TextIn, Digest):
    pass


class TextOut(BaseModel):
    text: str


@router.get("/rc-local")
async def rc_local(router_id: str, ctx: Ctx) -> TextOut:
    return TextOut(text=await ctx.system.rc_local(_known(ctx, router_id)))


@router.post("/rc-local/preview")
async def rc_local_preview(router_id: str, body: TextIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.system.plan_rc_local(_known(ctx, router_id), body.text))


@router.post("/rc-local/apply")
async def rc_local_apply(router_id: str, body: TextApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.system.apply_rc_local(_known(ctx, router_id), body.text, body.digest)


class DiagnoseIn(BaseModel):
    tool: DiagTool
    target: str = Field(max_length=253)


@router.post("/diagnose")
async def diagnose(router_id: str, body: DiagnoseIn, ctx: Ctx) -> DiagResult:
    return await ctx.system.diagnose(_known(ctx, router_id), body.tool, body.target)


@router.get("/connections")
async def connections(router_id: str, ctx: Ctx) -> Connections:
    return await ctx.system.connections(_known(ctx, router_id))


@router.get("/timezones")
async def timezones(router_id: str, ctx: Ctx) -> TimeZones:
    return await ctx.system.timezones(_known(ctx, router_id))
