import requests
import time
import json
from concurrent.futures import ThreadPoolExecutor

base_url = "https://replay.pokemonshowdown.com/"
MAX_WORKERS = 10


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


def search_replays(format):
    url = f"{base_url}search.json?format={format}"
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
    if monindx1 == -1: return []

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

    return dict(sorted(pokemon_dictionary.items(), key=lambda item: item[1], reverse=True))


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
    RUNS = 10
    COOLDOWN = 30
    PARAM = "gen9ou|mons"
    cumulative_results = {}

    print(f"Starting {RUNS} iterations for {PARAM}...")

    for i in range(1, RUNS + 1):
        print(f"\n>>> RUN {i} OUTPUT <<<")

        # 1. Fetch data for this specific run
        current_run_data = collect(PARAM)

        # 2. Print the map output immediately
        print(json.dumps(current_run_data, indent=4))

        # 3. Merge into the cumulative map
        for key, value in current_run_data.items():
            cumulative_results[key] = cumulative_results.get(key, 0) + value

        # 4. Handle cooldown
        if i < RUNS:
            print(f"\nRun {i} complete. Waiting {COOLDOWN}s for next batch...")
            time.sleep(COOLDOWN)

    # Final report generation
    final_sorted = sorted(cumulative_results.items(), key=lambda x: x[1], reverse=True)
    with open("pokemon_usage_report.txt", "w") as f:
        f.write("=== FINAL SUMMARY REPORT ===\n")
        f.write(f"{'Name':<20} | {'Total':<10} | {'Avg':<10}\n")
        f.write("-" * 45 + "\n")
        for name, total in final_sorted:
            f.write(f"{name:<20} | {total:<10} | {round(total / RUNS, 2):<10}\n")

    print("\nAll runs complete. Final totals saved to 'pokemon_usage_report.txt'.")
