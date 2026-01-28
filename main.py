from flask import Flask, jsonify
import json
import Collectors


# --- Color-coded console logging ---
class Colors:
    RESET = "\033[0m"
    INFO = "\033[94m"     # Blue
    SUCCESS = "\033[92m"  # Green
    WARNING = "\033[93m"  # Yellow
    ERROR = "\033[91m"    # Red


def log_info(message: str) -> None:
    print(f"{Colors.INFO}[INFO]{Colors.RESET} {message}")


def log_success(message: str) -> None:
    print(f"{Colors.SUCCESS}[OK]{Colors.RESET} {message}")


def log_error(message: str) -> None:
    print(f"{Colors.ERROR}[ERROR]{Colors.RESET} {message}")


with open("config.json") as file:
    config = json.load(file)

app = Flask(__name__)

# Simple example payload
string = "Hello world"

try:
    collectors_result = Collectors.run_all()
    log_success("Collectors ran successfully.")
    log_info(f"Collectors result: {collectors_result}")
except Exception as exc:  # Basic error logging
    log_error(f"Collectors failed: {exc}")


@app.route("/", methods=["GET"])
def home():
    log_info("Received request for '/' endpoint.")
    return jsonify(string)


@app.route("/metrics", methods=["GET"])
def metrics():
    """
    Returns the JSON output of Collectors.run_all().
    """
    log_info("Received request for '/metrics' endpoint.")
    try:
        result = Collectors.run_all()
        log_success("Collectors.run_all() executed for /metrics.")
        return jsonify(result)
    except Exception as exc:
        log_error(f"Collectors.run_all() failed for /metrics: {exc}")
        return jsonify({"error": "Failed to collect metrics"}), 500


if __name__ == "__main__":
    # Read host/port from config with safe defaults
    server_cfg = config.get("server", {})
    host = server_cfg.get("host", "0.0.0.0")
    port = int(server_cfg.get("port", 8000))

    log_info(f"Starting Flask server on {host}:{port}")
    app.run(host=host, port=port, debug=True)
