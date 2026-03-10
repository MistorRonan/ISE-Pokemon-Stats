"""
PCInfo.py

Pure hardware metric collector. Samples CPU, memory, disk, and process
stats from the local machine and returns them as a flat dict.

Collector interface (read by collectors/__init__.py):
    collect(param="")  -> dict   flat metric readings
    aggregator_name    -> str    hostname of this machine
    aggregator_guid    -> UUID   stable hardware identity
    device_name        -> str    name of the device to store metrics under
    interval           -> int    seconds between collections
    multi_device       -> bool   False — collect() returns a single flat dict
"""

import sys
import platform
import psutil
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from collectors.snapshot_builder import get_machine_guid

_config = Config(__file__)

# ---------------------------------------------------------------------------
# Collector identity — read by collectors/__init__.py for DTO packaging
# ---------------------------------------------------------------------------

aggregator_name: str  = platform.node()
aggregator_guid       = get_machine_guid()
device_name: str      = platform.node()
interval: int         = _config.client.interval
multi_device: bool    = False  # collect() returns a single flat dict


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def get_pc_usage_map() -> dict:
    usage_map = {}

    try:
        # --- 1. THREAD & PROCESS COUNTS ---
        # Summing threads across all active processes
        total_threads = 0
        process_count = 0
        for proc in psutil.process_iter(['num_threads']):
            try:
                total_threads += proc.info['num_threads'] or 0
                process_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass  # Process closed or restricted during scan

        usage_map.update({
            "system-thread-count": total_threads,
            "system-process-count": process_count
        })

        # --- 2. DISK & PARTITION DATA ---
        try:
            path = "C:\\" if sys.platform == "win32" else "/"
            disk = psutil.disk_usage(path)
            usage_map.update({
                "disk-total-gb": disk.total // (1024 ** 3),
                "disk-free-gb": disk.free // (1024 ** 3)
            })
        except Exception as e:
            usage_map["disk-error"] = str(e)

        # --- 3. SYSTEM UP-TIME & NETWORK ---
        boot_time_timestamp = psutil.boot_time()
        bt = datetime.datetime.fromtimestamp(boot_time_timestamp)

        # Network total bytes (Accumulated since boot, not current speed)
        net_io = psutil.net_io_counters()

        usage_map.update({
            "boot-time-epoch": psutil.boot_time(),
            "net-total-sent-mb": round(net_io.bytes_sent / (1024 ** 2), 2),
            "net-total-recv-mb": round(net_io.bytes_recv / (1024 ** 2), 2),
            "users-logged-in": len(psutil.users())
        })

    except Exception as e:
        return {"error": f"Failed to collect metrics: {str(e)}"}

    return usage_map


def collect(param="") -> dict:
    """Return a flat dict of current hardware metrics."""
    return get_pc_usage_map()


if __name__ == "__main__":
    import json
    print(json.dumps(collect(), indent=2))
