"""The System screen's reads pass the read-only check (they work during a harness run); its writes do not."""

from __future__ import annotations

import pytest

from openwrtgui.guard.readonly import is_read_only_command
from openwrtgui.system import commands as s

READS = (
    s.BOARD,
    s.INFO,
    s.UCI_SYSTEM,
    s.RC_LIST,
    s.TIMEZONES,
    s.TOP,
    s.DMESG,
    s.RC_LOCAL,
    s.CRONTAB,
    s.TZ_FILE,
    s.LIVE,
    s.CONNTRACK,
    s.BACKUP_SIZE,
    s.logread(100),
    s.logread(500),
    s.logread(2000),
)


@pytest.mark.parametrize("command", READS)
def test_system_reads_pass_the_read_only_check(command: str) -> None:
    assert is_read_only_command(command)


@pytest.mark.parametrize(
    "command",
    [
        s.BACKUP,
        "/etc/init.d/cron restart",
        "reboot",
        "ubus call luci setLocaltime '{}'",
        "ubus call rc init '{}'",
    ],
)
def test_system_writes_do_not(command: str) -> None:
    assert not is_read_only_command(command)


def test_logread_takes_only_the_three_lengths() -> None:
    assert s.logread(500) == "logread -l 500"
    with pytest.raises(ValueError):
        s.logread(7)  # type: ignore[arg-type]
