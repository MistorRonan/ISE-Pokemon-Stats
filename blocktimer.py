import time
from datetime import datetime

class BlockTimer:
    """RAII-style context manager for performance timing."""
    
    def __init__(self, label="Operation"):
        self.label = label
    
    def __enter__(self):
        self.start_perf = time.perf_counter()
        self.start_time = datetime.utcnow()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_perf = time.perf_counter()
        self.end_time = datetime.utcnow()
        self.elapsed = self.end_perf - self.start_perf
        return False