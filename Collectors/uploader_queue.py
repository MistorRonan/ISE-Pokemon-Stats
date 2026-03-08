"""
collectors/uploader_queue.py

A thread-safe queue that buffers serialized snapshots and uploads them to
the ingest API in the background, retrying failed attempts with exponential
backoff.

This decouples collection from transmission — collectors never block waiting
for the network, and snapshots are never silently dropped if the ingest API
is temporarily unavailable.

                collectors
                    │
                    ▼
            ┌───────────────┐
            │ UploaderQueue │  ← in-memory buffer
            └───────┬───────┘
                    │  background thread retries until success
                    ▼
              ingest_api.py
                    │
                    ▼
                   DB

Usage:
    queue = UploaderQueue(ingest_url="http://localhost:5001/aggregator_snapshots")
    queue.start()
    queue.enqueue(raw_json)   # non-blocking, returns immediately
"""

import logging
import queue
import requests
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

_logger = logging.getLogger(__name__)

# Maximum number of snapshots to hold in memory before dropping the oldest.
# Prevents unbounded memory growth if the ingest API is down for a long time.
MAX_QUEUE_SIZE = 500

# Retry backoff settings
INITIAL_RETRY_DELAY = 5    # seconds before first retry
MAX_RETRY_DELAY     = 300  # seconds — cap so retries don't stretch to infinity
BACKOFF_FACTOR      = 2    # multiply delay by this after each failed attempt


@dataclass
class _QueueItem:
    """A single snapshot waiting to be uploaded, with retry metadata."""

    raw_json:    str               # serialized DTO_Aggregator JSON
    enqueued_at: datetime          # when this item entered the queue
    attempts:    int   = 0         # how many upload attempts have been made
    next_retry:  float = field(    # earliest time (epoch) to attempt next upload
        default_factory=lambda: time.time()
    )


class UploaderQueue:
    """
    Buffers snapshots in memory and uploads them to the ingest API in a
    dedicated background thread. Failed uploads are retried with exponential
    backoff. The queue is bounded to prevent memory exhaustion.
    """

    def __init__(self, ingest_url: str):
        """
        Args:
            ingest_url: Full URL of the ingest API snapshot endpoint,
                        e.g. "http://localhost:5001/aggregator_snapshots"
        """
        self._ingest_url  = ingest_url
        self._queue       = queue.Queue(maxsize=MAX_QUEUE_SIZE)
        self._retry_items = []          # items waiting for their next retry
        self._lock        = threading.Lock()
        self._thread      = threading.Thread(
            target=self._upload_loop,
            name="UploaderQueue",
            daemon=True             # exits automatically when main process ends
        )
        self._running = False

    def start(self):
        """Start the background upload thread. Must be called before enqueue()."""
        self._running = True
        self._thread.start()
        _logger.info("UploaderQueue started, posting to %s", self._ingest_url)

    def stop(self):
        """Signal the background thread to stop after finishing its current item."""
        self._running = False
        _logger.info("UploaderQueue stopping")

    def enqueue(self, raw_json: str):
        """Add a serialized snapshot to the upload queue.

        Non-blocking — returns immediately regardless of queue state.
        If the queue is full, the oldest item is dropped to make room and a
        warning is logged, ensuring recent data is always prioritised.

        Args:
            raw_json: Serialized DTO_Aggregator JSON string from build_snapshot()
        """
        item = _QueueItem(raw_json=raw_json, enqueued_at=datetime.utcnow())
        try:
            self._queue.put_nowait(item)
            _logger.debug("Snapshot enqueued (queue size: ~%d)", self._queue.qsize())
        except queue.Full:
            # Drop the oldest item to make room for the new one
            try:
                dropped = self._queue.get_nowait()
                _logger.warning(
                    "Queue full (%d items) — dropped snapshot enqueued at %s",
                    MAX_QUEUE_SIZE, dropped.enqueued_at.isoformat()
                )
            except queue.Empty:
                pass
            self._queue.put_nowait(item)

    def qsize(self) -> int:
        """Return the approximate number of items currently in the queue.
        Includes both fresh items and items waiting to retry.
        """
        return self._queue.qsize() + len(self._retry_items)

    def _upload_loop(self):
        """Background thread — continuously drains the queue and handles retries.

        On each iteration:
          1. Re-enqueue any retry items whose next_retry time has passed
          2. Pull the next item from the queue (blocking with timeout)
          3. Attempt to POST it to the ingest API
          4. On success: discard the item
          5. On failure: calculate next retry time and park it in _retry_items
        """
        while self._running:
            self._requeue_ready_retries()

            try:
                item = self._queue.get(timeout=1)
            except queue.Empty:
                continue

            self._attempt_upload(item)

    def _requeue_ready_retries(self):
        """Move any retry items whose wait period has elapsed back into the
        main queue so they get picked up on the next loop iteration.
        """
        now = time.time()
        with self._lock:
            ready    = [i for i in self._retry_items if i.next_retry <= now]
            deferred = [i for i in self._retry_items if i.next_retry >  now]
            self._retry_items = deferred

        for item in ready:
            _logger.debug(
                "Re-queuing snapshot for retry (attempt %d, enqueued %s)",
                item.attempts, item.enqueued_at.isoformat()
            )
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                _logger.warning("Queue full during retry re-queue, snapshot dropped")

    def _attempt_upload(self, item: _QueueItem):
        """Try to POST a single snapshot to the ingest API.

        On success the item is discarded. On failure the retry delay is
        calculated using exponential backoff and the item is parked in
        _retry_items to be re-queued later.

        Args:
            item: The _QueueItem to attempt uploading
        """
        item.attempts += 1
        try:
            response = requests.post(
                self._ingest_url,
                data=item.raw_json,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            if response.status_code == 201:
                age = (datetime.utcnow() - item.enqueued_at).total_seconds()
                _logger.info(
                    "Snapshot uploaded successfully (attempt %d, age %.1fs)",
                    item.attempts, age
                )
                # Item is discarded — do not add to retry list
                return

            _logger.error(
                "Ingest API returned %d on attempt %d: %s",
                response.status_code, item.attempts, response.text
            )

        except requests.exceptions.RequestException as e:
            _logger.warning(
                "Upload attempt %d failed (network error): %s",
                item.attempts, str(e)
            )

        # Schedule retry with exponential backoff, capped at MAX_RETRY_DELAY
        delay          = min(INITIAL_RETRY_DELAY * (BACKOFF_FACTOR ** (item.attempts - 1)),
                             MAX_RETRY_DELAY)
        item.next_retry = time.time() + delay
        _logger.info(
            "Snapshot scheduled for retry in %.0fs (attempt %d)",
            delay, item.attempts
        )
        with self._lock:
            self._retry_items.append(item)
