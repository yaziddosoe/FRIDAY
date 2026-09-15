import asyncio
import logging
import os

import httpx
from livekit.agents import RunContext, function_tool

logger = logging.getLogger("bridge_tools")


class BridgeError(RuntimeError):
    pass


def _make_client() -> httpx.Client:
    headers = {"Authorization": f"Bearer {os.environ.get('FRIDAY_BRIDGE_TOKEN', '')}"}
    return httpx.Client(
        base_url=os.environ.get("FRIDAY_BRIDGE_URL", "http://127.0.0.1:8787"),
        timeout=20.0,
        headers=headers,
    )


def _request(method: str, path: str, **kwargs: object) -> object:
    with _make_client() as client:
        resp = client.request(method, path, **kwargs)
        if resp.status_code >= 400:
            detail = "Bridge request failed"
            if resp.headers.get("content-type", "").startswith("application/json"):
                body = resp.json()
                detail = body.get("detail", detail)
            raise BridgeError(detail)
        return resp.json()


async def _arequest(method: str, path: str, **kwargs: object) -> object:
    return await asyncio.to_thread(_request, method, path, **kwargs)


def _format_error(exc: Exception) -> str:
    if isinstance(exc, httpx.ConnectError):
        return "The FRIDAY bridge is not reachable on this computer right now. It may not be running."
    if isinstance(exc, BridgeError):
        return str(exc)
    logger.warning("Bridge request failed: %s", exc)
    return "I could not reach the bridge; please try again shortly."


@function_tool
async def get_system_status(context: RunContext):
    """Reads this computer's current status: CPU usage, memory, battery, and free disk space.

    Use this when the user asks how their computer is doing, whether it is running slowly,
    how much battery is left, or how much disk space remains.
    """

    try:
        data = await _arequest("GET", "/api/v1/status")
    except Exception as exc:
        return _format_error(exc)
    assert isinstance(data, dict)
    parts = [
        f"CPU usage is {data['cpu_percent']} percent",
        f"memory is {data['memory_used_gb']} of {data['memory_total_gb']} gigabytes in use",
        f"{data['disk_free_gb']} gigabytes free on the main drive",
    ]
    battery = data.get("battery_percent")
    if battery is not None:
        state = "and charging" if data.get("battery_charging") else "running on battery"
        parts.append(f"battery at {battery} percent, {state}")
    return ". ".join(parts) + "." if len(parts) > 1 else parts[0]


@function_tool
async def create_note(context: RunContext, text: str):
    """Saves a note that is stored on the computer and persists across calls.

    Use this for things the user asks to remember, such as grocery lists, ideas, or tasks.

    Args:
        text: The note content to save.
    """

    try:
        data = await _arequest("POST", "/api/v1/notes", json={"content": text})
    except Exception as exc:
        return _format_error(exc)
    assert isinstance(data, dict)
    return f"Noted: {data['content']}"


@function_tool
async def list_notes(context: RunContext):
    """Lists all saved notes in plain text.

    Use this when the user asks what notes exist or what they asked you to remember.
    """

    try:
        data = await _arequest("GET", "/api/v1/notes")
    except Exception as exc:
        return _format_error(exc)
    assert isinstance(data, list)
    if not data:
        return "You have no notes."
    return " ".join(f"{item['id']}. {item['content']}" for item in data)


@function_tool
async def delete_note(context: RunContext, note_id: int):
    """Deletes a saved note by its id.

    Args:
        note_id: The numeric id of the note to delete.
    """

    try:
        data = await _arequest("DELETE", f"/api/v1/notes/{note_id}")
    except Exception as exc:
        return _format_error(exc)
    assert isinstance(data, dict)
    if data.get("deleted"):
        return f"Deleted note {note_id}."
    return f"There is no note with id {note_id}."


@function_tool
async def start_timer(context: RunContext, label: str, minutes: int):
    """Starts a countdown timer in minutes and notifies when it finishes.

    Use this when the user asks for a timer, e.g. "start a five minute timer".

    Args:
        label: A short name for the timer, e.g. "pasta".
        minutes: How long the timer should run, in minutes.
    """

    if minutes < 1:
        return "Please provide a positive number of minutes."
    try:
        data = await _arequest(
            "POST", "/api/v1/timers", json={"label": label, "minutes": minutes}
        )
    except Exception as exc:
        return _format_error(exc)
    assert isinstance(data, dict)
    return f"Timer '{data['label']}' set for {data['minutes']} minute(s). I will let you know when it finishes."


@function_tool
async def list_timers(context: RunContext):
    """Lists the currently running timers."""

    try:
        data = await _arequest("GET", "/api/v1/timers")
    except Exception as exc:
        return _format_error(exc)
    assert isinstance(data, list)
    if not data:
        return "No timers are running."
    return " ".join(
        f"Timer {item['id']} '{item['label']}' ends at {item['end_at']}"
        for item in data
    )


@function_tool
async def cancel_timer(context: RunContext, timer_id: int):
    """Cancels a running timer by its id.

    Args:
        timer_id: The numeric id of the timer to cancel.
    """

    try:
        data = await _arequest("DELETE", f"/api/v1/timers/{timer_id}")
    except Exception as exc:
        return _format_error(exc)
    assert isinstance(data, dict)
    if data.get("deleted"):
        return f"Cancelled timer {timer_id}."
    return f"There is no running timer with id {timer_id}."


@function_tool
async def schedule_reminder(context: RunContext, label: str, at: str):
    """Schedules a reminder for a specific local date and time and notifies when due.

    Reminders persist across restarts and are shown as a desktop notification.

    Args:
        label: What to remind the user about.
        at: The local date and time in ISO format, e.g. "2026-09-15T20:00:00".
    """

    try:
        data = await _arequest(
            "POST", "/api/v1/reminders", json={"label": label, "at": at}
        )
    except Exception as exc:
        return _format_error(exc)
    assert isinstance(data, dict)
    return f"Reminder set for {data['at']}: {data['label']}."


@function_tool
async def list_reminders(context: RunContext):
    """Lists the upcoming (not yet fired) reminders."""

    try:
        data = await _arequest("GET", "/api/v1/reminders")
    except Exception as exc:
        return _format_error(exc)
    assert isinstance(data, list)
    upcoming = [item for item in data if not item["fired"]]
    if not upcoming:
        return "You have no upcoming reminders."
    return " ".join(
        f"{item['id']}. {item['label']} at {item['at']}" for item in upcoming
    )


@function_tool
async def cancel_reminder(context: RunContext, reminder_id: int):
    """Cancels a reminder by its id.

    Args:
        reminder_id: The numeric id of the reminder to cancel.
    """

    try:
        data = await _arequest("DELETE", f"/api/v1/reminders/{reminder_id}")
    except Exception as exc:
        return _format_error(exc)
    assert isinstance(data, dict)
    if data.get("deleted"):
        return f"Cancelled reminder {reminder_id}."
    return f"There is no reminder with id {reminder_id}."


@function_tool
async def launch_app(context: RunContext, app_name: str):
    """Opens almost any program installed on the computer by name.

    Use this when the user asks to open or launch an app, e.g. "open Discord",
    "open Steam", "start WhatsApp" or "open the calculator". The bridge looks
    the name up in the Start menu and the installed-apps list, so nearly any
    installed program will be found even when it was never added to a preset.

    Args:
        app_name: The name of the app to launch, e.g. "discord", "notepad" or "steam".
    """

    try:
        data = await _arequest("POST", "/api/v1/apps/launch", json={"name": app_name})
    except Exception as exc:
        return _format_error(exc)
    assert isinstance(data, dict)
    return data["message"]


@function_tool
async def search_files(context: RunContext, query: str):
    """Searches this computer for files and folders by name, looking in the user's home directory.

    Use this when the user asks where a file is or to find a file with a given name.

    Args:
        query: A keyword or part of the file name to look for, e.g. "tax".
    """

    try:
        data = await _arequest("GET", "/api/v1/files/search", params={"q": query})
    except Exception as exc:
        return _format_error(exc)
    assert isinstance(data, dict)
    matches = data["matches"]
    if not matches:
        return f"Nothing named '{query}' was found in your home directory."
    return "Found: " + " | ".join(matches)


@function_tool
async def open_file(context: RunContext, path: str):
    """Opens a file or folder on the computer with its default program.

    Use this when the user asks to open a specific file, picture, document, or folder.

    Args:
        path: The local path of the file or folder, e.g. "C:/Users/you/Documents/report.pdf".
    """

    try:
        data = await _arequest("POST", "/api/v1/files/open", json={"path": path})
    except Exception as exc:
        return _format_error(exc)
    assert isinstance(data, dict)
    return data["message"]


@function_tool
async def take_screenshot(context: RunContext):
    """Takes a screenshot of the primary screen and saves it as a PNG on the computer.

    Use this when the user asks to take a screenshot or capture the screen.
    """

    try:
        data = await _arequest("POST", "/api/v1/screenshot")
    except Exception as exc:
        return _format_error(exc)
    assert isinstance(data, dict)
    if data["ok"]:
        return f"Screenshot saved to {data['path']}."
    return data["path"]


@function_tool
async def media_control(context: RunContext, action: str):
    """Controls media playback on the computer: play or pause, next or previous track, and volume.

    Use this for commands like "pause the music", "next song", "skip track", "turn up the volume",
    "mute".

    Args:
        action: One of: play_pause, next, previous, volume_up, volume_down, mute.
    """

    try:
        data = await _arequest("POST", "/api/v1/media", json={"action": action})
    except Exception as exc:
        return _format_error(exc)
    assert isinstance(data, dict)
    return data["message"]
