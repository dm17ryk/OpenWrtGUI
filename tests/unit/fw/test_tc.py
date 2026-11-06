"""`tc qdisc show` text: devices, kinds, handles, root or parent, netem parameters; u32 address matches."""

from __future__ import annotations

from openwrtgui.fw.tc import parse_netem, parse_qdiscs, u32_match

QDISCS = """qdisc noqueue 0: dev lo root refcnt 2
qdisc fq_codel 0: dev eth0 root refcnt 2 limit 10240p flows 1024 quantum 1514 target 5ms interval 100ms
qdisc prio 1ee7: dev eth0.1 root refcnt 2 bands 4 priomap 1 2 2 2 1 2 0 0 1 1 1 1 1 1 1 1
qdisc netem 1ee8: dev eth0.1 parent 1ee7:4 limit 1000 delay 100ms  20ms loss 1%
qdisc ingress ffff: dev phy0-ap0 parent ffff:fff1 ----------------
"""


def test_qdisc_owner_fields() -> None:
    q = parse_qdiscs(QDISCS)
    assert [(x.dev, x.kind, x.handle, x.root, x.parent) for x in q] == [
        ("lo", "noqueue", "0:", True, None),
        ("eth0", "fq_codel", "0:", True, None),
        ("eth0.1", "prio", "1ee7:", True, None),
        ("eth0.1", "netem", "1ee8:", False, "1ee7:4"),
        ("phy0-ap0", "ingress", "ffff:", False, "ffff:fff1"),
    ]
    assert parse_netem(q[3].params) == {"delay": "100ms", "jitter": "20ms", "loss": "1%"}


def test_netem_every_term() -> None:
    params = "limit 1000 delay 50ms  10ms distribution normal loss 2% duplicate 1% reorder 25% 50%"
    assert parse_netem(params) == {
        "delay": "50ms",
        "jitter": "10ms",
        "distribution": "normal",
        "loss": "2%",
        "duplicate": "1%",
        "reorder": "25%",
    }


def test_u32_match() -> None:
    assert u32_match("192.168.1.30", "dst") == "c0a8011e/ffffffff at 16"
    assert u32_match("192.168.1.30", "src") == "c0a8011e/ffffffff at 12"
