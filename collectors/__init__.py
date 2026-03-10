"""
collectors/__init__.py

Auto-discovers all collector modules in this package and provides both
a one-shot run_all() and a continuous agent loop run_agent().

A valid collector module must expose:
    collect(param="")   callable  returns a dict of metric name → value
    aggregator_name     str       name of the aggregator this data belongs to
    aggregator_guid     UUID      stable identity for the aggregator
    interval            int       seconds between collections (default: 60)
    multi_device        bool      if True, collect() is called once per format/device.
                                  Each format becomes its own staggered thread.
                                  If False (default), collect() is called once and
                                  stored under device_name.
    get_devices()       callable  optional — if defined, called instead of
                                  config.pokemon.formats to get the device list.
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

def _package(collector: dict) -> str | None:
    """Package a single-device collector's result into a snapshot JSON string.

    Multi-device collectors are expanded into individual single-device entries
    before this is called (see run_agent), so this function always handles
    exactly one device at a time.
    """
    result = collector["func"](collector.get("param", ""))
    if not result:
        _logger.warning("Collector '%s' returned no data for device '%s'",
                        collector["source"], collector.get("device_name", ""))
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
    """Thread target — runs a single collector device on its own interval forever.

    Multi-device collectors are pre-expanded into one entry per device before
    this is called, so each thread always owns exactly one device. An optional
    startup delay staggers multi-device collectors evenly across their interval
    so they don't all fire simultaneously.

    Args:
        collector:    Collector descriptor dict (always single-device at this point)
        upload_queue: Shared UploaderQueue instance to hand snapshots to
    """
    name      = collector["source"]
    device    = collector.get("device_name", "")
    interval  = collector["interval"]
    delay     = collector.get("delay", 0)

    _logger.info("Starting collector '%s' device '%s' (startup delay %ds, interval %ds)",
                 name, device, delay, interval)

    # Stagger startup — each format fires at a different offset within the hour
    if delay > 0:
        time.sleep(delay)

    # Fire immediately after delay, then once per interval
    last_run = datetime.now() - timedelta(seconds=interval)

    while True:
        time.sleep(0.5)
        if (datetime.now() - last_run).total_seconds() >= interval:
            last_run = datetime.now()
            try:
                raw_json = _package(collector)
                if raw_json is None:
                    continue
                upload_queue.enqueue(raw_json)
                _logger.debug("Collector '%s' device '%s' snapshot enqueued", name, device)
            except Exception as e:
                _logger.exception("Collector '%s' device '%s' failed during packaging: %s",
                                  name, device, str(e))


def _expand_collector(collector: dict, config: Config) -> list[dict]:
    """Expand a multi_device collector into one entry per device, staggered.

    For single-device collectors, returns a list with the original entry
    (plus param="" and delay=0 for consistency).

    For multi-device collectors, fetches the device list via get_devices()
    if available, otherwise falls back to config.pokemon.formats. Each device
    gets a startup delay so they fire evenly spread across the interval rather
    than all at once.

    Args:
        collector: Collector descriptor dict from all_collectors
        config:    Loaded Config instance

    Returns:
        List of expanded single-device collector dicts
    """
    if not collector["multi_device"]:
        return [{**collector, "param": "", "delay": 0}]

    mod = importlib.import_module(f"collectors.{collector['source']}")
    if hasattr(mod, 'get_devices'):
        devices = mod.get_devices()
    else:
        devices = config.pokemon.formats if hasattr(config, 'pokemon') else []

    if not devices:
        _logger.warning("Collector '%s' is multi_device but has no devices — skipping",
                        collector["source"])
        return []

    n = len(devices)
    expanded = []
    for i, device_name in enumerate(devices):
        # Spread startup delays evenly across the interval
        delay = i * (collector["interval"] // n)
        expanded.append({
            **collector,
            "multi_device": False,
            "device_name":  device_name,
            "param":        device_name,
            "delay":        delay,
        })

    return expanded


def run_agent(collector_names: list = None):
    """Start the uploader queue and each collector device in its own daemon thread,
    then block until the process is interrupted.

    Multi-device collectors (e.g. PokemonInfo, SupaInfo) are expanded into one
    thread per device before startup. Devices within the same collector are
    staggered evenly across the collector's interval so they don't all hit the
    external API at the same moment.

    A single UploaderQueue is shared across all threads. All snapshots flow
    through one background upload thread, maintaining ordering and avoiding
    multiple simultaneous connections to the ingest API.

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

    # Expand multi_device collectors into one entry per device
    expanded_targets = []
    for collector in targets:
        expanded_targets.extend(_expand_collector(collector, config))

    if not expanded_targets:
        raise ValueError("No collector devices found after expansion.")

    # Start the shared uploader queue before any collector threads
    upload_queue = UploaderQueue(ingest_url=ingest_url)
    upload_queue.start()

    # Start one thread per device
    threads = []
    for collector in expanded_targets:
        thread_name = f"{collector['source']}-{collector.get('device_name', '')}"
        t = threading.Thread(
            target=_collector_loop,
            args=(collector, upload_queue),
            name=thread_name,
            daemon=True
        )
        t.start()
        threads.append(t)

    _logger.info(
        "Agent running %d collector thread(s): %s",
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