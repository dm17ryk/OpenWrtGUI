import json
from pathlib import Path

import pytest

from openwrtgui.lte.sms import SmsMessage, check_text, parse_cpms, parse_ids, parse_message

_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "ap2" / "modem_sim.json"


def _recorded(option: str) -> str:
    answers = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    for command, answer in answers.items():
        if option in command:
            return str(answer["stdout"])
    raise AssertionError(option)


def test_message_ids_and_a_message() -> None:
    assert parse_ids(_recorded("--list-messages")) == tuple(range(20))
    msg = parse_message(
        '{"smsc":"+15550100","sender":"+15550101","timestamp":"2026-11-20 10:00:00","text":"Hi"}',
        3,
        "sim",
    )
    assert msg == SmsMessage(
        id=3, storage="sim", sender="+15550101", time="2026-11-20 10:00:00", text="Hi", part=None
    )


def test_a_message_part_and_a_binary_message() -> None:
    part = parse_message('{"sender":"x","concat_ref":5,"concat_part":2,"concat_parts":3,"text":"b"}', 1, "me")
    assert part is not None
    assert part.part == "2 of 3"
    binary = parse_message('{"sender":"x"}', 1, "me")
    assert binary is not None
    assert binary.text is None


@pytest.mark.parametrize("bad", ["", "nope", "[1,"])
def test_bad_ids_and_messages_are_no_answer(bad: str) -> None:
    assert parse_ids(bad) is None
    assert parse_message(bad, 1, "sim") is None


def test_ids_must_be_a_list_of_numbers_and_a_message_an_object() -> None:
    assert parse_ids('{"a":1}') is None
    assert parse_ids('["a"]') is None
    assert parse_message("[1]", 1, "sim") is None


def test_cpms_gives_use_and_capacity_per_storage() -> None:
    assert parse_cpms(('+CPMS: "ME",0,23,"ME",0,23,"SM",20,20',)) == {
        "me": (0, 23),
        "sim": (20, 20),
    }
    assert parse_cpms(("OK",)) == {}


@pytest.mark.parametrize("bad", ["é", "€", "[", "שלום", "🙂", "x" * 161, ""])
def test_send_text_is_1_to_160_gsm_basic_characters(bad: str) -> None:
    with pytest.raises(ValueError, match="1 to 160 characters"):
        check_text(bad)


def test_good_text_passes_unchanged() -> None:
    text = "Hello, world! 100% OK?\n" + "x" * 100
    assert check_text(text) == text
    assert check_text("x" * 160) == "x" * 160
