#!/usr/bin/env python3
"""
server.py

Entry point for the API servers.

Usage:
    python server.py ingest   — run the ingest API only
    python server.py read     — run the read API only
    python server.py both     — run both APIs concurrently (normal usage)

When running both, a threading.Event is created here and passed into both
APIs. IngestAPI sets it after every successful snapshot write; ReadAPI's SSE
generator waits on it and pushes to connected frontend clients the moment it
fires — no polling, no delay.

Running as separate processes (python server.py ingest / python server.py read)
loses the shared Event, so the SSE generator falls back to polling SystemState
in the database. This is fine for deployments where the two APIs need to be
managed separately, but for normal usage 'both' is recommended.
"""

import sys
import logging
import threading

logging.basicConfig(level=logging.INFO)

_logger = logging.getLogger(__name__)


def _import_apis():
    from api.ingest_api import IngestAPI
    from api.read_api import ReadAPI
    return IngestAPI, ReadAPI


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ('ingest', 'read', 'both'):
        print("Usage: python server.py [ingest | read | both]")
        return 1

    IngestAPI, ReadAPI = _import_apis()
    mode = sys.argv[1]

    if mode == 'ingest':
        return IngestAPI().run()

    elif mode == 'read':
        return ReadAPI().run()

    elif mode == 'both':
        # Create the shared event that connects the two APIs.
        # IngestAPI.set_update_event() and ReadAPI.set_update_event() both
        # receive this same object so they share it in memory.
        update_event = threading.Event()

        ingest = IngestAPI()
        ingest.set_update_event(update_event)

        read = ReadAPI()
        read.set_update_event(update_event)

        # Run ingest in a background thread, read in the main thread.
        # Flask needs the main thread for signal handling in debug mode.
        ingest_thread = threading.Thread(
            target=ingest.run,
            name='IngestAPI',
            daemon=True
        )
        ingest_thread.start()
        _logger.info("IngestAPI started in background thread")

        try:
            return read.run()
        except KeyboardInterrupt:
            _logger.info("Server shutting down")
            return 0


if __name__ == "__main__":
    sys.exit(main())