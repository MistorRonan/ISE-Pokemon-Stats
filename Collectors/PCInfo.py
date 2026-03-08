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
    """Collect a snapshot of CPU, memory, disk, and process metrics from this
    machine and return them as a flat dict of metric-name → value pairs."""

    cpu_usage = psutil.cpu_percent(interval=0.1)
    memory    = psutil.virtual_memory()
    disk      = psutil.disk_usage('/')

    num_system_threads = 0
    num_processes      = 0
    for process in psutil.process_iter(['num_threads', 'name']):
        try:
            num_system_threads += process.num_threads()
            num_processes      += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return {
        # CPU
        "cpu-usage":           cpu_usage,
        "cpu-cores":           psutil.cpu_count(),

        # Memory
        "memory-usage":        memory.percent,
        "memory-used-gb":      round(memory.used  / (1024 ** 3), 2),
        "memory-total-gb":     round(memory.total / (1024 ** 3), 2),
        "memory-available-gb": round(memory.available / (1024 ** 3), 2),
        "used-ram-mb":         round(memory.used  / (1024 ** 2), 2),
        "total-ram-mb":        round(memory.total / (1024 ** 2), 2),

        # Disk
        "disk-usage":          disk.percent,
        "disk-free-gb":        disk.free  // (1024 ** 3),
        "disk-total-gb":       disk.total // (1024 ** 3),

        # Processes
        "num-system-threads":  num_system_threads,
        "num-processes":       num_processes,
    }


def collect(param="") -> dict:
    """Return a flat dict of current hardware metrics."""
    return get_pc_usage_map()


if __name__ == "__main__":
    import json
    print(json.dumps(collect(), indent=2))