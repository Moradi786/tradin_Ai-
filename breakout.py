"""Early directional signals near support/resistance, before breakout confirmation."""
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
    """Use 4h support/resistance for early directional signals; breakout is secondary."""
    from core import klines

    rows = await klines(symbol, "4h", LEVEL_LOOKBACK + 5)
    if not rows or len(rows) < LEVEL_LOOKBACK + 2:
        return None

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

    support_distance = abs(price - support) / support * 100
    resistance_distance = abs(resistance - price) / resistance * 100

    # Send directional signals BEFORE a breakout. Require volume expansion and
    # a directional buying/selling bias; the signal does not wait for candle close
    # beyond support/resistance.
    if vol_ratio >= LEVEL_WATCH_VOLUME_RATIO:
        if support_distance <= LEVEL_NEAR_PCT and price >= support and buy_ratio >= 0.50:
            return {"kind": "EARLY", "direction": "LONG", "level_type": "SUPPORT",
                    "support": support, "resistance": resistance, "price": price,
                    "distance_pct": support_distance, "volume_ratio": vol_ratio,
                    "buy_ratio": buy_ratio, "close": close}
        if resistance_distance <= LEVEL_NEAR_PCT and price <= resistance and buy_ratio <= 0.50:
            return {"kind": "EARLY", "direction": "SHORT", "level_type": "RESISTANCE",
                    "support": support, "resistance": resistance, "price": price,
                    "distance_pct": resistance_distance, "volume_ratio": vol_ratio,
                    "buy_ratio": buy_ratio, "close": close}

    # Optional later confirmation remains available if price moves beyond a level.
    buffer = BREAKOUT_BUFFER_PCT / 100.0
    if close > resistance * (1 + buffer) and vol_ratio >= BREAKOUT_VOLUME_RATIO and buy_ratio >= 0.52:
        return {"kind": "BREAKOUT", "direction": "LONG", "support": support,
                "resistance": resistance, "price": price, "close": close,
                "volume_ratio": vol_ratio, "buy_ratio": buy_ratio}
    if close < support * (1 - buffer) and vol_ratio >= BREAKOUT_VOLUME_RATIO and buy_ratio <= 0.48:
        return {"kind": "BREAKOUT", "direction": "SHORT", "support": support,
                "resistance": resistance, "price": price, "close": close,
                "volume_ratio": vol_ratio, "buy_ratio": buy_ratio}
    return None


def early_signal_message(symbol, signal, btc_line=""):
    direction = signal["direction"]
    is_long = direction == "LONG"
    emoji = "🟢" if is_long else "🔴"
    level_fa = "حمایت" if is_long else "مقاومت"
    action = "احتمال واکنش صعودی؛ هنوز شکست/تأیید نهایی لازم نیست." if is_long else "احتمال واکنش نزولی؛ هنوز شکست/تأیید نهایی لازم نیست."
    return f"""
<b>{emoji} سیگنال زودهنگام {direction} — نزدیک {level_fa}</b>
🪙 <b>#{symbol}</b>
💵 قیمت فعلی: <code>{signal['price']:.8g}</code>
🧱 حمایت: <code>{signal['support']:.8g}</code>
🧱 مقاومت: <code>{signal['resistance']:.8g}</code>
📏 فاصله تا {level_fa}: <b>{signal['distance_pct']:.2f}%</b>
📊 حجم ۲۴ ساعته: <b>{signal.get('volume_24h_btc', 0):,.0f} BTC</b>
{btc_line}
📈 حجم نسبت به میانگین: <b>{signal['volume_ratio']:.2f}x</b>
🛒 نسبت خرید: <b>{signal['buy_ratio'] * 100:.1f}%</b>
{SEP}
{action}
⚠️ این هشدار پیش از شکست صادر می‌شود؛ برگشت قیمت تضمین نیست و سطح ممکن است شکسته شود.
"""


def watch_message(symbol, signal, volume, btc_line=""):
    level = signal["level_type"]
    level_fa = "حمایت" if level == "SUPPORT" else "مقاومت"
    return f"""
<b>🟡 نزدیک {level_fa} — هشدار زودهنگام</b>
🪙 <b>#{symbol}</b>
💵 قیمت فعلی: <code>{signal['price']:.8g}</code>
🧱 حمایت: <code>{signal['support']:.8g}</code>
🧱 مقاومت: <code>{signal['resistance']:.8g}</code>
📏 فاصله تا {level_fa}: <b>{signal['distance_pct']:.2f}%</b>
📊 حجم ۲۴ ساعته: <b>{signal.get('volume_24h_btc', 0):,.0f} BTC</b>
{btc_line}
📈 حجم نسبت به میانگین: <b>{signal['volume_ratio']:.2f}x</b>
{SEP}
هشدار نزدیک سطح؛ جهت قطعی نیست.
⚠️ شکست سطح ممکن است.
"""


def breakout_message(symbol, signal, volume, flow=None, oi=None, btc_line=""):
    direction = signal["direction"]
    emoji = "🟢" if direction == "LONG" else "🔴"
    level = "مقاومت" if direction == "LONG" else "حمایت"
    broken_level = signal["resistance"] if direction == "LONG" else signal["support"]
    return f"""
<b>{emoji} BREAKOUT {direction}</b>
🪙 <b>#{symbol}</b>
💵 قیمت فعلی: <code>{signal['price']:.8g}</code>
🧱 سطح شکسته‌شده ({level}): <code>{broken_level:.8g}</code>
🕯️ بسته‌شدن کندل 4h: <code>{signal['close']:.8g}</code>
{btc_line}
📈 حجم نسبت به میانگین: <b>{signal['volume_ratio']:.2f}x</b>
🛒 نسبت خرید: <b>{signal['buy_ratio'] * 100:.1f}%</b>
{SEP}
کندل ۴ ساعته بیرون سطح بسته شده است.
⚠️ شکست کاذب ممکن است.
"""
