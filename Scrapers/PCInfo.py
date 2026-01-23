import psutil

def collect(param=""):
    return get_pc_usage_map()

def get_pc_usage_map():
    # Capture snapshots
    # We use a small interval (0.1) so cpu_percent doesn't return 0.0 on a single run
    cpu_usage = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    # Create the flattened map
    usage_map = {
        # CPU data
        "cpu-usage": cpu_usage,
        "cpu-cores": psutil.cpu_count(),

        # Memory data
        "memory-usage": memory.percent,
        "memory-used-gb": round(memory.used / (1024 ** 3), 2),
        "memory-total-gb": round(memory.total / (1024 ** 3), 2),
        "memory-available-gb": round(memory.available / (1024 ** 3), 2),

        # Disk data
        "disk-usage": disk.percent,
        "disk-free-gb": disk.free // (1024 ** 3),
        "disk-total-gb": disk.total // (1024 ** 3)
    }

    return usage_map


