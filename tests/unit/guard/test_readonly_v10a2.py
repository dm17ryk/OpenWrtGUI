"""v1.0a2 D12: Plugins', Mount points' and Legacy iptables' reads run during a harness run; their writes
do not."""

from __future__ import annotations

import pytest

from openwrtgui.guard.readonly import is_read_only_command
from openwrtgui.system import commands as s


@pytest.mark.parametrize(
    "cmd",
    [
        s.UCI_PLUGINS,
        s.LIST_PLUGINS,
        f"cat {s.PLUGIN_DIR}/c0ffee2cf63e160c091224d95d69cdff.js",
        s.UCI_FSTAB,
        s.BLOCK_DEVICES,
        s.BLOCK_DETECT,
        "iptables --line-numbers -w -nvxL -t filter",
        "ip6tables --line-numbers -w -nvxL -t raw",
        "iptables -L -n -v -x -t nat",
    ],
)
def test_the_new_reads_are_reads(cmd: str) -> None:
    assert is_read_only_command(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "iptables -Z",
        "ip6tables -Z",
        "iptables -F",
        "iptables -t filter -A INPUT -j DROP",
        "iptables -nvxL -t filter -Z",
        "iptables --line-numbers -w -nvxL -t security",  # not a table LuCI shows
        "iptables -t filter",  # nothing listed
        s.BLOCK_MOUNT,
        "block mount",
        "block umount",
        "umount /mnt/usb",
        "ubus call luci setBlockDetect",
    ],
)
def test_their_writes_are_not(cmd: str) -> None:
    assert not is_read_only_command(cmd)
