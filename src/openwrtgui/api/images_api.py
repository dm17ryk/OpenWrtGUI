"""Imported images (Settings › Images): import a sysupgrade file sent as the raw request body, list and delete
profiles, and build a profile from a router's /rom."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.context import AppContext
from openwrtgui.images.profile import Profile, ProfileKey
from openwrtgui.images.sysupgrade import MAX_IMAGE

router = APIRouter(dependencies=[Depends(require_token)], tags=["images"])
Ctx = Annotated[AppContext, Depends(get_ctx)]
MAX_UPLOAD = MAX_IMAGE
FILE_NAME = re.compile(r"[A-Za-z0-9._ ()-]{1,200}")


class ProfileOut(BaseModel):
    key: ProfileKey
    label: str
    folder: str
    source: Literal["image", "rom"]
    image_name: str | None
    image_size: int | None
    boards: list[str]
    revision: str
    packages: int
    custom: list[str]
    built_at: datetime

    @classmethod
    def of(cls, p: Profile) -> ProfileOut:
        return cls(
            key=p.key,
            label=p.key.label,
            folder=p.key.folder,
            source=p.source,
            image_name=p.image_name,
            image_size=p.image_size,
            boards=list(p.boards),
            revision=p.key.revision,
            packages=len(p.packages),
            custom=[c.name for c in p.custom],
            built_at=p.built_at,
        )


async def _body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="A sysupgrade image for these routers is at most 64 MB")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD:
            raise HTTPException(
                status_code=413, detail="A sysupgrade image for these routers is at most 64 MB"
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("/api/images")
async def list_images(ctx: Ctx) -> list[ProfileOut]:
    return [ProfileOut.of(p) for p in ctx.profiles.list()]


@router.post("/api/images")
async def import_image(
    request: Request, ctx: Ctx, x_file_name: Annotated[str, Header()] = "image.bin"
) -> ProfileOut:
    if not FILE_NAME.fullmatch(x_file_name):
        raise ValueError("That file name is not taken (letters, digits, spaces and . _ ( ) -)")
    data = await _body(request)
    profile = await asyncio.to_thread(ctx.profiles.import_image, data, x_file_name, datetime.now())
    ctx.discovery.summaries.clear()
    return ProfileOut.of(profile)


@router.delete("/api/images/{board}/{folder}", status_code=204)
async def delete_image(board: str, folder: str, ctx: Ctx) -> Response:
    found = next((p for p in ctx.profiles.list() if (p.key.board, p.key.folder) == (board, folder)), None)
    if found is None:
        raise HTTPException(status_code=404, detail=f"No imported image {board} {folder}")
    ctx.profiles.delete(found.key)
    ctx.discovery.summaries.clear()
    return Response(status_code=204)


@router.post("/api/routers/{router_id}/images/rom")
async def rom_profile(router_id: str, ctx: Ctx) -> ProfileOut:
    if ctx.routers.get(router_id) is None:
        raise HTTPException(status_code=404, detail=f"No router {router_id}")
    return ProfileOut.of(await ctx.discovery.rom_profile(router_id))
