"""
سیگنال سوم: WEAKENING (تضعیف حرکت)
=================================

تشخیص می‌دهد یک حرکت صعودی/نزولی در حال مردن است:
  - RSI 15m از ناحیه‌ی افراطی برگشته باشد
  - و حداقل یک تأیید: OI در حال کاهش یا برگشت Money Flow

کاربرد: اگر پوزیشن داری → سود را بگیر؛ اگر نداری → وارد نشو.

این ماژول توسط main.py ایمپورت می‌شود. منطق داده در core.py است.
"""

import os
from typing import Optional

import core
from core import klines, log, num, rsi

# ============================================================
# CONFIG
# ============================================================

def _float(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


# با WEAKENING_ENABLED=false کامل غیرفعال می‌شود.
WEAKENING_ENABLED = os.getenv("WEAKENING_ENABLED", "true").strip().lower() in (
    "1", "true", "yes",
)

# حداقل افت/رشد RSI نسبت به چند کندل قبل.
WEAKENING_RSI_DROP = _float("WEAKENING_RSI_DROP", "10")

# ناحیه‌ی افراطی: صعودی بالای HIGH، نزولی زیر LOW.
WEAKENING_RSI_HIGH = _float("WEAKENING_RSI_HIGH", "60")
WEAKENING_RSI_LOW = _float("WEAKENING_RSI_LOW", "40")

# تعداد کندل‌هایی که RSI فعلی با گذشته‌اش مقایسه می‌شود.
WEAKENING_RSI_LOOKBACK = int(os.getenv("WEAKENING_RSI_LOOKBACK", "3"))


# ============================================================
# DETECTION
# ============================================================

async def detect_weakening(symbol: str, flow: Optional[dict],
                           oi: Optional[dict]) -> Optional[dict]:
    """
    اگر حرکت در حال مردن باشد دیکشنری برمی‌گرداند:
      {
        "direction": "UP" | "DOWN",
        "rsi": {"current": float, "previous": float}
      }
      UP   → حرکت صعودی در حال تضعیف (ریسک ریزش)
      DOWN → حرکت نزولی در حال تضعیف (ریسک پمپ/برگشت)
    در غیر این صورت None.
    """
    if not WEAKENING_ENABLED:
        return None

    # RSI فعلی و RSI چند کندل قبل در تایم‌فریم ۱۵ دقیقه
    data = await klines(symbol, "15m", 60)
    if len(data) < 30:
        return None

    closes = [num(x[4]) for x in data]
    current = rsi(closes)
    previous = rsi(closes[:-WEAKENING_RSI_LOOKBACK])

    if current is None or previous is None:
        return None

    rsi_data = {"current": current, "previous": previous}

    # تأییدیه‌ها: بستن پوزیشن‌ها یا برگشت جریان پول
    oi_falling = bool(oi and oi["change_pct"] < 0)
    flow_not_bullish = core.flow_direction(flow) != "BULLISH"
    flow_not_bearish = core.flow_direction(flow) != "BEARISH"

    # حرکت صعودی در حال مردن
    if (
        previous >= WEAKENING_RSI_HIGH
        and current <= previous - WEAKENING_RSI_DROP
        and (oi_falling or flow_not_bullish)
    ):
        return {"direction": "UP", "rsi": rsi_data}

    # حرکت نزولی در حال مردن
    if (
        previous <= WEAKENING_RSI_LOW
        and current >= previous + WEAKENING_RSI_DROP
        and (oi_falling or flow_not_bearish)
    ):
        return {"direction": "DOWN", "rsi": rsi_data}

    return None


# ============================================================
# MESSAGE
# ============================================================

SEP = "━━━━━━━━━━━━━━━"
FOOTER = "⚠️ <i>فقط سیگنال — بدون اجرای معامله</i>"


def weakening_message(result: dict, symbol: str,
                      flow: Optional[dict], oi: Optional[dict],
                      flow_text_fn, oi_text_fn) -> str:
    rsi_data = result["rsi"]

    if result["direction"] == "UP":
        title = "⏳ حرکت صعودی در حال تضعیف است"
        hint = "LONG داری ← <b>سود را بگیر</b> · نداری ← <b>وارد نشو</b>"
    else:
        title = "⏳ حرکت نزولی در حال تضعیف است"
        hint = "SHORT داری ← <b>سود را بگیر</b> · نداری ← <b>وارد نشو</b>"

    return f"""
<b>⚪ WEAKENING</b>
🪙 <b>#{symbol}</b> ┆ {title}
{SEP}
📉 RSI ┆ {rsi_data['previous']:.1f} → <b>{rsi_data['current']:.1f}</b> ({rsi_data['current'] - rsi_data['previous']:+.1f})
📦 OI ┆ {oi_text_fn(oi)}
💰 FLOW ┆ {flow_text_fn(flow)}
{SEP}
💡 {hint}
{FOOTER}
"""
