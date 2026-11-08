"""The AT console's query forms (v0.6a plan D5): these run any time; everything else may change the modem."""

from __future__ import annotations

import pytest

from openwrtgui.lte.at import is_query


@pytest.mark.parametrize(
    "text",
    [
        "AT",
        "ATI",
        "at+csq",
        "AT+CGMI",
        "AT+CGMM",
        "AT+CGMR",
        "AT+COPS?",
        "AT+CGDCONT=?",
        "AT%BMSTATUS?",
        " ati ",
    ],
)
def test_queries(text: str) -> None:
    assert is_query(text)


@pytest.mark.parametrize(
    "text", ["AT+CFUN=0", "ATZ", "AT+COPS=0", "AT+CSQ;+CFUN=0", "ATD123;", "AT+CGMIX", "AT+COPS?;+CFUN=0"]
)
def test_commands_that_may_change_the_modem(text: str) -> None:
    assert not is_query(text)
