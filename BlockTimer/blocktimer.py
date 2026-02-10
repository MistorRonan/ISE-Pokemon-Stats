import time
from datetime import datetime, timezone

class BlockTimer:
    """RAII-style context manager for performance timing."""

    def __init__(self, label="Operation", logger=None):
        self.label = label
        self.logger = logger
        self.elapsed = 0.0

    def __enter__(self):
        # perf_counter is best for intervals; now() is best for timestamps
        self.start_perf = time.perf_counter()
        self.start_time = datetime.now(timezone.utc)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_perf = time.perf_counter()
        self.elapsed = self.end_perf - self.start_perf

        # If a logger was provided, use it!
        message = f"{self.label} completed in {self.elapsed:.4f} seconds"
        if self.logger:
            self.logger.info(message)
        else:
            print(message)

        return False  # Don't suppress exceptions