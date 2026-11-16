"""Imported images (Settings › Images): import a sysupgrade file sent as the raw request body, list and delete
profiles, and build a profile from a router's /rom."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request, Response
from pydantic import BaseModel

from openwrtgui.api.deps import get_ctx, require_token
from openwrtgui.context import AppContext
from openwrtgui.images.library import LibraryEntry, LibraryRead
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
    origin: str | None

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
            origin=p.origin,
        )


class LibraryEntryOut(BaseModel):
    sha256: str
    board: str
    boards: list[str]
    revision: str
    target: str
    title: str
    image_name: str
    size: int
    url: str
    release_tag: str
    release_name: str
    release_url: str
    published_at: datetime | None
    prerelease: bool
    imported: bool

    @classmethod
    def of(cls, e: LibraryEntry, imported: bool) -> LibraryEntryOut:
        return cls(
            **e.model_dump(exclude={"boards"}), board=e.board, boards=list(e.boards), imported=imported
        )


class LibraryOut(BaseModel):
    entries: list[LibraryEntryOut]
    read_at: datetime | None
    skipped: int
    error: str | None

    @classmethod
    def of(
        cls, read: LibraryRead, ctx: AppContext, board: str | None = None, revision: str | None = None
    ) -> LibraryOut:
        have = {p.key.sha256 for p in ctx.profiles.list()}
        return cls(
            entries=[
                LibraryEntryOut.of(e, e.sha256 in have)
                for e in read.entries
                if (board is None or e.board == board) and (revision is None or e.revision == revision)
            ],
            read_at=read.read_at,
            skipped=read.skipped,
            error=read.error,
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


@router.get("/api/images/library")
async def library(ctx: Ctx, board: str | None = None, revision: str | None = None) -> LibraryOut:
    return LibraryOut.of(await ctx.library.read(), ctx, board, revision)


@router.post("/api/images/library/refresh")
async def library_refresh(ctx: Ctx) -> LibraryOut:
    return LibraryOut.of(await ctx.library.read(force=True), ctx)


@router.post("/api/images/library/{sha256}")
async def library_download(sha256: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")], ctx: Ctx) -> ProfileOut:
    try:
        profile = await ctx.library.download(sha256)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No image {sha256[:12]} in the image library") from None
    ctx.discovery.summaries.clear()
    return ProfileOut.of(profile)
