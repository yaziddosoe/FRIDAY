import logging
import subprocess

logger = logging.getLogger("bridge.notify")


def notify(title: str, message: str) -> bool:
    """Show an unobtrusive Windows toast using a dependency-free PowerShell NotifyIcon."""
    script = _script(title, message)
    try:
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
            timeout=15,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except subprocess.TimeoutExpired:
        logger.warning("Toast for '%s' timed out", title)
        return False
    except Exception as exc:
        logger.warning("Failed to show toast '%s': %s", title, exc)
        return False


def _script(title: str, message: str) -> str:
    esc_title = title.replace("'", "''")
    esc_message = message.replace("'", "''")
    return (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "Add-Type -AssemblyName System.Drawing;"
        "$n = New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon = [System.Drawing.SystemIcons]::Information;"
        f"$n.BalloonTipTitle = '{esc_title}';"
        f"$n.BalloonTipText = '{esc_message}';"
        "$n.Visible = $true;"
        "$n.ShowBalloonTip(5000);"
        "Start-Sleep -Seconds 6;"
        "$n.Dispose()"
    )
