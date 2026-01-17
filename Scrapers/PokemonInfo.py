import requests

base_url = "https://replay.pokemonshowdown.com/"

def search_replays(format):
    url = f"{base_url}search.json?format={format}"
    responce = requests.get(url)
    print(responce)
    if responce.status_code == 200:
        output = responce.json()
        return output
    else:
        print(f"Failed: {responce}")
        return None


def get_replay_info(id):
    url=f"{base_url}{id}.json"
    responce = requests.get(url)
    print(responce)
    if responce.status_code == 200:
        output = responce.json()
        return output
    else:
        print(f"Failed: {responce}")
        return None

def get_replay_log(match_json):
    log = match_json["log"]
    print(log)
    return log

def get_replay_users(log):
    # find usernames
    playersection_start = log.find("|player|")
    playersection_end = log.find("|gen|")
    playersection = log[playersection_start:playersection_end]
    player_tags = playersection.split("|player|")[1:]
    usernames = []
    for i in player_tags:
        usernames.append(i.split("|")[1])
    print(usernames)


def get_replay_mons(log):

    #get pokémon
    monindx1 = log.find("|poke|")
    moninde2 = log.rfind("|poke|")
    monendind = log[moninde2:].split("\n")[0].rfind("|")
    pokémon_output= log[monindx1:moninde2 + monendind + 1].replace("\n", "")
    sep_list = pokémon_output.split("|poke|")[1:]
    pokemon_list=[]
    for entry in sep_list:
        pokemon_list.append(entry.split("|")[1:2][0].split(",")[0])
        pass
    return pokemon_list

    pass

match_id="gen5ou-2520810636"
format="gen5ou"

##print(search_replays(format))


def count_mons(replay_list,byname=False):
    replay_list=[id["id"] for id in replay_list]
    pokemon_dictionary = {}
    for entry in replay_list:
        mon_list = get_replay_mons(get_replay_log(get_replay_info(entry)))
        for mon in mon_list:
            if mon in pokemon_dictionary:
                pokemon_dictionary[mon] = pokemon_dictionary[mon]+1
            else:
                pokemon_dictionary[mon]=1

    sorted_pokemon_dictionary = dict(sorted(pokemon_dictionary.items(), key=lambda item: item[1]))
    return sorted_pokemon_dictionary

##mon_dict=count_mons(search_replays(format))
##for entry in mon_dict:
   ## print(f"{entry}:{mon_dict[entry]}")
output = get_replay_info(match_id)
print(get_replay_mons(get_replay_log(output)))
