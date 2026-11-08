"""discovery/overlay.py: busybox `ls -ldn` listings of /overlay/upper and /rom."""

from __future__ import annotations

from openwrtgui.discovery.overlay import parse_ls_ldn


def test_parse_ls_ldn() -> None:
    entries, unreadable = parse_ls_ldn(
        "-rw-r--r--    1 0        0               12 Nov  7 15:24 /overlay/upper/root/notes.txt\n"
        "lrwxrwxrwx    1 0        0                7 Nov  7 15:24 /overlay/upper/bin/x -> busybox\n"
        "c---------    1 0        0          0,   0 Nov  7 15:24 /overlay/upper/etc/uci-defaults/20_x\n"
        "crw-rw-rw-    1 0        0          1,   3 Jan  1  1970 /overlay/upper/dev/null\n",
        "/overlay/upper",
    )
    assert [(e.path, e.kind) for e in entries] == [
        ("/root/notes.txt", "file"),
        ("/bin/x", "link"),
        ("/etc/uci-defaults/20_x", "whiteout"),
        ("/dev/null", "other"),
    ]
    assert entries[0].size == 12
    assert entries[0].mode == "-rw-r--r--"
    assert entries[1].target == "busybox"
    assert unreadable == 0


def test_overlay_names_with_shell_characters() -> None:
    entries, unreadable = parse_ls_ldn(
        "-rw-r--r--    1 0        0                1 Nov  7 15:24 /overlay/upper/root/a b\n"
        "-rw-r--r--    1 0        0                1 Nov  7 15:24 /overlay/upper/root/it's\n"
        "-rw-r--r--    1 0        0                1 Nov  7 15:24 /overlay/upper/root/$(reboot)\n"
        "-rw-r--r--    1 0        0                1 Nov  7 15:24 /overlay/upper/root/new\n"
        "line\n"
        "-rw-r--r--    1 0        0                1 Nov  7 15:24 /elsewhere/x\n",
        "/overlay/upper",
    )
    assert [e.path for e in entries] == ["/root/a b", "/root/it's", "/root/$(reboot)", "/root/new"]
    assert unreadable == 2
