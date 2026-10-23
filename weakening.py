"""
سیگنال هفتم: WEAKENING (تضعیف حرکت)
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
                           oi: Optional[dict],
                           closes: Optional[list] = None) -> Optional[dict]:
    """
    اگر حرکت در حال مردن باشد دیکشنری برمی‌گرداند:
      {
        "direction": "UP" | "DOWN",
        "rsi": {"current": float, "previous": float},
        "price_confirmation": bool
      }
      UP   → حرکت صعودی در حال تضعیف (ریسک افت)
      DOWN → حرکت نزولی در حال تضعیف (احتمال برگشت صعودی)
    در غیر این صورت None.

    اگر closes (کندل‌های بستهٔ 15m از volume_analysis) داده شود،
    درخواست klines تکراری زده نمی‌شود — مهم برای rate-limit بایننس.
    """
    if not WEAKENING_ENABLED:
        return None

    # RSI فعلی و RSI چند کندل قبل در تایم‌فریم ۱۵ دقیقه
    if not closes:
        data = await klines(symbol, "15m", 60)
        if len(data) < 30:
            return None
        closes = [num(x[4]) for x in data]

    if len(closes) < 30:
        return None

    current = rsi(closes)
    previous = rsi(closes[:-WEAKENING_RSI_LOOKBACK])

    if current is None or previous is None:
        return None

    rsi_data = {"current": current, "previous": previous}
    # تأیید ساختار قیمت جدا از تضعیف مومنتوم سنجیده می‌شود؛
    # نبود آن سیگنال را حذف نمی‌کند، اما در پیام هشدار داده می‌شود.
    recent = [num(x) for x in closes[-4:]]
    price_confirmation_up = (
        len(recent) >= 4 and recent[-1] > max(recent[:-1])
    )
    price_confirmation_down = (
        len(recent) >= 4 and recent[-1] < min(recent[:-1])
    )

    # دادهٔ OI و FLOW هر دو باید موجود و تأییدکننده باشند.
    if not oi or oi.get("change_pct") is None or not flow:
        return None
    oi_falling = num(oi.get("change_pct")) < 0
    flow_dir = core.flow_direction(flow)
    trend = await core.trend_direction(symbol)
    if core.REQUIRE_TREND and trend == "UNKNOWN":
        return None

    # حرکت صعودی در حال تضعیف: افت RSI همراه کاهش OI و تضعیف خرید.
    if (
        previous >= WEAKENING_RSI_HIGH
        and current <= previous - WEAKENING_RSI_DROP
        and oi_falling
        and flow_dir in ("BEARISH", "NEUTRAL")
        and (not core.REQUIRE_TREND or trend == "UP")
    ):
        return {
            "direction": "UP",
            "rsi": rsi_data,
            "price_confirmation": price_confirmation_down,
        }

    # حرکت نزولی در حال تضعیف: برگشت RSI همراه کاهش OI و تضعیف فروش.
    if (
        previous <= WEAKENING_RSI_LOW
        and current >= previous + WEAKENING_RSI_DROP
        and oi_falling
        and flow_dir in ("BULLISH", "NEUTRAL")
        and (not core.REQUIRE_TREND or trend == "DOWN")
    ):
        return {
            "direction": "DOWN",
            "rsi": rsi_data,
            "price_confirmation": price_confirmation_up,
        }

    return None


# ============================================================
# MESSAGE
# ============================================================

SEP = "━━━━━━━━━━━━━━━"
FOOTER = "⚠️ <i>فقط سیگنال — بدون اجرای معامله</i>"

# جداکننده‌های جهت یونیکد (LRI...PDI) برای ترکیب درست فارسی/لاتین.
LRI = "⁦"
PDI = "⁩"


def ltr(text) -> str:
    return f"{LRI}{text}{PDI}"


def weakening_message(result: dict, symbol: str,
                      flow: Optional[dict], oi: Optional[dict],
                      flow_text_fn, oi_text_fn, btc_line="") -> str:
    rsi_data = result["rsi"]

    if result["direction"] == "UP":
        title = "⏳ مومنتوم صعودی در حال تضعیف است"
        hint = "اگر پوزیشن LONG داری، ریسک را دوباره ارزیابی کن؛ این پیام دستور فروش نیست."
    else:
        title = "⏳ مومنتوم نزولی در حال تضعیف است"
        hint = "اگر پوزیشن SHORT داری، ریسک را دوباره ارزیابی کن؛ این پیام دستور خرید نیست."

    rsi_line = ltr(
        f"{rsi_data['previous']:.1f} → {rsi_data['current']:.1f}"
        f" ({rsi_data['current'] - rsi_data['previous']:+.1f})"
    )

    price_confirmed = bool(result.get("price_confirmation"))
    confirmation_line = (
        "✅ ساختار قیمت: حرکت اخیر تأییدکنندهٔ ضعف است"
        if price_confirmed
        else "⚠️ ساختار قیمت: هنوز تأیید نشده؛ فقط مومنتوم ضعیف شده"
    )
    return f"""
<b>⚪ WEAKENING</b>
🪙 <b>#{ltr(symbol)}</b>
{btc_line}
{title}
{SEP}
📉 RSI ┆ {rsi_line}
📦 OI ┆ {oi_text_fn(oi)}
💰 FLOW ┆ {flow_text_fn(flow)}
{confirmation_line}
{SEP}
💡 {hint}
⚠️ تضعیف مومنتوم به‌تنهایی برگشت قیمت را ثابت نمی‌کند.
{FOOTER}
"""
