import socket


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
def decode_message(data_buffer):
    """
    Decode a message from protocol format: [4-char length header][payload]
    Returns: (payload, remaining_buffer) or (None, buffer) if incomplete
    """
    if len(data_buffer) < 4:
        return None, data_buffer  # Not enough data for header
    
    # Extract 4-character header (length)
    header = data_buffer[:4]
    try:
        payload_length = int(header)
    except ValueError:
        return None, ""  # Invalid header
    
    # Check if we have the full payload
    if len(data_buffer) < 4 + payload_length:
        return None, data_buffer  # Not enough data for payload
    
    # Extract payload
    payload = data_buffer[4:4 + payload_length]
    remaining = data_buffer[4 + payload_length:]
    
    return payload, remaining

def is_port_in_use(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


def start_server(port: int = 54545):
    # --- CONFIGURATION ---
    # '0.0.0.0' is a special IPv4 address that tells the server to listen
    # to every available network interface (WiFi, Ethernet, and Localhost).
    HOST = '0.0.0.0'
    PORT = port

    # --- SOCKET CREATION ---
    # socket.AF_INET: Specifies the IPv4 protocol family.
    # socket.SOCK_STREAM: Specifies TCP (Transmission Control Protocol).
    # TCP is 'connection-oriented', meaning it ensures data arrives intact and in order.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:

        # This bypasses the 'Time Wait' state of a socket, allowing you to
        # restart the server immediately on the same port without OS delays.
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # BINDING: This 'claims' the port on your operating system.
        # Only one application can bind to a specific port at a time.
        server_socket.bind((HOST, PORT))

        # LISTENING: The server enters 'passive' mode, waiting for a client
        # to initiate a "Three-Way Handshake" (SYN, SYN-ACK, ACK).
        log_info(f"Server is now in LISTENING state on port: {PORT}")
        server_socket.listen()

        # --- THE MAIN ACCEPTANCE LOOP ---
        # This loop allows the server to stay alive forever.
        while True:
            # ACCEPT: This is a 'blocking' call. The code pauses here until
            # a client attempts to connect. It then returns a NEW socket
            # object (conn) dedicated specifically to that client.
            conn, addr = server_socket.accept()

            with conn:
                # 'addr' contains the IP and Port of the machine connecting to us.
                log_success(f"Connection Established! Client Address: {addr}")

                # --- THE DATA READING LOOP ---
                # Buffer to accumulate data (TCP is stream-based, messages may be fragmented)
                data_buffer = ""
                
                while True:
                    # RECV: We pull 1024 bytes of data from the network buffer.
                    data = conn.recv(1024)

                    # THEORY: In TCP, an empty byte string (b'') is the universal
                    # signal that the client has initiated a 'Graceful Shutdown'.
                    if not data:
                        log_warning(f"Client {addr} closed the connection.")
                        break

                    # Add received data to buffer
                    data_buffer += data.decode('utf-8', errors='ignore')
                    
                    # Process complete messages from buffer
                    while True:
                        payload, data_buffer = decode_message(data_buffer)
                        if payload is None:
                            break  # Incomplete message, wait for more data
                        
                        log_debug(f"Data Received: {payload}")


if __name__ == "__main__":
    try:
        start_server()
    except KeyboardInterrupt:
        # Allows for a clean exit when you press Ctrl+C
        log_warning("\nServer shutting down...")