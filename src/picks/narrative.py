"""Plain-language analysis. The template writes only from the facts packet; an LLM may rewrite it,
but every sentence must pass validator.check_narrative or the template is used instead."""
import json

from . import validator

SECTIONS = ["market", "matchup", "context", "projection", "risk"]
PERSONA = ("You are an elite sportsbook market analyst and quantitative sports data scientist. "
           "Be objective and ruthless with numbers. No fluff, no clichés, no hype. "
           "Use ONLY facts present in the JSON you are given. Never invent a number, name, injury or trend. "
           "If an input is listed as unavailable, say it is unavailable. Recommend PASS when there is no edge.")


def pct(x):
    return f"{x * 100:.1f}%"


def _name(packet, side):
    return packet["game"]["home" if side == "home" else "away"]


def template(packet, model, decision):
    g, inputs = packet["game"], packet["inputs"]
    home, away = g["home"], g["away"]
    mk = inputs["market"]["value"]
    sec = {}
    if mk:
        line = (f"Moneyline: {home} {mk['home_ml']:+.0f}, {away} {mk['away_ml']:+.0f}"
                f"{' at ' + mk['book'] if mk.get('book') else ''}. No-vig chance: {home} {pct(mk['no_vig_home'])}, "
                f"{away} {pct(mk['no_vig_away'])} (vig {pct(mk['vig'])}).")
        op = mk.get("opening")
        if op and (op["home_ml"], op["away_ml"]) != (mk["home_ml"], mk["away_ml"]):
            line += f" First seen at {op['home_ml']:+.0f} / {op['away_ml']:+.0f}."
        sec["market"] = line
    else:
        sec["market"] = "Market line is unavailable for this game, so nothing can be priced."
    sec["matchup"] = ("Team and fighter efficiency data (pace, shooting, striking, grappling) is unavailable in this build; "
                      "only the market, rest and recent form are used.")
    ctx = []
    for k, label in (("schedule_rest", "Rest and schedule"), ("recent_form", "Recent form"), ("injuries", "Injury data")):
        v = inputs[k]["value"]
        if v is None:
            ctx.append(f"{label} is unavailable ({inputs[k]['reason']}).")
    notes = [a["text"] + "." for a in (model or {}).get("adjustments", [])]
    inj = inputs["injuries"]["value"]
    if inj:
        for side in ("home", "away"):
            names = [f"{p['name']} ({p['status']})" for p in inj.get(side, [])]
            if names:
                ctx.append(f"{_name(packet, side)} injury list: " + ", ".join(names) + ".")
            else:
                ctx.append(f"{_name(packet, side)} has no listed injuries.")
    sec["context"] = " ".join(notes + ctx) or "No context inputs available."
    if model and decision.get("model_prob") is not None:
        sel = _name(packet, decision["selection"])
        sec["projection"] = (f"Model: {home} {pct(model['p_home'])}, {away} {pct(model['p_away'])}, anchored to the market. "
                             f"Best side {sel}: model {pct(decision['model_prob'])} vs market {pct(decision['market_prob'])}, "
                             f"edge {decision['edge'] * 100:.1f}%, fair price {decision['fair_odds']:+d} vs quoted {decision['odds']:+.0f}.")
    else:
        sec["projection"] = "No projection: the model needs a market line to anchor to."
    missing = [u["label"] for u in packet["unavailable"]]
    sec["risk"] = ("Biggest risk: " + ("unavailable inputs (" + ", ".join(missing) + ") could hide news the price already reflects."
                                       if missing else "late lineup news can move the line after publication."))
    if decision["verdict"] == "PLAY":
        sel = _name(packet, decision["selection"])
        headline = f"PLAY: {sel} moneyline {decision['odds']:+.0f}"
        thesis = [f"Model {pct(decision['model_prob'])} vs no-vig market {pct(decision['market_prob'])}: edge {decision['edge'] * 100:.1f}%.",
                  f"Quoted {decision['odds']:+.0f} beats the fair price of {decision['fair_odds']:+d}.",
                  f"Coverage {pct(decision['coverage'])} of critical inputs."]
    else:
        headline = "PASS / NO BET"
        thesis = [decision["reason"] or "No edge.",
                  f"Coverage {pct(decision['coverage'])} of critical inputs.",
                  "No bet is recorded for this game."]
    return {**sec, "headline": headline, "thesis": thesis}


def validate_all(narr, packet, model, decision):
    text = "\n".join([narr[k] for k in SECTIONS] + list(narr["thesis"]))
    return validator.check_narrative(text, packet, {"model": model, "decision": decision})


def llm_prompt(packet, model, decision, base):
    schema = {k: "string" for k in SECTIONS}
    schema["thesis"] = ["string", "string", "string"]
    user = ("Rewrite the analysis below in tighter, sharper language without adding facts.\n"
            "Return ONLY JSON with keys " + json.dumps(schema) + ".\n"
            "FACTS: " + json.dumps({"packet": packet, "model": model, "decision": decision}, default=str) + "\n"
            "DRAFT: " + json.dumps({k: base[k] for k in SECTIONS + ["thesis"]}))
    return PERSONA, user


def narrate(packet, model, decision, chain=None, retries=2):
    """Return (narrative, source, problems). Falls back to the template whenever the LLM text fails validation."""
    base = template(packet, model, decision)
    if chain is None:
        return base, "template", []
    system, user = llm_prompt(packet, model, decision, base)
    problems = []
    for _ in range(retries + 1):
        try:
            text, provider = chain.generate(system, user)
            data = json.loads(text[text.index("{"): text.rindex("}") + 1])
            cand = {**base, **{k: str(data[k]) for k in SECTIONS}, "thesis": [str(t) for t in data["thesis"]][:3]}
        except Exception as exc:                   # provider down, quota, bad JSON: use the template
            problems = [f"llm unavailable: {exc}"]
            break
        problems = validate_all(cand, packet, model, decision)
        if not problems and len(cand["thesis"]) == 3:
            return cand, provider, []
    return base, "template", problems
