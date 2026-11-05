from __future__ import annotations

from typing import Any

import pytest
from apiconst import BASE, TOKEN, WS
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from openwrtgui.app import create_app
from openwrtgui.context import AppContext


def _client(ctx: AppContext) -> TestClient:
    return TestClient(create_app(ctx), base_url=BASE)


def test_rf_ws_streams_samples_and_records(ctx: AppContext) -> None:
    # the simulator records under its own data folder, never the user's Documents
    with _client(ctx).websocket_connect(f"{WS}/ws/rf/ap1?radio=radio0&t={TOKEN}") as ws:
        first: dict[str, Any] = ws.receive_json()
        assert first["type"] == "rf" and first["sample"]["radio_sample"]["channel"] == 1
        assert first["sample"]["stations"][0]["mac"] == "f4:12:fa:f3:57:68"
        ws.send_json({"type": "record", "on": True})
        msg = ws.receive_json()
        while msg["type"] != "recording":
            msg = ws.receive_json()
        assert msg["path"].startswith(str(ctx.data.root / "recordings"))
        ws.send_json({"type": "rates", "mac": "f4:12:fa:f3:57:68"})
        msg = ws.receive_json()
        while msg["type"] != "rates":
            msg = ws.receive_json()
        assert msg == {
            "type": "rates",
            "mac": "f4:12:fa:f3:57:68",
            "error": "Rates are read after the AP2 recording (O6)",
        }


def test_rf_ws_parked_radio_is_idle(ctx: AppContext) -> None:
    with _client(ctx).websocket_connect(f"{WS}/ws/rf/ap2?radio=radio0&t={TOKEN}") as ws:
        assert ws.receive_json() == {"type": "rf-idle", "reason": "radio0 is parked"}


def test_rf_ws_needs_token_and_known_router(ctx: AppContext) -> None:
    tc = _client(ctx)
    with pytest.raises(WebSocketDisconnect) as refused, tc.websocket_connect(f"{WS}/ws/rf/ap1") as ws:
        ws.receive_json()
    assert refused.value.code == 4401
    with (
        pytest.raises(WebSocketDisconnect) as missing,
        tc.websocket_connect(f"{WS}/ws/rf/nope?t={TOKEN}") as ws,
    ):
        ws.receive_json()
    assert missing.value.code == 4404
