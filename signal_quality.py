"""Pure market-confluence filters used by the signal engine."""


def market_direction_confirmed(
    market: dict,
    direction: str,
    score_enabled: bool,
    score_long: float,
    score_short: float,
    min_alignment: int = 3,
) -> bool:
    """Require the market score and independent alignment to agree.

    If score history is not available, retain the existing 3-of-5 rule.
    """
    minimum = max(1, min(5, int(min_alignment)))
    if direction == "LONG":
        aligned = int(market.get("long", 0) or 0)
        score = market.get("score")
        if score_enabled and score is not None:
            return float(score) >= score_long and aligned >= minimum
        return aligned >= 3

    if direction == "SHORT":
        aligned = int(market.get("short", 0) or 0)
        score = market.get("score")
        if score_enabled and score is not None:
            return float(score) <= score_short and aligned >= minimum
        return aligned >= 3

    return False
