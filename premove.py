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

سیگنال پنجم: GOLDEN ROTATION (ترکیب طلایی)
  BTC.D نزولی + آلت از BTC قوی‌تر + OI صعودی + ورود پول
  + حجم رشد کرده ولی قیمت هنوز نپریده.

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

# ------------------------------------------------------------
# GOLDEN ROTATION (ترکیب طلایی: چرخش پول از BTC به آلت)
# ------------------------------------------------------------

# با ROTATION_ENABLED=false غیرفعال می‌شود.
ROTATION_ENABLED = os.getenv("ROTATION_ENABLED", "true").strip().lower() in (
    "1", "true", "yes",
)

# حداقل برتری تغییر ۲۴ ساعتهٔ آلت نسبت به BTC (٪).
ROTATION_REL_MIN = _float("ROTATION_REL_MIN", "0.5")


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


def detect_rotation(symbol: str, volume: Optional[dict],
                    flow: Optional[dict], oi: Optional[dict],
                    market: Optional[dict]) -> Optional[dict]:
    """
    ترکیب طلایی: پول دارد از بیت‌کوین به این آلت می‌چرخد.

    هر ۵ شرط باید همزمان برقرار باشد:
      1. BTC.D نزولی است (از market_alignment)
      2. تغییر ۲۴ساعتهٔ آلت از BTC بهتر است (از کش tickers — درخواست اضافه نمی‌زند)
      3. OI صعودی = پول جدید وارد پوزیشن‌ها
      4. جریان پول مثبت (ورود پول)
      5. حجم رشد کرده ولی قیمت هنوز نپریده
    """
    if not ROTATION_ENABLED or not volume or not market:
        return None

    # ۵) حجم رشد کرده ولی قیمت هنوز حرکت نکرده
    if not (PREMOVE_VOLUME_MIN <= volume["volume_ratio"]):
        return None
    if abs(volume.get("price_move", 0)) > PREMOVE_MAX_PRICE_MOVE:
        return None

    # ۱) BTC.D نزولی (پول از بیت خارج می‌شود)
    if not market.get("long_details", {}).get("BTC.D"):
        return None

    # ۲) آلت از BTC قوی‌تر (از کش tickers؛ بدون درخواست جدید)
    tickers = core.tickers_cache.get("data") or {}
    alt, btc = tickers.get(symbol), tickers.get("BTCUSDT")
    if not alt or not btc:
        return None
    rel = num(alt.get("priceChangePercent")) - num(
        btc.get("priceChangePercent")
    )
    if rel < ROTATION_REL_MIN:
        return None

    # ۳) OI صعودی
    if not (oi and oi["change_pct"] >= PREMOVE_OI_MIN):
        return None

    # ۴) جریان پول مثبت
    if not flow:
        return None
    total = num(flow.get("inflow")) + num(flow.get("outflow"))
    if total <= 0 or num(flow.get("netflow")) / total < PREMOVE_FLOW_RATIO:
        return None

    return {"direction": "BULLISH", "rel_btc": rel}


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


def rotation_message(result: dict, symbol: str, volume: dict,
                     flow: Optional[dict], oi: Optional[dict],
                     flow_text_fn, oi_text_fn) -> str:
    return f"""
<b>🔥 GOLDEN ROTATION</b>
🪙 <b>#{ltr(symbol)}</b> ┆ 💵 <code>{volume['price']:,.8g}</code>
💱 پول از BTC به این کوین می‌چرخد
{SEP}
📉 BTC.D ┆ نزولی (خروج پول از بیت)
💪 ALT/BTC ┆ <b>{ltr(f"{result['rel_btc']:+.2f}%")}</b> قوی‌تر از بیت
📦 OI ┆ {oi_text_fn(oi)}
💰 FLOW ┆ {flow_text_fn(flow)}
📈 VOL ┆ {ltr(f"{volume['volume_ratio']:.2f}x · {volume['price_move']:+.2f}%")}
{SEP}
🔥 ترکیب طلایی کامل شد؛ قیمت هنوز حرکت نکرده.
{FOOTER}
"""


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
