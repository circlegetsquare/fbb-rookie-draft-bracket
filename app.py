"""Flask dashboard for ESPN Fantasy Basketball Playoff Tracker."""

import time

from flask import Flask, render_template

from bracket_data import build_bracket
from espn_playoffs import connect, LEAGUE_ID, YEAR

app = Flask(__name__)

# Cache ESPN data to avoid hitting the API on every page load
_cache: dict = {"bracket": None, "timestamp": 0}
CACHE_TTL = 300  # 5 minutes


def get_bracket():
    now = time.time()
    if _cache["bracket"] is None or (now - _cache["timestamp"]) > CACHE_TTL:
        league = connect()
        _cache["bracket"] = build_bracket(league)
        _cache["timestamp"] = now
    return _cache["bracket"]


@app.route("/")
def index():
    bracket = get_bracket()
    season_label = f"{YEAR - 1}-{str(YEAR)[2:]}"
    return render_template(
        "bracket.html",
        bracket=bracket,
        league_id=LEAGUE_ID,
        season=season_label,
        cache_age=int(time.time() - _cache["timestamp"]),
    )


@app.route("/refresh")
def refresh():
    """Force-refresh the cache and redirect to index."""
    _cache["bracket"] = None
    from flask import redirect
    return redirect("/")


if __name__ == "__main__":
    app.run(debug=False, port=5050)
