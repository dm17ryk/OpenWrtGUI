"""system/cron.py: busybox crond's crontab, checked line by line (a bad field silently never runs)."""

from __future__ import annotations

import pytest

from openwrtgui.system.cron import CronLine, check_crontab, parse_crontab


@pytest.mark.parametrize(
    "line",
    [
        "*/5 * * * * logger owg-test",
        "0 0 * * mon-fri echo hi",
        "0,30 8-18/2 1-15 jan,jun * /usr/bin/x --y",
        "59 23 31 12 7 x",
        "0 0 * * sun x",
    ],
)
def test_cron_fields_accepted(line: str) -> None:
    assert check_crontab(line) == line + "\n"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("61 * * * * x", "line 1: minute is 0-59"),
        ("0 24 * * * x", "line 1: hour is 0-23"),
        ("0 0 32 * * x", "line 1: day is 1-31"),
        ("0 0 * 13 * x", "line 1: month is 1-12 or jan-dec"),
        ("0 0 * * 8 x", "line 1: weekday is 0-7 or sun-sat"),
        ("# ok\n* * * *", "line 2: a task is five time fields and a command"),
        ("*/0 * * * * x", "line 1: minute is 0-59"),
        ("5-1 * * * * x", "line 1: minute is 0-59"),
    ],
)
def test_crontab_refusals(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=f"^{message}$"):
        check_crontab(text)


def test_comments_blank_lines_and_variables_pass_through() -> None:
    text = '# owg\n\nMAILTO=""\n*/30 * * * * logger owg-test\n'
    assert check_crontab(text) == text
    entries = parse_crontab(text)
    assert [type(e).__name__ for e in entries] == ["CronComment", "CronComment", "CronComment", "CronLine"]
    task = entries[3]
    assert isinstance(task, CronLine)
    assert (task.minute, task.hour, task.day, task.month, task.weekday, task.command) == (
        "*/30",
        "*",
        "*",
        "*",
        "*",
        "logger owg-test",
    )


def test_empty_crontab_is_no_tasks() -> None:
    assert parse_crontab("") == [] and check_crontab("") == ""
