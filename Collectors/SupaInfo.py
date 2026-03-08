import os
from dotenv import load_dotenv
from supabase import create_client, Client
from collections import defaultdict
# 1. Load the variables from the .env file
load_dotenv()

# 2. Pull the credentials from the environment
url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")

# 3. Initialize the client
# (If these are missing, create_client will throw an error)
supabase: Client = create_client(url, key)

def fetch_data():
    # Example: Fetching data from a table named 'profiles'
    try:
        profiles_res = supabase.table("profiles").select("*").execute()
        pokemon_res = supabase.table("pokemon").select("*").execute()

        profiles = profiles_res.data
        all_pokemon = pokemon_res.data
        trainer_data = {}

        for user in profiles:
            username = user.get('username', 'Unknown')
            user_id = user.get('id')

            # Initialize a dictionary for this specific user's generations
            gen_map = defaultdict(list)

            # Filter all_pokemon for matches to this user_id
            for p in all_pokemon:
                if p.get('user_id') == user_id:
                    gen = p.get('generation', 'Unknown Gen')
                    gen_map[gen].append(p.get('name'))

            # Convert defaultdict to a standard dict and assign to the username
            trainer_data[username] = dict(gen_map)

        return trainer_data
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    data = fetch_data()
    if data:
        print(data)