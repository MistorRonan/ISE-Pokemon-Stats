
from fastapi import FastAPI
import json

from starlette.middleware.cors import CORSMiddleware

from Scrapers import PokemonInfo as PKI

with open("config.json") as file:
    config = json.load(file)



app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
mon_dict = PKI.count_mons(PKI.search_replays("gen9ou"))
string = "Hello world"
@app.get("/")
def home():


    return mon_dict
