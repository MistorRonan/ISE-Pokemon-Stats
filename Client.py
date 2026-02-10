import socket
import time


# Color codes for terminal output
class Colors:
    RESET = '\033[0m'
    INFO = '\033[94m'      # Blue
    SUCCESS = '\033[92m'   # Green
    WARNING = '\033[93m'   # Yellow
    ERROR = '\033[91m'     # Red
    DEBUG = '\033[96m'     # Cyan


def log_info(message):
    """Log an info message in blue"""
    print(f"{Colors.INFO}[INFO]{Colors.RESET} {message}")


def log_success(message):
    """Log a success message in green"""
    print(f"{Colors.SUCCESS}[SUCCESS]{Colors.RESET} {message}")


def log_warning(message):
    """Log a warning message in yellow"""
    print(f"{Colors.WARNING}[WARNING]{Colors.RESET} {message}")


def log_error(message):
    """Log an error message in red"""
    print(f"{Colors.ERROR}[ERROR]{Colors.RESET} {message}")


def log_debug(message):
    """Log a debug message in cyan"""
    print(f"{Colors.DEBUG}[DEBUG]{Colors.RESET} {message}")


# --- APPLICATION PROTOCOL ---
def encode_message(payload):
    """
    Encode a message with protocol format: [4-char length header][payload]
    Header is zero-padded (e.g., "0060" for 60 characters)
    """
    length = len(payload)
    header = f"{length:04d}"  # 4-digit zero-padded length
    return header + payload


def start_client(port: int = 54545, server_ip: str = '127.0.0.1'):
    # --- CONFIGURATION ---
    # '127.0.0.1' is the 'loopback' address, referring to your own machine.
    # The PORT must match the server's listening port.
    SERVER_IP = server_ip
    SERVER_PORT = port

    # --- SOCKET CREATION ---
    # We create the same type of socket as the server (IPv4, TCP).
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:

        # --- THE CONNECTION (The Handshake) ---
        # Unlike the server which 'Binds' and 'Listens', the client 'Connects'.
        # This triggers the TCP Three-Way Handshake.
        try:
            client_socket.connect((SERVER_IP, SERVER_PORT))
            log_success(f"Connected to server at {SERVER_IP}:{SERVER_PORT}")
        except ConnectionRefusedError:
            log_error("Could not connect. Is the server.py running?")
            return

        # --- LOGGING SOCKET INFO ---
        # getsockname(): Returns the LOCAL IP and Port assigned to this script by the OS.
        # getpeername(): Returns the REMOTE (Server) IP and Port we are talking to.
        local_ip, local_port = client_socket.getsockname()
        remote_ip, remote_port = client_socket.getpeername()

        log_info(f"Local Socket (Me): {local_ip}:{local_port}")
        log_info(f"Remote Socket (Server): {remote_ip}:{remote_port}")

        # --- DATA TRANSMISSION LOOP ---
        log_info("Starting data transmission...")

        # Requirement: Send 50x 60-character strings
        for i in range(1, 51):
            # Create a string exactly 60 characters long
            # Example: "Message 01: ------------------------------------------------"
            payload = f"Message {i:02}: " + ("-" * 48)
            
            # Encode with protocol: [4-char header][payload]
            encoded_message = encode_message(payload)
            
            # THEORY: TCP is a 'Stream' protocol, not a 'Packet' protocol.
            # We must encode the string into bytes before sending.
            client_socket.sendall(encoded_message.encode('utf-8'))
            log_debug(f"Sent: {encoded_message[:20]}... (length: {len(payload)})")

            # Small sleep to prevent 'clumping' in the console,
            # making it easier for you to watch the server log it.
            time.sleep(0.05)

        log_success("All 50 messages sent successfully.")

        # --- EXIT STRATEGY ---
        # Waiting for keypress keeps the socket open so you can inspect
        # the connection state before the program terminates.
        input("Press Enter to close the connection and exit...")


if __name__ == "__main__":
    start_client()