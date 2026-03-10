"""
SupaInfo.py
"""

import os
import sys
import uuid
import logging
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import Config

load_dotenv()

_config = Config(__file__)
_log    = logging.getLogger(__name__)

_url: str      = os.getenv("SUPABASE_URL")
_key: str      = os.getenv("SUPABASE_KEY")
_supabase: Client = create_client(_url, _key)

# ---------------------------------------------------------------------------
# Collector identity
# ---------------------------------------------------------------------------

aggregator_name: str = "mobileapp"
aggregator_guid      = uuid.UUID("b2c3d4e5-f6a7-8901-bcde-f12345678901")
interval: int        = _config.mobileapp.interval
multi_device: bool   = True


# ---------------------------------------------------------------------------
# Dynamic device list — called by __init__.py instead of config.pokemon.formats
# ---------------------------------------------------------------------------

def get_devices() -> list[str]:
    """Fetch all trainer usernames from Supabase to use as device names."""
    try:
        res = _supabase.table("profiles").select("username").execute()
        return [row["username"] for row in res.data if row.get("username")]
    except Exception as e:
        _log.exception("SupaInfo failed to fetch trainer list: %s", str(e))
        return []


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def collect(param="") -> dict:
    """Fetch party data for a specific trainer (param = username).
    Returns a flat dict of { "generation|pokemon_name": 1.0, ... }
    """
    try:
        profiles_res = _supabase.table("profiles").select("*").execute()
        pokemon_res  = _supabase.table("pokemon").select("*").execute()

        trainer = next(
            (u for u in profiles_res.data if u.get("username") == param),
            None
        )
        if not trainer:
            _log.warning("No trainer found with username '%s'", param)
            return {}

        user_id = trainer.get("id")
        metrics = {}
        for p in pokemon_res.data:
            if p.get("user_id") == user_id:
                gen  = p.get("generation", "unknown")
                name = p.get("name", "unknown")
                metrics[f"{gen}|{name}"] = 1.0

        if not metrics:
            _log.warning("No pokemon found for trainer '%s'", param)
            return {}

        return metrics

    except Exception as e:
        _log.exception("SupaInfo collect failed: %s", str(e))
        return {}