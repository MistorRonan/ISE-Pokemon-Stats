import time
import threading
from datetime import datetime
from flask import Flask, jsonify
from libLogging import setup_logger
import json
import Collectors
log = setup_logger("Main")

# --- RAII Cache Object with Context Management ---
class MetricsCache:
    def __init__(self, ttl_seconds: int = 30):
        self.ttl = ttl_seconds
        self._data = None
        self._last_fetched_unix = 0
        self._lock = threading.Lock()

    def __enter__(self):
        """Acquire the lock when entering the 'with' block."""
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release the lock when exiting, regardless of exceptions."""
        self._lock.release()

    def get_metrics(self):
        """
        Logic for refreshing data. Note: This should be called 
        inside the 'with' block to ensure thread safety.
        """
        now = time.time()
        
        if now - self._last_fetched_unix > self.ttl:
            log.info("Cache expired. Refreshing metrics...")
            try:
                self._data = Collectors.run_all()
                self._last_fetched_unix = now
                log.info("Data refreshed.")
            except Exception as e:
                log.error(f"Refresh failed: {e}")
                raise e
        
        return self._data, self._last_fetched_unix

# --- App Setup ---
app = Flask(__name__)
cache = MetricsCache(ttl_seconds=30)

with open("config.json") as file:
    config = json.load(file)

@app.route("/metrics", methods=["GET"])
def metrics():
    log.info("Received request for '/metrics'.")
    
    try:
        # RAII Implementation: Lock is acquired here
        with cache:
            data, data_read_unix = cache.get_metrics()
        # Lock is released here automatically
        
        # Format timestamps separately
        data_read_at = datetime.fromtimestamp(data_read_unix).isoformat()
        request_finished_at = datetime.now().isoformat()

        return jsonify({
            "status": "success",
            "metrics": data,
            "metadata": {
                "data_read_at": data_read_at,
                "request_finished_at": request_finished_at
            }
        })

    except Exception as exc:
        log.error(f"Endpoint error: {exc}")
        return jsonify({"error": str(exc)}), 500

if __name__ == "__main__":
    server_cfg = config.get("server", {})
    app.run(
        host=server_cfg.get("host", "0.0.0.0"),
        port=int(server_cfg.get("port", 8000)),
        debug=True
    )