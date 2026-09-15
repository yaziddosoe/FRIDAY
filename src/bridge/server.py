import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Callable

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field

from . import files, launcher, media, notify, screenshot
from .scheduler import Scheduler
from .status import get_status
from .store import BridgeStore, now_ts

logger = logging.getLogger("bridge.server")

load_dotenv(".env.local")


class NoteIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class TimerIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    minutes: int = Field(ge=0, le=10080)


class ReminderIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    at: str


class AppIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class OpenFileIn(BaseModel):
    path: str = Field(min_length=1, max_length=2048)


class MediaIn(BaseModel):
    action: str = Field(min_length=1, max_length=32)


def create_app(
    store: BridgeStore,
    scheduler: Scheduler,
    status_fn: Callable[[], dict[str, object]],
    token: str,
    app_launcher: Callable[[str], tuple[bool, str]] = launcher.launch_app,
    file_search: Callable[[str], list[str]] = files.search_files,
    file_open: Callable[[str], tuple[bool, str]] = launcher.open_file,
    take_screenshot: Callable[[], tuple[bool, str]] = screenshot.take_screenshot,
    media_control: Callable[[str], tuple[bool, str]] = media.media_control,
) -> FastAPI:
    app = FastAPI(title="FRIDAY Bridge")
    app.state.store = store
    app.state.scheduler = scheduler
    app.state.status_fn = status_fn
    app.state.app_launcher = app_launcher
    app.state.file_search = file_search
    app.state.file_open = file_open
    app.state.take_screenshot = take_screenshot
    app.state.media_control = media_control

    def _auth(authorization: str = Header(default="")) -> None:
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="Missing or invalid token")

    @app.get("/api/v1/status", dependencies=[Depends(_auth)])
    def status() -> dict[str, object]:
        return app.state.status_fn()

    @app.get("/api/v1/notes", dependencies=[Depends(_auth)])
    def list_notes() -> list[dict[str, object]]:
        return app.state.store.list_notes()

    @app.post("/api/v1/notes", dependencies=[Depends(_auth)])
    def add_note(payload: NoteIn, response: Response) -> dict[str, object]:
        note_id = app.state.store.add_note(payload.content)
        response.status_code = 201
        return {"id": note_id, "content": payload.content}

    @app.delete("/api/v1/notes/{note_id}", dependencies=[Depends(_auth)])
    def delete_note(note_id: int) -> dict[str, int]:
        return {"deleted": app.state.store.delete_note(note_id)}

    @app.get("/api/v1/timers", dependencies=[Depends(_auth)])
    def list_timers() -> list[dict[str, object]]:
        return app.state.scheduler.list_timers()

    @app.post("/api/v1/timers", dependencies=[Depends(_auth)])
    def add_timer(payload: TimerIn, response: Response) -> dict[str, object]:
        timer_id = app.state.scheduler.add_timer(payload.label, payload.minutes)
        response.status_code = 201
        item = next(
            timer
            for timer in app.state.scheduler.list_timers()
            if timer["id"] == timer_id
        )
        return item

    @app.delete("/api/v1/timers/{timer_id}", dependencies=[Depends(_auth)])
    def delete_timer(timer_id: int) -> dict[str, int]:
        return {"deleted": app.state.scheduler.cancel_timer(timer_id)}

    @app.get("/api/v1/reminders", dependencies=[Depends(_auth)])
    def list_reminders() -> list[dict[str, object]]:
        return app.state.store.list_reminders()

    @app.post("/api/v1/reminders", dependencies=[Depends(_auth)])
    def add_reminder(payload: ReminderIn, response: Response) -> dict[str, object]:
        from .store import normalize_at

        try:
            normalized = normalize_at(payload.at)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        reminder_id = app.state.store.add_reminder(payload.label, payload.at)
        response.status_code = 201
        return {"id": reminder_id, "label": payload.label, "at": normalized}

    @app.delete("/api/v1/reminders/{reminder_id}", dependencies=[Depends(_auth)])
    def delete_reminder(reminder_id: int) -> dict[str, int]:
        return {"deleted": app.state.store.delete_reminder(reminder_id)}

    @app.post("/api/v1/apps/launch", dependencies=[Depends(_auth)])
    def launch_app(payload: AppIn) -> dict[str, object]:
        ok, message = app.state.app_launcher(payload.name)
        return {"ok": ok, "message": message}

    @app.get("/api/v1/files/search", dependencies=[Depends(_auth)])
    def search_files(q: str = Query(min_length=1)) -> dict[str, object]:
        matches = app.state.file_search(q)
        return {"ok": True, "matches": matches}

    @app.post("/api/v1/files/open", dependencies=[Depends(_auth)])
    def open_file(payload: OpenFileIn) -> dict[str, object]:
        ok, message = app.state.file_open(payload.path)
        return {"ok": ok, "message": message}

    @app.post("/api/v1/screenshot", dependencies=[Depends(_auth)])
    def capture_screenshot() -> dict[str, object]:
        ok, message = app.state.take_screenshot()
        return {"ok": ok, "path": message}

    @app.post("/api/v1/media", dependencies=[Depends(_auth)])
    def control_media(payload: MediaIn) -> dict[str, object]:
        ok, message = app.state.media_control(payload.action)
        return {"ok": ok, "message": message}

    return app


async def _ticker(scheduler: Scheduler) -> None:
    while True:
        try:
            await asyncio.to_thread(scheduler.check_due, now_ts())
        except Exception:
            logger.exception("Bridge scheduler tick failed")
        await asyncio.sleep(1.0)


def main() -> None:
    import uvicorn

    token = os.environ.get("FRIDAY_BRIDGE_TOKEN", "")
    if not token:
        raise SystemExit(
            "FRIDAY_BRIDGE_TOKEN is not set; add it to .env.local and set the "
            "environment variable before starting the bridge."
        )

    store = BridgeStore()
    scheduler = Scheduler(store, notify.notify)
    app = create_app(store, scheduler, get_status, token)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        prewarm = asyncio.create_task(asyncio.to_thread(launcher.prewarm_app_list))
        task = asyncio.create_task(_ticker(scheduler))
        yield
        prewarm.cancel()
        task.cancel()

    app.router.lifespan_context = lifespan
    uvicorn.run(app, host="127.0.0.1", port=8787, log_level="info")


if __name__ == "__main__":
    main()
