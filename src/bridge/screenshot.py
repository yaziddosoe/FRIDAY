import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("bridge.screenshot")

_DEFAULT_DIR = Path(os.path.expanduser("~/.friday/screenshots"))
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run_powershell(script: str, timeout: int = 20) -> None:
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-WindowStyle",
            "Hidden",
            "-STA",
            "-Command",
            script,
        ],
        capture_output=True,
        timeout=timeout,
        check=False,
        creationflags=_CREATE_NO_WINDOW,
    )


def take_screenshot(
    out_dir: str | os.PathLike[str] | None = None,
) -> tuple[bool, str]:
    directory = Path(out_dir) if out_dir is not None else _DEFAULT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / (
        "screenshot-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".png"
    )
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "Add-Type -AssemblyName System.Drawing;"
        "$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
        "$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height;"
        "$g = [System.Drawing.Graphics]::FromImage($bmp);"
        "$g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size);"
        f"$bmp.Save('{output}', [System.Drawing.Imaging.ImageFormat]::Png);"
        "$g.Dispose();$bmp.Dispose()"
    )
    try:
        _run_powershell(script)
    except subprocess.TimeoutExpired:
        return False, "Taking the screenshot timed out."
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("Screenshot failed: %s", exc)
        return False, f"I could not take a screenshot: {exc}"
    if output.exists():
        return True, str(output)
    return False, "The screenshot could not be saved."
