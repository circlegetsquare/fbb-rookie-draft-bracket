#!/usr/bin/env python3
"""ESPN Fantasy Basketball Playoff Tracker — H2H Categories league."""

import argparse
import csv
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from espn_api.basketball import League

LEAGUE_ID = 189630
YEAR = 2026
CONSOLATION_START_WEEK = 20  # First week of consolation bracket
WINNERS_BRACKET_SIZE = 4     # Top N seeds go to winners bracket


def connect() -> League:
    """Authenticate and return the League object."""
    load_dotenv()
    espn_s2 = os.getenv("ESPN_S2")
    swid = os.getenv("SWID")
    if not espn_s2 or not swid:
        sys.exit("ERROR: ESPN_S2 and SWID must be set in your .env file. See README.md.")
    return League(league_id=LEAGUE_ID, year=YEAR, espn_s2=espn_s2, swid=swid)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The 8 H2H scoring categories for this league
SCORED_CATEGORIES = {"PTS", "BLK", "STL", "AST", "REB", "3PM", "FG%", "FT%"}


def get_scored_categories(cats: dict) -> list[str]:
    """Return category names that are scored H2H categories.

    Uses the known set of scored categories rather than relying on the
    'result' field, since box_scores may not always populate results.
    """
    return [k for k in cats if k in SCORED_CATEGORIES]


def get_team_stats_for_week(league: League, week: int, team_name: str) -> dict | None:
    """Pull a team's raw category stats for a matchup period.

    Uses league.scoreboard() which returns cumulative stats for the matchup
    period. For multi-week periods, this is the running total.
    """
    for m in league.scoreboard(week):
        if m.home_team.team_name == team_name:
            return getattr(m, "home_team_cats", None)
        if m.away_team.team_name == team_name:
            return getattr(m, "away_team_cats", None)
    return None


def get_daily_sp_range(league: League, matchup_period: int) -> list[int]:
    """Return the list of daily scoring period IDs for a matchup period."""
    ids = league.matchup_ids.get(matchup_period, [])
    return [int(x) for x in ids]


def get_current_daily_sp(league: League) -> int:
    """Return the current daily scoring period ID."""
    return league.current_week


# Lineup slots where player stats don't count toward team totals
_INACTIVE_SLOTS = {"BE", "IR"}


def get_team_stats_for_daily_range(
    league: League,
    matchup_period: int,
    daily_sps: list[int],
    team_name: str,
) -> dict | None:
    """Aggregate a team's stats from player-level data across specific daily SPs.

    This is the only reliable way to get per-week stats within ESPN's multi-week
    matchup periods. For each daily scoring period, we sum up active players'
    stat breakdowns, then compute FG%/FT% from the component totals.

    Returns stats in the same format as scoreboard ({"CAT": {"score": X, "result": None}}).
    """
    totals: dict[str, float] = {}
    has_data = False

    for sp in daily_sps:
        boxes = league.box_scores(
            matchup_period=matchup_period, scoring_period=sp, matchup_total=False
        )
        for box in boxes:
            for side in ["home", "away"]:
                team = getattr(box, f"{side}_team")
                if team.team_name != team_name:
                    continue
                lineup = getattr(box, f"{side}_lineup", [])
                for player in lineup:
                    if player.slot_position in _INACTIVE_SLOTS:
                        continue
                    for cat, val in player.points_breakdown.items():
                        totals[cat] = totals.get(cat, 0) + val
                        has_data = True

    if not has_data:
        return None

    # Compute FG% and FT% from components
    if "FGM" in totals and "FGA" in totals and totals["FGA"] > 0:
        totals["FG%"] = totals["FGM"] / totals["FGA"]
    if "FTM" in totals and "FTA" in totals and totals["FTA"] > 0:
        totals["FT%"] = totals["FTM"] / totals["FTA"]

    # Convert to scoreboard format
    return {cat: {"score": totals[cat], "result": None} for cat in totals}


def get_scoring_periods(league: League) -> dict[int, list[int]]:
    """Return mapping of matchup period -> scoring periods from league settings.

    E.g. {20: [20, 21], 21: [22, 23]} means matchup period 20 covers
    scoring periods 20 and 21.
    """
    raw = league.settings.matchup_periods
    return {int(k): v for k, v in raw.items()}


def compute_h2h(cats_a: dict, cats_b: dict) -> tuple[int, int, int, list]:
    """Compare two teams' raw stats head-to-head across scored categories.

    Returns (wins_a, wins_b, ties, details) where details is a list of
    (category, score_a, score_b, result_for_a) tuples.
    """
    scored = get_scored_categories(cats_a)
    wins_a = wins_b = ties = 0
    details = []
    for cat in scored:
        if cat not in cats_b:
            continue
        a = cats_a[cat]["score"]
        b = cats_b[cat]["score"]
        if a > b:
            wins_a += 1
            details.append((cat, a, b, "W"))
        elif b > a:
            wins_b += 1
            details.append((cat, a, b, "L"))
        else:
            ties += 1
            details.append((cat, a, b, "T"))
    return wins_a, wins_b, ties, details


def combine_stats(stats_week1: dict, stats_week2: dict) -> dict:
    """Combine two weeks of category stats by summing raw scores.

    For percentage categories (FG%, FT%), recompute from component stats.
    """
    combined = {}
    for cat in stats_week1:
        if cat not in stats_week2:
            continue
        s1 = stats_week1[cat]["score"]
        s2 = stats_week2[cat]["score"]
        if cat == "FG%":
            # Recompute from FGM/FGA if available
            if "FGM" in stats_week1 and "FGA" in stats_week1:
                fgm = stats_week1["FGM"]["score"] + stats_week2["FGM"]["score"]
                fga = stats_week1["FGA"]["score"] + stats_week2["FGA"]["score"]
                combined[cat] = {"score": fgm / fga if fga else 0, "result": None}
            else:
                combined[cat] = {"score": (s1 + s2) / 2, "result": None}
        elif cat == "FT%":
            if "FTM" in stats_week1 and "FTA" in stats_week1:
                ftm = stats_week1["FTM"]["score"] + stats_week2["FTM"]["score"]
                fta = stats_week1["FTA"]["score"] + stats_week2["FTA"]["score"]
                combined[cat] = {"score": ftm / fta if fta else 0, "result": None}
            else:
                combined[cat] = {"score": (s1 + s2) / 2, "result": None}
        else:
            combined[cat] = {"score": s1 + s2, "result": stats_week1[cat].get("result")}
    return combined


def determine_winner(team_a, team_b, wins_a: int, wins_b: int):
    """Return the winning team. Tiebreaker: better regular season seed (lower standing number)."""
    if wins_a > wins_b:
        return team_a
    elif wins_b > wins_a:
        return team_b
    else:
        # Tie — better regular season record (lower standing) wins
        if team_a.standing < team_b.standing:
            return team_a
        else:
            return team_b


# ---------------------------------------------------------------------------
# Current week matchups
# ---------------------------------------------------------------------------

def find_latest_week(league: League) -> int:
    """Find the latest week that has matchup data."""
    for w in range(25, 0, -1):
        if league.scoreboard(w):
            return w
    return 1


def print_current_matchups(league: League):
    """Print the latest week's matchups with live scores."""
    week = find_latest_week(league)
    matchups = league.scoreboard(week)
    is_playoff = week >= CONSOLATION_START_WEEK

    label = "PLAYOFF" if is_playoff else "REGULAR SEASON"
    print(f"\n{'=' * 64}")
    print(f"  WEEK {week} MATCHUPS  ({label})")
    print(f"{'=' * 64}")

    for m in matchups:
        home_live = getattr(m, "home_team_live_score", None)
        away_live = getattr(m, "away_team_live_score", None)
        hl = str(int(home_live)) if home_live is not None and home_live == int(home_live) else str(home_live or "—")
        al = str(int(away_live)) if away_live is not None and away_live == int(away_live) else str(away_live or "—")

        winner = getattr(m, "winner", None)
        home_cats = getattr(m, "home_team_cats", None)

        print(f"\n  {m.home_team.team_name}")
        print(f"    vs")
        print(f"  {m.away_team.team_name}")
        print(f"  Category Score: {hl} - {al}")

        if home_cats:
            scored = get_scored_categories(home_cats)
            parts = []
            for cat in scored:
                marker = {"WIN": "W", "LOSS": "L", "TIE": "T"}.get(home_cats[cat]["result"], "?")
                parts.append(f"{cat} {marker}")
            print(f"    {' | '.join(parts)}")

        if winner:
            print(f"  Winner: {winner}")
    print()


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------

def print_standings(league: League):
    """Print current standings."""
    teams = sorted(league.teams, key=lambda t: t.standing)
    print(f"{'=' * 64}")
    print(f"  CURRENT STANDINGS")
    print(f"{'=' * 64}")
    print(f"  {'Seed':<6}{'Team':<38}{'Record':<12}")
    print(f"  {'-' * 56}")
    for t in teams:
        record = f"{t.wins}-{t.losses}-{t.ties}"
        if t.standing <= WINNERS_BRACKET_SIZE:
            tag = " [W]"
        else:
            tag = " [C]"
        print(f"  {t.standing:<6}{t.team_name:<38}{record:<12}{tag}")
    print(f"\n  [W] = Winners bracket  [C] = Consolation bracket")
    print()


# ---------------------------------------------------------------------------
# Consolation bracket
# ---------------------------------------------------------------------------

def get_consolation_teams(league: League) -> list:
    """Return teams seeded 5-12 by regular season standing."""
    teams = sorted(league.teams, key=lambda t: t.standing)
    return teams[WINNERS_BRACKET_SIZE:]


def run_consolation_bracket(league: League):
    """Build and display the full consolation bracket using bracket_data."""
    from bracket_data import build_bracket

    bracket = build_bracket(league)

    print(f"{'=' * 64}")
    print(f"  CONSOLATION BRACKET")
    print(f"{'=' * 64}")
    print(f"\n  Seeds (regular season standing):")
    for t in bracket.teams:
        print(f"    {t.seed}. {t.name} ({t.record})")

    for rnd in bracket.rounds:
        print(f"\n  {'─' * 60}")
        print(f"  ROUND {rnd.number} — {rnd.week_label} ({rnd.duration_label})")
        print(f"  {'─' * 60}")

        for m in rnd.matchups:
            if m.label:
                print(f"\n    {m.label}")
            print(f"    ({m.team_a_seed}) {m.team_a_name}")
            print(f"      vs")
            print(f"    ({m.team_b_seed}) {m.team_b_name}")

            if m.is_complete:
                tie_note = " (tiebreak: better seed)" if m.is_tiebreak else ""
                source_note = "" if m.espn_matched else "  [computed from raw stats]"
                print(f"    Result: {m.score_display}  →  {m.winner_name} wins{tie_note}{source_note}")
                _print_cat_details(m.details)
            else:
                print(f"    Result: Pending")

        # Show week 1 progress for two-week rounds
        if rnd.is_two_week and rnd.week1_progress:
            print(f"\n    Week {rnd.weeks[0]} progress:")
            for p in rnd.week1_progress:
                print(f"      {p.team_a_name} vs {p.team_b_name}: {p.wins_a}-{p.wins_b}-{p.ties}")
                _print_cat_details(p.details)

        if not rnd.is_complete and rnd.number < 3:
            print(f"\n  Round {rnd.number} not yet complete — cannot advance bracket.")
            break

    print()


def _print_cat_details(details: list):
    """Print per-category breakdown."""
    parts = []
    for cat, score_a, score_b, result in details:
        parts.append(f"{cat} {result}")
    if parts:
        print(f"      {' | '.join(parts)}")


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def get_standings_rows(league: League) -> list[dict]:
    """Return standings as a list of dicts for CSV export."""
    teams = sorted(league.teams, key=lambda t: t.standing)
    return [
        {
            "seed": t.standing,
            "team": t.team_name,
            "wins": t.wins,
            "losses": t.losses,
            "ties": t.ties,
            "bracket": "Winners" if t.standing <= WINNERS_BRACKET_SIZE else "Consolation",
        }
        for t in teams
    ]


def export_csv(league: League, standings: list):
    """Write standings and current matchups to timestamped CSV files."""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    week = find_latest_week(league)

    matchup_file = f"matchups_{ts}.csv"
    with open(matchup_file, "w", newline="") as f:
        fields = ["week", "home_team", "home_cat_score", "away_team", "away_cat_score"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for m in league.scoreboard(week):
            hl = getattr(m, "home_team_live_score", None)
            al = getattr(m, "away_team_live_score", None)
            writer.writerow({
                "week": week,
                "home_team": m.home_team.team_name,
                "home_cat_score": hl,
                "away_team": m.away_team.team_name,
                "away_cat_score": al,
            })
    print(f"  Exported matchups  -> {matchup_file}")

    standings_file = f"standings_{ts}.csv"
    with open(standings_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["seed", "team", "wins", "losses", "ties", "bracket"])
        writer.writeheader()
        writer.writerows(standings)
    print(f"  Exported standings -> {standings_file}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ESPN Fantasy Basketball Playoff Tracker")
    parser.add_argument("--export", action="store_true", help="Export matchups and standings to CSV files")
    args = parser.parse_args()

    print(f"\nConnecting to ESPN league {LEAGUE_ID} ({YEAR - 1}-{str(YEAR)[2:]} season)...")
    league = connect()

    print_current_matchups(league)
    print_standings(league)
    run_consolation_bracket(league)

    if args.export:
        standings = get_standings_rows(league)
        export_csv(league, standings)


if __name__ == "__main__":
    main()
