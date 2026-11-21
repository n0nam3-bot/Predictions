"""Walk-forward check of the rating alone: predict each stored final before updating on it."""
import math

from .ratings import Ratings


def evaluate(rows, params, min_games):
    r = Ratings(params)
    n = hits = home_wins = 0
    ll = brier = base_ll = 0.0
    for g in rows:
        h, a = g["home"], g["away"]
        if r.games[h] >= min_games and r.games[a] >= min_games and g["home_score"] != g["away_score"]:
            p = min(max(r.p_home(h, a), 0.01), 0.99)
            y = 1.0 if g["home_score"] > g["away_score"] else 0.0
            prior = (home_wins + 1) / (n + 2)                       # running home-win rate, the naive baseline
            ll += -(y * math.log(p) + (1 - y) * math.log(1 - p))
            base_ll += -(y * math.log(prior) + (1 - y) * math.log(1 - prior))
            brier += (p - y) ** 2
            hits += (p >= 0.5) == (y == 1.0)
            home_wins += y
            n += 1
        r.update(h, a, g["home_score"], g["away_score"])
    if not n:
        return {"games": 0}
    return {"games": n, "accuracy": round(hits / n, 4), "log_loss": round(ll / n, 4), "baseline_log_loss": round(base_ll / n, 4),
            "brier": round(brier / n, 4)}


def run(store, cfg):
    out = {}
    for sport, params in cfg["model"]["elo"].items():
        rows = store.q("SELECT home, away, home_score, away_score FROM games WHERE sport = ? AND status = 'final' "
                       "AND home_score IS NOT NULL AND away_score IS NOT NULL ORDER BY start_utc, id", (sport,))
        out[sport] = evaluate(rows, params, cfg["model"]["min_rated_games"])
    return out
