"""Grade a locked pick against a final result. W, L, V (void) or PENDING."""
from datetime import timedelta

from .timing import parse_utc

VOID_STATUSES = {"cancelled", "canceled", "no_contest", "withdrawn", "replaced"}
WAIT_STATUSES = {"postponed", "suspended", "delayed"}
VOID_AFTER = timedelta(hours=48)


def grade_pick(pick, game, now):
    """pick: market (ML|SPREAD|TOTAL), selection (home|away|over|under), line.
    game: status, home_score, away_score, winner (bouts), start_utc."""
    status = (game.get("status") or "").lower()
    if status in VOID_STATUSES:
        return {"grade": "V", "reason": f"game {status}"}
    if status in WAIT_STATUSES:
        if parse_utc(now) - parse_utc(game["start_utc"]) >= VOID_AFTER:
            return {"grade": "V", "reason": f"{status} and not completed within 48 hours"}
        return {"grade": "PENDING", "reason": status}
    if status != "final":
        return {"grade": "PENDING", "reason": status or "not final"}
    market, sel = pick["market"], pick["selection"]
    if market == "ML":
        winner = game.get("winner")
        if winner is None:
            hs, as_ = game.get("home_score"), game.get("away_score")
            if hs is None or as_ is None:
                return {"grade": "PENDING_REVIEW", "reason": "final without a winner or score"}
            winner = "home" if hs > as_ else "away" if as_ > hs else "draw"
        if winner in ("draw", "no_contest"):
            return {"grade": "V", "reason": "tie or draw on a moneyline"}
        return {"grade": "W" if winner == sel else "L", "reason": f"{winner} won"}
    hs, as_ = game.get("home_score"), game.get("away_score")
    if hs is None or as_ is None:
        return {"grade": "PENDING_REVIEW", "reason": "final without a score"}
    if market == "SPREAD":
        margin = (hs - as_) if sel == "home" else (as_ - hs)
        cover = margin + float(pick["line"])
    elif market == "TOTAL":
        cover = (hs + as_ - float(pick["line"])) * (1 if sel == "over" else -1)
    else:
        raise ValueError(f"unknown market {market}")
    if cover == 0:
        return {"grade": "V", "reason": "push"}
    return {"grade": "W" if cover > 0 else "L", "reason": f"score {hs}-{as_}"}
