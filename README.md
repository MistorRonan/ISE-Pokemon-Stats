# ISE-Pokemon-Stats

A metrics collection and visualisation system that tracks Pokémon Showdown usage stats, mobile app trainer party data, and PC hardware snapshots — all stored in a local SQLite database and served via a REST API with a built-in dashboard.

---

## Architecture Overview

```
agent.py          ← runs collectors on a schedule
    └── collectors/
            ├── PCInfo.py         ← hardware metrics (CPU, disk, network)
            ├── PokemonInfo.py    ← Showdown replay usage stats
            └── SupaInfo.py       ← mobile app trainer party data (Supabase)

Server.py         ← runs the two API servers
    ├── api/ingest_api.py         ← receives & stores snapshots (port 5001)
    └── api/read_api.py           ← serves data to the dashboard (port 5002)

static/dashboard.html            ← frontend explorer
```

---

## Requirements

- Python 3.10+ (3.12 recommended) — [python.org](https://python.org)
- A `.env` file in the project root (see [Environment Variables](#environment-variables))

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/your-repo/ISE-Pokemon-Stats.git
cd ISE-Pokemon-Stats
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
```

These are only required if running the `SupaInfo` collector (mobile app trainer data). The PC and Pokémon collectors work without them.

### 4. Initialise the database

Run once to create the SQLite database and tables:

```bash
python init_db.py
```

This creates `metrics.db` in the project root. You only need to run this once — re-running it on an existing database is safe.

---

## Running the Project

### Start the API servers

```bash
python Server.py both
```

This starts both APIs in the same process:
- **Ingest API** on `http://localhost:5001` — receives data from the agent
- **Read API** on `http://localhost:5002` — serves the dashboard

You can also run them separately if needed:

```bash
python Server.py ingest   # ingest API only
python Server.py read     # read API only
```

### Start the collector agent

In a separate terminal:

```bash
python agent.py
```

This runs all discovered collectors. To run a specific subset:

```bash
python agent.py PCInfo
python agent.py PCInfo PokemonInfo
python agent.py SupaInfo
```

### Open the dashboard

```
http://localhost:5002/static/dashboard.html
```

---

## Configuration

All settings live in `config.json` in the project root:

```json
{
    "pokemon": {
        "interval": 3600,
        "formats": ["gen9ou", "gen9vgc2026reg"]
    },
    "mobileapp": {
        "interval": 60
    },
    "client": {
        "interval": 30
    },
    "ingest_api": {
        "host": "http://localhost",
        "port": 5001,
        "debug": false
    },
    "read_api": {
        "host": "http://localhost",
        "port": 5002,
        "debug": false
    },
    "database": {
        "connection_string": "sqlite:///metrics.db"
    }
}
```

### Pinning Pokémon Showdown formats

The `formats` list under `pokemon` controls which Showdown formats the agent tracks. You can edit this manually or use the **Formats browser** in the dashboard to pin/unpin formats without touching the file. The agent must be restarted to pick up newly pinned formats.

---

## Collectors

### PCInfo
Collects hardware metrics from the machine running the agent every 30 seconds: disk usage, process/thread count, network traffic since boot, and system uptime.

### PokemonInfo
Fetches recent Showdown replay data for each pinned format every hour. Each format is collected on a staggered schedule so they don't all hit the Showdown API at the same time. Formats are stored as separate devices in the database.

### SupaInfo
Connects to a Supabase database and fetches each trainer's current Pokémon party every minute. Each trainer becomes their own device. Trainers are discovered dynamically from the database — no static list needed in config.

---

## Dashboard Endpoints

| Endpoint | Description |
|---|---|
| `/hello` | Health check |
| `/devices` | List devices for an aggregator |
| `/metrics` | Query stored metric values with optional filters |
| `/pc_info` | Latest hardware snapshot |
| `/pokemon_info` | Pokémon usage counts for a format |
| `/formats` | Browse and pin Showdown formats |
| `/trainers` | List all trainers from the mobile app |
| `/trainer_info` | Current party for a trainer grouped by generation |
| `/stream` | SSE live push on every ingest commit |

---

## Adding a New Collector

Drop a new `.py` file into the `collectors/` folder. The agent auto-discovers it on startup. The file must expose:

```python
aggregator_name: str   # name for the data source
aggregator_guid: UUID  # stable UUID (generate once and hardcode)
interval: int          # seconds between collections
multi_device: bool     # True if collect() is called once per device
device_name: str       # device name (only if multi_device is False)

def collect(param="") -> dict:
    # Returns { "metric_name": float_value, ... }
```

For dynamic device lists (like SupaInfo), also define:

```python
def get_devices() -> list[str]:
    # Returns list of device names to collect for
```

No changes to any other file are needed.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'collectors'`**
The `collectors` folder must be lowercase. On Windows, rename it:
```bash
ren Collectors collectors_temp
ren collectors_temp collectors
```

**`ModuleNotFoundError: No module named 'dataclasses_json'`** (or any other missing module)
Run `pip install -r requirements.txt` to install all dependencies.

**Agent returns no data for a format**
Check the format string is valid — use the Formats browser in the dashboard to browse all available Showdown formats. Common mistake: `gen9vgc2026` should be `gen9vgc2026reg`.

**Dashboard shows no data**
Make sure both the server (`Server.py both`) and the agent (`agent.py`) are running. The agent must post at least one snapshot before the dashboard has anything to show.

