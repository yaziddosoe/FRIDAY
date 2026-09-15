import platform
import socket
from datetime import datetime
from pathlib import Path

import psutil

_DRIVE = Path.home().anchor or "C:\\"


def get_status() -> dict[str, object]:
    cpu = psutil.cpu_percent(interval=0.4)
    vm = psutil.virtual_memory()
    battery = psutil.sensors_battery()
    disk = psutil.disk_usage(_DRIVE)
    boot = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "cpu_percent": cpu,
        "memory_total_gb": round(vm.total / (1024**3), 1),
        "memory_used_gb": round(vm.used / (1024**3), 1),
        "memory_percent": vm.percent,
        "battery_percent": round(battery.percent, 1) if battery else None,
        "battery_charging": bool(battery.power_plugged) if battery else None,
        "disk_free_gb": round(disk.free / (1024**3), 1),
        "disk_total_gb": round(disk.total / (1024**3), 1),
        "hostname": socket.gethostname(),
        "booted_at": boot,
        "os": platform.system(),
    }
