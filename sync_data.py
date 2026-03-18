#!/usr/bin/env python3
"""Sync ESPN Fantasy Basketball data to static JSON for GitHub Pages."""

import json
import time
from pathlib import Path

from bracket_data import build_bracket
from espn_playoffs import connect, LEAGUE_ID, YEAR

OUTPUT_DIR = Path("docs")
SEASON_LABEL = f"{YEAR - 1}-{str(YEAR)[2:]}"


def sync():
    """Fetch ESPN data and write to static JSON file."""
    print(f"Connecting to ESPN league {LEAGUE_ID}...")
    league = connect()

    print("Building bracket data...")
    bracket = build_bracket(league)

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(exist_ok=True)

    data = {
        "bracket": bracket.to_dict(),
        "cache_age": 0,
        "league_id": LEAGUE_ID,
        "season": SEASON_LABEL,
        "last_updated": int(time.time()),
    }

    output_file = OUTPUT_DIR / "data.json"
    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Data written to {output_file}")
    return data


if __name__ == "__main__":
    sync()
