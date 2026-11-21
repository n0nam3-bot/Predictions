"""Elo-style team ratings built only from final scores already stored in the database."""
import math
from collections import defaultdict

UNIT = {"nba": "points", "nfl": "points", "nhl": "goals", "mlb": "runs"}


def expected(diff):
    return 1 / (1 + 10 ** (-diff / 400))


class Ratings:
    def __init__(self, params):
        self.k, self.home_adv = params["k"], params["home"]
        self.elo = defaultdict(lambda: 1500.0)
        self.games = defaultdict(int)
        self.wins = defaultdict(int)
        self.losses = defaultdict(int)
        self.margin = defaultdict(float)

    def p_home(self, home, away):
        return expected(self.elo[home] - self.elo[away] + self.home_adv)

    def update(self, home, away, hs, as_):
        e = self.p_home(home, away)
        s = 1.0 if hs > as_ else 0.0 if as_ > hs else 0.5
        margin = abs(hs - as_)
        winner_diff = (self.elo[home] + self.home_adv - self.elo[away]) * (1 if hs >= as_ else -1)
        mult = (1 + math.log(1 + margin)) * 2.2 / (0.001 * winner_diff + 2.2)
        delta = self.k * mult * (s - e)
        self.elo[home] += delta
        self.elo[away] -= delta
        for team, mine, theirs in ((home, hs, as_), (away, as_, hs)):
            self.games[team] += 1
            self.margin[team] += mine - theirs
            if mine > theirs:
                self.wins[team] += 1
            elif theirs > mine:
                self.losses[team] += 1

    def avg_margin(self, team):
        return self.margin[team] / self.games[team] if self.games[team] else 0.0


def build(store, sport, cfg, before_utc):
    params = cfg["model"]["elo"].get(sport)
    if not params:
        return None
    r = Ratings(params)
    rows = store.q("SELECT home, away, home_score, away_score FROM games WHERE sport = ? AND status = 'final' "
                   "AND home_score IS NOT NULL AND away_score IS NOT NULL AND start_utc < ? ORDER BY start_utc, id",
                   (sport, before_utc))
    for g in rows:
        r.update(g["home"], g["away"], g["home_score"], g["away_score"])
    r.n_games = len(rows)
    return r


class Cache:
    """One ratings build per sport per run."""

    def __init__(self, store, cfg):
        self.store, self.cfg, self.by = store, cfg, {}

    def get(self, sport, before_utc):
        if sport not in self.by:
            self.by[sport] = build(self.store, sport, self.cfg, before_utc)
        return self.by[sport]
