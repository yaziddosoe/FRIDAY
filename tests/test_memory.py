from pathlib import Path

from memory import MemoryStore


def test_add_and_list_facts() -> None:
    store = MemoryStore(":memory:")
    assert store.add_fact("The user is called Steve") == 1
    assert store.add_fact("The user hates mint tea") == 2
    assert store.get_facts() == [
        "The user is called Steve",
        "The user hates mint tea",
    ]


def test_memory_persists_across_instances(tmp_path: Path) -> None:
    db = tmp_path / "friday.db"
    writer = MemoryStore(db)
    writer.add_fact("Call the user 'sir'")

    reader = MemoryStore(db)
    assert reader.get_facts() == ["Call the user 'sir'"]


def test_forget_removes_matching_facts(tmp_path: Path) -> None:
    db = tmp_path / "friday.db"
    store = MemoryStore(db)
    store.add_fact("The user hates mint tea")
    store.add_fact("The user likes green tea")

    removed = store.forget_fact("mint")
    assert removed == 1
    assert store.get_facts() == ["The user likes green tea"]


def test_forget_is_case_insensitive_substring(tmp_path: Path) -> None:
    db = tmp_path / "friday.db"
    store = MemoryStore(db)
    store.add_fact("Lunch break at 13:00")

    assert store.forget_fact("LUNCH") == 1
    assert store.get_facts() == []


def test_store_with_missing_db_returns_empty(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "does-not-exist.db")
    assert store.get_facts() == []
    assert store.has_facts() is False


def test_create_dir_when_missing(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "deep" / "friday.db"
    store = MemoryStore(db)
    store.add_fact("The user prefers coffee")
    assert db.exists()
    assert store.get_facts() == ["The user prefers coffee"]


def test_default_path_uses_env_override(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "env.db"
    monkeypatch.setenv("FRIDAY_MEMORY_DB", str(db))
    store = MemoryStore()
    assert store.db_path == Path(db)
