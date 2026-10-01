"""
ردیابی عملکرد سیگنال‌ها (Turso / libSQL)
=========================================

هر سیگنال ارسال‌شده ذخیره می‌شود و بعد از ۱ و ۴ ساعت با قیمت
واقعی بایننس ارزیابی می‌شود. هر ۲۴ ساعت یک گزارش موفقیت به
تلگرام ارسال می‌شود.

اتصال از طریق HTTP Pipeline API تورسو است؛ بدون نیاز به پکیج اضافه.
اگر TURSO_DATABASE_URL / TURSO_AUTH_TOKEN ست نشده باشد، ردیابی
خاموش می‌ماند و بقیهٔ ربات بدون تغییر کار می‌کند.

قواعد ارزیابی (۴ ساعت بعد):
  LONG      : حرکت >= +WIN_MOVE_PCT  → WIN، <= -WIN_MOVE_PCT → LOSS
  SHORT     : آینه‌ای LONG
  PRE-MOVE  : مثل LONG/SHORT ولی با جهت BULLISH/BEARISH ذخیره می‌شود
  EARLY     : |حرکت| >= EARLY_WIN_MOVE → WIN (حرکت بزرگ آمد)
  WEAKENING : حرکت متوقف/برگشت → WIN، ادامهٔ قوی در جهت قبلی → LOSS
"""

import os
import time
from typing import Optional

import core
from core import http_get, http_post, log, num

# ============================================================
# CONFIG
# ============================================================

def _float(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()

# حداقل حرکت قیمت (٪) برای موفق دانستن LONG/SHORT در ۴ ساعت.
TRACKER_WIN_MOVE = _float("TRACKER_WIN_MOVE", "1.5")
# برای EARLY: حرکت بزرگ در هر جهت یعنی هشدار درست بوده.
TRACKER_EARLY_WIN_MOVE = _float("TRACKER_EARLY_WIN_MOVE", "2.0")

CHECK_1H = 3600
CHECK_4H = 4 * 3600
REPORT_INTERVAL = 24 * 3600
REPORT_WINDOW = 24 * 3600

TRACKING_ENABLED = bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)

_last_report = 0.0
_init_done = False


# ============================================================
# TURSO HTTP API
# ============================================================

def _base_url() -> str:
    url = TURSO_DATABASE_URL
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://"):]
    return url.rstrip("/")


def _arg(value) -> dict:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": repr(value)}
    return {"type": "text", "value": str(value)}


async def _execute(sql: str, args: Optional[list] = None):
    """اجرای یک statement و برگرداندن ردیف‌ها (لیست لیستی)."""
    stmt = {"sql": sql}
    if args:
        stmt["args"] = [_arg(a) for a in args]

    data = await http_post(
        f"{_base_url()}/v2/pipeline",
        {"requests": [{"type": "execute", "stmt": stmt},
                      {"type": "close"}]},
        {
            "Authorization": f"Bearer {TURSO_AUTH_TOKEN}",
            "content-type": "application/json",
        },
    )
    if not data:
        return None

    try:
        result = data["results"][0]
        if result.get("type") != "ok":
            log.warning("Turso error: %s", result.get("error"))
            return None
        rows = result["response"]["result"].get("rows", [])
        return [[cell.get("value") for cell in row] for row in rows]
    except (KeyError, IndexError, TypeError, AttributeError) as e:
        log.warning("Turso parse error: %s", e)
        return None


async def init_db() -> None:
    global _init_done
    if not TRACKING_ENABLED:
        log.info("TRACKER: disabled (set TURSO_DATABASE_URL + "
                 "TURSO_AUTH_TOKEN to enable)")
        return

    rows = await _execute(
        """
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT DEFAULT '',
            price REAL NOT NULL,
            ts REAL NOT NULL,
            result_1h TEXT,
            move_1h REAL,
            result_4h TEXT,
            move_4h REAL
        )
        """
    )
    if rows is None:
        log.warning("TRACKER: Turso init failed (check URL/token)")
        return

    _init_done = True
    log.info("TRACKER: Turso connected, table ready")


# ============================================================
# RECORD / EVALUATE
# ============================================================


async def record_signal(kind: str, symbol: str, direction: str,
                        price: float) -> None:
    if not (TRACKING_ENABLED and _init_done) or not price:
        return
    await _execute(
        "INSERT INTO signals (kind, symbol, direction, price, ts)"
        " VALUES (?, ?, ?, ?, ?)",
        [kind, symbol, direction, float(price), time.time()],
    )


def _evaluate(kind: str, direction: str, move_pct: float) -> str:
    if kind == "LONG":
        if move_pct >= TRACKER_WIN_MOVE:
            return "WIN"
        if move_pct <= -TRACKER_WIN_MOVE:
            return "LOSS"
        return "FLAT"
    if kind == "SHORT":
        if move_pct <= -TRACKER_WIN_MOVE:
            return "WIN"
        if move_pct >= TRACKER_WIN_MOVE:
            return "LOSS"
        return "FLAT"
    if kind == "PRE":
        # هشدار قبل از حرکت؛ جهت به‌صورت BULLISH/BEARISH ذخیره شده.
        if direction == "BULLISH":
            if move_pct >= TRACKER_WIN_MOVE:
                return "WIN"
            if move_pct <= -TRACKER_WIN_MOVE:
                return "LOSS"
            return "FLAT"
        if direction == "BEARISH":
            if move_pct <= -TRACKER_WIN_MOVE:
                return "WIN"
            if move_pct >= TRACKER_WIN_MOVE:
                return "LOSS"
            return "FLAT"
        return "FLAT"
    if kind == "EARLY":
        # هشدار زودهنگام موفق است اگر حرکت بزرگ آمد (هر جهت).
        return "WIN" if abs(move_pct) >= TRACKER_EARLY_WIN_MOVE else "FLAT"
    if kind == "WEAK":
        # هشدار تضعیف موفق است اگر حرکت ادامهٔ قوی نداشت.
        if direction == "UP":
            if move_pct >= TRACKER_WIN_MOVE:
                return "LOSS"   # حرکت صعودی ادامه یافت
            return "WIN"        # متوقف/برگشت/ضعیف شد
        if direction == "DOWN":
            if move_pct <= -TRACKER_WIN_MOVE:
                return "LOSS"
            return "WIN"
    return "FLAT"


async def _current_price(symbol: str) -> Optional[float]:
    data = await http_get(
        f"{core.BINANCE}/fapi/v1/ticker/price", {"symbol": symbol}
    )
    if not data:
        return None
    price = num(data.get("price"))
    return price or None


async def check_pending() -> None:
    """ارزیابی سیگنال‌های معلق (۱ ساعته و ۴ ساعته)."""
    if not (TRACKING_ENABLED and _init_done):
        return

    rows = await _execute(
        "SELECT id, kind, symbol, direction, price, ts, result_1h"
        " FROM signals WHERE result_4h IS NULL"
    )
    if not rows:
        return

    now = time.time()
    for row in rows:
        try:
            sig_id = int(row[0])
            kind, symbol, direction = row[1], row[2], row[3] or ""
            price, ts = float(row[4]), float(row[5])
            done_1h = row[6] is not None
        except (TypeError, ValueError, IndexError):
            continue

        age = now - ts
        if age < CHECK_1H:
            continue

        current = await _current_price(symbol)
        if not current or not price:
            continue

        move = (current - price) / price * 100
        result = _evaluate(kind, direction, move)

        if not done_1h:
            await _execute(
                "UPDATE signals SET result_1h = ?, move_1h = ?"
                " WHERE id = ?",
                [result, move, sig_id],
            )
            log.info("TRACKER 1h: %s %s -> %s (%+.2f%%)",
                     kind, symbol, result, move)

        if age >= CHECK_4H:
            await _execute(
                "UPDATE signals SET result_4h = ?, move_4h = ?"
                " WHERE id = ?",
                [result, move, sig_id],
            )
            log.info("TRACKER 4h: %s %s -> %s (%+.2f%%)",
                     kind, symbol, result, move)


# ============================================================
# STATS QUERIES (برای گزارش روزانه و منوی تلگرام)
# ============================================================


async def get_stats(since_ts: float):
    """
    آمار نتایج از یک زمان به بعد.
    برمی‌گرداند: (stats, pending)
      stats   : {kind: {"WIN": n, "LOSS": n, "FLAT": n}}  (ارزیابی‌شده‌ها)
      pending : {kind: n}  (هنوز ارزیابی نشده)
    """
    empty = ({}, {})
    if not (TRACKING_ENABLED and _init_done):
        return empty

    rows = await _execute(
        "SELECT kind, result_4h, COUNT(*) FROM signals"
        " WHERE ts >= ? AND result_4h IS NOT NULL"
        " GROUP BY kind, result_4h",
        [since_ts],
    )
    pend_rows = await _execute(
        "SELECT kind, COUNT(*) FROM signals"
        " WHERE ts >= ? AND result_4h IS NULL"
        " GROUP BY kind",
        [since_ts],
    )
    if rows is None and pend_rows is None:
        return empty

    stats: dict = {}
    for row in rows or []:
        try:
            kind, result = row[0], row[1]
            count = int(row[2])
        except (TypeError, ValueError, IndexError):
            continue
        stats.setdefault(kind, {"WIN": 0, "LOSS": 0, "FLAT": 0})
        stats[kind][result] = stats[kind].get(result, 0) + count

    pending: dict = {}
    for row in pend_rows or []:
        try:
            pending[row[0]] = int(row[1])
        except (TypeError, ValueError, IndexError):
            continue

    return stats, pending


async def get_recent(limit: int = 10) -> list:
    """آخرین سیگنال‌های ثبت‌شده (برای منوی تلگرام)."""
    if not (TRACKING_ENABLED and _init_done):
        return []
    rows = await _execute(
        "SELECT kind, symbol, direction, price, ts, result_4h, move_4h"
        " FROM signals ORDER BY id DESC LIMIT ?",
        [limit],
    )
    return rows or []


# ============================================================
# DAILY REPORT
# ============================================================

SEP = "━━━━━━━━━━━━━━━"
LRI = "⁦"
PDI = "⁩"


def _ltr(text) -> str:
    return f"{LRI}{text}{PDI}"


_KIND_LABEL = {
    "LONG": "🟢 LONG",
    "SHORT": "🔴 SHORT",
    "PRE": "🔥 PRE-MOVE",
    "EARLY": "⚡ EARLY",
    "WEAK": "⚪ WEAKENING",
}


async def maybe_daily_report(telegram_fn) -> None:
    global _last_report
    if not (TRACKING_ENABLED and _init_done):
        return

    now = time.time()
    if now - _last_report < REPORT_INTERVAL:
        return

    stats, pending = await get_stats(now - REPORT_WINDOW)
    if not stats and not pending:
        # هیچ داده‌ای نیست؛ ولی برای اینکه هر ۲۴ ساعت گم نشود،
        # فقط وقتی گزارش بده که واقعاً چیزی برای گفتن هست.
        _last_report = now
        return

    _last_report = now

    lines = []
    total_win = total_decisive = 0
    for kind, label in _KIND_LABEL.items():
        s = stats.get(kind)
        wait = pending.get(kind, 0)
        if not s and not wait:
            continue
        win, loss, flat = s["WIN"], s["LOSS"], s["FLAT"]
        decisive = win + loss
        total_win += win
        total_decisive += decisive
        pct = f"{win / decisive * 100:.0f}%" if decisive else "—"
        line = (
            f"{label} ┆ {_ltr(f'{win + loss + flat}')} سیگنال"
            f" · ✅ {_ltr(str(win))} · ❌ {_ltr(str(loss))}"
            f" · ➖ {_ltr(str(flat))} · موفقیت <b>{_ltr(pct)}</b>"
        )
        if wait:
            line += f" · ⏳ {_ltr(str(wait))}"
        lines.append(line)

    overall = (
        f"{total_win / total_decisive * 100:.0f}%" if total_decisive else "—"
    )

    await telegram_fn(
        "<b>📊 گزارش عملکرد ۲۴ ساعت گذشته</b>\n"
        f"{SEP}\n"
        + "\n".join(lines)
        + f"\n{SEP}\n"
        f"🎯 موفقیت کلی: <b>{_ltr(overall)}</b>\n"
        f"{SEP}\n"
        "ℹ️ بر اساس قیمت ۴ ساعت بعد از هر سیگنال"
        " · ⏳ = هنوز ارزیابی نشده"
    )
    log.info("TRACKER: daily report sent")
