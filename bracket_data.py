"""Data layer for consolation bracket — returns structured state for CLI and web."""

from dataclasses import dataclass, field
from espn_api.basketball import League

from espn_playoffs import (
    CONSOLATION_START_WEEK,
    WINNERS_BRACKET_SIZE,
    compute_h2h,
    combine_stats,
    determine_winner,
    get_consolation_teams,
    get_team_stats_for_week,
    get_team_stats_for_daily_range,
    get_daily_sp_range,
    get_current_daily_sp,
)


@dataclass
class MatchupResult:
    team_a_name: str
    team_a_seed: int
    team_b_name: str
    team_b_seed: int
    wins_a: int | None = None
    wins_b: int | None = None
    ties: int | None = None
    winner_name: str | None = None
    loser_name: str | None = None
    details: list = field(default_factory=list)  # [(cat, score_a, score_b, "W"/"L"/"T")]
    is_complete: bool = False
    is_live: bool = False  # Has scores but week not yet final
    is_tiebreak: bool = False
    espn_matched: bool = True
    label: str = ""
    week_label: str = ""

    @property
    def score_display(self) -> str:
        if not self.is_complete:
            return "Pending"
        return f"{self.wins_a}-{self.wins_b}-{self.ties}"

    def to_dict(self) -> dict:
        return {
            "team_a_name": self.team_a_name,
            "team_a_seed": self.team_a_seed,
            "team_b_name": self.team_b_name,
            "team_b_seed": self.team_b_seed,
            "wins_a": self.wins_a,
            "wins_b": self.wins_b,
            "ties": self.ties,
            "winner_name": self.winner_name,
            "loser_name": self.loser_name,
            "details": self.details,
            "is_complete": self.is_complete,
            "is_live": self.is_live,
            "is_tiebreak": self.is_tiebreak,
            "espn_matched": self.espn_matched,
            "label": self.label,
            "week_label": self.week_label,
        }


@dataclass
class BracketRound:
    number: int
    weeks: list[int]
    matchups: list[MatchupResult]
    is_complete: bool = False
    is_two_week: bool = False
    # For in-progress two-week matchups
    week1_progress: list[MatchupResult] | None = None

    @property
    def week_label(self) -> str:
        if len(self.weeks) == 1:
            return f"Week {self.weeks[0]}"
        return f"Weeks {self.weeks[0]}-{self.weeks[1]}"

    @property
    def duration_label(self) -> str:
        return "2-week matchup" if self.is_two_week else "1-week matchup"

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "weeks": self.weeks,
            "matchups": [m.to_dict() for m in self.matchups],
            "is_complete": self.is_complete,
            "is_two_week": self.is_two_week,
            "week1_progress": [p.to_dict() for p in self.week1_progress] if self.week1_progress else None,
            "week_label": self.week_label,
            "duration_label": self.duration_label,
        }


@dataclass
class TeamInfo:
    name: str
    seed: int
    wins: int
    losses: int
    ties: int

    @property
    def record(self) -> str:
        return f"{self.wins}-{self.losses}-{self.ties}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "seed": self.seed,
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "record": self.record,
        }


@dataclass
class BracketState:
    teams: list[TeamInfo]
    rounds: list[BracketRound]
    consolation_start_week: int

    def to_dict(self) -> dict:
        return {
            "teams": [t.to_dict() for t in self.teams],
            "rounds": [r.to_dict() for r in self.rounds],
            "consolation_start_week": self.consolation_start_week,
        }


def _get_week_status(league: League, matchup_period: int, week_index: int) -> str:
    """Determine the status of a fantasy week within a matchup period.

    Returns 'complete', 'live', or 'future'.

    Uses the daily scoring period IDs to determine where we are:
    - MP 20 daily SPs: [140, 141, ..., 147, ...]
    - Regular season weeks are 7 days each
    - Week 20 = first 7 daily SPs of MP 20
    - Week 21 = next 7 daily SPs of MP 20
    """
    daily_sps = get_daily_sp_range(league, matchup_period)
    current_sp = get_current_daily_sp(league)

    if not daily_sps:
        # ESPN may not have populated matchup_ids yet for this period.
        # Estimate from the previous period's range.
        prev_sps = get_daily_sp_range(league, matchup_period - 1)
        if prev_sps and current_sp > prev_sps[-1]:
            # We're past the previous period, so this one should be live.
            # Estimate 14 daily SPs (2-week matchup) starting after prev.
            estimated_start = prev_sps[-1] + 1
            week_size = 7
            week_start = estimated_start + (week_index * week_size)
            week_end = week_start + week_size - 1
            if current_sp > week_end:
                return "complete"
            elif current_sp >= week_start:
                return "live"
        return "future"

    # Determine the daily SP boundary for this week_index
    # Each fantasy week within a matchup period is ~7 daily scoring periods
    week_size = 7
    week_start = daily_sps[0] + (week_index * week_size)
    week_end = week_start + week_size - 1

    if current_sp > week_end:
        return "complete"
    elif current_sp >= week_start:
        return "live"
    else:
        return "future"


def _check_espn_matchup(league: League, week: int, name_a: str, name_b: str) -> bool:
    for m in league.scoreboard(week):
        names = {m.home_team.team_name, m.away_team.team_name}
        if name_a in names and name_b in names:
            return True
    return False


def _resolve_matchup(
    league: League,
    matchup_period: int,
    team_a,
    team_b,
    label: str = "",
    status: str = "future",
    daily_sps: list[int] | None = None,
) -> MatchupResult:
    """Resolve a single matchup.

    If daily_sps is provided, aggregates player-level stats for those specific
    daily scoring periods (used to split multi-week matchup periods into
    individual weeks). Otherwise falls back to scoreboard cumulative data.
    """
    result = MatchupResult(
        team_a_name=team_a.team_name,
        team_a_seed=team_a.standing,
        team_b_name=team_b.team_name,
        team_b_seed=team_b.standing,
        label=label,
    )

    if status == "future":
        return result

    if daily_sps:
        stats_a = get_team_stats_for_daily_range(league, matchup_period, daily_sps, team_a.team_name)
        stats_b = get_team_stats_for_daily_range(league, matchup_period, daily_sps, team_b.team_name)
    else:
        stats_a = get_team_stats_for_week(league, matchup_period, team_a.team_name)
        stats_b = get_team_stats_for_week(league, matchup_period, team_b.team_name)

    if stats_a and stats_b:
        wa, wb, ties, details = compute_h2h(stats_a, stats_b)
        winner = determine_winner(team_a, team_b, wa, wb)
        result.wins_a = wa
        result.wins_b = wb
        result.ties = ties
        result.details = details
        result.winner_name = winner.team_name
        result.loser_name = (team_b if winner == team_a else team_a).team_name
        result.is_tiebreak = wa == wb
        result.espn_matched = _check_espn_matchup(
            league, matchup_period, team_a.team_name, team_b.team_name
        )
        result.is_live = (status == "live")
        result.is_complete = (status == "complete")

    return result


def _resolve_two_week_matchup(
    league: League,
    matchup_period: int,
    team_a,
    team_b,
    label: str = "",
    status: str = "future",
) -> tuple[MatchupResult, MatchupResult | None]:
    """Resolve a two-week matchup.

    Tries scoreboard cumulative data first. If ESPN hasn't populated it yet
    (all zeros), falls back to aggregating player-level box scores from
    the daily scoring periods.
    """
    result = MatchupResult(
        team_a_name=team_a.team_name,
        team_a_seed=team_a.standing,
        team_b_name=team_b.team_name,
        team_b_seed=team_b.standing,
        label=label,
    )
    week1_progress = None

    if status == "future":
        return result, None

    stats_a = get_team_stats_for_week(league, matchup_period, team_a.team_name)
    stats_b = get_team_stats_for_week(league, matchup_period, team_b.team_name)

    # ESPN sometimes returns all-zero scoreboard data for new matchup periods.
    # Detect this and fall back to player-level box score aggregation.
    def _has_real_scores(stats):
        if not stats:
            return False
        return any(v["score"] != 0 for v in stats.values())

    if not _has_real_scores(stats_a) or not _has_real_scores(stats_b):
        # Estimate daily SPs from the previous matchup period
        prev_sps = get_daily_sp_range(league, matchup_period - 1)
        if prev_sps:
            current_sp = get_current_daily_sp(league)
            estimated_start = prev_sps[-1] + 1
            active_sps = list(range(estimated_start, current_sp + 1))
            if active_sps:
                stats_a = get_team_stats_for_daily_range(
                    league, matchup_period, active_sps, team_a.team_name
                )
                stats_b = get_team_stats_for_daily_range(
                    league, matchup_period, active_sps, team_b.team_name
                )

    if stats_a and stats_b:
        wa, wb, ties, details = compute_h2h(stats_a, stats_b)
        winner = determine_winner(team_a, team_b, wa, wb)
        result.wins_a = wa
        result.wins_b = wb
        result.ties = ties
        result.details = details
        result.winner_name = winner.team_name
        result.loser_name = (team_b if winner == team_a else team_a).team_name
        result.is_tiebreak = wa == wb

        result.is_live = (status == "live")
        if status == "complete":
            result.is_complete = True
        else:
            # In progress — show as week 1 progress
            week1_progress = MatchupResult(
                team_a_name=team_a.team_name,
                team_a_seed=team_a.standing,
                team_b_name=team_b.team_name,
                team_b_seed=team_b.standing,
                wins_a=wa,
                wins_b=wb,
                ties=ties,
                details=details,
                is_complete=False,
                label=label,
                week_label="In progress",
            )

    return result, week1_progress


def build_bracket(league: League) -> BracketState:
    """Build the full consolation bracket state from ESPN data.

    ESPN groups playoff weeks into multi-week matchup periods:
      MP 20 = 2-week matchup -> our Round 1 (Week 20) + Round 2 (Week 21)
      MP 21 = 2-week matchup -> our Round 3 (Weeks 22-23)

    For Rounds 1 and 2 (within MP 20), we use the scoreboard cumulative
    data and determine which week is active based on daily scoring period IDs.
    Round 1 uses the cumulative data when its week is live or complete.
    Round 2 will need the cumulative minus a Week 20 snapshot (future work).
    """
    con_teams = get_consolation_teams(league)
    by_seed = {t.standing: t for t in con_teams}
    seeds = sorted(by_seed.keys())

    teams = [
        TeamInfo(
            name=by_seed[s].team_name,
            seed=s,
            wins=by_seed[s].wins,
            losses=by_seed[s].losses,
            ties=by_seed[s].ties,
        )
        for s in seeds
    ]

    # Determine which matchup periods cover the consolation bracket
    # MP 20 = Round 1 (week 0 within MP) + Round 2 (week 1 within MP)
    # MP 21 = Round 3 (2-week final)
    mp_r1r2 = CONSOLATION_START_WEEK      # MP 20
    mp_r3 = CONSOLATION_START_WEEK + 1    # MP 21

    # Determine status of each fantasy week
    r1_status = _get_week_status(league, mp_r1r2, week_index=0)
    r2_status = _get_week_status(league, mp_r1r2, week_index=1)

    # Compute daily SP ranges for each week within MP 20
    # Each fantasy week is 7 daily scoring periods
    all_daily_sps = get_daily_sp_range(league, mp_r1r2)
    first_sp = all_daily_sps[0] if all_daily_sps else 140
    week_size = 7
    r1_daily_sps = list(range(first_sp, first_sp + week_size))
    r2_daily_sps = list(range(first_sp + week_size, first_sp + 2 * week_size))

    rounds: list[BracketRound] = []

    # ---- Round 1 (Week 20) ----
    r1_pairings = [
        (seeds[0], seeds[7]),  # 5v12
        (seeds[1], seeds[6]),  # 6v11
        (seeds[2], seeds[5]),  # 7v10
        (seeds[3], seeds[4]),  # 8v9
    ]

    r1_matchups = []
    for seed_a, seed_b in r1_pairings:
        m = _resolve_matchup(
            league, mp_r1r2, by_seed[seed_a], by_seed[seed_b],
            status=r1_status,
            daily_sps=r1_daily_sps,
        )
        r1_matchups.append(m)

    r1 = BracketRound(
        number=1,
        weeks=[CONSOLATION_START_WEEK],
        matchups=r1_matchups,
    )
    r1.is_complete = all(m.is_complete for m in r1_matchups)
    rounds.append(r1)

    if not r1.is_complete:
        return BracketState(teams=teams, rounds=rounds, consolation_start_week=CONSOLATION_START_WEEK)

    # Map winners/losers from round 1
    r1_winners = []
    r1_losers = []
    for m in r1_matchups:
        for t in con_teams:
            if t.team_name == m.winner_name:
                r1_winners.append(t)
            elif t.team_name == m.loser_name:
                r1_losers.append(t)

    # ---- Round 2 (Week 21) ----
    r2_pairings = [
        ("5th Place Semi", r1_winners[0], r1_winners[3]),
        ("5th Place Semi", r1_winners[1], r1_winners[2]),
        ("9th Place Semi", r1_losers[0], r1_losers[3]),
        ("9th Place Semi", r1_losers[1], r1_losers[2]),
    ]

    r2_matchups = []
    for label, team_a, team_b in r2_pairings:
        m = _resolve_matchup(
            league, mp_r1r2, team_a, team_b, label=label,
            status=r2_status,
            daily_sps=r2_daily_sps,
        )
        r2_matchups.append(m)

    r2 = BracketRound(
        number=2,
        weeks=[CONSOLATION_START_WEEK + 1],
        matchups=r2_matchups,
    )
    r2.is_complete = all(m.is_complete for m in r2_matchups)
    rounds.append(r2)

    if not r2.is_complete:
        return BracketState(teams=teams, rounds=rounds, consolation_start_week=CONSOLATION_START_WEEK)

    # Map R2 winners/losers by label
    r2_results = []
    for m in r2_matchups:
        winner = next(t for t in con_teams if t.team_name == m.winner_name)
        loser = next(t for t in con_teams if t.team_name == m.loser_name)
        r2_results.append((m.label, winner, loser))

    fifth_winners = [w for label, w, l in r2_results if label == "5th Place Semi"]
    fifth_losers = [l for label, w, l in r2_results if label == "5th Place Semi"]
    ninth_winners = [w for label, w, l in r2_results if label == "9th Place Semi"]
    ninth_losers = [l for label, w, l in r2_results if label == "9th Place Semi"]

    # ---- Round 3 (Weeks 22-23, aligns with ESPN MP 21) ----
    # Determine R3 status based on MP 21
    r3_status_w1 = _get_week_status(league, mp_r3, week_index=0)
    r3_status_w2 = _get_week_status(league, mp_r3, week_index=1)
    # Overall R3 status: complete only if both weeks done
    if r3_status_w2 == "complete":
        r3_status = "complete"
    elif r3_status_w1 in ("live", "complete"):
        r3_status = "live"
    else:
        r3_status = "future"

    r3_pairings = [
        ("5th Place Final", fifth_winners[0], fifth_winners[1]),
        ("7th Place Final", fifth_losers[0], fifth_losers[1]),
        ("9th Place Final", ninth_winners[0], ninth_winners[1]),
        ("11th Place Final", ninth_losers[0], ninth_losers[1]),
    ]

    r3_matchups = []
    r3_week1_progress = []
    for label, team_a, team_b in r3_pairings:
        result, progress = _resolve_two_week_matchup(
            league, mp_r3, team_a, team_b, label=label,
            status=r3_status,
        )
        r3_matchups.append(result)
        if progress:
            r3_week1_progress.append(progress)

    r3 = BracketRound(
        number=3,
        weeks=[CONSOLATION_START_WEEK + 2, CONSOLATION_START_WEEK + 3],
        matchups=r3_matchups,
        is_two_week=True,
        week1_progress=r3_week1_progress if r3_week1_progress else None,
    )
    r3.is_complete = all(m.is_complete for m in r3_matchups)
    rounds.append(r3)

    return BracketState(teams=teams, rounds=rounds, consolation_start_week=CONSOLATION_START_WEEK)
