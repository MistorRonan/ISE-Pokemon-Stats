import sys
import datetime

try:
    import psutil
except ImportError:
    print("Error: 'psutil' library not found. Install it via 'pip install psutil'.")
    sys.exit(1)


def get_pc_usage_map():
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
                "disk-free-gb": disk.free // (1024 ** 3),
                "disk-fstype": psutil.disk_partitions()[0].fstype  # e.g., NTFS or ext4
            })
        except Exception as e:
            usage_map["disk-error"] = str(e)

        # --- 3. SYSTEM UP-TIME & NETWORK ---
        boot_time_timestamp = psutil.boot_time()
        bt = datetime.datetime.fromtimestamp(boot_time_timestamp)

        # Network total bytes (Accumulated since boot, not current speed)
        net_io = psutil.net_io_counters()

        usage_map.update({
            "boot-time": bt.strftime("%Y-%m-%d %H:%M:%S"),
            "net-total-sent-mb": round(net_io.bytes_sent / (1024 ** 2), 2),
            "net-total-recv-mb": round(net_io.bytes_recv / (1024 ** 2), 2),
            "users-logged-in": len(psutil.users())
        })

    except Exception as e:
        return {"error": f"Failed to collect metrics: {str(e)}"}

    return usage_map


def collect(param=""):
    return get_pc_usage_map()


if __name__ == "__main__":
    import pprint

    pprint.pprint(collect())