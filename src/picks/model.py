"""v0 baseline: start from the no-vig market and nudge it with schedule/form signals.

It is deliberately small and transparent. It has NOT been backtested; every sport ships as
Experimental until docs/METHODOLOGY.md records a walk-forward backtest.
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
    w = cfg["model"]["logit_weights"]
    shrink = cfg["model"]["anchor_shrink"]
    p_mkt = mk["no_vig_home"]
    adj, notes = 0.0, []
    sr = packet["inputs"]["schedule_rest"]["value"]
    if sr:
        diff = max(-3.0, min(3.0, sr["home_rest_days"] - sr["away_rest_days"]))
        a = w["rest_day_diff"] * diff
        adj += a
        notes.append({"name": "rest", "logit": round(a, 4),
                      "text": f"Home rest {sr['home_rest_days']} days vs away {sr['away_rest_days']} days"})
        b2b = (-w["back_to_back"] if sr["home_back_to_back"] else 0) + (w["back_to_back"] if sr["away_back_to_back"] else 0)
        if b2b:
            adj += b2b
            side = "home" if sr["home_back_to_back"] else "away"
            notes.append({"name": "back_to_back", "logit": round(b2b, 4), "text": f"The {side} side is on a back-to-back"})
    rf = packet["inputs"]["recent_form"]["value"]
    if rf and rf["home"]["games"] >= 3 and rf["away"]["games"] >= 3:
        d = rf["home"]["w"] / rf["home"]["games"] - rf["away"]["w"] / rf["away"]["games"]
        a = w["recent_form"] * d
        adj += a
        notes.append({"name": "form", "logit": round(a, 4),
                      "text": f"Last five: home {rf['home']['w']}-{rf['home']['l']}, away {rf['away']['w']}-{rf['away']['l']}"})
    p_home = sigmoid(logit(p_mkt) + shrink * adj)
    return {"p_home": round(p_home, 4), "p_away": round(1 - p_home, 4), "market_home": round(p_mkt, 4),
            "adjustments": notes, "shrink": shrink}
