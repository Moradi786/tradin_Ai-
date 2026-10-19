"""Deterministic helpers for conservative pre-move scoring and risk planning.

These helpers do not place orders and do not promise future returns. They operate
only on closed-candle/market inputs supplied by the scanner.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else default
    except (TypeError, ValueError):
        return default


def score_setup(
    direction: str,
    *,
    volume_ratio: float,
    price_move_pct: float,
    buy_ratio: float,
    oi_change_pct: Optional[float],
    netflow: Optional[float],
    trend_1h: Optional[str],
    trend_4h: Optional[str],
    distance_to_level_pct: float,
    false_breakout: bool = False,
) -> Dict[str, Any]:
    """Return a transparent 0-100 quality score with hard conservative gates."""
    direction = direction.upper()
    if direction not in {"LONG", "SHORT", "BULLISH", "BEARISH"}:
        raise ValueError("direction must be LONG/SHORT or BULLISH/BEARISH")
    long_side = direction in {"LONG", "BULLISH"}
    score = 0
    checks = {}

    checks["controlled_volume"] = 1.2 <= _num(volume_ratio) <= 2.5
    score += 15 if checks["controlled_volume"] else 0
    checks["not_chasing"] = abs(_num(price_move_pct)) <= 0.8
    score += 15 if checks["not_chasing"] else 0

    buy = _num(buy_ratio, 0.5)
    checks["taker_direction"] = buy >= 0.55 if long_side else buy <= 0.45
    score += 15 if checks["taker_direction"] else 0

    oi = None if oi_change_pct is None else _num(oi_change_pct)
    checks["oi_confirmation"] = oi is not None and (oi >= 0.5 if long_side else oi <= -0.5)
    score += 15 if checks["oi_confirmation"] else 0

    flow = None if netflow is None else _num(netflow)
    checks["flow_confirmation"] = flow is not None and (flow > 0 if long_side else flow < 0)
    score += 15 if checks["flow_confirmation"] else 0

    expected = "UP" if long_side else "DOWN"
    checks["trend_1h"] = trend_1h == expected
    checks["trend_4h"] = trend_4h == expected
    score += 10 if checks["trend_1h"] else 0
    score += 5 if checks["trend_4h"] else 0

    checks["near_level"] = 0 <= _num(distance_to_level_pct, 999) <= 1.0
    score += 10 if checks["near_level"] else 0
    checks["no_false_break"] = not false_breakout
    if false_breakout:
        score = max(0, score - 25)

    hard_gates = all(checks[k] for k in (
        "controlled_volume", "not_chasing", "taker_direction",
        "oi_confirmation", "flow_confirmation", "trend_1h",
        "near_level", "no_false_break"
    ))
    return {
        "score": min(100, score),
        "checks": checks,
        "eligible": hard_gates and score >= 75,
        "stage": "PRE_MOVE" if hard_gates and score >= 75 else "WATCH_ONLY",
    }


def risk_plan(entry: float, atr: float, direction: str, rr: float = 2.0) -> Optional[Dict[str, float]]:
    """ATR-based reference stop/target only; no order execution."""
    entry, atr, rr = _num(entry), _num(atr), _num(rr)
    if entry <= 0 or atr <= 0 or rr <= 0:
        return None
    side = direction.upper()
    if side in {"LONG", "BULLISH"}:
        stop = entry - 1.5 * atr
        return {"entry_reference": entry, "stop_reference": stop,
                "target_reference": entry + rr * (entry - stop), "rr": rr}
    if side in {"SHORT", "BEARISH"}:
        stop = entry + 1.5 * atr
        return {"entry_reference": entry, "stop_reference": stop,
                "target_reference": entry - rr * (stop - entry), "rr": rr}
    raise ValueError("direction must be LONG/SHORT or BULLISH/BEARISH")


def evaluate_forward_path(entry: float, future_candles: list, stop: float,
                          target: float, direction: str) -> Dict[str, Any]:
    """Conservative candle-path evaluator; if stop and target hit in one candle,
    count stop first because OHLC cannot reveal intrabar ordering.
    """
    entry = _num(entry)
    if entry <= 0 or not future_candles:
        return {"outcome": "NO_DATA", "bars": 0, "mfe_pct": 0.0, "mae_pct": 0.0}
    long_side = direction.upper() in {"LONG", "BULLISH"}
    mfe = mae = 0.0
    for index, candle in enumerate(future_candles, 1):
        high, low = _num(candle.get("high")), _num(candle.get("low"))
        if long_side:
            mfe = max(mfe, (high - entry) / entry * 100)
            mae = min(mae, (low - entry) / entry * 100)
            stop_hit, target_hit = low <= stop, high >= target
        else:
            mfe = max(mfe, (entry - low) / entry * 100)
            mae = min(mae, (entry - high) / entry * 100)
            stop_hit, target_hit = high >= stop, low <= target
        if stop_hit:
            return {"outcome": "STOP", "bars": index, "mfe_pct": mfe, "mae_pct": mae}
        if target_hit:
            return {"outcome": "TARGET", "bars": index, "mfe_pct": mfe, "mae_pct": mae}
    return {"outcome": "OPEN", "bars": len(future_candles), "mfe_pct": mfe, "mae_pct": mae}
