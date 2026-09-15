"""Deterministic mocks for bridge tools under CI simulations.

`lk agent simulate` spawns the agent as a local worker on the CI runner, where
the local FRIDAY bridge does not exist. These mocks intercept the bridge-bound
tools so simulation scenarios exercise the same tool plumbing the agent uses in
production, but with canned, reproducible results driven by scenario ``userdata``.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

MockSet = dict[str, Callable[..., Any]]

logger = logging.getLogger("agent")


def build_bridge_mocks(userdata: dict[str, Any] | None = None) -> MockSet:
    """Return session-scoped mocks for every bridge tool.

    ``userdata`` (from the scenario) may supply deterministic state:

    - ``notes``: list of note strings that exist at the start of the run.
    - ``timers``: list of timer dicts (each with ``label`` and ``minutes``) that
      exist at the start of the run; ``id`` is assigned in order.
    - ``reminders``: list of reminder dicts (each with ``label`` and ``at``) that
      exist at the start of the run; ``id`` is assigned in order.
    - ``launch_result``: the exact string returned by ``launch_app``.
    - ``status``: dict overriding the reported machine status fields.
    - ``file_matches``: list of paths returned by ``search_files``.
    - ``open_result``: the exact string returned by ``open_file``.
    - ``screenshot_path``: path reported by ``take_screenshot``.

    Mocks keep in-memory state (notes appended by ``create_note`` are visible to
    a later ``list_notes``), so a scenario can exercise multi-step flows.

    Every mock mirrors the live tool's signature, thankfully accepting the same
    leading ``RunContext`` parameter first so the framework's positional
    argument trimming binds the real parameter values instead of the context.
    """
    userdata = userdata or {}
    notes: list[str] = list(userdata.get("notes") or [])
    timers: list[dict[str, Any]] = [
        {"id": timer.get("id", index + 1), **timer}
        for index, timer in enumerate(userdata.get("timers") or [])
    ]
    reminders: list[dict[str, Any]] = list(userdata.get("reminders") or [])
    status = userdata.get("status") or {}

    def get_system_status(_context: object) -> str:
        cpu = status.get("cpu_percent", 30.0)
        mem = status.get("memory_used_gb", 6.0)
        mem_total = status.get("memory_total_gb", 8.0)
        disk = status.get("disk_free_gb", 40.0)
        return (
            f"CPU usage is {cpu} percent. memory is {mem} of {mem_total} "
            f"gigabytes in use. {disk} gigabytes free on the main drive."
        )

    def create_note(_context: object, text: str) -> str:
        if not text:
            return "Please provide the note content."
        notes.append(text)
        logger.info("mock create_note -> %d note(s): %r", len(notes), notes)
        return f"Noted: {text}"

    def list_notes(_context: object) -> str:
        logger.info("mock list_notes sees %r", notes)
        if not notes:
            return "You have no notes."
        return " ".join(f"{i + 1}. {item}" for i, item in enumerate(notes))

    def delete_note(_context: object, note_id: int) -> str:
        if 1 <= note_id <= len(notes):
            notes.pop(note_id - 1)
            return f"Deleted note {note_id}."
        return f"There is no note with id {note_id}."

    def start_timer(_context: object, label: str, minutes: int) -> str:
        if minutes < 1:
            return "Please provide a positive number of minutes."
        timers.append({"id": len(timers) + 1, "label": label, "minutes": minutes})
        return f"Timer '{label}' set for {minutes} minute(s). I will let you know when it finishes."

    def list_timers(_context: object) -> str:
        if not timers:
            return "No timers are running."
        return " ".join(
            f"Timer {t['id']} '{t['label']}' ends in {t['minutes']} minute(s)"
            for t in timers
        )

    def cancel_timer(_context: object, timer_id: int) -> str:
        for i, timer in enumerate(timers):
            if timer["id"] == timer_id:
                timers.pop(i)
                return f"Cancelled timer {timer_id}."
        return f"There is no running timer with id {timer_id}."

    def schedule_reminder(_context: object, label: str, at: str) -> str:
        reminders.append({"label": label, "at": at})
        return f"Reminder set for {at}: {label}."

    def list_reminders(_context: object) -> str:
        if not reminders:
            return "You have no upcoming reminders."
        return " ".join(
            f"{i + 1}. {item['label']} at {item['at']}"
            for i, item in enumerate(reminders)
        )

    def cancel_reminder(_context: object, reminder_id: int) -> str:
        if 1 <= reminder_id <= len(reminders):
            reminders.pop(reminder_id - 1)
            return f"Cancelled reminder {reminder_id}."
        return f"There is no reminder with id {reminder_id}."

    def launch_app(_context: object, app_name: str) -> str:
        result = userdata.get("launch_result")
        if result:
            return str(result)
        return f"Launching {app_name}."

    def search_files(_context: object, query: str) -> str:
        matches = userdata.get("file_matches")
        if matches:
            return "Found: " + " | ".join(str(m) for m in matches)
        return f"Nothing named '{query}' was found in your home directory."

    def open_file(_context: object, path: str) -> str:
        result = userdata.get("open_result")
        if result:
            return str(result)
        return f"Opened {path}."

    def take_screenshot(_context: object) -> str:
        path = userdata.get(
            "screenshot_path", "C:/Users/ci/.friday/screenshots/shot.png"
        )
        return f"Screenshot saved to {path}."

    def media_control(_context: object, action: str) -> str:
        return f"Media: {action}."

    return {
        "get_system_status": get_system_status,
        "create_note": create_note,
        "list_notes": list_notes,
        "delete_note": delete_note,
        "start_timer": start_timer,
        "list_timers": list_timers,
        "cancel_timer": cancel_timer,
        "schedule_reminder": schedule_reminder,
        "list_reminders": list_reminders,
        "cancel_reminder": cancel_reminder,
        "launch_app": launch_app,
        "search_files": search_files,
        "open_file": open_file,
        "take_screenshot": take_screenshot,
        "media_control": media_control,
    }


def covers_every_bridge_tool(mocks: MockSet) -> bool:
    """True if ``mocks`` maps every tool the live agent registers from bridge_tools."""
    expected = {
        "cancel_reminder",
        "cancel_timer",
        "create_note",
        "delete_note",
        "get_system_status",
        "launch_app",
        "list_notes",
        "list_reminders",
        "list_timers",
        "media_control",
        "open_file",
        "schedule_reminder",
        "search_files",
        "start_timer",
        "take_screenshot",
    }
    return expected.issubset(mocks)
