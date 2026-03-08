"""
PokemonInfo.py

Fetches recent Pokémon Showdown replays for a given format and returns
usage counts for Pokémon appearances or moves.

Collector interface (read by collectors/__init__.py):
    collect(param="")  -> dict   usage counts keyed by Pokémon/move name
    aggregator_name    -> str    fixed name for the Showdown data source
    aggregator_guid    -> UUID   fixed stable identity for the Showdown source
    interval           -> int    seconds between collections
    multi_device       -> bool   True — collect() is called once per format,
                                 each format becomes its own device

param format: "<format_name>|<type>"
    format_name  — Showdown format string, e.g. "gen9ou" (default)
    type         — "mons" for Pokémon counts (default), "move" for move counts
"""

import uuid
import requests
import logging
from concurrent.futures import ThreadPoolExecutor
from lib_config.config import Config

_config = Config(__file__)
_log    = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Collector identity — read by collectors/__init__.py for DTO packaging
# ---------------------------------------------------------------------------

aggregator_name: str = "PokemonShowdown"
aggregator_guid      = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
interval: int        = _config.pokemon.interval
multi_device: bool   = True  # collect() is called once per format in config


# ---------------------------------------------------------------------------
# Showdown formats
# ---------------------------------------------------------------------------

base_url    = "https://replay.pokemonshowdown.com/"
MAX_WORKERS = 5

showdown_formats = [
    # --- Generation 9 (Scarlet/Violet) ---
    "gen9ou", "gen9uu", "gen9ru", "gen9nu", "gen9pu", "gen9zu", "gen9ubers", "gen9lc",
    "gen9anythinggoes", "gen9cap", "gen9customgame", "gen9doublesou", "gen9doublesuu",
    "gen9doublesubers", "gen9doubleslc", "gen9vgc2026", "gen9vgc2026regi", "gen9vgc2025regi",

    # --- National Dex ---
    "gen9nationaldex", "gen9nationaldexuu", "gen9nationaldexru", "gen9nationaldexubers",
    "gen9nationaldexag", "gen9nationaldexmonotype", "gen9nationaldexdoubles", "gen9nationaldexlc",
    "gen9nationaldexbh",

    # --- Factory & Randomized ---
    "gen91v1factory", "gen9battlefactory", "gen9monotypefactory", "gen9hackmonscup",
    "gen9challengecup1v1", "gen9randombattle", "gen9randomdoublesbattle",
    "gen9monotyperandombattle", "gen9randombattleblitz", "gen9computer-assistedrandombattle",
    "gen9superstaffbrosultimate",

    # --- Other Metagames ---
    "gen9balancedhackmons", "gen9almostanyability", "gen9stabmons", "gen9camomons",
    "gen9inheritance", "gen9partnersincrime", "gen9sharedpower", "gen9godlygift",
    "gen9freeforall", "gen9purehackmons", "gen9mixandmega", "gen9metronomebattle",
    "gen9tieringtest", "gen91v1", "gen9monotype",

    # --- Generation 8 ---
    "gen8ou", "gen8uu", "gen8ru", "gen8nu", "gen8pu", "gen8zu", "gen8ubers", "gen8lc",
    "gen8anythinggoes", "gen8monotype", "gen81v1", "gen8bdspou", "gen8bdspuu",
    "gen8bdspubers", "gen8battlefactory", "gen8vgc2022", "gen8randombattle",

    # --- Generation 7 ---
    "gen7ou", "gen7uu", "gen7ru", "gen7nu", "gen7pu", "gen7zu", "gen7ubers", "gen7lc",
    "gen7anythinggoes", "gen7letsgou", "gen7letsgooverused", "gen7randombattle",
    "gen7battlefactory", "gen7vgc2019", "gen7monotype",

    # --- Generation 6 ---
    "gen6ou", "gen6uu", "gen6ru", "gen6nu", "gen6pu", "gen6ubers", "gen6lc",
    "gen6anythinggoes", "gen6randombattle", "gen6battlefactory", "gen6vgc2016",

    # --- Generation 5 ---
    "gen5ou", "gen5uu", "gen5ru", "gen5nu", "gen5pu", "gen5ubers", "gen5lc",
    "gen5randombattle", "gen5battlefactory", "gen5vgc2013", "gen5bw2customgame",

    # --- Generation 4 ---
    "gen4ou", "gen4uu", "gen4nu", "gen4pu", "gen4ubers", "gen4lc", "gen4randombattle",
    "gen4battlefactory", "gen4customgame",

    # --- Generation 3 ---
    "gen3ou", "gen3uu", "gen3nu", "gen3ubers", "gen3lc", "gen3randombattle",
    "gen3battlefactory", "gen3customgame",

    # --- Generation 2 ---
    "gen2ou", "gen2uu", "gen2nu", "gen2ubers", "gen2lc", "gen2randombattle",
    "gen2stadium2", "gen2customgame",

    # --- Generation 1 ---
    "gen1ou", "gen1uu", "gen1ubers", "gen1lc", "gen1randombattle", "gen1stadium",
    "gen1customgame"
]


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def collect(param="") -> dict:
    """Fetch replay stats for a format and return usage counts.

    param format: "<format_name>|<type>"
      format_name  — Showdown format string (default: gen9ou)
      type         — "mons" (default) or "move"
    """
    parts       = param.split("|")
    format_name = parts[0] if parts[0] else "gen9ou"
    data_type   = parts[1] if len(parts) > 1 else "mons"

    replays = search_replays(format_name)
    if not replays:
        return {}

    if data_type == "move":
        return count_moves(replays)
    return count_mons(replays)


def search_replays(game_format=""):
    if game_format in showdown_formats:
        url = f"{base_url}search.json?format={game_format}"
    else:
        if len(game_format.replace(" ", "")) > 0:
            _log.warning("Game format '%s' was invalid, performing default search", game_format)
        url = f"{base_url}search.json"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return None


def get_replay_info(replay_id):
    url      = f"{base_url}{replay_id}.json"
    response = requests.get(url, timeout=5)
    if response.status_code == 200:
        return response.json()
    return None


def get_replay_log(match_json):
    return match_json.get("log", "")


def get_replay_mons(log):
    monindx1 = log.find("|poke|")
    moninde2 = log.rfind("|poke|")
    if monindx1 == -1:
        ownerdictionary = {}
        swichlogs = [x for x in log.split("\n") if "|switch|" in x]
        for entry in swichlogs:
            player  = entry.split("|")[2].split(":")[0]
            pokemon = entry.split("|")[3].split(",")[0]
            if player in ownerdictionary:
                if pokemon not in ownerdictionary[player]:
                    ownerdictionary[player].append(pokemon)
            else:
                ownerdictionary[player] = [pokemon]
        pokemon_list = []
        for keys in ownerdictionary:
            pokemon_list += ownerdictionary[keys]
        return pokemon_list
    else:
        monendind       = log[moninde2:].split("\n")[0].rfind("|")
        pokémon_output  = log[monindx1:moninde2 + monendind + 1].replace("\n", "")
        sep_list        = pokémon_output.split("|poke|")[1:]
        pokemon_list    = []
        for entry in sep_list:
            pokemon_list.append(entry.split("|")[1:2][0].split(",")[0])
        return pokemon_list


def get_replay_moves(log):
    moves_log = [x for x in log.split("\n") if "|move|" in x]
    return [x.split("|")[3] for x in moves_log]


def count_mons(replay_list):
    replay_ids       = [item["id"] for item in replay_list]
    pokemon_dictionary = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        all_match_data = list(executor.map(get_replay_info, replay_ids))
    for match_json in all_match_data:
        if match_json:
            for mon in get_replay_mons(get_replay_log(match_json)):
                pokemon_dictionary[mon] = pokemon_dictionary.get(mon, 0) + 1
    if not pokemon_dictionary:
        _log.error("Something went wrong when retrieving the replays")
        return {}
    return dict(sorted(pokemon_dictionary.items(), key=lambda item: item[1], reverse=True))


def count_moves(replay_list):
    replay_ids       = [item["id"] for item in replay_list]
    moves_dictionary = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        all_match_data = list(executor.map(get_replay_info, replay_ids))
    for match_json in all_match_data:
        if match_json:
            for move in get_replay_moves(get_replay_log(match_json)):
                moves_dictionary[move] = moves_dictionary.get(move, 0) + 1
    return dict(sorted(moves_dictionary.items(), key=lambda item: item[1], reverse=True))


if __name__ == "__main__":
    import json
    print(json.dumps(collect("gen9ou"), indent=2))
