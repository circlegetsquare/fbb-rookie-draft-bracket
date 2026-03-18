"""Flask dashboard for ESPN Fantasy Basketball Playoff Tracker."""

import time

from flask import Flask, render_template, jsonify

from bracket_data import build_bracket
from espn_playoffs import connect, LEAGUE_ID, YEAR

app = Flask(__name__)

# Cache ESPN data to avoid hitting the API on every page load
_cache: dict = {"bracket": None, "timestamp": 0}
CACHE_TTL = 300  # 5 minutes

SEASON_LABEL = f"{YEAR - 1}-{str(YEAR)[2:]}"


def get_bracket(force_refresh=False):
    now = time.time()
    if force_refresh or _cache["bracket"] is None or (now - _cache["timestamp"]) > CACHE_TTL:
        league = connect()
        _cache["bracket"] = build_bracket(league)
        _cache["timestamp"] = now
    return _cache["bracket"]


@app.route("/")
def index():
    """Serve the page shell immediately - data loaded via API."""
    return render_template(
        "bracket.html",
        league_id=LEAGUE_ID,
        season=SEASON_LABEL,
    )


@app.route("/api/bracket")
def api_bracket():
    """Return bracket data as JSON."""
    bracket = get_bracket()
    return jsonify({
        "bracket": bracket.to_dict(),
        "cache_age": int(time.time() - _cache["timestamp"]),
        "league_id": LEAGUE_ID,
        "season": SEASON_LABEL,
    })


@app.route("/api/refresh")
def api_refresh():
    """Force-refresh and return new bracket data."""
    bracket = get_bracket(force_refresh=True)
    return jsonify({
        "bracket": bracket.to_dict(),
        "cache_age": 0,
        "league_id": LEAGUE_ID,
        "season": SEASON_LABEL,
    })


if __name__ == "__main__":
    app.run(debug=False, port=5050)
