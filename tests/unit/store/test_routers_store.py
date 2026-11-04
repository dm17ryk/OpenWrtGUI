from datetime import datetime
from pathlib import Path

from openwrtgui.store.routers import RouterRecord, RouterStore, make_router_id, router_key_paths


def _rec(router_id: str, host: str) -> RouterRecord:
    return RouterRecord(
        id=router_id, name=router_id.upper(), host=host, auth="key", added_at=datetime(2026, 11, 3)
    )


def test_router_id_slug_and_collision() -> None:
    assert make_router_id("AP1 · bench", []) == "ap1-bench"
    assert make_router_id("AP1 · bench", ["ap1-bench"]) == "ap1-bench-2"
    assert make_router_id("AP1 · bench", ["ap1-bench", "ap1-bench-2"]) == "ap1-bench-3"


def test_router_store_roundtrip_and_remove(tmp_path: Path) -> None:
    store = RouterStore(tmp_path / "routers.json")
    store.upsert(_rec("ap1", "192.168.1.1"))
    store.upsert(_rec("ap2", "192.168.1.2"))
    again = RouterStore(tmp_path / "routers.json")
    assert [r.id for r in again.list()] == ["ap1", "ap2"]
    got = again.get("ap2")
    assert got is not None and got.host == "192.168.1.2" and got.port == 22 and got.username == "root"
    assert again.remove("ap1") is True
    assert again.remove("ap1") is False
    assert [r.id for r in RouterStore(tmp_path / "routers.json").list()] == ["ap2"]


def test_upsert_replaces_same_id(tmp_path: Path) -> None:
    store = RouterStore(tmp_path / "routers.json")
    store.upsert(_rec("ap1", "192.168.1.1"))
    store.upsert(_rec("ap1", "192.168.1.9"))
    assert [(r.id, r.host) for r in store.list()] == [("ap1", "192.168.1.9")]


def test_port_labels_survive_json(tmp_path: Path) -> None:
    store = RouterStore(tmp_path / "routers.json")
    store.upsert(_rec("ap2", "192.168.1.2").model_copy(update={"port_labels": {0: "LAN4", 6: "CPU (eth0)"}}))
    got = RouterStore(tmp_path / "routers.json").get("ap2")
    assert got is not None and got.port_labels == {0: "LAN4", 6: "CPU (eth0)"}


def test_key_path_defaults_to_the_app_key_and_survives_json(tmp_path: Path) -> None:
    assert _rec("ap1", "192.168.1.1").key_path is None
    store = RouterStore(tmp_path / "routers.json")
    store.upsert(
        _rec("ap2", "192.168.1.2").model_copy(update={"key_path": r"C:\Essence_SC\home\.ssh\id_rsa"})
    )
    got = RouterStore(tmp_path / "routers.json").get("ap2")
    assert got is not None and got.key_path == r"C:\Essence_SC\home\.ssh\id_rsa"


def test_router_key_paths_use_the_records_own_key(tmp_path: Path) -> None:
    app_key = tmp_path / "keys" / "id_ed25519"
    assert router_key_paths(_rec("ap1", "192.168.1.1"), app_key) == [app_key]
    own = _rec("ap2", "192.168.1.2").model_copy(update={"key_path": str(tmp_path / "id_rsa")})
    assert router_key_paths(own, app_key) == [tmp_path / "id_rsa"]


def test_missing_file_is_empty(tmp_path: Path) -> None:
    assert RouterStore(tmp_path / "routers.json").list() == []
