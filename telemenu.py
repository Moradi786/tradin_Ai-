"""
منوی کمکی تلگرام (/menu)
========================

به فرمان‌های /menu و /start جواب می‌دهد و یک کیبورد شیشه‌ای
(دکمه‌ای) می‌دهد برای دیدن عملکرد سیگنال‌ها:

  📊 آمار ۲۴ ساعت      → درصد موفقیت هر نوع سیگنال در ۲۴ ساعت
  📈 آمار ۷ روز        → همین برای ۷ روز گذشته
  🕒 آخرین سیگنال‌ها   → ۱۰ سیگنال اخیر + نتیجهٔ هرکدام
  ℹ️ راهنما            → توضیح کوتاه هر نوع سیگنال

پیام‌های کاربر با getUpdates (long polling) خوانده می‌شود؛
نیازی به وب‌هوک نیست. فقط وقتی فعال می‌شود که tracker هم فعال
باشد (TURSO_DATABASE_URL + TURSO_AUTH_TOKEN).

این ماژول توسط main.py ایمپورت می‌شود.
"""

import asyncio
import time
from typing import Optional

import core
import tracker
from core import http_get, http_post, log

# ============================================================
# CONFIG
# ============================================================

API = f"https://api.telegram.org/bot{core.TELEGRAM_BOT_TOKEN}"

# فقط به همین چت جواب می‌دهد تا هرکسی نتواند آمار را ببیند.
ALLOWED_CHAT = str(core.TELEGRAM_CHAT_ID).strip()

MENU_BUTTONS = {
    "inline_keyboard": [
        [
            {"text": "📊 آمار ۲۴ ساعت", "callback_data": "stats_24h"},
            {"text": "📈 آمار ۷ روز", "callback_data": "stats_7d"},
        ],
        [
            {"text": "🕒 آخرین سیگنال‌ها", "callback_data": "recent"},
            {"text": "ℹ️ راهنما", "callback_data": "help"},
        ],
    ]
}

# وضعیت long polling
_offset = 0


def enabled() -> bool:
    return bool(core.TELEGRAM_BOT_TOKEN and tracker.TRACKING_ENABLED)


# ============================================================
# BIDI / FORMAT HELPERS
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
    "ROT": "💱 ROTATION",
    "EARLY": "⚡ EARLY",
    "WEAK": "⚪ WEAKENING",
}

_RESULT_EMOJI = {"WIN": "✅", "LOSS": "❌", "FLAT": "➖"}


# ============================================================
# TEXTS
# ============================================================


def menu_text() -> str:
    return (
        "<b>🎛 منوی ربات</b>\n"
        f"{SEP}\n"
        "از دکمه‌های زیر عملکرد سیگنال‌ها را ببین:"
    )


def help_text() -> str:
    return (
        "<b>ℹ️ راهنمای سیگنال‌ها</b>\n"
        f"{SEP}\n"
        "🟢🔴 LONG/SHORT ┆ سیگنال نهایی — موفق اگر قیمت ظرف "
        "۴ ساعت حداقل ۱.۵٪ در جهت سیگنال برود\n"
        "🔥 PRE-MOVE ┆ قبل از حرکت — نشانه‌های ورود پول وقتی "
        "قیمت هنوز جایی نرفته\n"
        "💱 ROTATION ┆ ترکیب طلایی — BTC.D نزولی + آلت قوی‌تر "
        "از بیت + ورود پول و OI صعودی\n"
        "⚡ EARLY ┆ هشدار زودهنگام — موفق اگر حرکت بزرگ "
        "(۲٪+) بیاید\n"
        "⚪ WEAKENING ┆ هشدار مردن حرکت — موفق اگر روند "
        "ادامهٔ قوی پیدا نکند\n"
        f"{SEP}\n"
        "✅ موفق · ❌ ناموفق · ➖ خنثی · ⏳ هنوز ارزیابی نشده\n"
        "ارزیابی: ۱ ساعت و ۴ ساعت بعد از هر سیگنال"
    )


def stats_text(title: str, stats: dict, pending: dict) -> str:
    if not stats and not pending:
        return (
            f"<b>{title}</b>\n{SEP}\n"
            "هنوز سیگنالی ثبت نشده. اول باید ربات سیگنال بفرستد."
        )

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
            f"{label} ┆ ✅ {_ltr(str(win))} · ❌ {_ltr(str(loss))}"
            f" · ➖ {_ltr(str(flat))} · موفقیت <b>{_ltr(pct)}</b>"
        )
        if wait:
            line += f" · ⏳ {_ltr(str(wait))}"
        lines.append(line)

    overall = (
        f"{total_win / total_decisive * 100:.0f}%" if total_decisive else "—"
    )
    body = "\n".join(lines) if lines else "سیگنالی در این بازه نیست."

    return (
        f"<b>{title}</b>\n{SEP}\n"
        f"{body}\n{SEP}\n"
        f"🎯 موفقیت کلی: <b>{_ltr(overall)}</b>"
    )


def recent_text(rows: list) -> str:
    if not rows:
        return (
            "<b>🕒 آخرین سیگنال‌ها</b>\n"
            f"{SEP}\n"
            "هنوز سیگنالی ثبت نشده."
        )

    lines = []
    for row in rows:
        try:
            kind, symbol = row[0], row[1]
            result, move = row[5], row[6]
        except (TypeError, IndexError):
            continue
        label = _KIND_LABEL.get(kind, kind)
        if result:
            emoji = _RESULT_EMOJI.get(result, "❓")
            move_txt = f" {_ltr(f'{float(move):+.2f}%')}" if move is not None else ""
        else:
            emoji, move_txt = "⏳", ""
        lines.append(f"{emoji} {label} ┆ #{_ltr(symbol)}{move_txt}")

    return (
        "<b>🕒 آخرین سیگنال‌ها</b>\n"
        f"{SEP}\n"
        + "\n".join(lines)
    )


# ============================================================
# TELEGRAM API
# ============================================================


async def _send(chat_id, text: str, reply_markup: Optional[dict] = None) -> None:
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    await http_post(f"{API}/sendMessage", payload)


async def _answer_callback(callback_id: str) -> None:
    await http_post(f"{API}/answerCallbackQuery",
                    {"callback_query_id": callback_id})


# ============================================================
# HANDLERS
# ============================================================


async def _handle_message(message: dict) -> None:
    chat_id = str((message.get("chat") or {}).get("id", ""))
    if ALLOWED_CHAT and chat_id != ALLOWED_CHAT:
        return

    text = (message.get("text") or "").strip().lower()
    if text.startswith(("/menu", "/start", "/stats")):
        await _send(chat_id, menu_text(), MENU_BUTTONS)


async def _handle_callback(query: dict) -> None:
    await _answer_callback(query.get("id", ""))

    chat_id = str(((query.get("message") or {}).get("chat") or {})
                  .get("id", ""))
    if ALLOWED_CHAT and chat_id != ALLOWED_CHAT:
        return
    if not chat_id:
        return

    action = query.get("data", "")
    now = time.time()

    if action == "stats_24h":
        stats, pending = await tracker.get_stats(now - 24 * 3600)
        await _send(chat_id, stats_text("📊 آمار ۲۴ ساعت گذشته",
                                        stats, pending), MENU_BUTTONS)
    elif action == "stats_7d":
        stats, pending = await tracker.get_stats(now - 7 * 24 * 3600)
        await _send(chat_id, stats_text("📈 آمار ۷ روز گذشته",
                                        stats, pending), MENU_BUTTONS)
    elif action == "recent":
        rows = await tracker.get_recent(10)
        await _send(chat_id, recent_text(rows), MENU_BUTTONS)
    elif action == "help":
        await _send(chat_id, help_text(), MENU_BUTTONS)
    else:
        await _send(chat_id, menu_text(), MENU_BUTTONS)


# ============================================================
# POLLING LOOP
# ============================================================


async def polling_loop() -> None:
    """خواندن پیام‌های کاربر با long polling (بدون وب‌هوک)."""
    global _offset

    if not enabled():
        log.info("TELEMENU: disabled (tracking off or no bot token)")
        return

    log.info("TELEMENU: /menu listener started")
    await asyncio.sleep(15)  # کمی صبر بعد از استارتاپ

    while True:
        try:
            data = await http_get(
                f"{API}/getUpdates",
                {"offset": _offset, "timeout": 10,
                 "allowed_updates": '["message","callback_query"]'},
            )
            if not data or not data.get("ok"):
                await asyncio.sleep(10)
                continue

            for update in data.get("result", []):
                _offset = max(_offset, update.get("update_id", 0) + 1)
                try:
                    if update.get("message"):
                        await _handle_message(update["message"])
                    elif update.get("callback_query"):
                        await _handle_callback(update["callback_query"])
                except Exception as e:
                    log.warning("TELEMENU handle error: %s", e)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("TELEMENU poll error: %s", e)
            await asyncio.sleep(10)
