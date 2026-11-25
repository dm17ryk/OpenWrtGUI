import pytest

from openwrtgui.lte.ussd import decode, parse_cusd, reply_of


def test_cusd_parses_text_with_commas_and_quotes() -> None:
    assert parse_cusd(('+CUSD: 0,"Balance: 1,50; "ok"",15',)) == (0, 'Balance: 1,50; "ok"', 15)
    assert parse_cusd(("+CUSD: 4",)) == (4, None, None)
    assert parse_cusd(("OK",)) is None


def test_cusd_without_a_dcs_and_amid_other_lines() -> None:
    assert parse_cusd(("", '+CUSD: 2,"bye"', "OK")) == (2, "bye", None)


def test_decode_follows_the_dcs() -> None:
    assert decode("Hello", 15) == "Hello"
    assert decode("05E905DC05D505DD", 72) == "שלום"  # UCS-2 hex
    assert decode("0102", 68) == "0102"  # 8-bit: shown as hex
    assert decode("05E905DC", 0x11) == "של"
    assert decode("05E905DC", 0x98) == "של"


def test_decode_shows_invalid_hex_as_given() -> None:
    assert decode("not hex", 72) == "not hex"
    assert decode("05E", 72) == "05E"


@pytest.mark.parametrize(
    ("m", "status"),
    [(0, "reply"), (1, "more"), (2, "ended"), (3, "ended"), (4, "error"), (5, "error")],
)
def test_reply_status_from_m(m: int, status: str) -> None:
    reply = reply_of((m, "t", 15))
    assert reply.status == status
    assert reply.closed is False
    assert reply_of(None).status == "no reply"


def test_reply_text_is_decoded() -> None:
    reply = reply_of((0, "05E9", 72))
    assert (reply.text, reply.dcs) == ("ש", 72)
