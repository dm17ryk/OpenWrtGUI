"""System › Access, LEDs and Mount points endpoints (spec 7.11, v0.6c plan)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.api.net_api import Digest, NetPlanOut
from openwrtgui.context import AppContext
from openwrtgui.net.apply import NetApplyResult
from openwrtgui.system.access import PasswordPolicy, SshChange
from openwrtgui.system.access_service import AccessState, LedState, MountState
from openwrtgui.system.sshkeys import KeysChange

router = APIRouter(
    prefix="/api/routers/{router_id}/system", dependencies=[Depends(require_token)], tags=["system"]
)
Ctx = Annotated[AppContext, Depends(get_ctx)]


def _known(ctx: AppContext, router_id: str) -> str:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return router_id


@router.get("/access")
async def access(router_id: str, ctx: Ctx) -> AccessState:
    return await ctx.access.access(_known(ctx, router_id))


@router.get("/leds")
async def leds(router_id: str, ctx: Ctx) -> LedState:
    return await ctx.access.leds(_known(ctx, router_id))


@router.get("/mounts")
async def mounts(router_id: str, ctx: Ctx) -> MountState:
    return await ctx.access.mounts(_known(ctx, router_id))


class PasswordIn(Digest):
    """The new password: checked by the service (no field limits here, so a refusal never echoes it)."""

    password: str


@router.post("/password/preview")
async def password_preview(router_id: str, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.access.plan_password(_known(ctx, router_id)))


@router.post("/password/apply")
async def password_apply(router_id: str, body: PasswordIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.access.apply_password(_known(ctx, router_id), body.password, body.digest)


class PolicyIn(BaseModel):
    enabled: bool = False
    pw_length: int = 0
    digits: bool = False
    uc_lc: bool = False
    special_characters: bool = False

    def to_domain(self) -> PasswordPolicy:
        return PasswordPolicy(**self.model_dump(exclude={"digest"}))


class PolicyApplyIn(PolicyIn, Digest):
    pass


@router.post("/password-policy/preview")
async def policy_preview(router_id: str, body: PolicyIn, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.access.plan_policy(_known(ctx, router_id), body.to_domain()))


@router.post("/password-policy/apply")
async def policy_apply(router_id: str, body: PolicyApplyIn, ctx: Ctx) -> NetApplyResult:
    return await ctx.access.apply_policy(_known(ctx, router_id), body.to_domain(), body.digest)


class KeysApplyIn(KeysChange):
    digest: str


@router.post("/ssh-keys/preview")
async def keys_preview(router_id: str, body: KeysChange, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.access.plan_keys(_known(ctx, router_id), body))


@router.post("/ssh-keys/apply")
async def keys_apply(router_id: str, body: KeysApplyIn, ctx: Ctx) -> NetApplyResult:
    change = KeysChange(add=body.add, remove=body.remove)
    return await ctx.access.apply_keys(_known(ctx, router_id), change, body.digest)


class KeyOwnerIn(BaseModel):
    fingerprint: str
    owner: str | None


@router.put("/ssh-keys/owner")
async def key_owner(router_id: str, body: KeyOwnerIn, ctx: Ctx) -> AccessState:
    """Name (or forget) a harness's key; the Access state comes back with the new labels."""
    _known(ctx, router_id)
    ctx.access.set_key_owner(body.fingerprint, body.owner)
    return await ctx.access.access(router_id)


class SshApplyIn(SshChange):
    digest: str


@router.post("/ssh/preview")
async def ssh_preview(router_id: str, body: SshChange, ctx: Ctx) -> NetPlanOut:
    return NetPlanOut.of(await ctx.access.plan_ssh(_known(ctx, router_id), body))


@router.post("/ssh/apply")
async def ssh_apply(router_id: str, body: SshApplyIn, ctx: Ctx) -> NetApplyResult:
    change = SshChange(instances=body.instances, remove=body.remove)
    return await ctx.access.apply_ssh(_known(ctx, router_id), change, body.digest)
