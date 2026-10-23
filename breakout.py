"""Support/resistance proximity alerts and closed-candle breakout confirmation."""
import os

LEVEL_LOOKBACK = max(8, int(os.getenv("LEVEL_LOOKBACK", "20")))
LEVEL_NEAR_PCT = max(0.1, float(os.getenv("LEVEL_NEAR_PCT", "0.8")))
LEVEL_WATCH_VOLUME_RATIO = max(1.0, float(os.getenv("LEVEL_WATCH_VOLUME_RATIO", "1.2")))
LEVEL_WATCH_COOLDOWN = max(60, int(os.getenv("LEVEL_WATCH_COOLDOWN", "1800")))
BREAKOUT_VOLUME_RATIO = max(1.0, float(os.getenv("BREAKOUT_VOLUME_RATIO", "1.5")))
BREAKOUT_BUFFER_PCT = max(0.0, float(os.getenv("BREAKOUT_BUFFER_PCT", "0.05")))
BREAKOUT_COOLDOWN = max(60, int(os.getenv("BREAKOUT_COOLDOWN", "1800")))

SEP = "━━━━━━━━━━━━━━━"


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def analyze(symbol, volume):
    """Return a WATCH near a level, or a BREAKOUT after a closed 15m candle."""
    from core import klines

    rows = await klines(symbol, "15m", LEVEL_LOOKBACK + 5)
    if not rows or len(rows) < LEVEL_LOOKBACK + 2:
        return None

    # Exclude the live candle; last_closed is the most recent completed 15m candle.
    last_closed = rows[-2]
    prior = rows[-(LEVEL_LOOKBACK + 2):-2]
    if len(prior) < LEVEL_LOOKBACK:
        return None

    resistance = max(_num(row[2]) for row in prior)
    support = min(_num(row[3]) for row in prior)
    close = _num(last_closed[4])
    price = _num((volume or {}).get("price")) or close
    vol_ratio = _num((volume or {}).get("volume_ratio"))
    buy_ratio = _num((volume or {}).get("buy_ratio"), 0.5)
    if not support or not resistance or not price or not close:
        return None

    buffer = BREAKOUT_BUFFER_PCT / 100.0
    if close > resistance * (1 + buffer) and vol_ratio >= BREAKOUT_VOLUME_RATIO and buy_ratio >= 0.52:
        return {"kind": "BREAKOUT", "direction": "LONG", "support": support,
                "resistance": resistance, "price": price, "close": close,
                "volume_ratio": vol_ratio, "buy_ratio": buy_ratio}
    if close < support * (1 - buffer) and vol_ratio >= BREAKOUT_VOLUME_RATIO and buy_ratio <= 0.48:
        return {"kind": "BREAKOUT", "direction": "SHORT", "support": support,
                "resistance": resistance, "price": price, "close": close,
                "volume_ratio": vol_ratio, "buy_ratio": buy_ratio}

    # Early alert: volume has started expanding while price is close to a key level.
    support_distance = abs(price - support) / support * 100
    resistance_distance = abs(resistance - price) / resistance * 100
    if vol_ratio >= LEVEL_WATCH_VOLUME_RATIO:
        if support_distance <= LEVEL_NEAR_PCT:
            return {"kind": "WATCH", "level_type": "SUPPORT", "direction": "",
                    "support": support, "resistance": resistance, "price": price,
                    "distance_pct": support_distance, "volume_ratio": vol_ratio,
                    "buy_ratio": buy_ratio}
        if resistance_distance <= LEVEL_NEAR_PCT:
            return {"kind": "WATCH", "level_type": "RESISTANCE", "direction": "",
                    "support": support, "resistance": resistance, "price": price,
                    "distance_pct": resistance_distance, "volume_ratio": vol_ratio,
                    "buy_ratio": buy_ratio}
    return None


def watch_message(symbol, signal, volume):
    level = signal["level_type"]
    level_fa = "حمایت" if level == "SUPPORT" else "مقاومت"
    action = "زیر نظر بگیر؛ شکست هنوز تأیید نشده است."
    return f"""
<b>🟡 نزدیک {level_fa} — هشدار زودهنگام</b>
🪙 <b>#{symbol}</b>
💵 قیمت فعلی: <code>{signal['price']:.8g}</code>
🧱 حمایت: <code>{signal['support']:.8g}</code>
🧱 مقاومت: <code>{signal['resistance']:.8g}</code>
📏 فاصله تا {level_fa}: <b>{signal['distance_pct']:.2f}%</b>
📈 حجم نسبت به میانگین: <b>{signal['volume_ratio']:.2f}x</b>
{SEP}
{action}
سیگنال شکست فقط پس از بسته‌شدن کندل 15m بیرون سطح و تأیید حجم صادر می‌شود.
⚠️ هشدار است، نه توصیهٔ قطعی معامله.
"""


def breakout_message(symbol, signal, volume, flow=None, oi=None):
    direction = signal["direction"]
    emoji = "🟢" if direction == "LONG" else "🔴"
    level = "مقاومت" if direction == "LONG" else "حمایت"
    return f"""
<b>{emoji} BREAKOUT {direction}</b>
🪙 <b>#{symbol}</b>
💵 قیمت فعلی: <code>{signal['price']:.8g}</code>
🧱 سطح شکسته‌شده ({level}): <code>{signal['resistance'] if direction == 'LONG' else signal['support']:.8g}</code>
🕯️ بسته‌شدن کندل 15m: <code>{signal['close']:.8g}</code>
📈 حجم نسبت به میانگین: <b>{signal['volume_ratio']:.2f}x</b>
🛒 نسبت خرید: <b>{signal['buy_ratio'] * 100:.1f}%</b>
{SEP}
کندل 15 دقیقه‌ای بیرون سطح بسته شده و حجم از آستانه گذشته است.
⚠️ شکست کاذب ممکن است؛ قبل از معامله مدیریت ریسک را رعایت کن.
"""
