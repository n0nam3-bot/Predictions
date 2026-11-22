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


def signed(x, nd=1):
    return f"{'+' if x > 0 else '\u2212' if x < 0 else ''}{abs(x):.{nd}f}"


def _name(packet, side):
    return packet["game"]["home" if side == "home" else "away"]


UNKNOWN = {
    "nhl": "The starting goalies are not in this data, and goaltending is the biggest swing factor in hockey.",
    "nba": "Late scratches and rotation changes are not captured, and they can move an NBA line quickly.",
    "nfl": "Quarterback status and weather are not factored in.",
    "mlb": "The starting pitchers are not in this data, and they drive baseball lines.",
    "ufc": "Fighter styles, reach, layoffs and weight cuts are not connected, so this bout has no real analysis.",
    "dwcs": "Fighter styles, reach, layoffs and weight cuts are not connected, so this bout has no real analysis.",
}


def _days(n):
    return "back-to-back" if n == 0 else f"{n} day{'s' if n != 1 else ''} off"


def _context(packet, model):
    g, inputs = packet["game"], packet["inputs"]
    home, away = g["home"], g["away"]
    out = []
    sr = inputs["schedule_rest"]["value"]
    if sr:
        out.append(f"Schedule: {home} {_days(sr['home_days_off'])}, {away} {_days(sr['away_days_off'])}. "
                   f"Games in the last 7 days including this one: {home} {sr['home_games_in_last_7_days']}, {away} {sr['away_games_in_last_7_days']}.")
    else:
        out.append(f"Rest and schedule are unavailable ({inputs['schedule_rest']['reason']}).")
    rf = inputs["recent_form"]["value"]
    unit = (inputs["ratings"]["value"] or {}).get("unit", "points")
    if rf:
        h, a = rf["home"], rf["away"]
        out.append(f"Recent form: {home} {h['w']}-{h['l']} over its last {h['games']} ({signed(h['diff'], 0)} {unit}); "
                   f"{away} {a['w']}-{a['l']} over its last {a['games']} ({signed(a['diff'], 0)} {unit}).")
    inj = inputs["injuries"]["value"]
    if inj:
        for side, name in (("home", home), ("away", away)):
            names = [f"{p['name']} ({p['status']})" for p in inj[side]]
            lt = inj[f"{side}_long_term"]
            if names:
                out.append(f"{name} out or doubtful: " + ", ".join(names) + (f", plus {lt} on long-term injured reserve (not listed)." if lt else "."))
            else:
                out.append(f"{name} has nobody listed out or doubtful" + (f" ({lt} on long-term injured reserve, not listed)." if lt else "."))
        out.append("The feed lists who is out, not how much each player matters, so the size of these absences is not measured.")
    else:
        out.append(f"Injury data is unavailable ({inputs['injuries']['reason']}).")
    return " ".join(out)


def template(packet, model, decision):
    g, inputs = packet["game"], packet["inputs"]
    home, away = g["home"], g["away"]
    mk, rat = inputs["market"]["value"], inputs["ratings"]["value"]
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
    if rat:
        stronger = home if rat["home_elo"] >= rat["away_elo"] else away
        sec["matchup"] = (f"Elo ratings from {rat['home_games']} games for {home} and {rat['away_games']} for {away}: {home} {rat['home_elo']}, {away} {rat['away_elo']} "
                          f"({stronger} rates stronger by {rat['elo_gap']}). With a home edge of {rat['home_adv']} rating points that is {pct(rat['p_home'])} for {home}. "
                          f"Average margin: {home} {signed(rat['home_margin'], 2)} {rat['unit']} per game ({rat['home_record']}), "
                          f"{away} {signed(rat['away_margin'], 2)} ({rat['away_record']}).")
    elif g["kind"] == "bout":
        sec["matchup"] = ("Fighter statistics are not connected, so this bout is shown with the market only and has no matchup analysis."
                          if mk else "Fighter statistics are not connected, so this bout has no matchup analysis.")
    else:
        sec["matchup"] = f"The team rating is unavailable: {inputs['ratings']['reason']}."
    sec["context"] = _context(packet, model) if g["kind"] == "team" else "Fight-camp context (layoff, weight cut, short notice) is unavailable."
    if model and decision.get("model_prob") is not None:
        sel = _name(packet, decision["selection"])
        if model["rated"]:
            head = (f"Ratings alone give {home} {pct(model['rating_home'])}. The model weights the rating at {model['shrink'] * 100:.0f}% "
                    f"and the market at the rest, giving {home} {pct(model['p_home'])}. ")
        else:
            head = "The team rating is unavailable, so the model equals the market. "
        sec["projection"] = (head + f"Side with the most value, {sel}: model {pct(decision['model_prob'])} vs market {pct(decision['market_prob'])}, "
                             f"edge {decision['edge'] * 100:.1f}%, fair price {decision['fair_odds']:+d} vs quoted {decision['odds']:+.0f}.")
    else:
        sec["projection"] = "No projection: the model needs a market line to anchor to."
    missing = [u["label"] for u in packet["unavailable"]]
    risk = UNKNOWN.get(g["sport"], "")
    if missing and g["kind"] == "team":
        risk += (" " if risk else "") + "Missing inputs: " + ", ".join(missing) + "."
    sec["risk"] = risk or "Late news can move the line after publication."
    if decision["verdict"] == "PLAY":
        sel = _name(packet, decision["selection"])
        headline = f"PLAY: {sel} moneyline {decision['odds']:+.0f}"
        thesis = [f"Model {pct(decision['model_prob'])} vs no-vig market {pct(decision['market_prob'])}: edge {decision['edge'] * 100:.1f}%.",
                  f"Quoted {decision['odds']:+.0f} beats the fair price of {decision['fair_odds']:+d}.",
                  f"Coverage {pct(decision['coverage'])} of critical inputs."]
    else:
        headline = "Pass"
        if decision.get("selection") and decision.get("edge") is not None:
            lean = _name(packet, decision["selection"])
            first = (f"Leans {lean}: model {pct(decision['model_prob'])} vs market {pct(decision['market_prob'])}, "
                     f"edge {decision['edge'] * 100:.1f}% against a {decision['min_edge'] * 100:.1f}% minimum.")
        else:
            first = decision["reason"] or "No edge."
        no_model = decision.get("model_prob") is None
        second = (f"Ratings alone give {home} {pct(model['rating_home'])}; the no-vig market gives {home} {pct(model['market_home'])}."
                  if model and model.get("rated") and decision.get("edge") is not None and not (decision["reason"] or "").startswith("Coverage")
                  else decision["reason"] or "No edge.")
        if no_model:
            second = UNKNOWN.get(g["sport"], "Not enough data to compare a model with the market.")
        cov_reason = (decision["reason"] or "").startswith("Coverage")
        thesis = [first, second, "No bet is recorded for this game." if (cov_reason or no_model) else f"Coverage {pct(decision['coverage'])} of critical inputs, and no bet is recorded."]
    return {**sec, "headline": headline, "thesis": thesis}


def signals(packet, model):
    """Up to three short facts that explain a row at a glance. 'Home' and 'Away' follow the 'Away at Home' row title."""
    inp = packet["inputs"]
    side = lambda is_home: "Home" if is_home else "Away"
    out = []
    rat = inp["ratings"]["value"]
    if rat and rat["elo_gap"] >= 40:
        out.append(f"{side(rat['home_elo'] >= rat['away_elo'])} rated higher by {rat['elo_gap']}")
    sr = inp["schedule_rest"]["value"]
    if sr and sr["home_back_to_back"] != sr["away_back_to_back"]:
        out.append(f"{side(sr['home_back_to_back'])} on a back-to-back")
    inj = inp["injuries"]["value"]
    if inj:
        n_home, n_away = len(inj["home"]), len(inj["away"])
        if max(n_home, n_away):
            out.append(f"{side(n_home >= n_away)}: {max(n_home, n_away)} out or doubtful")
    rf = inp["recent_form"]["value"]
    if rf and rf["home"]["games"] >= 3 and rf["away"]["games"] >= 3:
        hr, ar = rf["home"]["w"] / rf["home"]["games"], rf["away"]["w"] / rf["away"]["games"]
        if abs(hr - ar) >= 0.4:
            t = rf["home"] if hr > ar else rf["away"]
            out.append(f"{side(hr > ar)} {t['w']}-{t['l']} in its last {t['games']}")
    return out[:3]


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
