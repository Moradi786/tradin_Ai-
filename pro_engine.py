"""Conservative, deterministic signal quality; scores are not probabilities."""
import math

def finite(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None

def market_regime(market):
    long = finite((market or {}).get("long"))
    short = finite((market or {}).get("short"))
    if long is None or short is None or long + short == 0:
        return "UNKNOWN"
    if long >= 3 and long > short:
        return "BULLISH"
    if short >= 3 and short > long:
        return "BEARISH"
    return "MIXED"

def assess(direction, volume, oi, flow_side, market, btc, structure=None):
    if direction not in ("LONG", "SHORT"):
        raise ValueError("Invalid direction")
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    trend = "UP" if direction == "LONG" else "DOWN"
    v = finite(volume.get("volume_ratio"))
    buy = finite(volume.get("buy_ratio"))
    change = finite((oi or {}).get("change_pct"))
    atr = finite(volume.get("atr"))
    price = finite(volume.get("price"))
    regime = market_regime(market)
    checks = {
        "volume": (15, v is not None and v >= 1.5),
        "oi": (15, change is not None and change > 0),
        "flow": (15, flow_side == expected and buy is not None and (buy >= .55 if direction == "LONG" else buy <= .45)),
        "trend": (15, volume.get("trend") == trend),
        "market": (15, regime == expected),
        "relative_strength": (10, (btc or {}).get("direction") == expected),
        "structure": (5, (structure or {}).get("structure") == expected or (structure or {}).get("sweep") == expected),
        "risk_data": (10, price is not None and atr is not None and 0 < atr < price / 3),
    }
    score = sum(weight for weight, ok in checks.values() if ok)
    return {"score": score, "regime": regime, "checks": {k: ok for k, (_, ok) in checks.items()},
            "eligible": score >= 75 and all(checks[k][1] for k in ("oi", "flow", "risk_data")) and regime != ("BEARISH" if direction == "LONG" else "BULLISH")}
