"""
aggregators/aggregator_client.py

Packages locally collected metrics into the DTO hierarchy expected by the
server's POST /aggregator_snapshots endpoint.

Responsibilities:
  - Identify this machine with a stable GUID and hostname
  - Call PCInfo.collect() to get raw hardware readings
  - Wrap those readings into DTO_Aggregator / DTO_Device / DTO_DataSnapshot /
    DTO_Metric objects ready for serialization and transmission

Deliberately knows nothing about how metrics are collected (that is PCInfo's
job) or how they are stored (that is main.py and models.py's job).
"""

import platform
import uuid
import logging
from dataclasses import dataclass
from dataclasses_json import dataclass_json
from uuid import UUID

from metrics_datamodel import (
    DTO_Aggregator, DTO_DataSnapshot, DTO_Device, DTO_Metric
)
import PCInfo

# winreg is Windows-only — guard the import so this module works cross-platform
try:
    import winreg
    _WINREG_AVAILABLE = True
except ImportError:
    _WINREG_AVAILABLE = False


@dataclass_json
@dataclass
class AggregatorClient(DTO_Aggregator):
    """Extends DTO_Aggregator with machine identity and metric packaging.

    Inherits to_json() / from_json() / to_dict() from DTO_Aggregator via
    dataclass_json, so the instance serializes directly as the POST body
    for /aggregator_snapshots.
    """

    logger = logging.getLogger(__name__)

    def __init__(self):
        """Identify this machine by hostname and a stable GUID."""
        self.devices = []
        self.name    = platform.node()
        self.guid    = self._get_machine_guid()

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Machine identity
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    def _get_machine_guid(self) -> UUID:
        """Return a stable UUID for this machine.

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
                self.logger.warning("Could not read Windows MachineGuid from registry")

        for path in ('/etc/machine-id', '/var/lib/dbus/machine-id'):
            try:
                with open(path) as f:
                    return UUID(f.read().strip())
            except (FileNotFoundError, ValueError):
                continue

        fallback = uuid.uuid4()
        self.logger.warning(
            "Could not determine a stable machine GUID; using random UUID %s. "
            "This machine will appear as a new aggregator after each restart.",
            fallback
        )
        return fallback

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Metric packaging
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    def add_PC_metrics(self) -> DTO_DataSnapshot:
        """Fetch a fresh hardware snapshot from PCInfo and package it into a
        new DTO_DataSnapshot under this machine's device entry.
        Returns the newly created DTO_DataSnapshot.
        """
        device   = self._ensure_device(platform.node())
        snapshot = self._new_snapshot(device)

        self.logger.info("Packaging metrics for device '%s'", device.name)

        for metric_name, metric_value in PCInfo.collect().items():
            self.logger.debug("  %s = %s", metric_name, metric_value)
            snapshot.metrics.append(DTO_Metric(name=metric_name, value=float(metric_value)))

        return snapshot

    def add_metric(self, name: str, value: float, device_name: str = None) -> None:
        """Add a single named metric to the current device's latest snapshot.
        Useful for appending one-off metrics outside of the standard PCInfo set.
        """
        if not self.devices:
            self._ensure_device(device_name or platform.node())
        device   = self.devices[-1]
        snapshot = device.data_snapshots[-1] if device.data_snapshots else self._new_snapshot(device)
        snapshot.metrics.append(DTO_Metric(name=name, value=float(value)))

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Internal helpers
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    def _ensure_device(self, name: str) -> DTO_Device:
        """Return the device with the given name, creating it if absent."""
        for device in self.devices:
            if device.name == name:
                return device
        new_device = DTO_Device(name=name)
        self.devices.append(new_device)
        return new_device

    def _new_snapshot(self, device: DTO_Device) -> DTO_DataSnapshot:
        """Create a fresh DTO_DataSnapshot, append it to the device, and return it."""
        snapshot = DTO_DataSnapshot()
        device.data_snapshots.append(snapshot)
        return snapshot


if __name__ == "__main__":
    client = AggregatorClient()
    client.add_PC_metrics()
    print(client.to_json())
