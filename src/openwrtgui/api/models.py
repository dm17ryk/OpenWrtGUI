"""Response shapes the UI reads (also what tools/dump_openapi.py publishes for the frontend)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from openwrtgui.guard.bench_guard import GuardState
from openwrtgui.probe.describe import DescriptionSummary
from openwrtgui.probe.status import RouterStatus
from openwrtgui.store.routers import RouterRecord
from openwrtgui.transport.pool import RouterHealth
from openwrtgui.update.github import Release
from openwrtgui.update.service import UpdateStatus


class ReasonOut(BaseModel):
    kind: str
    detail: str
    since: datetime | None
    router: str | None
    pid: int | None
    text: str


class GuardOut(BaseModel):
    live: bool
    reasons: list[ReasonOut]
    checked_at: datetime

    @classmethod
    def of(cls, state: GuardState) -> GuardOut:
        return cls(
            live=state.live,
            checked_at=state.checked_at,
            reasons=[
                ReasonOut(
                    kind=r.kind, detail=r.detail, since=r.since, router=r.router, pid=r.pid, text=r.text
                )
                for r in state.reasons
            ],
        )


class RouterItem(BaseModel):
    record: RouterRecord
    health: RouterHealth
    status: RouterStatus | None
    summary: DescriptionSummary | None


class RouterDetail(RouterItem):
    pass


class ReleaseOut(BaseModel):
    version: str
    name: str
    notes: str
    prerelease: bool
    published_at: datetime | None
    size: int

    @classmethod
    def of(cls, r: Release) -> ReleaseOut:
        return cls(
            version=str(r.version),
            name=r.name,
            notes=r.notes,
            prerelease=r.prerelease,
            published_at=r.published_at,
            size=r.installer_size,
        )


class UpdateOut(BaseModel):
    current: str
    channel: str
    latest: ReleaseOut | None
    available: bool
    last_check: datetime | None
    error: str | None
    can_install: bool
    has_previous: bool

    @classmethod
    def of(cls, s: UpdateStatus, has_previous: bool) -> UpdateOut:
        return cls(
            current=s.current,
            channel=s.channel,
            latest=ReleaseOut.of(s.latest) if s.latest else None,
            available=s.available,
            last_check=s.last_check,
            error=s.error,
            can_install=s.can_install,
            has_previous=has_previous,
        )


class AppKeyOut(BaseModel):
    public_line: str
    fingerprint: str


class Preview(BaseModel):
    commands: list[str]


class Ok(BaseModel):
    ok: bool = True


class Health(BaseModel):
    status: str
    version: str
    mode: str


def wire(msg: dict[str, Any], has_previous: bool = False) -> Any:
    """Turn a hub message into JSON-ready data with the same shapes as the REST responses."""
    if msg.get("type") == "guard":
        return {"type": "guard", "state": jsonable_encoder(GuardOut.of(msg["state"]))}
    if msg.get("type") == "update":
        return {"type": "update", "status": jsonable_encoder(UpdateOut.of(msg["status"], has_previous))}
    return jsonable_encoder(msg)
