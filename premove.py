"""
سیگنال چهارم: PRE-MOVE (گرفتن کوین قبل از حرکت)
=============================================

هدف: کوین‌هایی که هنوز حرکت نکرده‌اند اما نشانه‌های تجمیع دارند
را زودتر از حرکت اصلی پیدا کند.

چهار نشانهٔ تجمیع (امتیازی — حداقل ۳ از ۴ لازم است):
  1. حجم در حال رشد است (ولی هنوز انفجار نکرده)
  2. OI صعودی = پول جدید وارد پوزیشن‌ها می‌شود
  3. جریان پول (taker flow) یک‌طرفه شده
  4. RSI در حال بالا آمدن است (مومنتوم در حال ساخته شدن)

جهت احتمالی از علامت netflow و buy_ratio تعیین می‌شود.

این ماژول توسط main.py ایمپورت می‌شود. منطق داده در core.py است.
"""

import os
from typing import Optional

import core
from core import log, num, rsi

# ============================================================
# CONFIG
# ============================================================


def _float(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


# با PREMOVE_ENABLED=false کامل غیرفعال می‌شود.
PREMOVE_ENABLED = os.getenv("PREMOVE_ENABLED", "true").strip().lower() in (
    "1", "true", "yes",
)

# حجم: بین این مقدار و VOLUME_MULTIPLIER (رشد کرده، ولی هنوز منفجر نشده).
PREMOVE_VOLUME_MIN = _float("PREMOVE_VOLUME_MIN", "1.2")

# قیمت نباید بیشتر از این حرکت کرده باشد (٪) — هدف «قبل از حرکت» است.
PREMOVE_MAX_PRICE_MOVE = _float("PREMOVE_MAX_PRICE_MOVE", "0.8")

# حداقل رشد OI (٪) به‌عنوان نشانهٔ ورود پول به پوزیشن‌ها.
PREMOVE_OI_MIN = _float("PREMOVE_OI_MIN", "0.5")

# حداقل نسبت یک‌طرفه بودن جریان پول (taker).
PREMOVE_FLOW_RATIO = _float("PREMOVE_FLOW_RATIO", "0.05")

# چند کندل قبل برای مقایسهٔ جهت RSI.
PREMOVE_RSI_LOOKBACK = int(os.getenv("PREMOVE_RSI_LOOKBACK", "3"))

# حداقل امتیاز لازم از ۴ نشانه.
PREMOVE_MIN_SCORE = int(os.getenv("PREMOVE_MIN_SCORE", "3"))


# ============================================================
# DETECTION
# ============================================================


def detect_premove(symbol: str, volume: Optional[dict],
                   flow: Optional[dict],
                   oi: Optional[dict]) -> Optional[dict]:
    """
    اگر نشانه‌های تجمیع قبل از حرکت دیده شود دیکشنری برمی‌گرداند:
      {
        "direction": "BULLISH" | "BEARISH",
        "score": 3 | 4,
        "checks": {"volume": bool, "oi": bool, "flow": bool, "rsi": bool},
        "rsi": {"current": float, "previous": float} | None
      }
    در غیر این صورت None.

    نکته: هیچ درخواست جدیدی به بایننس نمی‌زند — همهٔ ورودی‌ها
    از scan_symbol پاس داده می‌شوند (مهم برای rate-limit).
    """
    if not PREMOVE_ENABLED or not volume:
        return None

    closes = volume.get("closes") or []

    # --- شرط صفر: قیمت هنوز حرکت نکرده باشد ---
    if abs(volume.get("price_move", 0)) > PREMOVE_MAX_PRICE_MOVE:
        return None

    checks = {}

    # ۱) حجم در حال رشد (ولی زیر آستانهٔ سیگنال نهایی)
    checks["volume"] = (
        PREMOVE_VOLUME_MIN
        <= volume["volume_ratio"]
        < core.VOLUME_MULTIPLIER
    )

    # ۲) OI صعودی = ورود پول جدید به پوزیشن‌ها
    checks["oi"] = bool(oi and oi["change_pct"] >= PREMOVE_OI_MIN)

    # ۳) جریان پول یک‌طرفه
    flow_ratio_ok = False
    if flow:
        total = num(flow.get("inflow")) + num(flow.get("outflow"))
        if total > 0:
            flow_ratio_ok = (
                abs(num(flow.get("netflow"))) / total >= PREMOVE_FLOW_RATIO
            )
    checks["flow"] = flow_ratio_ok

    # ۴) RSI در حال بالا آمدن (مومنتوم در حال ساخته شدن)
    rsi_data = None
    checks["rsi"] = False
    if len(closes) >= 30:
        current = rsi(closes)
        previous = rsi(closes[:-PREMOVE_RSI_LOOKBACK])
        if current is not None and previous is not None:
            rsi_data = {"current": current, "previous": previous}
            checks["rsi"] = current > previous

    score = sum(checks.values())
    if score < PREMOVE_MIN_SCORE:
        return None

    # --- جهت احتمالی از پول و خریدارها ---
    netflow = num(flow.get("netflow")) if flow else 0.0
    buy_ratio = volume.get("buy_ratio", 0.5)

    if netflow > 0 and buy_ratio >= 0.52:
        direction = "BULLISH"
    elif netflow < 0 and buy_ratio <= 0.48:
        direction = "BEARISH"
    else:
        # جهت نامشخص = هشدار PRE-MOVE بدون جهت معتبر نیست.
        return None

    return {
        "direction": direction,
        "score": score,
        "checks": checks,
        "rsi": rsi_data,
    }


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


def premove_message(result: dict, symbol: str, volume: dict,
                    flow: Optional[dict], oi: Optional[dict],
                    flow_text_fn, oi_text_fn) -> str:
    checks = result["checks"]
    rsi_data = result.get("rsi")

    if result["direction"] == "BULLISH":
        dir_line = "🟢 جهت احتمالی: <b>صعودی</b>"
    else:
        dir_line = "🔴 جهت احتمالی: <b>نزولی</b>"

    # چک‌لیست چهار نشانه در یک خط
    marks = (
        f"{'✅' if checks['volume'] else '❌'} حجم"
        f" {'✅' if checks['oi'] else '❌'} OI"
        f" {'✅' if checks['flow'] else '❌'} پول"
        f" {'✅' if checks['rsi'] else '❌'} RSI"
    )

    rsi_line = ""
    if rsi_data:
        rsi_line = (
            "\n📊 RSI ┆ "
            + ltr(
                f"{rsi_data['previous']:.1f} → {rsi_data['current']:.1f}"
                f" ({rsi_data['current'] - rsi_data['previous']:+.1f})"
            )
        )

    return f"""
<b>🔥 PRE-MOVE</b>
🪙 <b>#{ltr(symbol)}</b> ┆ 💵 <code>{volume['price']:,.8g}</code>
{dir_line}
{SEP}
🧪 نشانه‌ها ┆ {marks} <b>({result['score']}/4)</b>
📈 VOL ┆ {ltr(f"{volume['volume_ratio']:.2f}x · {volume['price_move']:+.2f}%")} · خرید <b>{ltr(f"{volume['buy_ratio'] * 100:.1f}%")}</b>
📦 OI ┆ {oi_text_fn(oi)}
💰 FLOW ┆ {flow_text_fn(flow)}{rsi_line}
{SEP}
🔥 قیمت هنوز حرکت نکرده؛ نشانه‌های ورود پول دیده می‌شود.
{FOOTER}
"""
