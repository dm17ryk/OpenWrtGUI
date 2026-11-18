"""Saved good setups (spec 4.4): one JSON file per router in <data>/lte-setups, user-only, secrets kept out
of repr."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from openwrtgui.lte.at import ModemInfo
from openwrtgui.lte.setups import LteSetup, SetupStore, SetupUnreadable
from openwrtgui.store import keys

SAVED = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
OPTIONS = {"apn": "test-apn", "auth": "none", "pdptype": "ipv4", "password": "secret-pw", "pincode": "1234"}


@pytest.fixture
def restricted(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []
    monkeypatch.setattr(keys, "restrict_to_user", calls.append)
    return calls


def _setup(router_id: str = "ap2") -> LteSetup:
    return LteSetup(
        router_id=router_id,
        router_name="AP2 · office",
        saved_at=SAVED,
        modem=ModemInfo(manufacturer="BroadMobi", model="BM806C", firmware="M1.2.0_E1.0.3_A1.1.8"),
        options=OPTIONS,
    )


def test_save_then_get_round_trips_without_secrets_in_repr(tmp_path: Path, restricted: list[Path]) -> None:
    store = SetupStore(tmp_path / "lte-setups")
    store.save(_setup())
    got = store.get("ap2")
    assert got == _setup()
    assert "secret-pw" not in repr(got) and "1234" not in repr(got)
    assert restricted == [tmp_path / "lte-setups"]
    (summary,) = store.summaries()
    assert (summary.router_id, summary.apn, summary.pdptype, summary.readable) == (
        "ap2",
        "test-apn",
        "ipv4",
        True,
    )
    assert summary.saved_at == SAVED
    assert "options" not in summary.model_dump() and "secret-pw" not in summary.model_dump_json()


def test_no_setup_is_none(tmp_path: Path) -> None:
    store = SetupStore(tmp_path / "lte-setups")
    assert store.get("ap2") is None
    assert store.summaries() == []


def test_an_unreadable_file_is_listed_and_refused(tmp_path: Path) -> None:
    folder = tmp_path / "lte-setups"
    folder.mkdir()
    (folder / "ap2.json").write_text('{"router_id":', encoding="utf-8")
    store = SetupStore(folder)
    (summary,) = store.summaries()
    assert (summary.router_id, summary.readable, summary.apn, summary.saved_at) == ("ap2", False, None, None)
    with pytest.raises(SetupUnreadable, match=r"^ap2\.json cannot be read$"):
        store.get("ap2")


def test_delete_removes_the_file_and_a_missing_one_is_fine(tmp_path: Path, restricted: list[Path]) -> None:
    store = SetupStore(tmp_path / "lte-setups")
    store.save(_setup())
    store.delete("ap2")
    assert store.get("ap2") is None
    store.delete("ap2")


@pytest.mark.parametrize("router_id", ["../x", "a/b", "", "a\\b"])
def test_a_router_id_never_leaves_the_folder(tmp_path: Path, router_id: str) -> None:
    with pytest.raises(ValueError):
        SetupStore(tmp_path / "lte-setups").get(router_id)
