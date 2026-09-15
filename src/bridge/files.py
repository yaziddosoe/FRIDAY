import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("bridge.files")

_SKIP_DIRS = {
    ".git",
    ".cache",
    "__pycache__",
    "node_modules",
    "$RECYCLE.BIN",
    "System Volume Information",
    ".venv",
    ".friday",
    "AppData",
}


def search_files(
    query: str,
    root: str | None = None,
    max_results: int = 15,
    max_depth: int = 4,
    time_budget: float = 1.5,
) -> list[str]:
    """Search filenames under ``root`` (default: the user's home folder).

    Returns absolute paths of matches, descending shallow-first up to
    ``max_depth``, skipping known noisy/build directories, and stopping as
    soon as ``time_budget`` seconds have elapsed so the voice agent never
    blocks too long.
    """
    if not query:
        return []
    home = Path.home().resolve()
    base = Path(os.path.expanduser(root or str(home))).resolve() if root else home
    if not base.exists() or not base.is_dir():
        return []
    lowered = query.lower()
    matches: list[str] = []
    deadline = time.monotonic() + time_budget

    def walk(path: Path, depth: int) -> None:
        if depth > max_depth or len(matches) >= max_results:
            return
        if time.monotonic() > deadline:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        dirs: list[Path] = []
        for entry in entries:
            if len(matches) >= max_results:
                break
            try:
                if entry.is_dir():
                    if entry.name in _SKIP_DIRS:
                        continue
                    if lowered in entry.name.lower():
                        matches.append(str(entry))
                    dirs.append(entry)
                elif lowered in entry.name.lower():
                    matches.append(str(entry))
            except OSError:
                continue
        if len(matches) >= max_results:
            return
        for directory in dirs:
            walk(directory, depth + 1)

    walk(base, 0)
    return matches[:max_results]
