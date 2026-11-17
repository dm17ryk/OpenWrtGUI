"""Every router's saved good LTE setup (spec 4.4): the list Reconfigure chooses from. No secrets."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.context import AppContext
from openwrtgui.lte.setups import LteSetupSummary

router = APIRouter(prefix="/api/lte-setups", dependencies=[Depends(require_token)], tags=["lte"])
Ctx = Annotated[AppContext, Depends(get_ctx)]


@router.get("")
async def lte_setups(ctx: Ctx) -> list[LteSetupSummary]:
    return ctx.lte_setups.summaries()
