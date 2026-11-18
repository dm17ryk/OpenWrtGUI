import json
import shlex
from pathlib import Path

import pytest

from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.fake import ReplayTransport, SimState, load_commands

LINE = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample openwrtgui@TEST"


def _install(line: str) -> str:
    q, ak = shlex.quote(line), "/etc/dropbear/authorized_keys"
    return (
        f"mkdir -p /etc/dropbear && touch {ak} && chmod 600 {ak} && "
        f'(grep -qxF {q} {ak} || {{ [ -z "$(tail -c1 {ak})" ] || echo >> {ak}; echo {q} >> {ak}; }})'
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


async def test_remove_old_key_command_is_recognised_exactly() -> None:
    from openwrtgui.onboard.rotate import remove_old_key_command

    new, old = "ssh-ed25519 AAAAnew openwrtgui@pc", LINE
    state = SimState(authorized_keys=["# kept", old, new])
    t = ReplayTransport({}, state=state)
    changed = remove_old_key_command(new, old).replace("chmod 600", "chmod 644")
    refused = await t.run(changed)
    assert (refused.exit_status, refused.stderr) == (1, "sim: unexpected key remove command")
    assert state.authorized_keys == ["# kept", old, new]
    assert (await t.run(remove_old_key_command(new, old))).ok
    assert state.authorized_keys == ["# kept", new]


async def test_passwd_sets_root_password() -> None:
    state = SimState()
    t = ReplayTransport({}, state=state)
    assert (await t.run_stdin("passwd root", "pw1\npw1\n")).ok
    assert state.root_password == "pw1"


async def test_root_password_state_follows_sim_state() -> None:
    cmd = 'awk -F: \'$1=="root"{print ($2=="" ? "none" : "set")}\' /etc/shadow'
    state = SimState(root_password=None)
    t = ReplayTransport({}, state=state)
    assert (await t.run(cmd)).stdout == "none\n"
    state.root_password = "x"
    assert (await t.run(cmd)).stdout == "set\n"


async def test_simulator_has_no_shell() -> None:
    with pytest.raises(NotImplementedError):
        await ReplayTransport({}).open_shell(80, 24)
