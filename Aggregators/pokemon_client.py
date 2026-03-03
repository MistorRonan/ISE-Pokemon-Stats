"""
aggregators/pokemon_client.py

Packages Pokémon Showdown usage data into the DTO hierarchy expected by the
server's POST /aggregator_snapshots endpoint.

Responsibilities:
  - Represent the Showdown data source as a fixed aggregator
  - Iterate over a configured list of formats
  - Call PokemonInfo.collect() for each format
  - Map format name → device name, Pokémon usage counts → DTO_Metric objects

Deliberately knows nothing about how replays are fetched (that is
PokemonInfo's job) or how data is stored (that is main.py and models.py's job).
"""

import uuid
import logging
from dataclasses import dataclass
from dataclasses_json import dataclass_json

from metrics_datamodel import (
    DTO_Aggregator, DTO_DataSnapshot, DTO_Device, DTO_Metric
)
import PokemonInfo

# Fixed identity for the Showdown data source — this never changes, so the
# server will always resolve it to the same aggregator row in the database.
SHOWDOWN_AGGREGATOR_GUID = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
SHOWDOWN_AGGREGATOR_NAME = "PokemonShowdown"


@dataclass_json
@dataclass
class PokemonClient(DTO_Aggregator):
    """Extends DTO_Aggregator with Pokémon Showdown usage packaging.

    Inherits to_json() / from_json() / to_dict() from DTO_Aggregator via
    dataclass_json, so the instance serializes directly as the POST body
    for /aggregator_snapshots.
    """

    logger = logging.getLogger(__name__)

    def __init__(self):
        """Initialise with the fixed Showdown aggregator identity."""
        self.devices = []
        self.guid    = SHOWDOWN_AGGREGATOR_GUID
        self.name    = SHOWDOWN_AGGREGATOR_NAME

    def add_format_metrics(self, format_name: str) -> DTO_DataSnapshot | None:
        """Fetch usage data for a single format from PokemonInfo and package it
        into a DTO_DataSnapshot under a device named after the format.

        Each Pokémon name becomes a DTO_Metric with its usage count as the value.
        Returns the new DTO_DataSnapshot, or None if no data was returned.
        """
        self.logger.info("Collecting Pokémon usage for format '%s'", format_name)

        usage = PokemonInfo.collect(f"{format_name}|mons")
        if not usage:
            self.logger.warning("No data returned for format '%s', skipping", format_name)
            return None

        device   = self._ensure_device(format_name)
        snapshot = self._new_snapshot(device)

        for pokemon_name, count in usage.items():
            self.logger.debug("  %s = %d", pokemon_name, count)
            snapshot.metrics.append(DTO_Metric(name=pokemon_name, value=float(count)))

        return snapshot

    def add_all_formats(self, formats: list[str]) -> None:
        """Collect and package usage data for every format in the supplied list.
        Formats that return no data are skipped with a warning.
        """
        for format_name in formats:
            self.add_format_metrics(format_name)

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
    # Quick test against a single format
    client = PokemonClient()
    client.add_format_metrics("gen9ou")
    print(client.to_json())
