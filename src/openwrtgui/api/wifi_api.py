"""Wi-Fi per router: state, preview, apply with proof on air, All options, stations."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.models import Ok
from openwrtgui.context import AppContext
from openwrtgui.wifi.model import (
    ChannelSelection,
    Mode,
    ModeSelection,
    RadioRequest,
    Security,
    SsidRequest,
    TxPowerSetting,
)
from openwrtgui.wifi.options import OptionEdit, OptionRow
from openwrtgui.wifi.service import ApplyResult, Expectation, WifiPlan
from openwrtgui.wifi.state import WifiState
from openwrtgui.wifi.stations import Station

router = APIRouter(
    prefix="/api/routers/{router_id}/wifi", dependencies=[Depends(require_token)], tags=["wifi"]
)
Ctx = Annotated[AppContext, Depends(get_ctx)]


class ModesIn(BaseModel):
    kind: Literal["auto", "all", "set"]
    modes: list[Mode] = []

    def to_domain(self) -> ModeSelection:
        if self.kind == "auto":
            return ModeSelection.auto()
        return ModeSelection.all() if self.kind == "all" else ModeSelection.of(*self.modes)


class ChannelsIn(BaseModel):
    kind: Literal["auto", "all", "none", "set"]
    channels: list[int] = []

    def to_domain(self) -> ChannelSelection:
        if self.kind == "set":
            return ChannelSelection.of(*self.channels)
        return ChannelSelection(self.kind)


class TxPowerIn(BaseModel):
    kind: Literal["auto", "fixed"]
    dbm: int | None = None


class SsidIn(BaseModel):
    section: str
    ssid: str | None = None
    security: Security | None = None
    key: str | None = Field(default=None, repr=False)


class RadioRequestIn(BaseModel):
    radio: str
    modes: ModesIn | None = None
    channels: ChannelsIn | None = None
    txpower: TxPowerIn | None = None
    ssids: list[SsidIn] = []

    def to_domain(self) -> RadioRequest:
        return RadioRequest(
            radio=self.radio,
            modes=self.modes.to_domain() if self.modes else None,
            channels=self.channels.to_domain() if self.channels else None,
            txpower=TxPowerSetting(self.txpower.kind, self.txpower.dbm) if self.txpower else None,
            ssids=tuple(SsidRequest(s.section, s.ssid, s.security, s.key) for s in self.ssids),
        )


class PlanOut(BaseModel):
    """The preview: never the script itself, which can hold a Wi-Fi key."""

    router_id: str
    radio: str
    lines: list[str]
    warnings: list[str]
    expect: Expectation

    @classmethod
    def of(cls, plan: WifiPlan) -> PlanOut:
        return cls(
            router_id=plan.router_id,
            radio=plan.radio,
            lines=list(plan.lines),
            warnings=list(plan.warnings),
            expect=plan.expect,
        )


class OptionEditIn(BaseModel):
    section: str
    name: str
    value: str | list[str] | None = Field(default=None, repr=False)


class OptionsIn(BaseModel):
    radio: str
    edits: list[OptionEditIn]

    def edits_domain(self) -> list[OptionEdit]:
        return [OptionEdit(e.section, e.name, e.value) for e in self.edits]


class BlockIn(BaseModel):
    seconds: int


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


@router.get("")
async def wifi_state(router_id: str, ctx: Ctx) -> WifiState:
    return await ctx.wifi.state(_known(ctx, router_id))


@router.post("/preview")
async def wifi_preview(router_id: str, body: RadioRequestIn, ctx: Ctx) -> PlanOut:
    return PlanOut.of(await ctx.wifi.plan(_known(ctx, router_id), body.to_domain()))


@router.post("/apply")
async def wifi_apply(router_id: str, body: RadioRequestIn, ctx: Ctx) -> ApplyResult:
    return await ctx.wifi.apply(_known(ctx, router_id), body.to_domain())


@router.get("/options")
async def wifi_options(router_id: str, radio: str, ctx: Ctx) -> list[OptionRow]:
    return await ctx.wifi.options(_known(ctx, router_id), radio)


@router.post("/options/preview")
async def wifi_options_preview(router_id: str, body: OptionsIn, ctx: Ctx) -> PlanOut:
    return PlanOut.of(await ctx.wifi.plan_options(_known(ctx, router_id), body.radio, body.edits_domain()))


@router.post("/options/apply")
async def wifi_options_apply(router_id: str, body: OptionsIn, ctx: Ctx) -> ApplyResult:
    return await ctx.wifi.apply_options(_known(ctx, router_id), body.radio, body.edits_domain())


@router.get("/stations")
async def wifi_stations(router_id: str, ctx: Ctx) -> list[Station]:
    return await ctx.wifi.stations(_known(ctx, router_id))


@router.post("/stations/{mac}/deauth")
async def wifi_deauth(router_id: str, mac: str, ctx: Ctx) -> Ok:
    result = await ctx.wifi.deauth(_known(ctx, router_id), mac)
    if not result.ok:
        raise HTTPException(status_code=502, detail=f"The router refused: {result.stderr.strip()}")
    return Ok()


@router.post("/stations/{mac}/block")
async def wifi_block(router_id: str, mac: str, body: BlockIn, ctx: Ctx) -> Ok:
    result = await ctx.wifi.block(_known(ctx, router_id), mac, body.seconds)
    if not result.ok:
        raise HTTPException(status_code=502, detail=f"The router refused: {result.stderr.strip()}")
    return Ok()
