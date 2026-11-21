"""Turn a facts packet + model output into a PLAY or PASS card. All thresholds come from config."""
from . import market


def decide(packet, model, coverage, cfg):
    th = cfg["thresholds"]
    mk = packet["inputs"]["market"]["value"]
    base = {"verdict": "PASS", "market": None, "selection": None, "line": None, "odds": None, "fair_odds": None,
            "model_prob": None, "market_prob": None, "edge": None, "units": None, "confidence": None,
            "rank_score": None, "reason": None, "min_edge": th["play_min_edge"]}
    if model is None or mk is None:
        return {**base, "reason": "No usable market line, so there is nothing to price against."}
    side = "home" if model["p_home"] - mk["no_vig_home"] >= model["p_away"] - mk["no_vig_away"] else "away"   # the side with value
    p = model["p_home"] if side == "home" else model["p_away"]
    p_mkt = mk["no_vig_home"] if side == "home" else mk["no_vig_away"]
    odds = mk["home_ml"] if side == "home" else mk["away_ml"]
    edge = p - p_mkt
    out = {**base, "market": "ML", "selection": side, "odds": odds, "model_prob": p, "market_prob": p_mkt,
           "edge": round(edge, 4), "fair_odds": market.prob_to_american(p)}
    ev = market.ev_per_unit(p, odds)
    if coverage < th["play_min_coverage"]:
        return {**out, "reason": f"Coverage is {coverage:.0%}, under the {th['play_min_coverage']:.0%} needed to bet."}
    if edge > th["edge_error_cap"]:
        return {**out, "reason": "The model disagrees with the market by more than the sanity cap, "
                                 "so it is treated as a likely data error."}
    if edge < th["play_min_edge"]:
        return {**out, "reason": f"Edge is {edge:.1%}, under the {th['play_min_edge']:.1%} minimum."}
    if ev <= 0:
        return {**out, "reason": "The quoted price is worse than the model's fair price after the vig."}
    units = market.units_for(edge, coverage, th["max_units"])
    return {**out, "verdict": "PLAY", "units": units, "confidence": market.confidence_for(edge, coverage),
            "rank_score": round(edge * coverage, 5), "ev": round(ev, 4), "reason": None}
