import json
import shlex
from pathlib import Path

import pytest

from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.fake import ReplayTransport, SimState, load_commands

LINE = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample openwrtgui@TEST"


def _install(line: str) -> str:
    q = shlex.quote(line)
    return (
        "mkdir -p /etc/dropbear && touch /etc/dropbear/authorized_keys && "
        "chmod 600 /etc/dropbear/authorized_keys && "
        f"(grep -qxF {q} /etc/dropbear/authorized_keys || echo {q} >> /etc/dropbear/authorized_keys)"
    )


def test_load_commands(tmp_path: Path) -> None:
    p = tmp_path / "commands.json"
    data = {"uname": {"stdout": "Linux\n", "exit": 0}, "x": {"stdout": "", "exit": 2, "stderr": "bad"}}
    p.write_text(json.dumps(data), encoding="utf-8")
    cmds = load_commands(p)
    assert cmds["uname"] == CommandResult("uname", "Linux\n", "", 0)
    assert cmds["x"].stderr == "bad" and cmds["x"].exit_status == 2


async def test_returns_recording_and_logs_calls() -> None:
    t = ReplayTransport({"uname": CommandResult("uname", "Linux\n", "", 0)})
    assert (await t.run("uname")).stdout == "Linux\n"
    assert t.calls == ["uname"]


async def test_unknown_command_is_127() -> None:
    r = await ReplayTransport({}).run("reboot")
    assert r.exit_status == 127 and "no recording" in r.stderr


async def test_install_key_appends_once() -> None:
    state = SimState()
    t = ReplayTransport({}, state=state)
    assert (await t.run(_install(LINE))).ok
    assert (await t.run(_install(LINE))).ok
    assert state.authorized_keys == [LINE]


async def test_passwd_sets_root_password() -> None:
    state = SimState()
    t = ReplayTransport({}, state=state)
    assert (await t.run_stdin("passwd root", "pw1\npw1\n")).ok
    assert state.root_password == "pw1"


async def test_root_password_state_follows_sim_state() -> None:
    cmd = "awk -F: '$1==\"root\"{print ($2==\"\" ? \"none\" : \"set\")}' /etc/shadow"
    state = SimState(root_password=None)
    t = ReplayTransport({}, state=state)
    assert (await t.run(cmd)).stdout == "none\n"
    state.root_password = "x"
    assert (await t.run(cmd)).stdout == "set\n"


async def test_simulator_has_no_shell() -> None:
    with pytest.raises(NotImplementedError):
        await ReplayTransport({}).open_shell(80, 24)
