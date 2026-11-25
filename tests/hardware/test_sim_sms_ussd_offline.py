"""Offline: the 1.3b AP2 window's four parts, run against the simulator through the same functions the window
runs (sim_sms_ussd_window), with the fixture written into tmp_path, never into tests/fixtures. It proves the
window records shapes only and that a part runs only when its option is given (E13)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import sim_sms_ussd_window as w
from test_ap2_wifi import _recorder

from openwrtgui.context import AppContext, build_context
from openwrtgui.paths import DataDir
from openwrtgui.simmodem import SimModem
from openwrtgui.store import keys as keys_module
from openwrtgui.transport.base import CommandResult, TransportError
from openwrtgui.transport.fake import ReplayTransport

SIM_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "sim"
PRIVATE = ("+1555010", "Test message", "Balance", "*100#", "Window text", "+15550199")


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppContext]:
    monkeypatch.setattr(keys_module, "restrict_to_user", lambda path: None)
    monkeypatch.delenv("OPENWRTGUI_SIM_GUARD", raising=False)
    yield build_context(
        DataDir.at(tmp_path / "data"), token="t" * 32, port=8765, simulator=SIM_DIR, web_dir=None
    )


def _window(ctx: AppContext) -> w.Window:
    return w.Window(modem=ctx.lte_modem, lte=ctx.lte, guard=ctx.guard, audit=ctx.audit, router_id="ap1")


async def _sim_modem(ctx: AppContext) -> SimModem:
    t = await ctx.pool.get(ctx.routers.get("ap1"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport) and t.state is not None and t.state.modem is not None
    return t.state.modem


def test_the_options_parse() -> None:
    assert w.parse_read("sim:2") == ("sim", 2)
    assert w.parse_delete("sim:0,1") == ("sim", (0, 1))
    assert w.parse_read(None) is None
    for bad in ("sim", "usb:1", "sim:x", "sim:"):
        with pytest.raises(ValueError):
            w.parse_read(bad)
    with pytest.raises(ValueError):
        w.parse_delete("me:")


async def test_with_no_option_only_the_reads_run(ctx: AppContext, tmp_path: Path) -> None:
    out = tmp_path / "modem_sms.json"
    recorded = await w.run_window(_window(ctx), _recorder(), w.Options(), out)
    assert recorded == json.loads(out.read_text(encoding="utf-8"))
    assert set(recorded) == {"sim", "lists", "cpms", "message_keys", "message", "bmmododr_test"}
    assert recorded["lists"]["sim"]["count"] == 3
    assert recorded["message_keys"] == sorted(recorded["message_keys"])
    assert recorded["message"]["text"] == "<str 14 chars>"
    assert (await _sim_modem(ctx)).sent == []
    assert len((await _sim_modem(ctx)).messages["sim"]) == 3


async def test_each_part_runs_only_when_named_and_records_shapes(ctx: AppContext, tmp_path: Path) -> None:
    out = tmp_path / "modem_sms.json"
    opts = w.Options(
        read=("sim", 2), delete=("sim", (0, 1)), to="+15550199", text="Window text", ussd="*100#"
    )
    recorded = await w.run_window(_window(ctx), _recorder(), opts, out)
    assert recorded["deleted"] == 2
    assert recorded["sent"] == {"ok": True}
    assert recorded["ussd"] == {"m": 0, "dcs": 15, "status": "reply", "text_chars": 13, "closed": False}
    assert recorded["bmmododr_test"] == ["+BMMODODR: (2,3,17)"]
    text = out.read_text(encoding="utf-8")
    for private in PRIVATE:
        assert private not in text
    modem = await _sim_modem(ctx)
    assert sorted(modem.messages["sim"]) == [2]
    assert modem.sent == [("+15550199", "Window text")]


@pytest.mark.parametrize(
    "opts",
    [
        w.Options(to="+15550199", delete=("sim", (0,)), ussd="*100#"),
        w.Options(text="Window text", delete=("sim", (0,)), ussd="*100#"),
    ],
)
async def test_a_half_given_send_is_a_usage_error_before_anything_runs(
    ctx: AppContext, tmp_path: Path, opts: w.Options
) -> None:
    """Final review I5: --sms-to without --sms-text (or the reverse) is not skipped silently. The window fails
    before any read or write, and the fixture file is not touched."""
    out = tmp_path / "modem_sms.json"
    with pytest.raises(pytest.UsageError, match=r"^--sms-to and --sms-text go together"):
        await w.run_window(_window(ctx), _recorder(), opts, out)
    modem = await _sim_modem(ctx)
    assert modem.sent == [] and sorted(modem.messages["sim"]) == [0, 1, 2]
    assert ctx.audit.query() == [] and not out.exists()


async def test_the_ussd_part_runs_alone(ctx: AppContext, tmp_path: Path) -> None:
    out = tmp_path / "modem_sms.json"
    recorded = await w.run_window(_window(ctx), _recorder(), w.Options(ussd="*100#"), out)
    assert set(recorded) >= {"ussd"} and "sent" not in recorded and "deleted" not in recorded


async def test_a_part_that_fails_midway_keeps_what_it_read(ctx: AppContext, tmp_path: Path) -> None:
    """Final review I5: each key is recorded as it is read, so a failure after the SIM state, the lists and
    AT+CPMS? still leaves them in the written file."""
    modem = await _sim_modem(ctx)
    real = modem.answer

    def lost(command: str) -> CommandResult | None:
        if "AT+BMMODODR=?" in command:
            raise TransportError("connection lost")
        return real(command)

    modem.answer = lost  # type: ignore[method-assign]
    out = tmp_path / "modem_sms.json"
    with pytest.raises(TransportError):
        await w.run_window(_window(ctx), _recorder(), w.Options(), out)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert set(written) == {"sim", "lists", "cpms"}
    assert written["lists"]["sim"]["count"] == 3 and written["sim"]["pin"] == "off"


@pytest.mark.parametrize("stdout", ["not json\n", "[1]\n"])
async def test_a_message_that_does_not_parse_is_recorded_as_an_error_and_the_window_goes_on(
    ctx: AppContext, tmp_path: Path, stdout: str
) -> None:
    """The likeliest failure on an unproven shape: recorded as its own shape, never as the text, and the parts
    after it still run."""
    modem = await _sim_modem(ctx)
    real = modem.answer

    def odd_message(command: str) -> CommandResult | None:
        if "--get-message" in command:
            return CommandResult(command, stdout, "", 0)
        return real(command)

    modem.answer = odd_message  # type: ignore[method-assign]
    out = tmp_path / "modem_sms.json"
    recorded = await w.run_window(_window(ctx), _recorder(), w.Options(ussd="*100#"), out)
    assert recorded == json.loads(out.read_text(encoding="utf-8"))
    assert recorded["message"] == {"error": "the modem's answer did not parse"}
    assert recorded["message_keys"] == {"error": "the modem's answer did not parse"}
    assert recorded["bmmododr_test"] == ["+BMMODODR: (2,3,17)"]
    assert recorded["ussd"]["status"] == "reply"


async def test_a_message_the_modem_does_not_give_is_recorded_as_an_error(
    ctx: AppContext, tmp_path: Path
) -> None:
    modem = await _sim_modem(ctx)
    real = modem.answer

    def refused(command: str) -> CommandResult | None:
        if "--get-message" in command:
            return CommandResult(command, "", "Request failed\n", 1)
        return real(command)

    modem.answer = refused  # type: ignore[method-assign]
    recorded = await w.run_window(_window(ctx), _recorder(), w.Options(), tmp_path / "modem_sms.json")
    assert recorded["message"] == {"error": "the modem did not give the message"}
    assert "message_keys" not in recorded and recorded["bmmododr_test"] == ["+BMMODODR: (2,3,17)"]
