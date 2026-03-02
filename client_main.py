#!/usr/bin/env python3
"""
Main entry point for the client application.

Runs two independent timed collection loops:

  1) PC metrics  — on config.client.interval (default 30s)
       Collects local hardware stats via PCInfo and POSTs them to
       /aggregator_snapshots via AggregatorClient.

  2) Pokémon usage — on config.pokemon.interval (default 3600s)
       Fetches Showdown replay stats for each format in
       config.pokemon.formats and POSTs them to /aggregator_snapshots
       via PokemonClient.
"""

import sys
import logging
import requests
import time
from datetime import datetime, timedelta
from lib_config.config import Config
from lib_metrics_datamodel.metrics_datamodel import *
from lib_utils.blocktimer import BlockTimer
from aggregators.aggregator_client import AggregatorClient
from aggregators.pokemon_client import PokemonClient


class Application:
    def __init__(self):
        """Initialize the application with required configuration and logging."""
        self.config = Config(__file__)
        self.logger = logging.getLogger(__name__)
        self.logger.debug("Application initialized")

    def run(self) -> int:
        """
        Main application logic.
        Returns:
            int: Exit code (0 for success, non-zero for error)
        """
        try:
            self.logger.info("Application starting...")

            pc_interval      = self.config.client.interval
            pokemon_interval = self.config.pokemon.interval

            # Initialise both timers to fire immediately on first tick
            last_pc_run      = datetime.now() - timedelta(seconds=pc_interval)
            last_pokemon_run = datetime.now() - timedelta(seconds=pokemon_interval)

            while True:
                time.sleep(0.5)  # 500ms polling resolution

                current_time = datetime.now()

                if (current_time - last_pc_run).total_seconds() >= pc_interval:
                    self.logger.info("PC metrics interval elapsed, collecting...")
                    last_pc_run = current_time
                    with BlockTimer("Capture and send PC metrics", self.logger):
                        self.capture_and_send_pc_metrics()

                if (current_time - last_pokemon_run).total_seconds() >= pokemon_interval:
                    self.logger.info("Pokémon interval elapsed, collecting...")
                    last_pokemon_run = current_time
                    with BlockTimer("Capture and send Pokémon metrics", self.logger):
                        self.capture_and_send_pokemon_metrics()

            self.logger.info("Application completed successfully")
            return 0

        except Exception as e:
            self.logger.exception("Application failed with error: %s", str(e))
            return 1

    def capture_and_send_pc_metrics(self):
        """Collect local hardware metrics and POST them to the server."""
        client = AggregatorClient()
        client.add_PC_metrics()
        self._post_snapshot(client.to_json())

    def capture_and_send_pokemon_metrics(self):
        """Collect Pokémon usage stats for all configured formats and POST them."""
        formats = self.config.pokemon.formats
        if not formats:
            self.logger.warning("No Pokémon formats configured, skipping collection")
            return

        self.logger.info("Collecting Pokémon usage for formats: %s", formats)
        client = PokemonClient()
        client.add_all_formats(formats)
        self._post_snapshot(client.to_json())

    def _post_snapshot(self, raw_json: str):
        """POST a serialized DTO_Aggregator snapshot to the server."""
        server_url = f"{self.config.web.host}:{self.config.web.port}/aggregator_snapshots"
        headers    = {'Content-Type': 'application/json'}

        self.logger.info("Sending snapshot to %s", server_url)
        response = requests.post(server_url, data=raw_json, headers=headers)

        if response.status_code != 201:
            self.logger.error("Failed to upload snapshot. Server returned: %s", response.text)
            raise Exception(f"Failed to upload snapshot. Status code: {response.status_code}")

        self.logger.info("Successfully uploaded snapshot to server")


def main() -> int:
    """Entry point for the application."""
    app = Application()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())