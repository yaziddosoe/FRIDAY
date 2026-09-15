from datetime import datetime, timedelta
from typing import Callable

from .store import _TS, BridgeStore


class Scheduler:
    """Owns the in-memory countdown timers and fires due reminders from the store."""

    def __init__(
        self, store: BridgeStore, notifier: Callable[[str, str], None]
    ) -> None:
        self._store = store
        self._notifier = notifier
        self._timers: dict[int, dict[str, object]] = {}
        self._next_timer_id = 1

    def add_timer(self, label: str, minutes: int) -> int:
        end = datetime.now() + timedelta(seconds=minutes * 60)
        timer_id = self._next_timer_id
        self._next_timer_id += 1
        self._timers[timer_id] = {
            "label": label,
            "minutes": minutes,
            "end_at": end.replace(microsecond=0).strftime(_TS),
        }
        return timer_id

    def list_timers(self) -> list[dict[str, object]]:
        return [{"id": timer_id, **item} for timer_id, item in self._timers.items()]

    def cancel_timer(self, timer_id: int) -> int:
        return 1 if self._timers.pop(timer_id, None) is not None else 0

    def check_due(self, now: str) -> list[str]:
        fired: list[str] = []
        for timer_id, item in list(self._timers.items()):
            if str(item["end_at"]) <= now:
                self._timers.pop(timer_id, None)
                self._notifier(
                    "Timer done",
                    f"Your {item['minutes']}-minute timer "
                    f"'{item['label']}' is complete.",
                )
                fired.append(f"Timer done: {item['label']}")
        for reminder in self._store.due_reminders(now):
            self._store.mark_reminder_fired(int(reminder["id"]))
            self._notifier("Reminder", str(reminder["label"]))
            fired.append(f"Reminder fired: {reminder['label']}")
        return fired
