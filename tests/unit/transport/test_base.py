import pytest

from openwrtgui.transport.base import CommandResult, TransportError, ubus_call, ubus_command
from openwrtgui.transport.fake import ReplayTransport


def _rec(cmd: str, stdout: str = "", exit_status: int = 0, stderr: str = "") -> dict[str, CommandResult]:
    return {cmd: CommandResult(cmd, stdout, stderr, exit_status)}


def test_ubus_command_format() -> None:
    assert ubus_command("system", "board") == "ubus call system board"
    assert ubus_command("network.wireless", "get_validate", {"device": "radio0"}) == (
        "ubus call network.wireless get_validate '{\"device\":\"radio0\"}'"
    )


def test_ubus_command_sorts_keys() -> None:
    assert ubus_command("uci", "get", {"section": "lan", "config": "dhcp"}) == (
        "ubus call uci get '{\"config\":\"dhcp\",\"section\":\"lan\"}'"
    )


def test_result_ok() -> None:
    assert CommandResult("true", "", "", 0).ok
    assert not CommandResult("false", "", "", 1).ok


async def test_ubus_call_parses_json() -> None:
    t = ReplayTransport(_rec("ubus call system board", '{"hostname": "AP2"}'))
    assert await ubus_call(t, "system", "board") == {"hostname": "AP2"}


async def test_ubus_call_not_found_is_none() -> None:
    t = ReplayTransport(_rec("ubus call luci getFeatures", "", 4, "Not found"))
    assert await ubus_call(t, "luci", "getFeatures") is None


async def test_ubus_call_method_not_found_is_none() -> None:
    t = ReplayTransport(_rec("ubus call luci nope", "", 3, "Method not found"))
    assert await ubus_call(t, "luci", "nope") is None


async def test_ubus_call_empty_output_is_empty_dict() -> None:
    t = ReplayTransport(_rec("ubus call rc list", ""))
    assert await ubus_call(t, "rc", "list") == {}


async def test_ubus_call_other_error_raises() -> None:
    t = ReplayTransport(_rec("ubus call system info", "", 7, "Request timed out"))
    with pytest.raises(TransportError, match="timed out"):
        await ubus_call(t, "system", "info")
