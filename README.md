# ISE-Pokemon-Stats Documentation
## Modules requires
- Flask

non-listed imports are either built in or made by us

## Project struture 
each folder contains a library as specified by the inclass exercise that required us to split the BlockTimer, Data Collor and Config and logging into seprate libraries

##Collectors Library
Each Info.py file in the library make use of 'Duck Typing', all of them share the function 'collect' for the library to recognise them and add them to the collection process. 
To add a new collector, simply make sure it has the function 'collect' and the library will automatically detect when it's searching through the files

### Pokémon data collector 
PokemonInfo.py has functions to collect replay data from Pokémon Showdown. 
'search_replays' makes an API call to pokémon showdown and returns the last 51 replays, you can filter specific formats or just make a general search

