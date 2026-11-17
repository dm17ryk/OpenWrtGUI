"""The LTE modem screen's endpoints (spec 7.10)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.net_api import Digest, NetPlanOut
from openwrtgui.api.wifi_api import OptionEditIn
from openwrtgui.context import AppContext
from openwrtgui.forms import OptionEdit, OptionRow
from openwrtgui.lte.at import AtResult
from openwrtgui.lte.recover import LteRecoverJob
from openwrtgui.lte.service import AtNeedsConfirm, LteAction, LteBusy, SetupMissing
from openwrtgui.lte.settings import METRIC_MAX, Auth, LteSettings, PdpType
from openwrtgui.lte.setups import LteSetupSummary
from openwrtgui.lte.state import LteState
from openwrtgui.net.apply import NetApplyResult

router = APIRouter(prefix="/api/routers/{router_id}/lte", dependencies=[Depends(require_token)], tags=["lte"])
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


class AtIn(BaseModel):
    command: str = Field(max_length=10_000)
    confirmed: bool = False


class ImeiOut(BaseModel):
    imei: str


class LteSettingsIn(BaseModel):
    """None leaves a field as it is; "" in a text field removes the option."""

    apn: str | None = None
    auth: Auth | None = None
    username: str | None = None
    password: str | None = Field(default=None, repr=False)
    pincode: str | None = Field(default=None, repr=False)
    pdptype: PdpType | None = None
    mtu: int | None = None
    metric: int | None = Field(default=None, ge=0, le=METRIC_MAX)  # netifd unsigned 32-bit (v1.0b2 D11)
    auto: bool | None = None
    defaultroute: bool | None = None
    edits: list[OptionEditIn] = []

    def to_domain(self) -> LteSettings:
        return LteSettings(
            apn=self.apn,
            auth=self.auth,
            username=self.username,
            password=self.password,
            pincode=self.pincode,
            pdptype=self.pdptype,
            mtu=self.mtu,
            metric=self.metric,
            auto=self.auto,
            defaultroute=self.defaultroute,
            edits=tuple(OptionEdit(e.section, e.name, e.value) for e in self.edits),
        )


class LteSettingsApplyIn(LteSettingsIn, Digest):
    pass


class ActionIn(BaseModel):
    action: LteAction


class ActionApplyIn(ActionIn, Digest):
    pass


@router.get("")
async def lte_state(router_id: str, ctx: Ctx) -> LteState:
    return await ctx.lte.state(_known(ctx, router_id))


@router.post("/action/preview")
async def action_preview(router_id: str, body: ActionIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.lte.plan_action(_known(ctx, router_id), body.action))


@router.post("/action/apply")
async def action_apply(router_id: str, body: ActionApplyIn, ctx: Ctx) -> NetApplyResult:
    try:
        return await ctx.lte.apply_action(_known(ctx, router_id), body.action, body.digest)
    except LteBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/settings/options")
async def settings_options(router_id: str, ctx: Ctx) -> list[OptionRow]:
    return await ctx.lte.settings_options(_known(ctx, router_id))


@router.post("/settings/preview")
async def settings_preview(router_id: str, body: LteSettingsIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.lte.plan_settings(_known(ctx, router_id), body.to_domain()))


@router.post("/settings/apply")
async def settings_apply(router_id: str, body: LteSettingsApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.lte.apply_settings(_known(ctx, router_id), body.to_domain(), body.digest)


@router.post("/at")
async def at_command(router_id: str, body: AtIn, ctx: Ctx) -> AtResult:
    try:
        return await ctx.lte.at_command(_known(ctx, router_id), body.command, body.confirmed)
    except AtNeedsConfirm as exc:
        raise HTTPException(status_code=428, detail=str(exc)) from exc
    except LteBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/setup")
async def save_setup(router_id: str, ctx: Ctx) -> LteSetupSummary:
    """Save good setup: refused (422) unless LTE works on the router right now."""
    return await ctx.lte.save_setup(_known(ctx, router_id), ctx.lte_setups)


class SetupSourceIn(BaseModel):
    """Reconfigure's source: the router whose saved setup is put back (the spec's `from`)."""

    source: str = Field(min_length=1, max_length=64)


class SetupApplyIn(SetupSourceIn, Digest):
    pass


@router.post("/setup/preview")
async def setup_preview(router_id: str, body: SetupSourceIn, ctx: Ctx) -> NetPlanOut:
    try:
        return NetPlanOut.of(await ctx.lte.plan_setup(_known(ctx, router_id), body.source, ctx.lte_setups))
    except SetupMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/setup/apply")
async def setup_apply(router_id: str, body: SetupApplyIn, ctx: Ctx) -> NetApplyResult:
    try:
        return await ctx.lte.apply_setup(_known(ctx, router_id), body.source, ctx.lte_setups, body.digest)
    except SetupMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class RecoverPreviewOut(BaseModel):
    lines: list[str]
    warnings: list[str]
    digest: str


@router.post("/recover/preview")
async def recover_preview(router_id: str, ctx: Ctx) -> RecoverPreviewOut:
    """Every command Recover may run; the server picks the router's own saved setup (spec 4.2)."""
    p = await ctx.lte_recover.preview(_known(ctx, router_id))
    return RecoverPreviewOut(lines=list(p.lines), warnings=list(p.warnings), digest=p.digest)


@router.post("/recover")
async def recover_start(router_id: str, body: Digest, ctx: Ctx) -> LteRecoverJob:
    """409 while another job holds the router or the preview changed; 423 during a harness run."""
    return await ctx.lte_recover.start(_known(ctx, router_id), body.digest)


@router.get("/recover")
async def recover_job(router_id: str, ctx: Ctx) -> LteRecoverJob | None:
    return ctx.lte_recover.job(_known(ctx, router_id))


@router.post("/recover/stop")
async def recover_stop(router_id: str, ctx: Ctx) -> LteRecoverJob | None:
    return await ctx.lte_recover.stop(_known(ctx, router_id))


@router.post("/imei")
async def imei(router_id: str, ctx: Ctx) -> ImeiOut:
    return ImeiOut(imei=await ctx.lte.imei(_known(ctx, router_id)))
