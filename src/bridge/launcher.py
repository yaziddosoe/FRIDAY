import json
import logging
import os
import subprocess
import time
from pathlib import Path

logger = logging.getLogger("bridge.launcher")

_APPS_FILE = Path(os.path.expanduser("~/.friday/apps.json"))
_OPEN_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_PRESETS: dict[str, list[str]] = {
    "spotify": ["cmd", "/c", "start", "", "spotify:"],
    "chrome": ["cmd", "/c", "start", "", "chrome"],
    "edge": ["cmd", "/c", "start", "", "msedge"],
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "explorer": ["explorer.exe"],
}

_START_MENU_DIRS: tuple[Path, ...] = (
    Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs",
    Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs",
)

# Installed-app listing is cached so repeated launches are instant; the list is
# rebuilt only when it is stale (or after the TTL expires).
_apps_cache: list[tuple[str, str]] | None = None
_apps_cache_at: float = 0.0
_APPS_CACHE_TTL = 300.0

# Same idea for the Start-Menu shortcut scan: it is the slowest step on the
# first launch, so it is built once and reused for the TTL window.
_shortcuts_index: list[Path] | None = None
_shortcuts_index_at: float = 0.0
_SHORTCUTS_CACHE_TTL = 300.0

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def apps_commands(
    apps_path: str | os.PathLike[str] | None = None,
) -> dict[str, list[str]]:
    commands = {name: list(argv) for name, argv in _PRESETS.items()}
    path = Path(apps_path) if apps_path is not None else _APPS_FILE
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read apps config %s: %s", path, exc)
            raw = {}
        for name, argv in raw.items():
            if isinstance(name, str) and isinstance(argv, list):
                commands[str(name).lower()] = [str(part) for part in argv]
    return commands


def _run_powershell(script: str, timeout: int = 30) -> str:
    proc = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-WindowStyle",
            "Hidden",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        creationflags=_CREATE_NO_WINDOW,
    )
    return proc.stdout


def _start_apps_list(force: bool = False) -> list[tuple[str, str]]:
    global _apps_cache, _apps_cache_at
    now = time.time()
    if not force and _apps_cache is not None and now - _apps_cache_at < _APPS_CACHE_TTL:
        return _apps_cache
    try:
        stdout = _run_powershell(
            'Get-StartApps | ForEach-Object { "$($_.Name)`t$($_.AppID)" }'
        )
        parsed: list[tuple[str, str]] = []
        for line in stdout.splitlines():
            name, _, app_id = line.strip().partition("\t")
            if name and app_id:
                parsed.append((name, app_id))
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("Get-StartApps failed: %s", exc)
        return []
    _apps_cache = parsed
    _apps_cache_at = now
    return parsed


def _find_start_menu_shortcuts(name: str) -> Path | None:
    needle = name.lower()
    for shortcut in _shortcuts_index_list():
        if needle in shortcut.stem.lower():
            return shortcut
    return None


def _build_shortcuts_index() -> list[Path]:
    index: list[Path] = []
    for root in _START_MENU_DIRS:
        if root.is_dir():
            index.extend(root.rglob("*.lnk"))
    return index


def _shortcuts_index_list() -> list[Path]:
    global _shortcuts_index, _shortcuts_index_at
    now = time.time()
    if (
        _shortcuts_index is not None
        and now - _shortcuts_index_at < _SHORTCUTS_CACHE_TTL
    ):
        return _shortcuts_index
    index = _build_shortcuts_index()
    _shortcuts_index = index
    _shortcuts_index_at = now
    return index


def _format_start_apps_fallback() -> str:
    apps = _start_apps_list()
    samples = ", ".join(sorted(app[0] for app in apps)[:12])
    tail = (
        "Add more to ~/.friday/apps.json to teach me one-off names." if samples else ""
    )
    return samples + (". " + tail if tail else ".")


def prewarm_app_list() -> None:
    """Pre-build the expensive app-lookup caches so the first launch is instant."""
    _start_apps_list(force=True)
    _shortcuts_index_list()


def launch_app(
    name: str, apps_path: str | os.PathLike[str] | None = None
) -> tuple[bool, str]:
    key = name.strip().lower()
    commands = apps_commands(apps_path)
    argv = commands.get(key)
    if argv is not None:
        try:
            subprocess.Popen(argv, creationflags=_OPEN_NO_WINDOW)
        except (OSError, ValueError) as exc:
            logger.warning("Failed to launch '%s': %s", name, exc)
            return False, f"I could not launch '{name}': {exc}"
        return True, f"Launching {name}."

    # Fall back to Start Menu shortcuts (classic installs).
    try:
        shortcut = _find_start_menu_shortcuts(key)
    except OSError as exc:
        shortcut = None
        logger.warning("Start menu scan failed: %s", exc)
    if shortcut is not None:
        try:
            os.startfile(shortcut)  # type: ignore[attr-defined]
        except OSError as exc:
            logger.warning("Failed to open shortcut '%s': %s", shortcut, exc)
            return False, f"I could not launch '{name}': {exc}"
        return True, f"Launching {shortcut.stem}."

    # Fall back to the installed-apps list (Store/UWP and others).
    matches = [
        (app_name, app_id)
        for app_name, app_id in _start_apps_list()
        if key in app_name.lower()
    ]
    if matches:
        pick = min(matches, key=lambda item: len(item[0]))
        display, app_id = pick
        try:
            os.startfile(f"shell:AppsFolder\\{app_id}")  # type: ignore[attr-defined]
        except OSError as exc:
            logger.warning("Failed to launch app id '%s': %s", app_id, exc)
            return False, f"I could not launch '{display}': {exc}"
        return True, f"Launching {display}."

    return False, (
        f"I could not find an app named '{name}' on this computer. "
        f"Apps I can open include: {_format_start_apps_fallback()}"
    )


def open_file(path: str) -> tuple[bool, str]:
    if not path or not isinstance(path, str):
        return False, "Please provide a file or folder path."
    target = Path(os.path.expanduser(path)).resolve()
    home = Path.home().resolve()
    if not target.exists():
        return False, f"I could not find '{path}'."
    if home not in target.parents and target != home:
        return False, "That path is outside your user profile, so I cannot open it."
    try:
        os.startfile(target)  # type: ignore[attr-defined]
    except OSError as exc:
        logger.warning("Failed to open '%s': %s", target, exc)
        return False, f"I could not open '{path}': {exc}"
    return True, f"Opened {target.name}."
