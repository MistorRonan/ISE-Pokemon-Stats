#!/usr/bin/env python3
"""
agent.py

Thin entry point for the collector agent.

Usage:
    python agent.py                     — run all discovered collectors
    python agent.py PCInfo              — run only the PC hardware collector
    python agent.py PCInfo PokemonInfo  — run a specific subset

Discovery and scheduling are handled by collectors/__init__.py.
Adding a new collector requires only dropping a new .py file into the
collectors/ folder with collect(), aggregator_name, aggregator_guid,
interval, and multi_device defined.
"""

import sys
import logging
from collectors import run_agent

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    requested = sys.argv[1:] if len(sys.argv) > 1 else None
    run_agent(collector_names=requested)
