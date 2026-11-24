"""Offline research primitives. No live orders or automatic model promotion."""
import math

def cvd(rows):
    """Cumulative taker quote imbalance from normalized closed exchange candles."""
    total = 0.0
    for row in rows:
        quote, buy = float(row[7]), float(row[10])
        if not all(map(math.isfinite, (quote, buy))) or quote <= 0 or not 0 <= buy <= quote:
            return None
        total += 2 * buy - quote
    return total if rows else None

def risk_levels(entry, atr, direction, rr=2.0):
    if direction not in ("LONG", "SHORT") or not all(map(math.isfinite, (entry, atr, rr))) or min(entry, atr, rr) <= 0:
        return None
    sign = 1 if direction == "LONG" else -1
    stop, target = entry - sign * 1.5 * atr, entry + sign * 1.5 * atr * rr
    if min(stop, target) <= 0:
        return None
    return stop, target

def backtest(candles, candidates, fee_bps=5, slippage_bps=5, horizon=16):
    """Replay precomputed causal candidates (bar index, direction, ATR, score).
    Enter next bar open; pessimistic same-bar exits; one position at a time.
    Candidate generation must not use future data.
    """
    results = []
    next_index = 0
    cost = 2 * (fee_bps + slippage_bps) / 10000
    for i, direction, atr, score in sorted(candidates, key=lambda x: x[0]):
        if i < 0 or i + 1 < next_index or i + horizon >= len(candles):
            continue
        entry = float(candles[i+1]["open"])
        levels = risk_levels(entry, atr, direction)
        if levels is None:
            continue
        stop, target = levels
        sign = 1 if direction == "LONG" else -1
        for j in range(i+1, i+horizon+1):
            bar = candles[j]
            op, hi, lo = (float(bar[k]) for k in ("open", "high", "low"))
            hit_stop = lo <= stop if sign == 1 else hi >= stop
            hit_target = hi >= target if sign == 1 else lo <= target
            if hit_stop:
                exit_price = min(op, stop) if sign == 1 else max(op, stop)
                break
            if hit_target:
                exit_price = target
                break
        else:
            exit_price = float(bar["close"])
        results.append({"index": i, "exit_index": j, "score": score, "net_return": sign * (exit_price-entry)/entry-cost})
        next_index = j+1
    return results

def calibration(results, min_samples=30):
    """Empirical score-bin win rates; research only, not a trained prediction."""
    bins = {}
    for row in results:
        key = min(90, int(row["score"]) // 10 * 10)
        bins.setdefault(key, []).append(row["net_return"])
    return {k: {"samples": len(v), "win_rate": sum(x > 0 for x in v)/len(v),
                "mean_return": sum(v)/len(v)} for k,v in bins.items() if len(v) >= min_samples}
