"""
ردیاب عملکرد سیگنال‌ها با دیتابیس رایگان Turso (libSQL)
=========================================================

هر سیگنال با قیمت و زمان ذخیره می‌شود؛ بعد از ۱ و ۴ ساعت قیمت
دوباره چک می‌شود و نتیجه ثبت می‌گردد (WIN / LOSS / NEUTRAL).
هر ۲۴ ساعت گزارش موفقیت هر نوع سیگنال به تلگرام ارسال می‌شود.

بدون کتابخانهٔ جدید — از HTTP API خود Turso (pipeline) استفاده می‌شود.

متغیرهای env:
  TURSO_DATABASE_URL  مثال: libsql://mydb-myorg.turso.io
  TURSO_AUTH_TOKEN    توکن دیتابیس از داشبورد Turso
"""

import asyncio
import os
import time
from typing import Optional

from core import (
    BINANCE,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    http_get,
    http_post,
    log,
    num,
)

# ============================================================
# CONFIG
# ============================================================

TURSO_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()

# آدرس libsql:// به https:// تبدیل می‌شود (HTTP pipeline).
if TURSO_URL.startswith("libsql://"):
    TURSO_URL = "https://" + TURSO_URL[len("libsql://"):]
TURSO_URL = TURSO_URL.rstrip("/")

TRACK_ENABLED = bool(TURSO_URL and TURSO_TOKEN)

# آستانهٔ موفقیت (درصد تغییر قیمت)
WIN_PCT = float(os.getenv("TRACK_WIN_PCT", "1.0"))        # LONG/SHORT
EARLY_WIN_PCT = float(os.getenv("TRACK_EARLY_WIN_PCT", "2.0"))  # EARLY
WEAK_WIN_PCT = float(os.getenv("TRACK_WEAK_WIN_PCT", "0.5"))    # WEAKENING

CHECK_1H = 3600
CHECK_4H = 4 * 3600
REPORT_INTERVAL = int(os.getenv("TRACK_REPORT_INTERVAL", "86400"))
KEEP_DAYS = 7  # سیگنال‌های قدیمی‌تر حذف می‌شوند

# جداکننده‌های جهت برای ترکیب فارسی/لاتین در گزارش
LRI = "\u2066"
PDI = "\u2069"


def ltr(text) -> str:
    return f"{LRI}{text}{PDI}"


_last_report = time.time()

ICONS = {"LONG": "🟢", "SHORT": "🔴", "EARLY": "🟡", "WEAK": "⚪"}

# ============================================================
# TURSO HTTP CLIENT
# ============================================================


def _arg(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": repr(value)}
    return {"type": "text", "value": str(value)}


async def execute(sql: str, args: Optional[list] = None):
    """اجرای یک کوئری روی Turso. در خطا None برمی‌گرداند."""
    if not TRACK_ENABLED:
        return None

    stmt = {"sql": sql}
    if args:
        stmt["args"] = [_arg(a) for a in args]

    data = await http_post(
        f"{TURSO_URL}/v2/pipeline",
        {"requests": [{"type": "execute", "stmt": stmt}, {"type": "close"}]},
        {
            "Authorization": f"Bearer {TURSO_TOKEN}",
            "content-type": "application/json",
        },
    )
    if not data:
        return None

    try:
        first = data["results"][0]
        if first.get("type") == "error":
            log.warning("TURSO ERROR: %s", first.get("error"))
            return None
        return first["response"]["result"]
    except (KeyError, IndexError, TypeError) as e:
        log.warning("TURSO PARSE ERROR: %s -> %s", e, str(data)[:200])
        return None


def _rows(result) -> list:
    if not result:
        return []
    cols = [c.get("name") for c in result.get("cols", [])]
    rows = []
    for row in result.get("rows", []):
        rows.append({cols[i]: cell.get("value") for i, cell in enumerate(row)})
    return rows


async def init_db() -> None:
    if not TRACK_ENABLED:
        log.warning(
            "TRACKING disabled: set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN"
        )
        return
    await execute(
        "CREATE TABLE IF NOT EXISTS signals ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " ts REAL NOT NULL,"
        " type TEXT NOT NULL,"
        " symbol TEXT NOT NULL,"
        " direction TEXT DEFAULT '',"
        " price REAL NOT NULL,"
        " pct_1h REAL, result_1h TEXT,"
        " pct_4h REAL, result_4h TEXT"
        ")"
    )
    log.info("TRACKING: turso connected")


# ============================================================
# RECORD
# ============================================================


async def record(type_: str, symbol: str, direction: str,
                 price: float) -> None:
    """ثبت سیگنال هنگام ارسال به تلگرام."""
    if not TRACK_ENABLED or not price:
        return
    await execute(
        "INSERT INTO signals (ts, type, symbol, direction, price)"
        " VALUES (?, ?, ?, ?, ?)",
        [time.time(), type_, symbol, direction, float(price)],
    )


# ============================================================
# EVALUATION
# ============================================================


def classify(type_: str, direction: str, change: float) -> str:
    """تغییر قیمت (٪) → WIN / LOSS / NEUTRAL بر اساس نوع سیگنال."""
    if type_ == "EARLY":
        # حرکت بزرگ (در هر جهت) = هشدار زودهنگام درست بوده
        return "WIN" if abs(change) >= EARLY_WIN_PCT else "NEUTRAL"

    if type_ == "WEAK":
        # سیگنال گفت «حرکت می‌میرد»؛ مردن حرکت = موفقیت
        if direction == "UP":
            if change <= WEAK_WIN_PCT:
                return "WIN"
            if change >= 2 * WEAK_WIN_PCT + 0.5:
                return "LOSS"
            return "NEUTRAL"
        # DOWN: حرکت نزولی می‌مرد
        if change >= -WEAK_WIN_PCT:
            return "WIN"
        if change <= -(2 * WEAK_WIN_PCT + 0.5):
            return "LOSS"
        return "NEUTRAL"

    # LONG / SHORT
    if direction == "LONG":
        if change >= WIN_PCT:
            return "WIN"
        if change <= -WIN_PCT:
            return "LOSS"
        return "NEUTRAL"
    # SHORT
    if change <= -WIN_PCT:
        return "WIN"
    if change >= WIN_PCT:
        return "LOSS"
    return "NEUTRAL"


async def _current_price(symbol: str) -> Optional[float]:
    data = await http_get(
        f"{BINANCE}/fapi/v1/ticker/price", {"symbol": symbol}
    )
    if not data:
        return None
    price = num(data.get("price"))
    return price or None


async def check_pending() -> None:
    """سیگنال‌هایی که موعد بررسی‌شان رسیده را ارزیابی می‌کند."""
    now = time.time()
    result = await execute(
        "SELECT id, ts, type, symbol, direction, price, result_1h, result_4h"
        " FROM signals"
        " WHERE (ts <= ? AND result_1h IS NULL)"
        "    OR (ts <= ? AND result_4h IS NULL)"
        " LIMIT 50",
        [now - CHECK_1H, now - CHECK_4H],
    )
    for row in _rows(result):
        price = await _current_price(row["symbol"])
        if not price:
            continue

        entry = num(row["price"])
        if not entry:
            continue

        change = (price - entry) / entry * 100
        ts = num(row["ts"])
        rid = int(num(row["id"]))

        # اول ۴ ساعته، بعد ۱ ساعته (یک ردیف در هر دور فقط یک‌بار)
        if ts <= now - CHECK_4H and row["result_4h"] is None:
            await execute(
                "UPDATE signals SET pct_4h = ?, result_4h = ? WHERE id = ?",
                [change, classify(row["type"], row["direction"], change), rid],
            )
        elif ts <= now - CHECK_1H and row["result_1h"] is None:
            await execute(
                "UPDATE signals SET pct_1h = ?, result_1h = ? WHERE id = ?",
                [change, classify(row["type"], row["direction"], change), rid],
            )

    # پاک‌سازی رکوردهای قدیمی
    await execute("DELETE FROM signals WHERE ts < ?", [now - KEEP_DAYS * 86400])


# ============================================================
# DAILY REPORT
# ============================================================


async def report_text() -> Optional[str]:
    now = time.time()
    result = await execute(
        "SELECT type, COUNT(*) AS total,"
        " SUM(CASE WHEN COALESCE(result_4h, result_1h) = 'WIN'"
        "     THEN 1 ELSE 0 END) AS wins,"
        " SUM(CASE WHEN COALESCE(result_4h, result_1h) = 'LOSS'"
        "     THEN 1 ELSE 0 END) AS losses,"
        " SUM(CASE WHEN COALESCE(result_4h, result_1h) = 'NEUTRAL'"
        "     THEN 1 ELSE 0 END) AS neutrals"
        " FROM signals WHERE ts >= ? GROUP BY type",
        [now - REPORT_INTERVAL],
    )
    rows = _rows(result)
    if not rows:
        return None

    lines = []
    for row in rows:
        total = int(num(row["total"]))
        wins = int(num(row["wins"]))
        losses = int(num(row["losses"]))
        neutrals = int(num(row["neutrals"]))
        decided = wins + losses
        rate = wins / decided * 100 if decided else 0.0
        icon = ICONS.get(row["type"], "▫️")
        lines.append(
            f"{icon} {ltr(row['type'])} ┆ {total} سیگنال"
            f" · ✅ {wins} · ❌ {losses} · ⚪ {neutrals}"
            f" · موفقیت <b>{ltr(f'{rate:.0f}%')}</b>"
        )

    sep = "━━━━━━━━━━━━━━━"
    return (
        "📊 <b>گزارش عملکرد ۲۴ ساعت گذشته</b>\n"
        f"{sep}\n"
        + "\n".join(lines)
        + f"\n{sep}\n"
        "⏱ موفقیت = نتیجهٔ قیمت ۱H/۴H بعد از سیگنال\n"
        "⚠️ <i>فقط سیگنال — بدون اجرای معامله</i>"
    )


async def _send(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    await http_post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
    )


async def maybe_report() -> None:
    global _last_report
    if time.time() - _last_report < REPORT_INTERVAL:
        return
    text = await report_text()
    _last_report = time.time()
    if text:
        await _send(text)
        log.info("TRACKING: daily report sent")


# ============================================================
# LOOP
# ============================================================


async def tracker_loop() -> None:
    if not TRACK_ENABLED:
        return
    log.info("Tracker task started.")
    await asyncio.sleep(60)  # کمی صبر اولیه بعد از استارت
    while True:
        try:
            await check_pending()
            await maybe_report()
        except Exception as e:
            log.error("TRACKER ERROR: %s", e)
        await asyncio.sleep(120)
