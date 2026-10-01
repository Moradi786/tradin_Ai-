"""
Crypto AI Signal Bot — core
============================

پیکربندی، کلاینت HTTP، کش‌ها و تمام منابع داده و منطق تحلیل.
این ماژول توسط main.py ایمپورت می‌شود.

منابع داده:
  - Binance Futures   : klines, tickers, taker flow, open interest (اصلی)
  - Bybit             : fallback کامل وقتی بایننس بن است (klines/tickers/OI)
  - OKX               : fallback جریان پول (taker buy/sell) هنگام بن بایننس
  - CoinGecko         : dominance / global market (رایگان، بدون کلید)
  - Coinpaprika       : fallback دادهٔ سراسری (رایگان)
  - CoinMarketCap     : آخرین fallback (در صورت داشتن کلید)
  - LiveCoinWatch     : دادهٔ بازار هر کوین (نیازمند کلید)
  - CryptoMeter       : volume flow (endpoint پولی — اختیاری)
  - alternative.me    : Fear & Greed (رایگان)

نکتهٔ مهم دربارهٔ بن: بن بایننس روی آی‌پی اشتراکی Render فقط مخصوص
همان صرافی است. وقتی بایننس بن باشد، ربات خودکار با Bybit + OKX
به اسکن ادامه می‌دهد و بعد از پایان بن به بایننس برمی‌گردد.
"""

import asyncio
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Optional

import aiohttp
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from openai import AsyncOpenAI

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("signal-bot")

# ============================================================
# ENV / CONFIG
# ============================================================

load_dotenv()


def _int(name: str, default: str) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        log.warning("Invalid int for %s, using default %s", name, default)
        return int(default)


def _float(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        log.warning("Invalid float for %s, using default %s", name, default)
        return float(default)


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")

# Gemini (Google AI Studio) به‌عنوان provider جایگزین.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

# Groq - پلن رایگان، API سازگار با OpenAI.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# OpenRouter - مدل‌های :free هم دارد.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"
)

# اختیاری: اگر ست شود، این provider اول امتحان می‌شود.
AI_PROVIDER = os.getenv("AI_PROVIDER", "")

LIVECOINWATCH_API_KEY = os.getenv("LIVECOINWATCH_API_KEY", "")
CRYPTOMETER_API_KEY = os.getenv("CRYPTOMETER_API_KEY", "")
COINMARKETCAP_API_KEY = os.getenv("COINMARKETCAP_API_KEY", "")

SCAN_INTERVAL = _int("SCAN_INTERVAL", "120")
MAX_SYMBOLS = _int("MAX_SYMBOLS", "100")

# حداکثر تحلیل همزمان نمادها. بالا بردن آن سرعت اسکن را
# زیاد می‌کند اما ریسک rate-limit بایننس را هم بالا می‌برد.
SCAN_CONCURRENCY = _int("SCAN_CONCURRENCY", "8")

VOLUME_MULTIPLIER = _float("VOLUME_MULTIPLIER", "2.0")
MAX_PRICE_MOVE = _float("MAX_PRICE_MOVE", "1.5")
VOLUME_LOOKBACK = _int("VOLUME_LOOKBACK", "20")

LONG_RSI_15M = _float("LONG_RSI_15M", "35")
LONG_RSI_1H = _float("LONG_RSI_1H", "40")
LONG_RSI_4H = _float("LONG_RSI_4H", "45")

SHORT_RSI_15M = _float("SHORT_RSI_15M", "65")
SHORT_RSI_1H = _float("SHORT_RSI_1H", "60")
SHORT_RSI_4H = _float("SHORT_RSI_4H", "55")

SIGNAL_COOLDOWN = _int("SIGNAL_COOLDOWN", "1800")

CRYPTOMETER_FLOW_INTERVAL = _int("CRYPTOMETER_FLOW_INTERVAL", "600")
CRYPTOMETER_TIMEFRAME = os.getenv("CRYPTOMETER_TIMEFRAME", "15m")

LWC_INTERVAL = _int("LWC_INTERVAL", "120")
CMC_INTERVAL = _int("CMC_INTERVAL", "300")

# TTL دادهٔ Global Market. عمداً کمتر از SCAN_INTERVAL است تا
# هر اسکن دادهٔ تازه ببیند و market_alignment همیشه ۰/۵ نشود.
DOMINANCE_INTERVAL = _int("DOMINANCE_INTERVAL", "60")

LWC_LIMIT = _int("LWC_LIMIT", "100")

# ------------------------------------------------------------
# BINANCE RATE LIMIT
# ------------------------------------------------------------

# کش لیست tickers (وزن بالای endpoint /ticker/24hr بدون symbol).
TICKERS_INTERVAL = _int("TICKERS_INTERVAL", "60")

# اگر بایننس 418/429 بدهد و زمان دقیق بن در پاسخ نباشد،
# این مدت مکث می‌کنیم.
BINANCE_BLOCK_PAUSE = _int("BINANCE_BLOCK_PAUSE", "300")

# ------------------------------------------------------------
# OPEN INTEREST
# ------------------------------------------------------------

OI_PERIOD = os.getenv("OI_PERIOD", "15m")
OI_LOOKBACK = _int("OI_LOOKBACK", "5")

# اگر true شود، LONG فقط با OI صعودی و SHORT فقط با OI نزولی.
REQUIRE_OI_RISING = _bool("REQUIRE_OI_RISING")

# ------------------------------------------------------------
# FEAR & GREED (alternative.me - رایگان)
# ------------------------------------------------------------

FEAR_GREED_INTERVAL = _int("FEAR_GREED_INTERVAL", "3600")

# 0 = غیرفعال. اگر >0 باشد، در هیجان افراطی جلوی سیگنال گرفته می‌شود.
FEAR_GREED_MAX_LONG = _float("FEAR_GREED_MAX_LONG", "0")
FEAR_GREED_MIN_SHORT = _float("FEAR_GREED_MIN_SHORT", "0")

EARLY_FLOW_RATIO = _float("EARLY_FLOW_RATIO", "0.08")
EARLY_VOLUME_RATIO = _float("EARLY_VOLUME_RATIO", "1.3")
MIN_FLOW_RATIO_SIGNAL = _float("MIN_FLOW_RATIO_SIGNAL", "0.15")

# Money Flow از مشتقات بایننس (رایگان). بایننس هر ۵ دقیقه آپدیت می‌کند.
FLOW_INTERVAL = _int("FLOW_INTERVAL", "300")
FLOW_PERIOD = os.getenv("FLOW_PERIOD", "15m")

# آستانهٔ مخصوص حجم taker بایننس/OKX؛ مقیاسش با CryptoMeter فرق دارد.
BINANCE_FLOW_MIN_RATIO = _float("BINANCE_FLOW_MIN_RATIO", "0.06")

BINANCE = "https://fapi.binance.com"

# ============================================================
# CLIENTS / CACHE
# ============================================================

http_session: Optional[aiohttp.ClientSession] = None

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# cooldown سیگنال‌ها: key -> timestamp
last_signals: dict = {}

previous_dominance: Optional[dict] = None

lwc_cache = {"timestamp": 0.0, "data": {}}
cryptometer_cache = {"timestamp": 0.0, "data": {}}
tickers_cache = {"timestamp": 0.0, "data": {}}

# کش Money Flow و Open Interest هر نماد (per-symbol).
flow_cache: dict = {}
oi_cache: dict = {}

global_cache = {"timestamp": 0.0, "data": None}
fear_greed_cache = {"timestamp": 0.0, "data": None}

# اگر CryptoMeter endpoint پولی باشد، بعد از اولین خطا غیرفعال می‌شود.
cryptometer_disabled = False

# تا این زمان (epoch ثانیه)، درخواست‌های بایننس متوقف می‌مانند.
binance_blocked_until = 0.0

# ============================================================
# HTTP
# ============================================================

# بایننس در پاسخ 418 زمان دقیق پایان بن را می‌گوید:
#   "... banned until 1790845015074. ..."  (میلی‌ثانیه)
_BAN_RE = re.compile(r"banned until (\d+)")


async def get_session() -> aiohttp.ClientSession:
    global http_session
    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        )
    return http_session


def _mark_binance_blocked(body: str) -> None:
    """اگر زمان دقیق بن در پاسخ باشد تا همان لحظه مکث می‌کنیم."""
    global binance_blocked_until
    match = _BAN_RE.search(body or "")
    if match:
        # +60 ثانیه حاشیهٔ اطمینان بعد از پایان بن
        until = int(match.group(1)) / 1000 + 60
        binance_blocked_until = max(binance_blocked_until, until)
        log.warning(
            "Binance ban: scans paused for %ds (until ban expiry)",
            int(binance_blocked_until - time.time()),
        )
    else:
        binance_blocked_until = max(
            binance_blocked_until, time.time() + BINANCE_BLOCK_PAUSE
        )
        log.warning(
            "Binance rate-limited; scans paused for %ds",
            BINANCE_BLOCK_PAUSE,
        )


async def _request(method: str, url: str, retries: int = 2, **kwargs):
    """درخواست HTTP با retry ساده. در خطا None برمی‌گرداند."""
    session = await get_session()
    for attempt in range(retries + 1):
        try:
            async with session.request(method, url, **kwargs) as response:
                if response.status != 200:
                    body = await response.text()
                    log.warning(
                        "HTTP %s %s -> %s: %s",
                        method, url, response.status, body[:300],
                    )
                    # بن/ریت‌لیمیت بایننس: اسکن‌ها تا پایان بن متوقف می‌شوند.
                    if response.status in (418, 429) and "binance" in url:
                        _mark_binance_blocked(body)
                    # خطای 4xx با retry درست نمی‌شود.
                    if 400 <= response.status < 500:
                        return None
                    continue
                return await response.json()
        except Exception as e:
            log.warning("REQUEST %s %s failed (attempt %d): %s",
                        method, url, attempt + 1, e)
            await asyncio.sleep(1.5 * (attempt + 1))
    return None


async def http_get(url, params=None, headers=None):
    return await _request("GET", url, params=params, headers=headers)


async def http_post(url, payload, headers=None):
    return await _request("POST", url, json=payload, headers=headers)


# ============================================================
# HELPERS
# ============================================================


def num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def check(value) -> str:
    return "✅" if value else "❌"


def prune_cache(cache: dict, max_age: float) -> None:
    """جلوگیری از رشد بی‌نهایت کش‌های per-symbol و cooldown."""
    now = time.time()
    stale = [
        k for k, v in cache.items()
        if now - (v.get("timestamp", 0) if isinstance(v, dict) else v) > max_age
    ]
    for k in stale:
        cache.pop(k, None)
    if stale:
        log.debug("Pruned %d stale cache entries", len(stale))


def binance_blocked() -> bool:
    return time.time() < binance_blocked_until


# ============================================================
# BYBIT (fallback وقتی بایننس بن است)
# ============================================================

BYBIT = "https://api.bybit.com"
OKX = "https://www.okx.com"

_BYBIT_INTERVAL = {
    "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "2h": "120", "4h": "240", "1d": "D",
}


async def bybit_klines(symbol: str, interval: str, limit: int = 100) -> list:
    """کندل‌های Bybit، تبدیل‌شده به قالب بایننس تا بقیهٔ کد عوض نشود."""
    data = await http_get(
        f"{BYBIT}/v5/market/kline",
        {
            "category": "linear",
            "symbol": symbol,
            "interval": _BYBIT_INTERVAL.get(interval, "15"),
            "limit": limit,
        },
    )
    if not data or str(data.get("retCode")) != "0":
        return []

    rows = (data.get("result") or {}).get("list") or []
    # Bybit جدیدترین را اول می‌دهد؛ بایننس قدیمی‌ترین را.
    rows = list(reversed(rows))

    # قالب بایننس: [open_time, open, high, low, close, volume,
    #               close_time, quote_volume, trades, ..., taker_buy, ...]
    # Bybit تفکیک taker buy ندارد → اندیس ۱۰ = ۰ → buy_ratio خنثی (0.5)
    return [
        [r[0], r[1], r[2], r[3], r[4], r[5], 0, r[6], 0, 0, "0", "0"]
        for r in rows
    ]


async def bybit_tickers() -> dict:
    data = await http_get(
        f"{BYBIT}/v5/market/tickers", {"category": "linear"}
    )
    if not data or str(data.get("retCode")) != "0":
        return {}

    result = {}
    for item in (data.get("result") or {}).get("list") or []:
        symbol = item.get("symbol")
        if symbol and str(symbol).endswith("USDT"):
            result[symbol] = {
                "symbol": symbol,
                "quoteVolume": item.get("turnover24h") or "0",
                # Bybit درصد را به‌صورت نسبت می‌دهد (0.0123 = 1.23٪)
                "priceChangePercent": num(item.get("price24hPcnt")) * 100,
            }
    return result


async def bybit_symbols() -> list:
    data = await http_get(
        f"{BYBIT}/v5/market/instruments-info",
        {"category": "linear", "limit": 1000},
    )
    if not data or str(data.get("retCode")) != "0":
        return []

    return [
        item["symbol"]
        for item in (data.get("result") or {}).get("list") or []
        if item.get("status") == "Trading"
        and item.get("quoteCoin") == "USDT"
        and item.get("contractType") == "LinearPerpetual"
        and str(item.get("symbol", "")).endswith("USDT")
    ]


async def bybit_open_interest(symbol: str) -> Optional[dict]:
    data = await http_get(
        f"{BYBIT}/v5/market/open-interest",
        {
            "category": "linear",
            "symbol": symbol,
            "intervalTime": "15min",
            "limit": OI_LOOKBACK,
        },
    )
    if not data or str(data.get("retCode")) != "0":
        return None

    rows = (data.get("result") or {}).get("list") or []
    if len(rows) < 2:
        return None

    # Bybit جدیدترین را اول می‌دهد.
    first = num(rows[-1].get("openInterest"))
    last = num(rows[0].get("openInterest"))
    if first <= 0:
        return None

    return {
        "current": last,
        "change_pct": (last - first) / first * 100,
        "candles": len(rows),
        "period": "15m",
    }


# ============================================================
# OKX (fallback جریان پول — taker buy/sell رایگان)
# ============================================================


async def okx_flow(symbol: str) -> Optional[dict]:
    """حجم taker خرید/فروش از OKX (رایگان، جایگزین Binance futures/data)."""
    now = time.time()
    cached = flow_cache.get(symbol)
    if cached and now - cached["timestamp"] < FLOW_INTERVAL:
        return cached["data"]

    ccy = symbol.replace("USDT", "")
    data = await http_get(
        f"{OKX}/api/v5/rubik/stat/taker-volume",
        {"ccy": ccy, "instType": "CONTRACTS", "period": "5m"},
    )
    if not data or str(data.get("code")) != "0":
        return None

    rows = data.get("data") or []
    if not rows:
        return None

    # قالب: [ts, sell_volume, buy_volume] — جدیدترین اول
    row = rows[0]
    try:
        outflow = num(row[1])
        inflow = num(row[2])
    except IndexError:
        return None

    if inflow <= 0 and outflow <= 0:
        return None

    total = inflow + outflow
    result = {
        "inflow": inflow,
        "outflow": outflow,
        "netflow": inflow - outflow,
        "ratio": (inflow - outflow) / total if total else 0.0,
        "buy_share": inflow / total if total else 0.5,
        "source": "okx-taker",
    }

    flow_cache[symbol] = {"timestamp": now, "data": result}
    return result


# ============================================================
# BINANCE
# ============================================================


async def binance_symbols() -> list:
    # وقتی بایننس بن است از لیست نمادهای Bybit استفاده می‌کنیم.
    if binance_blocked():
        return await bybit_symbols()

    data = await http_get(f"{BINANCE}/fapi/v1/exchangeInfo")
    if not data:
        return []
    return [
        item["symbol"]
        for item in data.get("symbols", [])
        if item.get("status") == "TRADING"
        and item.get("contractType") == "PERPETUAL"
        and item.get("quoteAsset") == "USDT"
    ]


async def binance_tickers() -> dict:
    # endpoint /ticker/24hr بدون symbol وزن بالایی دارد؛ کش می‌شود.
    now = time.time()
    if tickers_cache["data"] and (
        now - tickers_cache["timestamp"] < TICKERS_INTERVAL
    ):
        return tickers_cache["data"]

    # وقتی بایننس بن است از tickers بایبیت استفاده می‌کنیم.
    if binance_blocked():
        result = await bybit_tickers()
        if result:
            tickers_cache["timestamp"] = now
            tickers_cache["data"] = result
        return result

    data = await http_get(f"{BINANCE}/fapi/v1/ticker/24hr")
    if not data:
        return {}
    result = {x["symbol"]: x for x in data if x.get("symbol")}
    tickers_cache["timestamp"] = now
    tickers_cache["data"] = result
    return result


async def klines(symbol: str, interval: str, limit: int = 100) -> list:
    # وقتی بایننس بن است کندل‌ها از Bybit خوانده می‌شوند.
    if binance_blocked():
        return await bybit_klines(symbol, interval, limit)

    data = await http_get(
        f"{BINANCE}/fapi/v1/klines",
        {"symbol": symbol, "interval": interval, "limit": limit},
    )
    return data or []


# ============================================================
# RSI
# ============================================================


def rsi(closes: list, period: int = 14) -> Optional[float]:
    if len(closes) <= period:
        return None

    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


async def get_rsi(symbol: str, interval: str) -> Optional[float]:
    data = await klines(symbol, interval, 100)
    if not data:
        return None
    return rsi([num(x[4]) for x in data])


async def all_rsi(symbol: str) -> dict:
    r15, r1h, r4h = await asyncio.gather(
        get_rsi(symbol, "15m"),
        get_rsi(symbol, "1h"),
        get_rsi(symbol, "4h"),
    )
    return {"15m": r15, "1h": r1h, "4h": r4h}


# ============================================================
# BINANCE VOLUME
# ============================================================


async def volume_analysis(symbol: str) -> Optional[dict]:
    data = await klines(symbol, "15m", max(VOLUME_LOOKBACK + 5, 30))
    if len(data) < (VOLUME_LOOKBACK + 2):
        return None

    # آخرین کندل کامل
    candle = data[-2]
    previous = data[-(VOLUME_LOOKBACK + 2):-2]

    current_volume = num(candle[5])
    current_quote_volume = num(candle[7])

    avg_volume = sum(num(x[5]) for x in previous) / len(previous)
    volume_ratio = current_volume / avg_volume if avg_volume else 0

    open_price = num(candle[1])
    close_price = num(candle[4])
    price_move = (
        (close_price - open_price) / open_price * 100 if open_price else 0
    )

    taker_buy = num(candle[10])
    taker_sell = current_quote_volume - taker_buy
    buy_ratio = (
        taker_buy / current_quote_volume if current_quote_volume else 0.5
    )

    return {
        "price": close_price,
        # کندل‌های بسته‌شده برای WEAKENING تا دوباره klines نگیرد.
        "closes": [num(x[4]) for x in data[:-1]],
        "volume": current_volume,
        "quote_volume": current_quote_volume,
        "average_volume": avg_volume,
        "volume_ratio": volume_ratio,
        "price_move": price_move,
        "taker_buy": taker_buy,
        "taker_sell": taker_sell,
        "buy_ratio": buy_ratio,
    }


# ============================================================
# LIVECOINWATCH
# ============================================================


async def livecoinwatch() -> dict:
    if not LIVECOINWATCH_API_KEY:
        return {}

    now = time.time()
    if now - lwc_cache["timestamp"] < LWC_INTERVAL:
        return lwc_cache["data"]

    data = await http_post(
        "https://api.livecoinwatch.com/coins/list",
        {
            "currency": "USD",
            "sort": "volume",
            "order": "descending",
            "offset": 0,
            "limit": LWC_LIMIT,
            "meta": True,
        },
        {
            "content-type": "application/json",
            "x-api-key": LIVECOINWATCH_API_KEY,
        },
    )

    if not isinstance(data, list):
        return {}

    result = {}
    for item in data:
        symbol = str(item.get("code") or "").upper()
        if not symbol:
            continue

        delta = item.get("delta") or {}
        volume = num(item.get("volume"))
        market_cap = num(item.get("cap"))

        # API فعلی LiveCoinWatch فیلد volToMcap را برنمی‌گرداند؛
        # در صورت نبودن، خودمان Volume / MarketCap را حساب می‌کنیم.
        vol_to_mcap = num(item.get("volToMcap"))
        if not vol_to_mcap and market_cap:
            vol_to_mcap = volume / market_cap

        result[symbol] = {
            "volume": volume,
            "market_cap": market_cap,
            "vol_to_mcap": vol_to_mcap,
            "liquidity": num(item.get("liquidity")),
            "pressure": num(item.get("pressure")),
            "change_1h": num(delta.get("hour")),
            "change_24h": num(delta.get("day")),
        }

    lwc_cache["timestamp"] = now
    lwc_cache["data"] = result
    return result


# ============================================================
# CRYPTOMETER
# ============================================================


async def cryptometer_flow() -> dict:
    global cryptometer_disabled

    if not CRYPTOMETER_API_KEY or cryptometer_disabled:
        return {}

    now = time.time()
    if now - cryptometer_cache["timestamp"] < CRYPTOMETER_FLOW_INTERVAL:
        return cryptometer_cache["data"]

    data = await http_get(
        "https://api.cryptometer.io/volume-flow/",
        {
            "timeframe": CRYPTOMETER_TIMEFRAME,
            "api_key": CRYPTOMETER_API_KEY,
        },
    )

    if not data:
        return {}

    if data.get("success") not in (True, "true", 1, "1"):
        error = str(data.get("error") or "unknown error")
        log.warning("CryptoMeter flow unavailable: %s", error)

        # اگر endpoint پولی/غیرفعال باشد دیگر در هر اسکن
        # دوباره درخواست نمی‌فرستیم.
        if "paid" in error.lower():
            cryptometer_disabled = True
            log.warning("CryptoMeter disabled: volume-flow is a paid endpoint.")
        return {}

    raw = data.get("data", {})
    result: dict = {}

    def ensure(symbol: str) -> dict:
        return result.setdefault(
            symbol, {"inflow": 0.0, "outflow": 0.0, "netflow": 0.0}
        )

    for row in raw.get("inflow", []):
        symbol = str(row.get("to") or "").upper()
        if symbol:
            ensure(symbol)["inflow"] += num(row.get("volume"))

    for row in raw.get("outflow", []):
        symbol = str(row.get("from") or "").upper()
        if symbol:
            ensure(symbol)["outflow"] += num(row.get("volume"))

    for value in result.values():
        value["netflow"] = value["inflow"] - value["outflow"]

    cryptometer_cache["timestamp"] = now
    cryptometer_cache["data"] = result
    return result


# ============================================================
# MONEY FLOW (Binance futures - رایگان، fallback: OKX)
# ============================================================

# جایگزین رایگان CryptoMeter volume-flow. حجم واقعی خرید/فروش
# taker ها دقیقاً همان مفهوم ورود/خروج پول را می‌دهد.


async def binance_flow(symbol: str) -> Optional[dict]:
    now = time.time()
    cached = flow_cache.get(symbol)
    if cached and now - cached["timestamp"] < FLOW_INTERVAL:
        return cached["data"]

    rows = await http_get(
        f"{BINANCE}/futures/data/takerlongshortRatio",
        {"symbol": symbol, "period": FLOW_PERIOD, "limit": 1},
    )

    if not isinstance(rows, list) or not rows:
        return None

    row = rows[-1]
    inflow = num(row.get("buyVol"))
    outflow = num(row.get("sellVol"))

    if inflow <= 0 and outflow <= 0:
        return None

    total = inflow + outflow
    data = {
        "inflow": inflow,
        "outflow": outflow,
        "netflow": inflow - outflow,
        "ratio": (inflow - outflow) / total if total else 0.0,
        "buy_share": inflow / total if total else 0.5,
        "source": "binance-taker",
    }

    flow_cache[symbol] = {"timestamp": now, "data": data}
    return data


async def money_flow(symbol: str) -> Optional[dict]:
    # اگر پلن پولی CryptoMeter فعال باشد از آن استفاده می‌شود،
    # وگرنه از مشتقات بایننس — و هنگام بن بایننس از OKX.
    base = symbol.replace("USDT", "")

    cryptometer = await cryptometer_flow()
    if cryptometer and base in cryptometer:
        return cryptometer[base]

    if binance_blocked():
        return await okx_flow(symbol)

    flow = await binance_flow(symbol)
    if flow is None and binance_blocked():
        # وسط درخواست بن شدیم → OKX
        return await okx_flow(symbol)
    return flow


# ============================================================
# OPEN INTEREST (Binance futures - رایگان، fallback: Bybit)
# ============================================================


async def binance_open_interest(symbol: str) -> Optional[dict]:
    """تغییر پوزیشن باز. OI صعودی = پول جدید وارد شده."""
    now = time.time()
    cached = oi_cache.get(symbol)
    if cached and now - cached["timestamp"] < FLOW_INTERVAL:
        return cached["data"]

    # وقتی بایننس بن است از OI بایبیت استفاده می‌کنیم.
    if binance_blocked():
        data = await bybit_open_interest(symbol)
        if data:
            oi_cache[symbol] = {"timestamp": now, "data": data}
        return data

    rows = await http_get(
        f"{BINANCE}/futures/data/openInterestHist",
        {"symbol": symbol, "period": OI_PERIOD, "limit": OI_LOOKBACK},
    )

    if not isinstance(rows, list) or len(rows) < 2:
        return None

    first = num(rows[0].get("sumOpenInterest"))
    last = num(rows[-1].get("sumOpenInterest"))

    if first <= 0:
        return None

    data = {
        "current": last,
        "change_pct": (last - first) / first * 100,
        "candles": len(rows),
        "period": OI_PERIOD,
    }

    oi_cache[symbol] = {"timestamp": now, "data": data}
    return data


# ============================================================
# FEAR & GREED (alternative.me - رایگان)
# ============================================================


async def fear_greed() -> Optional[dict]:
    now = time.time()
    if (
        fear_greed_cache["data"]
        and now - fear_greed_cache["timestamp"] < FEAR_GREED_INTERVAL
    ):
        return fear_greed_cache["data"]

    data = await http_get("https://api.alternative.me/fng/", {"limit": 1})
    if not data:
        return None

    rows = data.get("data") or []
    if not rows:
        return None

    result = {
        "value": int(num(rows[0].get("value"))),
        "label": str(rows[0].get("value_classification") or ""),
    }

    fear_greed_cache["timestamp"] = now
    fear_greed_cache["data"] = result
    return result


# ============================================================
# GLOBAL MARKET / DOMINANCE (منابع رایگان)
# ============================================================

# ترتیب منابع:
#   1. CoinGecko     - رایگان و بدون کلید (اصلی)
#   2. Coinpaprika   - رایگان و بدون کلید (fallback)
#   3. CoinMarketCap - فقط اگر کلید بگذاری (آخرین راه)
#
# علت: پلن رایگان CoinMarketCap حدود ۱۰٬۰۰۰ درخواست در ماه می‌دهد
# و ربات با بازهٔ ۳۰۰ ثانیه نزدیک ۸٬۶۴۰ درخواست مصرف می‌کرد.

# منبعی که پی‌درپی خطا بدهد (مثلاً 429 در آی‌پی‌های اشتراکی Render)
# به‌مدت SOURCE_FAIL_COOLDOWN ثانیه کنار گذاشته می‌شود تا مستقیم
# سراغ منبع سالم برویم و درخواست هدر نرود.
SOURCE_FAIL_COOLDOWN = _int("SOURCE_FAIL_COOLDOWN", "1800")
_source_blocked_until: dict = {}


async def coinmarketcap_global_snapshot() -> Optional[dict]:
    headers = {}
    if COINMARKETCAP_API_KEY:
        url = (
            "https://pro-api.coinmarketcap.com/"
            "v1/global-metrics/quotes/latest"
        )
        headers = {"X-CMC_PRO_API_KEY": COINMARKETCAP_API_KEY}
    else:
        # Public API قدیمی CMC دیگر کار نمی‌کند؛ بدون کلید رد می‌شویم.
        return None

    data = await http_get(url, {"convert": "USD"}, headers)
    if not data:
        return None

    result = data.get("data")
    if not result:
        return None

    quote = result.get("quote", {}).get("USD", {})

    return {
        "btc_d": num(result.get("btc_dominance")),
        "eth_d": num(result.get("eth_dominance")),
        "usdt_d": 0.0,  # CMC مقدار USDT را نمی‌دهد.
        "total_market_cap": num(quote.get("total_market_cap")),
        "source": "coinmarketcap",
    }


async def coingecko_global_snapshot() -> Optional[dict]:
    data = await http_get("https://api.coingecko.com/api/v3/global")
    if not data:
        return None

    market = data.get("data") or {}
    percentages = market.get("market_cap_percentage") or {}
    totals = market.get("total_market_cap") or {}

    total = num(totals.get("usd"))
    btc_d = num(percentages.get("btc"))
    if not total or not btc_d:
        return None

    return {
        "btc_d": btc_d,
        "eth_d": num(percentages.get("eth")),
        "usdt_d": num(percentages.get("usdt")),
        "total_market_cap": total,
        "source": "coingecko",
    }


async def coinpaprika_global_snapshot() -> Optional[dict]:
    data = await http_get("https://api.coinpaprika.com/v1/global")
    if not data:
        return None

    total = num(data.get("market_cap_usd"))
    btc_d = num(data.get("bitcoin_dominance_percentage"))
    if not total or not btc_d:
        return None

    # Coinpaprika فقط dominance بیت‌کوین را می‌دهد.
    return {
        "btc_d": btc_d,
        "eth_d": 0.0,
        "usdt_d": 0.0,
        "total_market_cap": total,
        "source": "coinpaprika",
    }


async def market_global() -> Optional[dict]:
    now = time.time()
    if (
        global_cache["data"]
        and now - global_cache["timestamp"] < DOMINANCE_INTERVAL
    ):
        return global_cache["data"]

    sources = [coingecko_global_snapshot, coinpaprika_global_snapshot]
    if COINMARKETCAP_API_KEY:
        sources.append(coinmarketcap_global_snapshot)

    for source in sources:
        name = source.__name__
        if now < _source_blocked_until.get(name, 0):
            continue  # این منبع موقتاً کنار گذاشته شده (429/خطای مکرر)

        snapshot = await source()
        if snapshot:
            _source_blocked_until.pop(name, None)
            global_cache["timestamp"] = now
            global_cache["data"] = snapshot
            return snapshot

        _source_blocked_until[name] = now + SOURCE_FAIL_COOLDOWN
        log.warning(
            "dominance source failed: %s (blocked for %ds)",
            name, SOURCE_FAIL_COOLDOWN,
        )

    return None


# ============================================================
# DOMINANCE SNAPSHOT
# ============================================================


async def get_dominance() -> Optional[dict]:
    global_data = await market_global()
    if not global_data:
        return None

    btc_d = global_data["btc_d"]
    eth_d = global_data["eth_d"]
    usdt_d = global_data["usdt_d"]
    total = global_data["total_market_cap"]

    total2 = total * (1 - btc_d / 100)          # کل بازار بدون BTC
    total3 = total * (1 - (btc_d + eth_d) / 100)  # بدون BTC و ETH

    # OTHERS.D تقریبی: بازار آلت‌ها بدون BTC، ETH و استیبل‌ها.
    if usdt_d:
        others_d = max(0.0, 100 - btc_d - eth_d - usdt_d)
    else:
        others_d = max(0.0, 100 - btc_d - eth_d)

    return {
        "BTC.D": btc_d,
        "USDT.D": usdt_d,
        "OTHERS.D": others_d,
        "TOTAL2": total2,
        "TOTAL3": total3,
        "TOTAL": total,
        "SOURCE": global_data["source"],
        "timestamp": time.time(),
    }


# ============================================================
# MARKET ALIGNMENT
# ============================================================

_ALIGNMENT_KEYS = ("BTC.D", "USDT.D", "OTHERS.D", "TOTAL2", "TOTAL3")


def _empty_alignment() -> dict:
    empty = {k: False for k in _ALIGNMENT_KEYS}
    return {
        "long": 0,
        "short": 0,
        "total": 5,
        "long_details": dict(empty),
        "short_details": dict(empty),
    }


def market_alignment(current: Optional[dict], previous: Optional[dict]) -> dict:
    if not current or not previous:
        return _empty_alignment()

    long_details = {
        "BTC.D": current["BTC.D"] < previous["BTC.D"],
        "USDT.D": current["USDT.D"] < previous["USDT.D"],
        "OTHERS.D": current["OTHERS.D"] > previous["OTHERS.D"],
        "TOTAL2": current["TOTAL2"] > previous["TOTAL2"],
        "TOTAL3": current["TOTAL3"] > previous["TOTAL3"],
    }
    short_details = {k: not v for k, v in long_details.items()}

    return {
        "long": sum(long_details.values()),
        "short": sum(short_details.values()),
        "total": 5,
        "long_details": long_details,
        "short_details": short_details,
    }


# ============================================================
# BTC PAIR
# ============================================================


def _direction(change: float) -> str:
    if change > 0:
        return "BULLISH"
    if change < 0:
        return "BEARISH"
    return "NEUTRAL"


async def btc_pair(symbol: str) -> dict:
    base = symbol.replace("USDT", "")
    pair = f"{base}BTC"

    # حالت fallback هنگام بن بایننس: تغییر ۲۴ ساعتهٔ نسبی به BTC
    # از tickers (که خودش به Bybit سوئیچ می‌کند).
    if binance_blocked():
        tickers = await binance_tickers()
        alt, btc = tickers.get(symbol), tickers.get("BTCUSDT")
        if not alt or not btc:
            return {
                "pair": f"{base}/BTC",
                "direction": "UNKNOWN",
                "change": None,
            }
        relative = num(alt.get("priceChangePercent")) - num(
            btc.get("priceChangePercent")
        )
        return {
            "pair": f"{base}/BTC",
            "direction": _direction(relative),
            "change": relative,
        }

    direct = await http_get(
        f"{BINANCE}/fapi/v1/ticker/24hr", {"symbol": pair}
    )
    if direct:
        change = num(direct.get("priceChangePercent"))
        return {
            "pair": f"{base}/BTC",
            "direction": _direction(change),
            "change": change,
        }

    # Synthetic ALT/BTC
    alt, btc = await asyncio.gather(
        http_get(f"{BINANCE}/fapi/v1/ticker/24hr", {"symbol": symbol}),
        http_get(f"{BINANCE}/fapi/v1/ticker/24hr", {"symbol": "BTCUSDT"}),
    )

    if not alt or not btc:
        return {"pair": f"{base}/BTC", "direction": "UNKNOWN", "change": None}

    relative = num(alt.get("priceChangePercent")) - num(
        btc.get("priceChangePercent")
    )
    return {
        "pair": f"{base}/BTC",
        "direction": _direction(relative),
        "change": relative,
    }


# ============================================================
# FLOW DIRECTION
# ============================================================


def flow_threshold(flow: Optional[dict], fallback: float) -> float:
    # آستانهٔ CryptoMeter و حجم taker بایننس/OKX هم‌مقیاس نیستند.
    if flow and flow.get("source") in ("binance-taker", "okx-taker"):
        return BINANCE_FLOW_MIN_RATIO
    return fallback


def flow_direction(flow: Optional[dict]) -> str:
    if not flow:
        return "UNKNOWN"

    inflow = num(flow.get("inflow"))
    outflow = num(flow.get("outflow"))
    total = inflow + outflow
    if total <= 0:
        return "UNKNOWN"

    ratio = num(flow.get("netflow")) / total
    threshold = flow_threshold(flow, MIN_FLOW_RATIO_SIGNAL)

    if ratio >= threshold:
        return "BULLISH"
    if ratio <= -threshold:
        return "BEARISH"
    return "NEUTRAL"


# ============================================================
# EARLY WATCH
# ============================================================


def early_watch(volume: Optional[dict], lwc: Optional[dict],
                flow: Optional[dict]) -> bool:
    if not volume:
        return False
    if volume["volume_ratio"] < EARLY_VOLUME_RATIO:
        return False
    if abs(volume["price_move"]) > MAX_PRICE_MOVE:
        return False

    flow_ok = False
    if flow:
        total = num(flow.get("inflow")) + num(flow.get("outflow"))
        if total:
            ratio = abs(num(flow.get("netflow"))) / total
            flow_ok = ratio >= flow_threshold(flow, EARLY_FLOW_RATIO)

    return flow_ok or bool(lwc)


# ============================================================
# FINAL SIGNAL
# ============================================================


def detect_signal(rsi_data, volume, flow, btc, market,
                  oi=None, fg=None) -> Optional[str]:
    if not rsi_data or not volume:
        return None

    r15, r1h, r4h = rsi_data["15m"], rsi_data["1h"], rsi_data["4h"]
    if None in (r15, r1h, r4h):
        return None

    flow_dir = flow_direction(flow)

    # ---------------- OI / SENTIMENT ----------------
    # پیش‌فرض غیرفعال‌اند تا سیگنال بیش از حد سخت‌گیرانه نشود.

    oi_ok_long = oi_ok_short = True
    if REQUIRE_OI_RISING and oi:
        oi_ok_long = oi["change_pct"] > 0
        oi_ok_short = oi["change_pct"] < 0

    fg_ok_long = fg_ok_short = True
    if fg:
        if FEAR_GREED_MAX_LONG > 0:
            fg_ok_long = fg["value"] < FEAR_GREED_MAX_LONG
        if FEAR_GREED_MIN_SHORT > 0:
            fg_ok_short = fg["value"] > FEAR_GREED_MIN_SHORT

    # ---------------- LONG ----------------
    if all([
        r15 <= LONG_RSI_15M and r1h <= LONG_RSI_1H and r4h <= LONG_RSI_4H,
        volume["volume_ratio"] >= VOLUME_MULTIPLIER,
        flow_dir == "BULLISH" or volume["buy_ratio"] >= 0.55,
        btc["direction"] == "BULLISH",
        market["long"] >= 3,
        oi_ok_long,
        fg_ok_long,
    ]):
        return "LONG"

    # ---------------- SHORT ----------------
    if all([
        r15 >= SHORT_RSI_15M and r1h >= SHORT_RSI_1H and r4h >= SHORT_RSI_4H,
        volume["volume_ratio"] >= VOLUME_MULTIPLIER,
        flow_dir == "BEARISH" or volume["buy_ratio"] <= 0.45,
        btc["direction"] == "BEARISH",
        market["short"] >= 3,
        oi_ok_short,
        fg_ok_short,
    ]):
        return "SHORT"

    return None
