"""The switch MIB counters against AP2's real `swconfig dev switch0 show` (recorded read-only, 2026-11-05)."""

from pathlib import Path

from openwrtgui.ports.mib import totals
from openwrtgui.ports.parse import parse_port_mib
from openwrtgui.transport.fake import load_commands

AP2 = Path(__file__).resolve().parents[1] / "fixtures" / "ap2"
SHOW = load_commands(AP2 / "network.json")["swconfig dev switch0 show"].stdout


def test_mib_on_ap2() -> None:
    mib = parse_port_mib(SHOW)
    assert set(mib) == set(range(8))  # the mt7620 switch prints counters for ports 0-7
    cpu = totals(mib[6])
    assert (cpu.rx_bytes, cpu.tx_packets, cpu.rx_errors) == (2151276205, 58138, 3085)
    assert set(mib[0]) == {"TxGPC", "TxBOC", "TxGOC", "TxEPC", "RxGPC", "RxBOC", "RxGOC", "RxEPC1", "RxEPC2"}
