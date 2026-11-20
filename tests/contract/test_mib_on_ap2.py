"""The switch MIB counters against AP2's real `swconfig dev switch0 show` (recorded read-only, 2026-11-05)."""

import json
from pathlib import Path

from openwrtgui.ports.mib import WIDTH, totals
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


def test_the_packet_counters_are_16_bit_on_ap2() -> None:
    """The 1.2b window (2026-11-20): two reads around a 60 s iperf3 run from AP2 to this PC. The CPU port's
    octet counter rose by far more bytes than 65,536 full-size frames carry, while its packet counter stayed
    below 65,536 in both reads: the packet counters are 16 bits wide, as WIDTH says."""
    window = json.loads((AP2 / "mib.json").read_text(encoding="utf-8"))
    before, after = parse_port_mib(window["before"])[6], parse_port_mib(window["after"])[6]
    rose = (after["RxGOC"] - before["RxGOC"]) % 2**32
    assert rose > 2**16 * 1514
    assert before["RxGPC"] < 2**16 and after["RxGPC"] < 2**16
    assert WIDTH["RxGPC"] == WIDTH["TxGPC"] == 16 and WIDTH["RxGOC"] == 32
