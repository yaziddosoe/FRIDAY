import asyncio
import inspect

import httpx
import pytest

import bridge_tools


def _client_with(responses: dict[str, httpx.Response]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return responses.get(
            request.url.path, httpx.Response(404, json={"detail": "nope"})
        )

    return httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8787"
    )


async def _invoke_tool(name: str, **kwargs: object) -> str:
    tool = getattr(bridge_tools, name)
    result = tool(None, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


async def test_status_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    status = {
        "cpu_percent": 42.0,
        "memory_total_gb": 16.0,
        "memory_used_gb": 8.0,
        "memory_percent": 50.0,
        "battery_percent": 88.0,
        "battery_charging": True,
        "disk_free_gb": 45.0,
        "disk_total_gb": 237.0,
        "hostname": "STEVE-PC",
        "booted_at": "2026-09-14 00:00:00",
        "os": "Windows",
    }
    monkeypatch.setattr(
        bridge_tools,
        "_make_client",
        lambda: _client_with({"/api/v1/status": httpx.Response(200, json=status)}),
    )

    result = await _invoke_tool("get_system_status")
    assert "42.0" in result
    assert "battery at 88.0" in result


async def test_status_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_connect_error():
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(bridge_tools, "_make_client", raise_connect_error)
    result = await _invoke_tool("get_system_status")
    assert "not reachable" in result


async def test_create_note_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bridge_tools,
        "_make_client",
        lambda: _client_with(
            {
                "/api/v1/notes": httpx.Response(
                    201, json={"id": 3, "content": "buy milk"}
                )
            }
        ),
    )
    result = await _invoke_tool("create_note", text="buy milk")
    assert "buy milk" in result


async def test_create_note_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_connect_error():
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(bridge_tools, "_make_client", raise_connect_error)
    assert "not reachable" in await _invoke_tool("create_note", text="buy milk")


async def test_start_timer_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bridge_tools,
        "_make_client",
        lambda: _client_with(
            {
                "/api/v1/timers": httpx.Response(
                    201,
                    json={
                        "id": 1,
                        "label": "pasta",
                        "minutes": 8,
                        "end_at": "2026-09-14T12:05:00",
                    },
                )
            }
        ),
    )
    result = await _invoke_tool("start_timer", label="pasta", minutes=8)
    assert "8" in result and "pasta" in result


async def test_start_timer_rejects_negative_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge_tools, "_make_client", lambda: _client_with({}))
    result = await _invoke_tool("start_timer", label="pasta", minutes=-1)
    assert "positive number" in result


async def test_start_timer_reports_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bridge_tools,
        "_make_client",
        lambda: _client_with(
            {
                "/api/v1/timers": httpx.Response(
                    422, json={"detail": "minutes must be between 0 and 10080"}
                )
            }
        ),
    )
    result = await _invoke_tool("start_timer", label="pasta", minutes=99999)
    assert "minutes must be between 0 and 10080" in result


async def test_schedule_reminder_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bridge_tools,
        "_make_client",
        lambda: _client_with(
            {
                "/api/v1/reminders": httpx.Response(
                    201,
                    json={"id": 7, "label": "stretch", "at": "2026-09-15T20:00:00"},
                )
            }
        ),
    )
    result = await _invoke_tool(
        "schedule_reminder", label="stretch", at="2026-09-15T20:00:00"
    )
    assert "20:00" in result


async def test_cancel_timer_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bridge_tools,
        "_make_client",
        lambda: _client_with(
            {"/api/v1/timers/999": httpx.Response(200, json={"deleted": 1})}
        ),
    )
    assert "999" in await _invoke_tool("cancel_timer", timer_id=999)


async def test_launch_app_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bridge_tools,
        "_make_client",
        lambda: _client_with(
            {
                "/api/v1/apps/launch": httpx.Response(
                    200, json={"ok": True, "message": "Launching spotify."}
                )
            }
        ),
    )
    result = await _invoke_tool("launch_app", app_name="spotify")
    assert "spotify" in result


async def test_launch_app_unknown_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bridge_tools,
        "_make_client",
        lambda: _client_with(
            {
                "/api/v1/apps/launch": httpx.Response(
                    200,
                    json={"ok": False, "message": "'skyrim' is not a known app."},
                )
            }
        ),
    )
    result = await _invoke_tool("launch_app", app_name="skyrim")
    assert "not a known app" in result


async def test_search_files_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bridge_tools,
        "_make_client",
        lambda: _client_with(
            {
                "/api/v1/files/search": httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "matches": ["C:/Users/steve/Documents/tax-2025.pdf"],
                    },
                )
            }
        ),
    )
    result = await _invoke_tool("search_files", query="tax")
    assert "tax-2025.pdf" in result


async def test_search_files_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bridge_tools,
        "_make_client",
        lambda: _client_with(
            {
                "/api/v1/files/search": httpx.Response(
                    200, json={"ok": True, "matches": []}
                )
            }
        ),
    )
    result = await _invoke_tool("search_files", query="nothing-here")
    assert "nothing named" in result.lower()


async def test_open_file_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bridge_tools,
        "_make_client",
        lambda: _client_with(
            {
                "/api/v1/files/open": httpx.Response(
                    200, json={"ok": True, "message": "Opened report.pdf."}
                )
            }
        ),
    )
    result = await _invoke_tool("open_file", path="C:/report.pdf")
    assert "report.pdf" in result


async def test_take_screenshot_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bridge_tools,
        "_make_client",
        lambda: _client_with(
            {
                "/api/v1/screenshot": httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "path": "C:/Users/steve/.friday/screenshots/shot.png",
                    },
                )
            }
        ),
    )
    result = await _invoke_tool("take_screenshot")
    assert "shot.png" in result


async def test_media_control_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bridge_tools,
        "_make_client",
        lambda: _client_with(
            {
                "/api/v1/media": httpx.Response(
                    200, json={"ok": True, "message": "Media: play_pause."}
                )
            }
        ),
    )
    result = await _invoke_tool("media_control", action="play_pause")
    assert "play_pause" in result


async def test_every_tool_awaits_like_livekit_voice_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # LiveKit's voice ToolExecutor does `await tool(...)` unconditionally (it
    # never sniffs for sync functions), so every @function_tool must return a
    # coroutine. Sync tools crash it with "TypeError: 'str' object can't be
    # awaited" (the launch_app failure seen in production).
    def raise_connect_error():
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(bridge_tools, "_make_client", raise_connect_error)
    calls: dict[str, dict[str, object]] = {
        "get_system_status": {},
        "create_note": {"text": "x"},
        "list_notes": {},
        "delete_note": {"note_id": 1},
        "start_timer": {"label": "x", "minutes": 1},
        "list_timers": {},
        "cancel_timer": {"timer_id": 1},
        "schedule_reminder": {"label": "x", "at": "2026-09-15T20:00:00"},
        "list_reminders": {},
        "cancel_reminder": {"reminder_id": 1},
        "launch_app": {"app_name": "x"},
        "search_files": {"query": "x"},
        "open_file": {"path": "x"},
        "take_screenshot": {},
        "media_control": {"action": "play_pause"},
    }
    for name, kwargs in calls.items():
        result = getattr(bridge_tools, name)(None, **kwargs)
        assert asyncio.iscoroutine(result), (
            f"{name} is not awaitable; the voice executor will crash with "
            "'TypeError: 'str' object can't be awaited'"
        )
        assert isinstance(await result, str)
