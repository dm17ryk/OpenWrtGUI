"""tools/luci_spike.py: how it reads LuCI's answers (no router involved)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "luci_spike.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("luci_spike", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["luci_spike"] = module
    spec.loader.exec_module(module)
    return module


spike = _load()


def test_login_form_is_recognised() -> None:
    assert spike.has_login_form('<input class="cbi-input-password" type="password" name="luci_password" />')
    assert not spike.has_login_form("<h2>Wireless Overview</h2>")


def test_ubus_body_is_luci_json_rpc() -> None:
    body = json.loads(spike.ubus_body("abc", "iwinfo", "assoclist", {"device": "phy0-ap0"}))
    assert body == [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "call",
            "params": ["abc", "iwinfo", "assoclist", {"device": "phy0-ap0"}],
        }
    ]


def test_access_denied_is_told_apart_from_other_answers() -> None:
    denied = [{"jsonrpc": "2.0", "id": 1, "error": {"code": -32002, "message": "Access denied"}}]
    not_found = [{"jsonrpc": "2.0", "id": 1, "result": [4]}]
    ok = [{"jsonrpc": "2.0", "id": 1, "result": [0, {"results": []}]}]
    assert spike.ubus_outcome(denied) == "denied"
    assert spike.ubus_outcome(not_found) == "allowed (ubus status 4)"
    assert spike.ubus_outcome(ok) == "allowed"
    assert spike.ubus_outcome({"unexpected": True}) == "unreadable"


def test_refuses_other_hosts() -> None:
    assert spike.main(["--host", "192.168.1.3", "--identity", "k"]) == 2
