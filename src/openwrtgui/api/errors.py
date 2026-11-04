"""Map domain errors to HTTP answers the UI can show as they are."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from openwrtgui.api.models import GuardOut
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.transport.base import AuthFailed, HostKeyChanged, HostKeyUnknown, TransportError, Unreachable
from openwrtgui.update.service import UpdateFailed, UpdateInProgress

ROUTER_REFUSED = "The router refused the login."


def install(app: FastAPI) -> None:
    @app.exception_handler(GuardLocked)
    async def guard_locked(request: Request, exc: GuardLocked) -> JSONResponse:
        detail = exc.state.reasons[0].text if exc.state.reasons else "Bench Guard: read-only"
        return JSONResponse(
            status_code=423, content={"detail": detail, "guard": jsonable_encoder(GuardOut.of(exc.state))}
        )

    @app.exception_handler(HostKeyChanged)
    async def host_key_changed(request: Request, exc: HostKeyChanged) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "expected": exc.expected, "actual": jsonable_encoder(exc.actual)},
        )

    @app.exception_handler(HostKeyUnknown)
    async def host_key_unknown(request: Request, exc: HostKeyUnknown) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "expected": None, "actual": jsonable_encoder(exc.actual)},
        )

    @app.exception_handler(AuthFailed)
    async def auth_failed(request: Request, exc: AuthFailed) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": ROUTER_REFUSED})

    @app.exception_handler(Unreachable)
    async def unreachable(request: Request, exc: Unreachable) -> JSONResponse:
        return JSONResponse(status_code=504, content={"detail": str(exc)})

    @app.exception_handler(TransportError)
    async def transport_error(request: Request, exc: TransportError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(UpdateFailed)
    async def update_failed(request: Request, exc: UpdateFailed) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(UpdateInProgress)
    async def update_in_progress(request: Request, exc: UpdateInProgress) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
