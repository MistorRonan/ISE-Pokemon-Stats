"""
collectors/__init__.py

Auto-discovers all collector modules in this package and provides both
a one-shot run_all() and a continuous agent loop run_agent().

A valid collector module must expose:
    collect(param="")   callable  returns a dict of metric name → value
    aggregator_name     str       name of the aggregator this data belongs to
    aggregator_guid     UUID      stable identity for the aggregator
    interval            int       seconds between collections (default: 60)
    multi_device        bool      if True, collect() is called once per format
                                  in config.pokemon.formats, each becoming its
                                  own device. If False (default), collect() is
                                  called once and stored under device_name.
    device_name         str       device name for single-device collectors
                                  (only required when multi_device is False)

Any .py file in this folder with a callable collect() is picked up automatically.
No registration or changes to this file are needed when adding a new collector.
"""

import sys
import pkgutil
import importlib
import logging
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from collectors.snapshot_builder import build_snapshot
from collectors.uploader_queue import UploaderQueue

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auto-discovery
# ---------------------------------------------------------------------------

all_collectors = []

for _loader, _module_name, _is_pkg in pkgutil.iter_modules(__path__):
    _module = importlib.import_module(f".{_module_name}", package=__name__)

    if hasattr(_module, 'collect') and callable(_module.collect):
        all_collectors.append({
            "source":          _module_name,
            "func":            _module.collect,
            "interval":        getattr(_module, 'interval',        60),
            "aggregator_name": getattr(_module, 'aggregator_name', _module_name),
            "aggregator_guid": getattr(_module, 'aggregator_guid', None),
            "device_name":     getattr(_module, 'device_name',     _module_name),
            "multi_device":    getattr(_module, 'multi_device',    False),
        })
        _logger.debug("Discovered collector: %s", _module_name)


# ---------------------------------------------------------------------------
# Packaging helper
# ---------------------------------------------------------------------------

def _package(collector: dict, param="") -> str | None:
    """Call a collector's collect() and package the result into a serialized
    DTO_Aggregator JSON string using snapshot_builder.build_snapshot().

    Handles both single-device and multi-device collectors transparently.
    Returns None if no data was returned by the collector.
    """
    config = Config(__file__)

    if collector["multi_device"]:
        formats        = config.pokemon.formats if hasattr(config, 'pokemon') else []
        device_metrics = {}
        for format_name in formats:
            result = collector["func"](format_name)
            if result:
                device_metrics[format_name] = result
        if not device_metrics:
            _logger.warning("Collector '%s' returned no data for any format", collector["source"])
            return None
    else:
        result = collector["func"](param)
        if not result:
            _logger.warning("Collector '%s' returned no data", collector["source"])
            return None
        device_metrics = {collector["device_name"]: result}

    return build_snapshot(
        aggregator_name=collector["aggregator_name"],
        aggregator_guid=collector["aggregator_guid"],
        device_metrics=device_metrics
    )


# ---------------------------------------------------------------------------
# One-shot: run every collector once and return raw results
# ---------------------------------------------------------------------------

def run_all(param="") -> dict:
    """Execute every discovered collector once and return timestamped results.

    Does not use the uploader queue — results are returned directly to the
    caller rather than being posted to the ingest API. Useful for testing
    or one-off diagnostics.

    Returns:
        {
            "started_at":   ISO timestamp,
            "completed_at": ISO timestamp,
            "results": [
                {
                    "collector": module_name,
                    "timestamp": ISO timestamp,
                    "result":    raw dict from collect()
                },
                ...
            ]
        }
    """
    started_at = datetime.utcnow().isoformat() + "Z"
    results    = []

    for collector in all_collectors:
        result_time = datetime.utcnow().isoformat() + "Z"
        results.append({
            "collector": collector["source"],
            "timestamp": result_time,
            "result":    collector["func"](param),
        })

    return {
        "started_at":   started_at,
        "completed_at": datetime.utcnow().isoformat() + "Z",
        "results":      results,
    }


# ---------------------------------------------------------------------------
# Continuous agent: run each collector on its own interval in its own thread,
# handing snapshots to the UploaderQueue rather than posting directly
# ---------------------------------------------------------------------------

def _collector_loop(collector: dict, upload_queue: UploaderQueue):
    """Thread target — runs a single collector on its own interval forever.

    On each tick, packages the collected data and hands the resulting JSON
    to the UploaderQueue. The queue handles all network communication,
    retries, and backoff — this loop only concerns itself with collection.

    Args:
        collector:    Collector descriptor dict from all_collectors
        upload_queue: Shared UploaderQueue instance to hand snapshots to
    """
    name     = collector["source"]
    interval = collector["interval"]

    _logger.info("Starting collector '%s' with interval %ds", name, interval)
    last_run = datetime.now() - timedelta(seconds=interval)  # fire immediately

    while True:
        time.sleep(0.5)
        if (datetime.now() - last_run).total_seconds() >= interval:
            last_run = datetime.now()
            try:
                raw_json = _package(collector)
                if raw_json is None:
                    continue
                # Hand off to the queue — non-blocking, returns immediately
                upload_queue.enqueue(raw_json)
                _logger.debug("Collector '%s' snapshot enqueued", name)
            except Exception as e:
                # Log but don't crash the thread — retries on next interval
                _logger.exception("Collector '%s' failed during packaging: %s", name, str(e))


def run_agent(collector_names: list = None):
    """Start the uploader queue and each collector in its own daemon thread,
    then block until the process is interrupted.

    A single UploaderQueue is shared across all collectors. This means all
    snapshots from all collectors flow through one background upload thread,
    maintaining ordering and avoiding multiple simultaneous connections to
    the ingest API.

    Args:
        collector_names: Optional list of module names to run
                         e.g. ['PCInfo', 'PokemonInfo']
                         If None, all discovered collectors are run.
    """
    config     = Config(__file__)
    ingest_url = f"{config.ingest_api.host}:{config.ingest_api.port}/aggregator_snapshots"

    targets = [
        c for c in all_collectors
        if collector_names is None or c["source"] in collector_names
    ]

    if not targets:
        raise ValueError(
            "No matching collectors found. Available: "
            + str([c["source"] for c in all_collectors])
        )

    # Start the shared uploader queue before any collector threads
    upload_queue = UploaderQueue(ingest_url=ingest_url)
    upload_queue.start()

    # Start one collection thread per collector
    threads = []
    for collector in targets:
        t = threading.Thread(
            target=_collector_loop,
            args=(collector, upload_queue),
            name=collector["source"],
            daemon=True
        )
        t.start()
        threads.append(t)

    _logger.info(
        "Agent running %d collector(s): %s",
        len(threads),
        ", ".join(t.name for t in threads)
    )

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        upload_queue.stop()
        _logger.info("Agent shutting down")


if __name__ == "__main__":
    print(run_all())