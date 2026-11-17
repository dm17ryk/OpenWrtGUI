"""An error nobody planned for (v1.0c Task 8, D8): a plain 500 the screen can show; details go to the log."""

from __future__ import annotations

import logging

import httpx
import pytest
from apiconst import BASE

from openwrtgui.app import create_app
from openwrtgui.context import AppContext

UNEXPECTED = "Unexpected error in OpenWrtGUI (RuntimeError). The details are in the app log."


async def test_an_unexpected_error_answers_500_with_a_plain_message(
    ctx: AppContext, caplog: pytest.LogCaptureFixture
) -> None:
    app = create_app(ctx)

    async def boom() -> None:
        raise RuntimeError("secret detail")

    app.add_api_route("/api/test-boom", boom, methods=["GET"])
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    with caplog.at_level(logging.ERROR):
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as c:
            r = await c.get("/api/test-boom")
    assert r.status_code == 500
    assert r.json() == {"detail": UNEXPECTED}
    assert "secret detail" not in r.text
    assert "secret detail" in caplog.text  # the traceback is in the app log


def test_uvicorn_does_not_log_the_traceback_a_second_time(
    ctx: AppContext, caplog: pytest.LogCaptureFixture
) -> None:
    """#77 minor 13: Starlette re-raises after the handler, and uvicorn logs the traceback again (R5)."""
    create_app(ctx)
    uvicorn_error = logging.getLogger("uvicorn.error")
    try:
        raise RuntimeError("secret detail")
    except RuntimeError:
        with caplog.at_level(logging.ERROR):
            uvicorn_error.error("Exception in ASGI application\n", exc_info=True)
            uvicorn_error.error("Something else went wrong")
    assert "Exception in ASGI application" not in caplog.text
    assert "Something else went wrong" in caplog.text


async def test_a_known_error_keeps_its_own_answer(ctx: AppContext) -> None:
    app = create_app(ctx)

    async def refused() -> None:
        raise ValueError("That is not a radio")

    app.add_api_route("/api/test-refused", refused, methods=["GET"])
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as c:
        r = await c.get("/api/test-refused")
    assert (r.status_code, r.json()) == (422, {"detail": "That is not a radio"})
