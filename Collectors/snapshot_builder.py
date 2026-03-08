"""
collectors/snapshot_builder.py

Utility functions for DTO packaging and machine identity.
Used by collectors/__init__.py to convert raw metric dicts into serialized
DTO_Aggregator JSON ready to POST to the ingest API.

Nothing in here is collector-specific — it works with any flat dict of
metric name → value pairs regardless of where the data came from.
"""

import uuid
import logging
from uuid import UUID
from dataclasses import dataclass
from dataclasses_json import dataclass_json
from collectors.metrics_datamodel import (
    DTO_Aggregator, DTO_DataSnapshot, DTO_Device, DTO_Metric
)

try:
    import winreg
    _WINREG_AVAILABLE = True
except ImportError:
    _WINREG_AVAILABLE = False

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Machine identity
# ---------------------------------------------------------------------------

def get_machine_guid() -> UUID:
    """Return a stable UUID for the current machine.

    Priority:
      1. Windows registry MachineGuid   (most stable on Windows)
      2. /etc/machine-id                (Linux systemd)
      3. /var/lib/dbus/machine-id       (older Linux)
      4. Random UUID                    (last resort — not stable across reboots)
    """
    if _WINREG_AVAILABLE:
        try:
            reg_path = r"SOFTWARE\Microsoft\Cryptography"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path,
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                return UUID(winreg.QueryValueEx(key, "MachineGuid")[0])
        except OSError:
            _logger.warning("Could not read Windows MachineGuid from registry")

    for path in ('/etc/machine-id', '/var/lib/dbus/machine-id'):
        try:
            with open(path) as f:
                return UUID(f.read().strip())
        except (FileNotFoundError, ValueError):
            continue

    fallback = uuid.uuid4()
    _logger.warning(
        "Could not determine a stable machine GUID; using random UUID %s. "
        "This machine will appear as a new aggregator after each restart.",
        fallback
    )
    return fallback


# ---------------------------------------------------------------------------
# DTO packaging
# ---------------------------------------------------------------------------

@dataclass_json
@dataclass
class _AggregatorPackage(DTO_Aggregator):
    """Internal packaging class — not used directly outside this module."""

    def __init__(self, aggregator_name: str, aggregator_guid: UUID):
        self.name    = aggregator_name
        self.guid    = aggregator_guid
        self.devices = []

    def _ensure_device(self, name: str) -> DTO_Device:
        for device in self.devices:
            if device.name == name:
                return device
        new_device = DTO_Device(name=name)
        self.devices.append(new_device)
        return new_device

    def _new_snapshot(self, device: DTO_Device) -> DTO_DataSnapshot:
        snapshot = DTO_DataSnapshot()
        device.data_snapshots.append(snapshot)
        return snapshot


def build_snapshot(aggregator_name: str,
                   aggregator_guid: UUID,
                   device_metrics: dict[str, dict]) -> str:
    """Package metrics into a serialized DTO_Aggregator JSON string.

    Args:
        aggregator_name:  Name of the aggregator (e.g. machine hostname)
        aggregator_guid:  UUID identifying the aggregator
        device_metrics:   Dict mapping device name → flat metrics dict
                          Single device:  {"SavageLaptop": {"cpu-usage": 14.2, ...}}
                          Multi device:   {"gen9ou": {"Garchomp": 12, ...},
                                           "gen8ou": {"Toxapex": 9, ...}}

    Returns:
        Serialized JSON string of the fully packaged DTO_Aggregator.
    """
    package = _AggregatorPackage(aggregator_name, aggregator_guid)

    for device_name, metrics in device_metrics.items():
        device   = package._ensure_device(device_name)
        snapshot = package._new_snapshot(device)
        for metric_name, metric_value in metrics.items():
            snapshot.metrics.append(
                DTO_Metric(name=metric_name, value=float(metric_value))
            )

    return package.to_json()
