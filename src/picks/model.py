"""Rating model: Elo from stored final scores, small schedule nudges, then pulled toward the no-vig market.

The market already knows about goalies, lineups and late news; the rating only knows results. So the model
moves just a fraction of the gap between its rating and the market (anchor_shrink). It has NOT been
validated against closing lines; `python -m picks.cli backtest` reports how well the rating alone predicts winners.
"""
import math


def logit(p):
    return math.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + math.exp(-x))


def project(packet, cfg):
    mk = packet["inputs"]["market"]["value"]
    if mk is None:
        return None
    w, shrink = cfg["model"]["logit_weights"], cfg["model"]["anchor_shrink"]
    p_mkt = mk["no_vig_home"]
    rat = packet["inputs"]["ratings"]["value"]
    if rat is None:
        return {"p_home": round(p_mkt, 4), "p_away": round(1 - p_mkt, 4), "market_home": round(p_mkt, 4), "rating_home": None,
                "adjustments": [], "shrink": shrink, "rated": False}
    nudge, notes = 0.0, []
    sr = packet["inputs"]["schedule_rest"]["value"]
    if sr:
        diff = max(-3, min(3, sr["home_days_off"] - sr["away_days_off"]))
        if diff:
            a = w["rest_day_diff"] * diff
            nudge += a
            notes.append({"name": "rest", "logit": round(a, 4),
                          "text": f"Days off: home {sr['home_days_off']}, away {sr['away_days_off']}"})
        b = (-w["back_to_back"] if sr["home_back_to_back"] else 0) + (w["back_to_back"] if sr["away_back_to_back"] else 0)
        if b:
            nudge += b
            side = "home" if sr["home_back_to_back"] and not sr["away_back_to_back"] else "away" if sr["away_back_to_back"] and not sr["home_back_to_back"] else "both"
            notes.append({"name": "back_to_back", "logit": round(b, 4),
                          "text": "Both sides are on a back-to-back" if side == "both" else f"The {side} side is on a back-to-back"})
    rating_logit = logit(rat["p_home"]) + nudge
    p_home = sigmoid(logit(p_mkt) + shrink * (rating_logit - logit(p_mkt)))
    return {"p_home": round(p_home, 4), "p_away": round(1 - p_home, 4), "market_home": round(p_mkt, 4),
            "rating_home": round(sigmoid(rating_logit), 4), "adjustments": notes, "shrink": shrink, "rated": True}
