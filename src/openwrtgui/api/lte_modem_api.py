"""The LTE screen's SIM, SMS and USSD endpoints (v1.3b E1), under the LTE screen's prefix. `GET /lte` keeps
its pinned read count: each card reads its own endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.net_api import Digest, NetPlanOut
from openwrtgui.context import AppContext
from openwrtgui.lte.commands import Storage
from openwrtgui.lte.modem import NoSuchMessage, PinRefused, PinResult, SmsDone, SmsList
from openwrtgui.lte.sim import SimState
from openwrtgui.lte.sms import SmsMessage
from openwrtgui.lte.ussd import UssdReply

router = APIRouter(prefix="/api/routers/{router_id}/lte", dependencies=[Depends(require_token)], tags=["lte"])
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


class PinIn(BaseModel):
    """E4: never stored, logged or returned; the 422 handler drops the input it would echo."""

    pin: str = Field(repr=False, max_length=16)


@router.get("/sim")
async def sim(router_id: str, ctx: Ctx) -> SimState:
    return await ctx.lte_modem.sim(_known(ctx, router_id))


@router.post("/sim/pin")
async def enter_pin(router_id: str, body: PinIn, ctx: Ctx) -> PinResult:
    """409 when the SIM does not ask for a PIN, is blocked, has one try left or no tries count (E3), or another
    LTE write or Recover holds the router; 423 during a harness run. A 200 that is not accepted may still have
    sent the PIN: its message says so."""
    try:
        return await ctx.lte_modem.enter_pin(_known(ctx, router_id), body.pin)
    except PinRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ---------------------------------------------------------------- SMS (E5, E6, E7)
MessageId = Annotated[int, Field(ge=0)]


class SmsDeleteIn(BaseModel):
    storage: Storage
    ids: list[MessageId] = Field(min_length=1, max_length=50)


class SmsDeleteApplyIn(SmsDeleteIn, Digest):
    pass


class SmsSendIn(BaseModel):
    target: str
    text: str = Field(max_length=500)


class SmsSendApplyIn(SmsSendIn, Digest):
    pass


@router.get("/sms")
async def sms_list(router_id: str, ctx: Ctx, storage: Storage = "sim") -> SmsList:
    return await ctx.lte_modem.messages(_known(ctx, router_id), storage)


@router.get("/sms/{storage}/{message_id}")
async def sms_message(
    router_id: str, storage: Storage, message_id: Annotated[int, Path(ge=0)], ctx: Ctx
) -> SmsMessage:
    """Read during a harness run too; 404 for an id that is not in the list."""
    try:
        return await ctx.lte_modem.message(_known(ctx, router_id), storage, message_id)
    except NoSuchMessage as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sms/delete/preview")
async def sms_delete_preview(router_id: str, body: SmsDeleteIn, ctx: Ctx) -> NetPlanOut:
    try:
        return NetPlanOut.of(await ctx.lte_modem.plan_delete(_known(ctx, router_id), body.storage, body.ids))
    except NoSuchMessage as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sms/delete/apply")
async def sms_delete_apply(router_id: str, body: SmsDeleteApplyIn, ctx: Ctx) -> SmsDone:
    """423 during a harness run; 409 when the list changed since the preview or an LTE action runs."""
    return await ctx.lte_modem.delete(_known(ctx, router_id), body.storage, body.ids, body.digest)


@router.post("/sms/send/preview")
async def sms_send_preview(router_id: str, body: SmsSendIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.lte_modem.plan_send(_known(ctx, router_id), body.target, body.text))


@router.post("/sms/send/apply")
async def sms_send_apply(router_id: str, body: SmsSendApplyIn, ctx: Ctx) -> SmsDone:
    """423 during a harness run; 409 when the text changed since the preview or an LTE action runs."""
    return await ctx.lte_modem.send(_known(ctx, router_id), body.target, body.text, body.digest)


# ---------------------------------------------------------------- USSD (E8, E9)
class UssdIn(BaseModel):
    code: str = Field(max_length=40)


class UssdApplyIn(UssdIn, Digest):
    pass


@router.post("/ussd/preview")
async def ussd_preview(router_id: str, body: UssdIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.lte_modem.plan_ussd(_known(ctx, router_id), body.code))


@router.post("/ussd/apply")
async def ussd_apply(router_id: str, body: UssdApplyIn, ctx: Ctx) -> UssdReply:
    """Up to 45 s: the network's reply, or "no reply". 423 during a harness run; 409 when the code changed
    since the preview or an LTE action runs."""
    return await ctx.lte_modem.ussd(_known(ctx, router_id), body.code, body.digest)
