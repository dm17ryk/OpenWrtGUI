"""#29 (the v1.0 inventory): the frontend keeps copies of three server tables; they must stay the same.

The AT console's query forms (lte/at.py is_query), the AT commands whose argument the server hides
(guard/audit.py AT_MASKED_COMMANDS), and the LTE signal quality thresholds (lte/quality.py, v0.6a D11)."""

from __future__ import annotations

import re
from pathlib import Path

from openwrtgui.guard.audit import AT_MASKED_COMMANDS
from openwrtgui.lte.at import _QUERY
from openwrtgui.lte.quality import THRESHOLDS

LTE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "screens" / "lte"
CONSOLE = (LTE / "AtConsole.tsx").read_text(encoding="utf-8")
SIGNAL = (LTE / "signal.ts").read_text(encoding="utf-8")


def _regex(name: str) -> str:
    """The source of `const NAME = /…/i` in AtConsole.tsx."""
    m = re.search(rf"^const {name} = /(.+)/i$", CONSOLE, re.MULTILINE)
    assert m is not None, f"{name} is not a one-line regex literal in AtConsole.tsx"
    return m.group(1)


def test_the_console_asks_the_servers_query_forms() -> None:
    assert _regex("QUERY") == f"^{_QUERY.pattern}$"


def test_the_console_hides_the_commands_the_server_hides() -> None:
    assert _regex("PIN") == f"({AT_MASKED_COMMANDS}).*"


def test_the_signal_labels_use_the_servers_thresholds() -> None:
    for metric, (excellent, good, fair) in THRESHOLDS.items():
        line = rf"^\s*{metric}: \[{excellent:g}, {good:g}, {fair:g}\],$"
        assert re.search(line, SIGNAL, re.MULTILINE), f"{metric} differs in signal.ts"
