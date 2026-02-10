import requests
import time
import json

from BlockTimer import BlockTimer
import libLogging
from concurrent.futures import ThreadPoolExecutor

from libLogging import setup_logger

log = setup_logger("Pokemon Info")
base_url = "https://replay.pokemonshowdown.com/"
MAX_WORKERS = 5

#here is a list of the formats. I tried to make the process of getting them automatic but
#I don't wanna risk our ip address getting banned <3
#also its hard coded for preformance to prevent redundance disk I/O reads
showdown_formats = [
    # --- Generation 9 (Scarlet/Violet) ---
    "gen9ou", "gen9uu", "gen9ru", "gen9nu", "gen9pu", "gen9zu", "gen9ubers", "gen9lc",
    "gen9anythinggoes", "gen9cap", "gen9customgame", "gen9doublesou", "gen9doublesuu",
    "gen9doublesubers", "gen9doubleslc", "gen9vgc2026", "gen9vgc2026regi", "gen9vgc2025regi",

    # --- National Dex (The "Missing" Suite) ---
    "gen9nationaldex", "gen9nationaldexuu", "gen9nationaldexru", "gen9nationaldexubers",
    "gen9nationaldexag", "gen9nationaldexmonotype", "gen9nationaldexdoubles", "gen9nationaldexlc",
    "gen9nationaldexbh", # National Dex Balanced Hackmons

    # --- Factory & Randomized Metas ---
    "gen91v1factory", "gen9battlefactory", "gen9monotypefactory", "gen9hackmonscup",
    "gen9challengecup1v1", "gen9randombattle", "gen9randomdoublesbattle",
    "gen9monotyperandombattle", "gen9randombattleblitz", "gen9computer-assistedrandombattle",
    "gen9superstaffbrosultimate",

    # --- Other Metagames (OMs) ---
    "gen9balancedhackmons", "gen9almostanyability", "gen9stabmons", "gen9camomons",
    "gen9inheritance", "gen9partnersincrime", "gen9sharedpower", "gen9godlygift",
    "gen9freeforall", "gen9purehackmons", "gen9mixandmega", "gen9metronomebattle",
    "gen9tieringtest", "gen91v1", "gen9monotype",

    # --- Generation 8 (Sword/Shield + BDSP) ---
    "gen8ou", "gen8uu", "gen8ru", "gen8nu", "gen8pu", "gen8zu", "gen8ubers", "gen8lc",
    "gen8anythinggoes", "gen8monotype", "gen81v1", "gen8bdspou", "gen8bdspuu",
    "gen8bdspubers", "gen8battlefactory", "gen8vgc2022", "gen8randombattle",

    # --- Generation 7 (Sun/Moon + Let's Go) ---
    "gen7ou", "gen7uu", "gen7ru", "gen7nu", "gen7pu", "gen7zu", "gen7ubers", "gen7lc",
    "gen7anythinggoes", "gen7letsgou", "gen7letsgooverused", "gen7randombattle",
    "gen7battlefactory", "gen7vgc2019", "gen7monotype",

    # --- Generation 6 (X/Y) ---
    "gen6ou", "gen6uu", "gen6ru", "gen6nu", "gen6pu", "gen6ubers", "gen6lc",
    "gen6anythinggoes", "gen6randombattle", "gen6battlefactory", "gen6vgc2016",

    # --- Generation 5 (B/W) ---
    "gen5ou", "gen5uu", "gen5ru", "gen5nu", "gen5pu", "gen5ubers", "gen5lc",
    "gen5randombattle", "gen5battlefactory", "gen5vgc2013", "gen5bw2customgame",

    # --- Generation 4 (D/P/Pt/HGSS) ---
    "gen4ou", "gen4uu", "gen4nu", "gen4pu", "gen4ubers", "gen4lc", "gen4randombattle",
    "gen4battlefactory", "gen4customgame",

    # --- Generation 3 (R/S/E/FRLG) ---
    "gen3ou", "gen3uu", "gen3nu", "gen3ubers", "gen3lc", "gen3randombattle",
    "gen3battlefactory", "gen3customgame",

    # --- Generation 2 (G/S/C) ---
    "gen2ou", "gen2uu", "gen2nu", "gen2ubers", "gen2lc", "gen2randombattle",
    "gen2stadium2", "gen2customgame",

    # --- Generation 1 (R/B/Y) ---
    "gen1ou", "gen1uu", "gen1ubers", "gen1lc", "gen1randombattle", "gen1stadium",
    "gen1customgame"
]

def collect(param=""):
    # Keeping your original parameter parsing
    parts = param.split("|")
    format_name = parts[0] if parts[0] else "gen9ou"
    data_type = parts[1] if len(parts) > 1 else "mons"

    replays = search_replays(format_name)
    if not replays:
        return {}

    if data_type == "move":
        return count_moves(replays)
    else:
        return count_mons(replays)


def search_replays(game_format=""):
    if game_format in showdown_formats :
        url = f"{base_url}search.json?format={game_format}"
    else: #incase we recieve an invalid format
        if len(game_format.replace(" ", ""))>0:
            log.warning("Game format was invalid. Preforming default search")
        url = f"{base_url}search.json"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return None


def get_replay_info(replay_id):
    url = f"{base_url}{replay_id}.json"
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
        #this means we've detected a hidden mons battle because it doesn't have the |poke| notation
        #this algrithm is computationally more intensive so we avoid it where we can
        ownerdictionary={}
        swichlogs = [x for x in log.split("\n") if "|switch|" in x]
        for entry in swichlogs:
            player = entry.split("|")[2].split(":")[0]
            pokemon = entry.split("|")[3].split(",")[0]
            if player in ownerdictionary:
                if not pokemon in ownerdictionary[player]:
                    ownerdictionary[player].append(pokemon)
            else:
                ownerdictionary[player] = [pokemon]
        pokemon_list=[]
        for keys in ownerdictionary:
            pokemon_list += ownerdictionary[keys]
        return pokemon_list
    else :
        # Keeping your original parsing logic
        monendind = log[moninde2:].split("\n")[0].rfind("|")
        pokémon_output = log[monindx1:moninde2 + monendind + 1].replace("\n", "")
        sep_list = pokémon_output.split("|poke|")[1:]

        pokemon_list = []
        for entry in sep_list:
            pokemon_list.append(entry.split("|")[1:2][0].split(",")[0])
        return pokemon_list


def get_replay_moves(log):
    moves_log = [x for x in log.split("\n") if "|move|" in x]
    moves = [x.split("|")[3] for x in moves_log]
    return moves


def count_mons(replay_list):
    replay_ids = [item["id"] for item in replay_list]
    pokemon_dictionary = {}

    # Introduce concurrency here to fetch the data
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        all_match_data = list(executor.map(get_replay_info, replay_ids))

    # Process the fetched data
    for match_json in all_match_data:
        if match_json:
            mon_list = get_replay_mons(get_replay_log(match_json))
            for mon in mon_list:
                pokemon_dictionary[mon] = pokemon_dictionary.get(mon, 0) + 1
    final_return = dict(sorted(pokemon_dictionary.items(), key=lambda item: item[1], reverse=True))
    if len(final_return)==0 :
        log.error("Something went wrong when retriving the replays")
    else:
        return final_return


def count_moves(replay_list):
    replay_ids = [item["id"] for item in replay_list]
    moves_dictionary = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        all_match_data = list(executor.map(get_replay_info, replay_ids))

    for match_json in all_match_data:
        if match_json:
            moves_list = get_replay_moves(get_replay_log(match_json))
            for move in moves_list:
                moves_dictionary[move] = moves_dictionary.get(move, 0) + 1

    return dict(sorted(moves_dictionary.items(), key=lambda item: item[1], reverse=True))



if __name__ == "__main__":
    with BlockTimer("test",logger=log):
        print(collect("gen4ou"))

