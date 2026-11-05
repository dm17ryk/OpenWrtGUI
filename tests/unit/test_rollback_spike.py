"""tools/rollback_spike.py (O14): the exact command sequence, and that it always cleans up (no router)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from openwrtgui.transport.base import CommandResult

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "rollback_spike.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rollback_spike", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["rollback_spike"] = module
    spec.loader.exec_module(module)
    return module


spike = _load()
SAVE = "/var/run/rpcd/uci-S{n}"


class Router:
    """Shared by every connection: sessions S1, S2…; `uci get` answers in turn; one command can fail."""

    def __init__(self, gets: list[str], fail: str | None = None) -> None:
        self.gets = gets
        self.fail = fail
        self.sessions = 0
        self.log: list[tuple[int, str]] = []
        self.connections = 0


class Conn:
    def __init__(self, router: Router) -> None:
        router.connections += 1
        self.n = router.connections
        self.router = router
        self.closed = False

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        r = self.router
        r.log.append((self.n, command))
        if r.fail and command.startswith(r.fail):
            return CommandResult(command, "", "Permission denied\n", 1)
        if command.startswith("ubus call session create"):
            r.sessions += 1
            return CommandResult(command, json.dumps({"ubus_rpc_session": f"S{r.sessions}"}), "", 0)
        if command == "uci -q get owgprobe.t.v":
            value = r.gets.pop(0)
            return CommandResult(command, value + "\n" if value else "", "", 0 if value else 1)
        return CommandResult(command, "", "", 0)

    async def close(self) -> None:
        self.closed = True


async def _no_sleep(seconds: float) -> None:
    return None


def _commands(router: Router) -> list[str]:
    return [c for _, c in router.log]


async def test_two_rounds_rollback_then_confirm_from_a_new_connection() -> None:
    router = Router(gets=["1", "", "1"])
    findings = await spike.spike(lambda: _connect(router), _no_sleep)
    cmds = _commands(router)
    assert cmds[:7] == [
        "touch /etc/config/owgprobe",
        "ubus call session create '{\"timeout\":300}'",
        'ubus call session grant \'{"objects":[["owgprobe","read"],["owgprobe","write"]],'
        '"scope":"uci","ubus_rpc_session":"S1"}\'',
        "mkdir -p /var/run/rpcd/uci-S1",
        "uci -P /var/run/rpcd/uci-S1 set owgprobe.t='probe'",
        "uci -P /var/run/rpcd/uci-S1 set owgprobe.t.v='1'",
        'ubus call uci apply \'{"rollback":true,"timeout":10,"ubus_rpc_session":"S1"}\'',
    ]
    confirm = 'ubus call uci confirm \'{"ubus_rpc_session":"S2"}\''
    assert 'ubus call uci apply \'{"rollback":true,"timeout":30,"ubus_rpc_session":"S2"}\'' in cmds
    apply2 = next(n for n, c in router.log if '"timeout":30' in c)
    assert next(n for n, c in router.log if c == confirm) == apply2 + 1  # confirmed on a new connection
    assert cmds[-1] == "rm -f /etc/config/owgprobe"
    assert findings["round1"] == {"applied": True, "rolled_back": True}
    assert findings["round2"] == {"applied": True, "kept_after_reconnect": True}


async def test_cleanup_runs_when_apply_is_refused() -> None:
    router = Router(gets=[], fail="ubus call uci apply")
    findings = await spike.spike(lambda: _connect(router), _no_sleep)
    cmds = _commands(router)
    assert 'ubus call session destroy \'{"ubus_rpc_session":"S1"}\'' in cmds
    assert cmds[-1] == "rm -f /etc/config/owgprobe"
    assert findings["round1"]["applied"] is False
    assert "Permission denied" in findings["round1"]["error"]


def test_refuses_other_hosts(capsys: pytest.CaptureFixture[str]) -> None:
    assert spike.main(["--host", "192.168.1.1", "--identity", "k"]) == 2
    assert "only AP2" in capsys.readouterr().err


async def _connect(router: Router) -> Conn:
    return Conn(router)
