import socket
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from bridge import notify as notify_mod
from bridge.scheduler import Scheduler
from bridge.server import create_app
from bridge.status import get_status
from bridge.store import BridgeStore

TOKEN = "test-bridge-token"


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")


def _make_app(
    store: BridgeStore,
    scheduler: Scheduler,
    status_fn=None,
):
    return create_app(
        store=store,
        scheduler=scheduler,
        status_fn=status_fn or (lambda: {"ok": True}),
        token=TOKEN,
    )


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _make_store_and_scheduler(tmp_path, notifier=None):
    store = BridgeStore(tmp_path / "bridge.db")
    scheduler = Scheduler(store, notifier or notify_mod.notify)
    return store, scheduler


def test_status_endpoint_requires_token(tmp_path) -> None:
    store, scheduler = _make_store_and_scheduler(tmp_path)
    app = _make_app(store, scheduler)
    with TestClient(app) as client:
        responses = [
            client.get("/api/v1/status"),
            client.get("/api/v1/notes"),
            client.post("/api/v1/notes", json={"content": "x"}),
            client.post("/api/v1/timers", json={"label": "tea", "minutes": 1}),
            client.post(
                "/api/v1/reminders",
                json={"label": "stretch", "at": "2026-09-15T20:00:00"},
            ),
        ]
    assert all(r.status_code == 401 for r in responses)


def test_status_endpoint_returns_status_fn_shape(tmp_path) -> None:
    store, scheduler = _make_store_and_scheduler(tmp_path)

    def fake_status() -> dict[str, object]:
        return {"cpu_percent": 12.5, "battery_percent": 83.0}

    app = _make_app(store, scheduler, status_fn=fake_status)
    with TestClient(app) as client:
        resp = client.get("/api/v1/status", headers=_auth())
        body = resp.json()
    assert resp.status_code == 200
    assert body["cpu_percent"] == 12.5
    assert body["battery_percent"] == 83.0


def test_notes_create_list_delete_roundtrip(tmp_path) -> None:
    store, scheduler = _make_store_and_scheduler(tmp_path)
    app = _make_app(store, scheduler)
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/notes", json={"content": "buy milk"}, headers=_auth()
        )
        assert created.status_code == 201
        note_id = created.json()["id"]
        assert created.json()["content"] == "buy milk"

        listed = client.get("/api/v1/notes", headers=_auth()).json()
        assert len(listed) == 1
        assert listed[0]["content"] == "buy milk"

        deleted = client.delete(f"/api/v1/notes/{note_id}", headers=_auth()).json()
        assert deleted["deleted"] == 1

        assert client.get("/api/v1/notes", headers=_auth()).json() == []


def test_reminders_persist_across_store_instances(tmp_path) -> None:
    db = tmp_path / "bridge.db"
    store = BridgeStore(db)
    store.add_reminder("water the plants", "2026-09-15T20:00:00")

    reopened = BridgeStore(db)
    reminders = reopened.list_reminders()
    assert len(reminders) == 1
    assert reminders[0]["label"] == "water the plants"
    assert reminders[0]["fired"] == 0


def test_delete_reminder_via_api(tmp_path) -> None:
    store, scheduler = _make_store_and_scheduler(tmp_path)
    app = _make_app(store, scheduler)
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/reminders",
            json={"label": "call mom", "at": "2026-09-15T09:00:00"},
            headers=_auth(),
        )
        rid = created.json()["id"]
        assert (
            client.delete(f"/api/v1/reminders/{rid}", headers=_auth()).json()["deleted"]
            == 1
        )
        assert client.get("/api/v1/reminders", headers=_auth()).json() == []


def test_timers_via_api(tmp_path) -> None:
    store, scheduler = _make_store_and_scheduler(tmp_path)
    app = _make_app(store, scheduler)
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/timers", json={"label": "tea", "minutes": 1}, headers=_auth()
        ).json()
        assert created["minutes"] == 1

        listed = client.get("/api/v1/timers", headers=_auth()).json()
        assert len(listed) == 1
        assert listed[0]["label"] == "tea"

        assert (
            client.delete(f"/api/v1/timers/{created['id']}", headers=_auth()).json()[
                "deleted"
            ]
            == 1
        )
        assert client.get("/api/v1/timers", headers=_auth()).json() == []


def test_scheduler_fires_due_reminder_only_once(tmp_path) -> None:
    store = BridgeStore(tmp_path / "bridge.db")
    due = (
        (datetime.now() - timedelta(minutes=2))
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%S")
    )
    store.add_reminder("water the plants", due)

    fired: list[str] = []
    scheduler = Scheduler(store, lambda title, msg: fired.append(f"{title}: {msg}"))

    now = _now_iso()
    scheduler.check_due(now)
    assert len(fired) == 1
    assert "water the plants" in fired[0]

    scheduler.check_due(now)
    assert len(fired) == 1  # fired only once


def test_scheduler_fires_and_removes_expired_timer(tmp_path) -> None:
    store = BridgeStore(tmp_path / "bridge.db")
    fired: list[str] = []
    scheduler = Scheduler(store, lambda title, msg: fired.append(f"{title}: {msg}"))

    timer_id = scheduler.add_timer("micro tea", 0)
    assert scheduler.cancel_timer(timer_id) == 1
    assert scheduler.list_timers() == []

    timer_id = scheduler.add_timer("micro tea", 0)
    later = (
        (datetime.now() + timedelta(seconds=5))
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%S")
    )
    scheduler.check_due(later)
    assert len(fired) == 1
    assert scheduler.list_timers() == []


def test_get_status_reports_expected_fields(monkeypatch, tmp_path) -> None:
    import psutil

    class FakeVM:
        total = 16 * 1024**3
        used = 8 * 1024**3
        percent = 50.0

    class FakeBattery:
        percent = 88.0
        power_plugged = True

    class FakeUsage:
        free = 45 * 1024**3
        total = 237 * 1024**3

    monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None: 42.0)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: FakeVM())
    monkeypatch.setattr(psutil, "sensors_battery", lambda: FakeBattery())
    monkeypatch.setattr(psutil, "disk_usage", lambda path: FakeUsage())
    monkeypatch.setattr(psutil, "boot_time", lambda: 1_700_000_000.0)

    status = get_status()
    assert status["cpu_percent"] == 42.0
    assert status["memory_total_gb"] == 16.0
    assert status["memory_used_gb"] == 8.0
    assert status["battery_percent"] == 88.0
    assert status["battery_charging"] is True
    assert status["disk_free_gb"] == 45.0
    assert status["disk_total_gb"] == 237.0
    assert status["hostname"] == socket.gethostname()
    assert status["os"] == "Windows"
    assert "booted_at" in status


def test_get_status_handles_missing_battery(monkeypatch) -> None:
    import psutil

    class FakeVM:
        total = 16 * 1024**3
        used = 8 * 1024**3
        percent = 50.0

    class FakeUsage:
        free = 45 * 1024**3
        total = 237 * 1024**3

    monkeypatch.setattr(psutil, "sensors_battery", lambda: None)
    monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None: 0.0)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: FakeVM())
    monkeypatch.setattr(psutil, "disk_usage", lambda path: FakeUsage())
    monkeypatch.setattr(psutil, "boot_time", lambda: 1_700_000_000.0)

    status = get_status()
    assert status["battery_percent"] is None
    assert status["battery_charging"] is None


def _phase3_success_app(store: BridgeStore, scheduler: Scheduler):
    return create_app(
        store=store,
        scheduler=scheduler,
        status_fn=lambda: {"ok": True},
        token=TOKEN,
        app_launcher=lambda name: (name == "notepad", f"result for {name}"),
        file_search=lambda q: [f"C:/users/test/{q}.txt"],
        file_open=lambda p: (True, f"Opened {p}"),
        take_screenshot=lambda: (True, "C:/friday/shot.png"),
        media_control=lambda a: (True, f"Media: {a}"),
    )


def test_phase3_endpoints_require_token(tmp_path) -> None:
    store, scheduler = _make_store_and_scheduler(tmp_path)
    app = _phase3_success_app(store, scheduler)
    with TestClient(app) as client:
        responses = [
            client.post("/api/v1/apps/launch", json={"name": "notepad"}),
            client.get("/api/v1/files/search?q=report"),
            client.post("/api/v1/files/open", json={"path": "C:/x.txt"}),
            client.post("/api/v1/screenshot"),
            client.post("/api/v1/media", json={"action": "play_pause"}),
        ]
    assert all(r.status_code == 401 for r in responses)


def test_phase3_app_launch_endpoint(tmp_path) -> None:
    store, scheduler = _make_store_and_scheduler(tmp_path)
    app = _phase3_success_app(store, scheduler)
    with TestClient(app) as client:
        ok = client.post(
            "/api/v1/apps/launch", json={"name": "notepad"}, headers=_auth()
        ).json()
    assert ok == {"ok": True, "message": "result for notepad"}


def test_phase3_file_search_endpoint(tmp_path) -> None:
    store, scheduler = _make_store_and_scheduler(tmp_path)
    app = _phase3_success_app(store, scheduler)
    with TestClient(app) as client:
        body = client.get("/api/v1/files/search?q=report", headers=_auth()).json()
    assert body["ok"] is True
    assert body["matches"] == ["C:/users/test/report.txt"]


def test_phase3_open_and_screenshot_and_media_endpoints(tmp_path) -> None:
    store, scheduler = _make_store_and_scheduler(tmp_path)
    app = _phase3_success_app(store, scheduler)
    with TestClient(app) as client:
        opened = client.post(
            "/api/v1/files/open", json={"path": "C:/Users/test/a.pdf"}, headers=_auth()
        ).json()
        shot = client.post("/api/v1/screenshot", headers=_auth()).json()
        media_ok = client.post(
            "/api/v1/media", json={"action": "next"}, headers=_auth()
        ).json()
    assert opened["ok"] is True
    assert "a.pdf" in opened["message"]
    assert shot == {"ok": True, "path": "C:/friday/shot.png"}
    assert media_ok == {"ok": True, "message": "Media: next"}
