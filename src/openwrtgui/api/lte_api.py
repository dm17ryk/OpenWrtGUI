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
from openwrtgui.lte.service import AtNeedsConfirm, LteAction, LteBusy
from openwrtgui.lte.settings import Auth, LteSettings, PdpType
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
    metric: int | None = None
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


@router.post("/imei")
async def imei(router_id: str, ctx: Ctx) -> ImeiOut:
    return ImeiOut(imei=await ctx.lte.imei(_known(ctx, router_id)))
