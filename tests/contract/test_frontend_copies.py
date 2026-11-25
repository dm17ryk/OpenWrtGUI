"""#29 (the v1.0 inventory): the frontend keeps copies of server tables and rules; they must stay the same.

The AT console's query forms (lte/at.py is_query), the AT commands whose argument the server hides
(guard/audit.py AT_MASKED_COMMANDS), the LTE signal quality thresholds (lte/quality.py, v0.6a D11), and the
SMS and USSD cards' rules (v1.3b: lte/sms.py, lte/commands.py)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from openwrtgui.guard.audit import AT_MASKED_COMMANDS
from openwrtgui.lte.at import _QUERY
from openwrtgui.lte.commands import TARGET_MESSAGE, TARGET_RULE, USSD_CODE, USSD_MESSAGE
from openwrtgui.lte.quality import THRESHOLDS
from openwrtgui.lte.sms import GSM_7BIT_BASIC, GSM_RULE

LTE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "screens" / "lte"
CONSOLE = (LTE / "AtConsole.tsx").read_text(encoding="utf-8")
SIGNAL = (LTE / "signal.ts").read_text(encoding="utf-8")
SMS = (LTE / "sms.ts").read_text(encoding="utf-8")


def _regex(name: str) -> str:
    """The source of `const NAME = /…/i` in AtConsole.tsx."""
    m = re.search(rf"^const {name} = /(.+)/i$", CONSOLE, re.MULTILINE)
    assert m is not None, f"{name} is not a one-line regex literal in AtConsole.tsx"
    return m.group(1)


def test_the_console_asks_the_servers_query_forms() -> None:
    assert _regex("QUERY") == f"^{_QUERY.pattern}$"


def test_the_console_hides_the_commands_the_server_hides() -> None:
    assert _regex("PIN") == f"({AT_MASKED_COMMANDS}).*"


def _sms_literal(name: str) -> str:
    """The value of `export const NAME = "…"` in sms.ts (a one-line double-quoted literal)."""
    m = re.search(rf'^export const {name} = ("(?:[^"\\]|\\.)*")$', SMS, re.MULTILINE)
    assert m is not None, f"{name} is not a one-line string literal in sms.ts"
    result = json.loads(m.group(1))
    assert isinstance(result, str)
    return result


def test_the_sms_card_accepts_the_servers_gsm_characters() -> None:
    assert set(_sms_literal("GSM_CHARS")) == GSM_7BIT_BASIC
    assert len(_sms_literal("GSM_CHARS")) == len(GSM_7BIT_BASIC)


def test_the_sms_card_says_the_servers_rules() -> None:
    assert _sms_literal("GSM_RULE") == GSM_RULE
    assert _sms_literal("TARGET_RULE") == TARGET_MESSAGE
    m = re.search(r"^export const TARGET = /(.+)/$", SMS, re.MULTILINE)
    assert m is not None, "TARGET is not a one-line regex literal in sms.ts"
    assert m.group(1) == f"^{TARGET_RULE.pattern}$"


def test_the_ussd_card_says_and_checks_the_servers_rule() -> None:
    """Security L4 (P16): the card refuses the same supplementary-service strings the server refuses."""
    assert _sms_literal("USSD_RULE") == USSD_MESSAGE
    m = re.search(r"^export const USSD_CODE = /(.+)/$", SMS, re.MULTILINE)
    assert m is not None, "USSD_CODE is not a one-line regex literal in sms.ts"
    assert m.group(1) == f"^{USSD_CODE.pattern}$"
    card = (LTE / "UssdCard.tsx").read_text(encoding="utf-8")
    assert "USSD_CODE" in card and "USSD_RULE" in card and "const CODE" not in card


def test_the_signal_labels_use_the_servers_thresholds() -> None:
    for metric, (excellent, good, fair) in THRESHOLDS.items():
        line = rf"^\s*{metric}: \[{excellent:g}, {good:g}, {fair:g}\],$"
        assert re.search(line, SIGNAL, re.MULTILINE), f"{metric} differs in signal.ts"
