#!/usr/bin/env python3
"""
server.py

Thin entry point for the API servers.

Usage:
    python server.py ingest   — run the ingest API (receives snapshots from agents)
    python server.py read     — run the read API (serves data to the frontend)
    python server.py both     — run both APIs concurrently in separate threads

Each API runs on its own configured port (config.ingest_api.port and
config.read_api.port). Running both from this entry point is convenient
for development — in production you would typically run them as separate
processes on separate machines.
"""

import sys
import logging
import threading

logging.basicConfig(level=logging.INFO)

SERVERS = {
    'ingest': None,
    'read':   None,
}


def _import_servers():
    """Defer imports until after sys.path is set up by the API modules themselves."""
    from api.ingest_api import IngestAPI
    from api.read_api import ReadAPI
    SERVERS['ingest'] = IngestAPI
    SERVERS['read']   = ReadAPI


def _run_in_thread(server_class):
    """Start a server in a background thread. Used when running both concurrently."""
    t = threading.Thread(
        target=lambda: server_class().run(),
        name=server_class.__name__,
        daemon=True
    )
    t.start()
    return t


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ('ingest', 'read', 'both'):
        print("Usage: python server.py [ingest | read | both]")
        return 1

    _import_servers()
    mode = sys.argv[1]

    if mode == 'ingest':
        return SERVERS['ingest']().run()

    elif mode == 'read':
        return SERVERS['read']().run()

    elif mode == 'both':
        # Run ingest in a background thread, read in the main thread
        # (Flask needs the main thread for signal handling in debug mode)
        ingest_thread = _run_in_thread(SERVERS['ingest'])
        logging.getLogger(__name__).info(
            "IngestAPI started in background thread, starting ReadAPI in main thread"
        )
        try:
            return SERVERS['read']().run()
        except KeyboardInterrupt:
            logging.getLogger(__name__).info("Server shutting down")
            return 0


if __name__ == "__main__":
    sys.exit(main())
