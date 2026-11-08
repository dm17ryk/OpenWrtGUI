"""lte/at.py: finding the modem's AT port, and the identity reads on it."""

from __future__ import annotations

from openwrtgui.lte import commands as c
from openwrtgui.lte.at import find_at_port, read_modem_info
from openwrtgui.transport.base import CommandResult

OK = "AT\r\r\nOK\r\n"


class Modem:
    """Answers the exact commands it knows; anything else exits 0 with no output (a silent port)."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        self.calls.append(command)
        return CommandResult(command, self.answers.get(command, ""), "", 0)


async def test_the_first_port_that_answers_ok() -> None:
    t = Modem({c.TTY_LIST: "/dev/ttyUSB0\n/dev/ttyUSB1\n/dev/ttyUSB2\n", c.at("/dev/ttyUSB1", "AT"): OK})
    assert await find_at_port(t) == "/dev/ttyUSB1"  # type: ignore[arg-type]
    assert t.calls == [c.TTY_LIST, c.at("/dev/ttyUSB0", "AT"), c.at("/dev/ttyUSB1", "AT")]


async def test_no_tty_means_no_at_port_and_no_microcom() -> None:
    t = Modem({c.TTY_LIST: ""})
    assert await find_at_port(t) is None  # type: ignore[arg-type]
    assert t.calls == [c.TTY_LIST]


async def test_silent_ports_and_odd_names() -> None:
    t = Modem({c.TTY_LIST: "/dev/ttyUSB0\nls: /dev/ttyUSB*: No such file or directory\n/dev/ttyACM0\n"})
    assert await find_at_port(t) is None  # type: ignore[arg-type]
    assert c.at("/dev/ttyUSB0", "AT") in t.calls and not any("ttyACM0" in x for x in t.calls)


async def test_modem_info_on_the_port() -> None:
    port = "/dev/ttyUSB2"
    t = Modem(
        {
            c.at(port, "AT+CGMI", "AT+CGMM", "AT+CGMR"): (
                "\r\nBroadMobi\r\n\r\nOK\r\n\r\nBM806C\r\n\r\nOK\r\n\r\nM1.2.0_E1.0.3_A1.1.8\r\n\r\nOK\r\n"
            ),
            c.at(port, "AT+COPS?"): '\r\n+COPS: 0,0,"Partner",7\r\n\r\nOK\r\n',
            c.at(port, "AT+BMMODODR?"): "\r\n+BMMODODR: 17\r\n\r\nOK\r\n",
        }
    )
    info = await read_modem_info(t, port)  # type: ignore[arg-type]
    assert (info.manufacturer, info.model, info.firmware) == ("BroadMobi", "BM806C", "M1.2.0_E1.0.3_A1.1.8")
    assert (info.operator, info.mode_order, info.at_port) == ("Partner", 17, port)


async def test_modem_info_without_a_port() -> None:
    t = Modem({})
    info = await read_modem_info(t, None)  # type: ignore[arg-type]
    assert (info.manufacturer, info.model, info.firmware, info.operator, info.mode_order, info.at_port) == (
        None,
        None,
        None,
        None,
        None,
        None,
    )
    assert t.calls == []
