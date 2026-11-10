"""Mount points, read-only (plan D8): `/proc/mounts` and busybox `df -k`."""

from __future__ import annotations

from openwrtgui.system.mounts import Mount, Usage, parse_df, parse_mounts


def test_mounts_and_df() -> None:
    mounts = parse_mounts(
        "/dev/root /rom squashfs ro,relatime,errors=continue 0 0\n"
        "tmpfs /tmp tmpfs rw,nosuid,nodev,noatime 0 0\n"
        "/dev/sda1 /mnt/usb\\040stick vfat rw 0 0\n"
    )
    assert mounts == [
        Mount(device="/dev/root", target="/rom", fstype="squashfs", options="ro,relatime,errors=continue"),
        Mount(device="tmpfs", target="/tmp", fstype="tmpfs", options="rw,nosuid,nodev,noatime"),
        Mount(device="/dev/sda1", target="/mnt/usb stick", fstype="vfat", options="rw"),
    ]
    usage = parse_df(
        "Filesystem           1K-blocks      Used Available Use% Mounted on\n"
        "/dev/root                 8192      8192         0 100% /rom\n"
        "tmpfs                    27552      1856     25696   7% /tmp\n"
        "overlayfs:/overlay        5056       396      4660   8% /\n"
    )
    assert usage == [
        Usage(
            filesystem="/dev/root", size_kib=8192, used_kib=8192, available_kib=0, use_pct=100, target="/rom"
        ),
        Usage(
            filesystem="tmpfs", size_kib=27552, used_kib=1856, available_kib=25696, use_pct=7, target="/tmp"
        ),
        Usage(
            filesystem="overlayfs:/overlay",
            size_kib=5056,
            used_kib=396,
            available_kib=4660,
            use_pct=8,
            target="/",
        ),
    ]


def test_df_skips_what_it_cannot_read() -> None:
    assert parse_df("Filesystem 1K-blocks Used Available Use% Mounted on\nnonsense\n") == []
