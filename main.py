"""
Crypto AI Signal Bot — main
===========================

ربات سیگنال کریپتو — فقط سیگنال می‌دهد و هیچ معامله‌ای اجرا نمی‌کند.

این فایل نقطهٔ ورود است: تحلیل AI، ارسال تلگرام، حلقهٔ اسکنر،
اپ FastAPI و startup diagnostics. تمام منطق داده و تحلیل در core.py است.

هوش مصنوعی (به ترتیب اولویت، با fallback):
  Gemini -> Groq -> OpenRouter -> OpenAI

اجرا:
  python main.py
"""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI

import core
import weakening
from core import *  # noqa: F401,F403  (پیکربندی، دیتا، منطق سیگنال)

# مرجع به تسک اسکنر تا از garbage collection جلوگیری شود.
scanner_task: Optional[asyncio.Task] = None


# ============================================================
# AI
# ============================================================


def ai_providers() -> list:
    """ترتیب provider ها؛ AI_PROVIDER در صورت تنظیم اول می‌آید."""
    order = []
    if GEMINI_API_KEY:
        order.append("gemini")
    if GROQ_API_KEY:
        order.append("groq")
    if OPENROUTER_API_KEY:
        order.append("openrouter")
    if openai_client:
        order.append("openai")

    forced = AI_PROVIDER.strip().lower()
    if forced and forced in order:
        order.remove(forced)
        order.insert(0, forced)
    return order


async def openai_compatible(url, api_key, model, prompt, label):
    # Groq و OpenRouter هر دو API سازگار با OpenAI دارند.
    data = await http_post(
        url,
        {"model": model, "messages": [{"role": "user", "content": prompt}]},
        {
            "content-type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    if not data:
        return None

    try:
        text = data["choices"][0]["message"]["content"].strip()
        return text or None
    except (KeyError, IndexError, TypeError, AttributeError) as e:
        log.warning("%s PARSE ERROR: %s -> %s", label, e, str(data)[:200])
        return None


async def openai_analysis(prompt: str) -> Optional[str]:
    if not openai_client:
        return None
    try:
        response = await openai_client.responses.create(
            model=OPENAI_MODEL, input=prompt
        )
        return response.output_text.strip()
    except Exception as e:
        log.warning("OPENAI ERROR: %s", e)
        return None


async def gemini_analysis(prompt: str) -> Optional[str]:
    if not GEMINI_API_KEY:
        return None

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
    )
    data = await http_post(
        url,
        {"contents": [{"parts": [{"text": prompt}]}]},
        {
            "content-type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
        },
    )
    if not data:
        return None

    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
        return text or None
    except (KeyError, IndexError, TypeError) as e:
        log.warning("GEMINI PARSE ERROR: %s -> %s", e, str(data)[:200])
        return None


async def call_provider(provider: str, prompt: str) -> Optional[str]:
    if provider == "gemini":
        return await gemini_analysis(prompt)
    if provider == "groq":
        return await openai_compatible(
            "https://api.groq.com/openai/v1/chat/completions",
            GROQ_API_KEY, GROQ_MODEL, prompt, "GROQ",
        )
    if provider == "openrouter":
        return await openai_compatible(
            "https://openrouter.ai/api/v1/chat/completions",
            OPENROUTER_API_KEY, OPENROUTER_MODEL, prompt, "OPENROUTER",
        )
    if provider == "openai":
        return await openai_analysis(prompt)
    return None


async def ai_check() -> None:
    providers = ai_providers()
    if not providers:
        log.warning(
            "AI: no provider configured. Set one of GEMINI_API_KEY / "
            "GROQ_API_KEY / OPENROUTER_API_KEY / OPENAI_API_KEY."
        )
        return

    log.info("AI providers: %s", " -> ".join(providers))
    for provider in providers:
        text = await call_provider(provider, "Reply with exactly: OK")
        if text:
            log.info("AI check: %s OK -> %s", provider, text[:40])
            return
        log.warning("AI check: %s FAILED (bad key, quota, or model)", provider)

    log.error("AI check: *** ALL PROVIDERS FAILED ***")


AI_PROMPT_TEMPLATE = """
تو تحلیلگر یک ربات Crypto Signal هستی.

این ربات فقط سیگنال می‌دهد و معامله اجرا نمی‌کند.

داده زیر را به فارسی روان تحلیل کن.

باید توضیح بدهی:

1. حجم چه چیزی نشان می‌دهد؟
2. آیا پول وارد شده یا خارج شده؟
3. LiveCoinWatch چه چیزی نشان می‌دهد؟
4. CryptoMeter چه چیزی نشان می‌دهد؟
5. RSI در 15m / 1h / 4h چه می‌گوید؟
6. BTC Pair صعودی یا نزولی است؟
7. BTC.D / USDT.D / OTHERS.D / TOTAL2 / TOTAL3
   چقدر با جهت سیگنال هماهنگ هستند؟
8. آیا این حرکت early است یا حرکت شروع شده؟
9. تناقض یا ریسک اصلی چیست؟

هرگز:
Entry
Stop Loss
Take Profit
R:R

تولید نکن.

DATA:
{data}
"""


async def ai_analysis(data) -> str:
    providers = ai_providers()
    if not providers:
        return "AI فعال نیست؛ تحلیل عددی در پیام موجود است."

    prompt = AI_PROMPT_TEMPLATE.format(data=data)

    # اگر provider اول جواب نداد (quota یا خطای موقت)، بعدی امتحان می‌شود.
    for provider in providers:
        text = await call_provider(provider, prompt)
        if text:
            return text
        log.warning("AI: provider '%s' failed, trying next...", provider)

    return "تحلیل AI در دسترس نبود."


# ============================================================
# TELEGRAM
# ============================================================


async def telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM SKIPPED: TELEGRAM_BOT_TOKEN is empty.")
        return
    if not TELEGRAM_CHAT_ID:
        log.warning("TELEGRAM SKIPPED: TELEGRAM_CHAT_ID is empty.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    result = await http_post(
        url,
        {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
    )

    if not result or not result.get("ok"):
        log.error(
            "TELEGRAM SEND FAILED: %s",
            result.get("description") if isinstance(result, dict)
            else "no response",
        )


# ============================================================
# COOLDOWN
# ============================================================


def can_send(key: str) -> bool:
    now = time.time()
    if now - last_signals.get(key, 0) < SIGNAL_COOLDOWN:
        return False
    last_signals[key] = now

    # جلوگیری از رشد بی‌نهایت دیکشنری cooldown
    if len(last_signals) > 2000:
        prune_cache(last_signals, SIGNAL_COOLDOWN * 2)

    return True


# ============================================================
# MESSAGE FORMATTING
# ============================================================

SEP = "━━━━━━━━━━━━━━━"
FOOTER = "⚠️ <i>فقط سیگنال — بدون اجرای معامله</i>"


def fmt_big(n: float) -> str:
    """خلاصه‌نویسی اعداد بزرگ: 1.2K / 3.4M / 1.2B"""
    n = float(n)
    for unit in ("", "K", "M", "B", "T"):
        if abs(n) < 1000 or unit == "T":
            return f"{n:,.1f}{unit}" if unit else f"{n:,.0f}"
        n /= 1000
    return f"{n:,.1f}T"


def price_line(volume: Optional[dict]) -> str:
    if not volume or not volume.get("price"):
        return ""
    return f" 💵 <code>{volume['price']:,.8g}</code>"


def market_text(market: dict, direction: str) -> str:
    if direction == "LONG":
        details = market["long_details"]
        count = market["long"]
    else:
        details = market["short_details"]
        count = market["short"]

    row = " ".join(
        f"{check(details[k])}{k}" for k in
        ("BTC.D", "USDT.D", "OTHERS.D", "TOTAL2", "TOTAL3")
    )
    return f"{row}\n🎯 هم‌راستایی: <b>{count}/5</b>"


def flow_text(flow: Optional[dict]) -> str:
    if not flow:
        return "⚪ در دسترس نیست"

    inflow = num(flow.get("inflow"))
    outflow = num(flow.get("outflow"))
    netflow = num(flow.get("netflow"))

    if netflow > 0:
        direction = "🟢 ورود پول"
    elif netflow < 0:
        direction = "🔴 خروج پول"
    else:
        direction = "⚪ خنثی"

    total = inflow + outflow
    share = inflow / total * 100 if total else 0

    return (
        f"{direction} ┆ خالص {fmt_big(netflow)}\n"
        f"سهم خرید: <b>{share:.1f}%</b>"
    )


def oi_text(oi: Optional[dict]) -> str:
    if not oi:
        return "⚪ در دسترس نیست"

    change = oi["change_pct"]
    if change > 0:
        arrow, note = "🟢", "پول جدید وارد شده"
    elif change < 0:
        arrow, note = "🔴", "پوزیشن‌ها بسته می‌شوند"
    else:
        arrow, note = "⚪", "بدون تغییر"

    return (
        f"{arrow} <b>{change:+.2f}%</b> ({oi['candles']}×{oi['period']})"
        f" — {note}"
    )


def fg_text(fg: Optional[dict]) -> str:
    if not fg:
        return "⚪ در دسترس نیست"

    value = fg["value"]
    if value <= 25:
        emoji = "😱"
    elif value <= 45:
        emoji = "😟"
    elif value <= 55:
        emoji = "😐"
    elif value <= 75:
        emoji = "😀"
    else:
        emoji = "🤑"

    return f"{emoji} <b>{value}</b> — {fg['label']}"


def btc_text(btc: dict) -> str:
    dir_emoji = {
        "BULLISH": "🟢",
        "BEARISH": "🔴",
    }.get(btc["direction"], "⚪")

    change = btc["change"] if btc["change"] is not None else 0
    return (
        f"{btc['pair']} {dir_emoji} <b>{btc['direction']}</b>"
        f" ({change:+.2f}%)"
    )


def lwc_text(lwc: Optional[dict]) -> str:
    if not lwc:
        return "⚪ در دسترس نیست"
    return (
        f"Vol ${fmt_big(lwc['volume'])} ┆ V/MC {lwc['vol_to_mcap']:.2f}\n"
        f"1H {lwc['change_1h']:+.2f}% ┆ 24H {lwc['change_24h']:+.2f}%"
    )


def signal_message(direction, symbol, rsi_data, volume, lwc, flow, btc,
                   market, ai, oi=None, fg=None) -> str:
    emoji = "🟢" if direction == "LONG" else "🔴"

    return f"""
<b>{emoji} {direction} SIGNAL {emoji}</b>
🪙 <b>#{symbol}</b>{price_line(volume)}
{SEP}
📊 <b>RSI</b> ┆ 15m <b>{rsi_data['15m']:.1f}</b> ┆ 1H <b>{rsi_data['1h']:.1f}</b> ┆ 4H <b>{rsi_data['4h']:.1f}</b>
📈 <b>VOLUME</b> ┆ <b>{volume['volume_ratio']:.2f}x</b> ┆ {volume['price_move']:+.2f}% ┆ خرید <b>{volume['buy_ratio'] * 100:.1f}%</b>
📦 <b>OI</b> ┆ {oi_text(oi)}
💰 <b>FLOW</b> ┆ {flow_text(flow)}
₿ <b>BTC PAIR</b> ┆ {btc_text(btc)}
🌍 <b>DOMINANCE</b>
{market_text(market, direction)}
🌐 <b>LWC</b> ┆ {lwc_text(lwc)}
😨 <b>SENTIMENT</b> ┆ {fg_text(fg)}
{SEP}
🤖 <b>AI ANALYSIS</b>
{ai}
{SEP}
{FOOTER}
"""


def early_message(symbol, volume, lwc, flow, oi=None, fg=None) -> str:
    lwc = lwc or {}
    return f"""
<b>🟡 EARLY WATCH 🟡</b>
🪙 <b>#{symbol}</b>{price_line(volume)}
حجم و پول وارد شده، اما قیمت هنوز حرکت نکرده.
{SEP}
📈 <b>VOLUME</b> ┆ <b>{volume['volume_ratio']:.2f}x</b> ┆ {volume['price_move']:+.2f}% ┆ خرید <b>{volume['buy_ratio'] * 100:.1f}%</b>
📦 <b>OI</b> ┆ {oi_text(oi)}
💰 <b>FLOW</b> ┆ {flow_text(flow)}
🌐 <b>LWC</b> ┆ {lwc_text(lwc)}
😨 <b>SENTIMENT</b> ┆ {fg_text(fg)}
{SEP}
🟡 هنوز سیگنال نهایی LONG/SHORT نیست.
{FOOTER}
"""


# ============================================================
# SCANNER
# ============================================================

scan_semaphore = asyncio.Semaphore(SCAN_CONCURRENCY)


async def scan_symbol(symbol: str, lwc_coin: Optional[dict],
                      market: dict, fg: Optional[dict]) -> None:
    """تحلیل یک نماد: early watch، سیگنال نهایی و weakening."""
    async with scan_semaphore:
        try:
            volume = await volume_analysis(symbol)
            if not volume:
                return

            # ورود/خروج پول و تغییر OI همین نماد (همزمان)
            flow_coin, oi = await asyncio.gather(
                money_flow(symbol),
                binance_open_interest(symbol),
            )

            # ==========================
            # EARLY WATCH
            # ==========================
            if early_watch(volume, lwc_coin, flow_coin):
                key = f"EARLY:{symbol}"
                if can_send(key):
                    await telegram(
                        early_message(
                            symbol, volume, lwc_coin or {},
                            flow_coin or {}, oi, fg,
                        )
                    )
                    log.info("EARLY WATCH: %s", symbol)

            # ==========================
            # WEAKENING (سیگنال سوم)
            # ==========================
            # مستقل از آستانهٔ حجم چک می‌شود؛ تضعیف حرکت
            # معمولاً با خشک شدن حجم همراه است.
            weak = await weakening.detect_weakening(symbol, flow_coin, oi)
            if weak:
                key = f"WEAK:{weak['direction']}:{symbol}"
                if can_send(key):
                    await telegram(
                        weakening.weakening_message(
                            weak, symbol, flow_coin, oi,
                            flow_text, oi_text,
                        )
                    )
                    log.info("WEAKENING: %s %s", weak["direction"], symbol)

            # ==========================
            # FINAL SIGNAL
            # ==========================
            if volume["volume_ratio"] < VOLUME_MULTIPLIER:
                return

            rsi_data, btc = await asyncio.gather(
                all_rsi(symbol),
                btc_pair(symbol),
            )

            direction = detect_signal(
                rsi_data, volume, flow_coin, btc, market, oi, fg
            )
            if not direction:
                return

            key = f"{direction}:{symbol}"
            if not can_send(key):
                return

            signal_data = {
                "symbol": symbol,
                "direction": direction,
                "rsi": rsi_data,
                "volume": volume,
                "livecoinwatch": lwc_coin,
                "money_flow": flow_coin,
                "open_interest": oi,
                "fear_greed": fg,
                "btc_pair": btc,
                "market": market,
            }

            ai = await ai_analysis(signal_data)

            await telegram(
                signal_message(
                    direction, symbol, rsi_data, volume, lwc_coin,
                    flow_coin, btc, market, ai, oi, fg,
                )
            )
            log.info("SIGNAL: %s %s", direction, symbol)

            await asyncio.sleep(0.25)

        except Exception as e:
            log.error("SCAN ERROR %s: %s", symbol, e)


async def scan() -> None:
    log.info("Scanning market...")

    # ------------------------------
    # DOMINANCE + EXTERNAL DATA
    # ------------------------------
    dominance = await get_dominance()
    market = market_alignment(dominance, core.previous_dominance)
    if dominance:
        core.previous_dominance = dominance

    # این سه مستقل‌اند و همزمان گرفته می‌شوند.
    lwc, _, fg = await asyncio.gather(
        livecoinwatch(),
        cryptometer_flow(),  # کش می‌شود؛ money_flow بعداً از کش می‌خواند
        fear_greed(),
    )

    have_external_data = bool(lwc)
    if not have_external_data:
        log.warning(
            "LiveCoinWatch returned no data. "
            "Falling back to top-volume symbols only."
        )

    # ------------------------------
    # BINANCE
    # ------------------------------
    symbols, tickers = await asyncio.gather(
        binance_symbols(),
        binance_tickers(),
    )

    candidates = []
    for symbol in symbols:
        ticker = tickers.get(symbol)
        if not ticker:
            continue

        quote_volume = num(ticker.get("quoteVolume"))
        if quote_volume <= 0:
            continue

        base = symbol.replace("USDT", "")
        lwc_coin = lwc.get(base)

        # اگر دادهٔ خارجی داریم ولی برای این کوین چیزی نیست، رد می‌شود.
        # بدون هیچ دادهٔ خارجی، اسکن متوقف نمی‌شود.
        if not lwc_coin and have_external_data:
            continue

        candidates.append((symbol, quote_volume, lwc_coin))

    candidates.sort(key=lambda x: x[1], reverse=True)
    candidates = candidates[:MAX_SYMBOLS]

    log.info("Candidates: %d", len(candidates))

    # ------------------------------
    # COIN SCAN (همزمان با محدودیت)
    # ------------------------------
    await asyncio.gather(
        *(scan_symbol(symbol, lwc_coin, market, fg)
          for symbol, _, lwc_coin in candidates)
    )

    # پاک‌سازی دوره‌ای کش‌های per-symbol
    prune_cache(flow_cache, FLOW_INTERVAL * 4)
    prune_cache(oi_cache, FLOW_INTERVAL * 4)


# ============================================================
# BACKGROUND LOOP
# ============================================================


async def scanner_loop() -> None:
    await asyncio.sleep(10)
    while True:
        try:
            await scan()
        except Exception as e:
            log.exception("GLOBAL SCANNER ERROR: %s", e)
        await asyncio.sleep(SCAN_INTERVAL)


# ============================================================
# LIFESPAN
# ============================================================


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    global scanner_task

    await startup_diagnostics()

    scanner_task = asyncio.create_task(scanner_loop())
    log.info("Scanner task started.")

    try:
        yield
    finally:
        scanner_task.cancel()
        await asyncio.gather(scanner_task, return_exceptions=True)
        if core.http_session and not core.http_session.closed:
            await core.http_session.close()


# ============================================================
# APP
# ============================================================

app = FastAPI(title="Crypto AI Signal Bot", lifespan=lifespan)


# ============================================================
# STARTUP DIAGNOSTICS
# ============================================================


async def startup_diagnostics() -> None:
    def mark(value: str) -> str:
        return "set" if value else "*** MISSING ***"

    log.info("=" * 55)
    log.info("Crypto AI Signal Bot - startup check")
    log.info("PORT: %s", os.getenv("PORT", "<not set>"))
    log.info("TELEGRAM_BOT_TOKEN: %s", mark(TELEGRAM_BOT_TOKEN))
    log.info("TELEGRAM_CHAT_ID: %s", mark(TELEGRAM_CHAT_ID))
    log.info("OPENAI_API_KEY: %s", "set" if OPENAI_API_KEY else "not set")
    log.info("GEMINI_API_KEY: %s", "set" if GEMINI_API_KEY else "not set")
    log.info("GROQ_API_KEY: %s", "set" if GROQ_API_KEY else "not set")
    log.info("OPENROUTER_API_KEY: %s",
             "set" if OPENROUTER_API_KEY else "not set")
    log.info("LIVECOINWATCH_API_KEY: %s", mark(LIVECOINWATCH_API_KEY))
    log.info("CRYPTOMETER_API_KEY: %s",
             "set" if CRYPTOMETER_API_KEY else "not set")
    log.info("MONEY FLOW: CryptoMeter if paid plan active, "
             "else Binance futures taker (free)")
    log.info("COINMARKETCAP_API_KEY: %s",
             "set (last-resort fallback)" if COINMARKETCAP_API_KEY
             else "not set (not needed)")
    log.info("DOMINANCE SOURCE: CoinGecko -> Coinpaprika%s",
             " -> CoinMarketCap" if COINMARKETCAP_API_KEY else "")
    log.info("DOMINANCE_INTERVAL: %ds | SCAN_INTERVAL: %ds",
             DOMINANCE_INTERVAL, SCAN_INTERVAL)
    log.info("WEAKENING: %s",
             "enabled" if weakening.WEAKENING_ENABLED else "disabled")
    log.info("=" * 55)

    # بررسی واقعی provider هوش مصنوعی
    await ai_check()

    if not TELEGRAM_BOT_TOKEN:
        log.error(
            "TELEGRAM_BOT_TOKEN is missing. No message can be sent. "
            "Set it in the Render dashboard -> Environment."
        )
        return

    # اعتبارسنجی توکن ربات تلگرام
    me = await http_get(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"
    )
    if not me or not me.get("ok"):
        log.error(
            "TELEGRAM_BOT_TOKEN is invalid -> %s",
            me.get("description") if isinstance(me, dict) else "no response",
        )
        return

    log.info("Telegram bot OK: %s", me["result"].get("username"))

    if not TELEGRAM_CHAT_ID:
        log.error("TELEGRAM_CHAT_ID is missing.")
        return

    # اعتبارسنجی chat id
    chat = await http_get(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getChat",
        {"chat_id": TELEGRAM_CHAT_ID},
    )
    if not chat or not chat.get("ok"):
        log.error(
            "TELEGRAM_CHAT_ID is invalid -> %s",
            chat.get("description") if isinstance(chat, dict)
            else "no response",
        )
    else:
        log.info("Telegram chat OK: %s", chat["result"].get("type"))


@app.get("/")
async def health():
    return {
        "status": "online",
        "execution": False,
        "binance": True,
        "livecoinwatch": bool(LIVECOINWATCH_API_KEY),
        "money_flow": "binance-futures-taker",
        "dominance": "coingecko -> coinpaprika",
        "open_interest": "binance-futures",
        "sentiment": "alternative.me",
        "coinmarketcap": bool(COINMARKETCAP_API_KEY),
        "weakening": weakening.WEAKENING_ENABLED,
        "ai": ai_providers(),
    }


# ============================================================
# ENTRYPOINT (Render / Uvicorn)
# ============================================================

# Render متغیر PORT را خودش تعیین می‌کند و اپ باید
# روی 0.0.0.0 گوش بدهد (نه 127.0.0.1).

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    log.info("Starting uvicorn on 0.0.0.0:%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
