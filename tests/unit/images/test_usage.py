"""images/usage.py: the usage text of a shell script, read without running it."""

from __future__ import annotations

from openwrtgui.images.usage import MAX_USAGE, usage_text

PORTCTL = (
    b"#!/bin/sh\n\nset -eu\n\nusage() {\n\tcat <<'EOF'\n"
    b"Usage: dwr921-portctl {port-status|port-enable|port-disable} {lan1|lan2|lan3|lan4|wan}\nEOF\n}\n"
)


def test_usage_heredoc() -> None:
    assert usage_text(PORTCTL) == (
        "Usage: dwr921-portctl {port-status|port-enable|port-disable} {lan1|lan2|lan3|lan4|wan}"
    )


def test_heredoc_with_another_delimiter_and_dash() -> None:
    script = b"#!/bin/sh\nusage()\n{\n\tcat <<-USAGE\n\tUsage: x [-v]\n\t  -v  verbose\n\tUSAGE\n}\n"
    assert usage_text(script) == "Usage: x [-v]\n  -v  verbose"


def test_echo_usage_lines() -> None:
    script = b'#!/bin/sh\n[ -n "$1" ] || {\n\techo "usage: probe [-v] <host>"\n\texit 1\n}\n'
    assert usage_text(script) == "usage: probe [-v] <host>"


def test_first_usage_line_otherwise() -> None:
    script = b'#!/bin/sh\n# Usage: helper <file>\nexec cat "$1"\n'
    assert usage_text(script) == "# Usage: helper <file>"


def test_no_usage_and_binaries() -> None:
    assert usage_text(b"#!/bin/sh\n\nLED_NAME=green:internet\n") is None
    assert usage_text(b"\x7fELF\x01\x01\x01Usage: in a binary") is None


def test_usage_is_capped() -> None:
    script = b"#!/bin/sh\nusage() {\n\tcat <<'EOF'\n" + b"Usage: x\n" + b"y" * 10_000 + b"\nEOF\n}\n"
    text = usage_text(script)
    assert text is not None
    assert len(text) == MAX_USAGE
