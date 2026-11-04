from openwrtgui.probe.commands import BOARD_JSON, FEATURES, LUCI_MENU
from openwrtgui.probe.describe import describe_router, propose_port_labels
from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.fake import ReplayTransport


def _variant(base: ReplayTransport, **overrides: CommandResult) -> ReplayTransport:
    commands = dict(base._commands)
    for result in overrides.values():
        commands[result.command] = result
    return ReplayTransport(commands)


async def test_no_board_json(ap2_transport: ReplayTransport) -> None:
    t = _variant(ap2_transport, board=CommandResult(BOARD_JSON, "", "cat: can't open '/etc/board.json'", 1))
    d = await describe_router(t)
    assert d.board is None
    assert propose_port_labels(None) == {}
    assert "radio0" in d.wireless_options


async def test_no_luci(ap2_transport: ReplayTransport) -> None:
    t = _variant(
        ap2_transport,
        features=CommandResult(FEATURES, "", "Not found", 4),
        menu=CommandResult(LUCI_MENU, "", "", 0),
    )
    d = await describe_router(t)
    assert d.features is None and d.luci is None
    assert d.identity.board_name == "dlink,dwr-921-c3-uboot"
