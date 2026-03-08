"""
config.py

Reads config.json from the project root and exposes all values as
dot-notation attributes, matching how the rest of the codebase accesses them.

Usage:
    from config import Config
    config = Config(__file__)
    print(config.ingest_api.port)   # 5001
    print(config.pokemon.formats)   # ["gen9ou", "gen9vgc2026"]

The Config class finds config.json by walking up the directory tree from
the calling file until it finds it, so it works correctly regardless of
which subfolder (api/, collectors/) the calling module lives in.
"""

import json
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)


class _Namespace:
    """Wraps a dict so its keys are accessible as attributes.
    Nested dicts become nested _Namespace objects automatically.

    Example:
        ns = _Namespace({"port": 5001, "debug": false})
        ns.port   # 5001
        ns.debug  # False
    """

    def __init__(self, data: dict):
        for key, value in data.items():
            if isinstance(value, dict):
                setattr(self, key, _Namespace(value))
            else:
                setattr(self, key, value)

    def __repr__(self):
        return f"_Namespace({self.__dict__})"


class Config:
    """Loads config.json and exposes all sections as dot-notation attributes.

    Args:
        calling_file: Pass __file__ from the calling module. Config walks up
                      the directory tree from this location to find config.json,
                      so it works from any subfolder in the project.

    Raises:
        FileNotFoundError: If config.json cannot be found in any parent directory.
        KeyError:          If a required section is missing from config.json.
    """

    def __init__(self, calling_file: str):
        config_path = self._find_config(Path(calling_file).resolve())
        _logger.debug("Loading config from %s", config_path)

        with open(config_path, 'r') as f:
            data = json.load(f)

        # Expose each top-level section as a dot-accessible attribute
        for key, value in data.items():
            if isinstance(value, dict):
                setattr(self, key, _Namespace(value))
            else:
                setattr(self, key, value)

    def _find_config(self, start: Path) -> Path:
        """Walk up the directory tree from start until config.json is found.

        Args:
            start: The resolved path of the calling file.

        Returns:
            Path to config.json.

        Raises:
            FileNotFoundError: If config.json is not found before reaching
                               the filesystem root.
        """
        current = start.parent
        while True:
            candidate = current / 'config.json'
            if candidate.exists():
                return candidate
            if current == current.parent:
                # Reached filesystem root without finding config.json
                raise FileNotFoundError(
                    f"config.json not found in any parent directory of {start}"
                )
            current = current.parent


if __name__ == "__main__":
    # Quick sanity check — run from anywhere in the project
    config = Config(__file__)
    print("pokemon.interval:          ", config.pokemon.interval)
    print("pokemon.formats:           ", config.pokemon.formats)
    print("client.interval:           ", config.client.interval)
    print("ingest_api.host:           ", config.ingest_api.host)
    print("ingest_api.port:           ", config.ingest_api.port)
    print("ingest_api.debug:          ", config.ingest_api.debug)
    print("read_api.host:             ", config.read_api.host)
    print("read_api.port:             ", config.read_api.port)
    print("read_api.debug:            ", config.read_api.debug)
    print("database.connection_string:", config.database.connection_string)
