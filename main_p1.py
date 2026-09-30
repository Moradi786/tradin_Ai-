"""
Crypto AI Signal Bot
====================

ربات سیگنال کریپتو — فقط سیگنال می‌دهد و هیچ معامله‌ای اجرا نمی‌کند.

منابع داده:
  - Binance Futures   : klines, tickers, taker flow, open interest (رایگان)
  - CoinGecko         : dominance / global market (رایگان، بدون کلید)
  - Coinpaprika       : fallback دادهٔ سراسری (رایگان)
  - CoinMarketCap     : آخرین fallback (در صورت داشتن کلید)
  - LiveCoinWatch     : دادهٔ بازار هر کوین (نیازمند کلید)
  - CryptoMeter       : volume flow (endpoint پولی — اختیاری)
  - alternative.me    : Fear & Greed (رایگان)

هوش مصنوعی (به ترتیب اولویت، با fallback):
  Gemini -> Groq -> OpenRouter -> OpenAI
"""

import asyncio
import logging
import os
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

EARLY_FLOW_RATIO = _float("EARLY_FLOW_RATIO", "0.10")
EARLY_VOLUME_RATIO = _float("EARLY_VOLUME_RATIO", "1.5")
MIN_FLOW_RATIO_SIGNAL = _float("MIN_FLOW_RATIO_SIGNAL", "0.15")

# Money Flow از مشتقات بایننس (رایگان). بایننس هر ۵ دقیقه آپدیت می‌کند.
FLOW_INTERVAL = _int("FLOW_INTERVAL", "300")
FLOW_PERIOD = os.getenv("FLOW_PERIOD", "15m")

# آستانهٔ مخصوص حجم taker بایننس؛ مقیاسش با CryptoMeter فرق دارد.
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

# کش Money Flow و Open Interest هر نماد (per-symbol).
flow_cache: dict = {}
oi_cache: dict = {}

global_cache = {"timestamp": 0.0, "data": None}
fear_greed_cache = {"timestamp": 0.0, "data": None}

# اگر CryptoMeter endpoint پولی باشد، بعد از اولین خطا غیرفعال می‌شود.
cryptometer_disabled = False

# مرجع به تسک اسکنر تا از garbage collection جلوگیری شود.
scanner_task: Optional[asyncio.Task] = None

# ============================================================
# HTTP
# ============================================================


async def get_session() -> aiohttp.ClientSession:
    global http_session
    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        )
    return http_session


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


# ============================================================
# BINANCE
# ============================================================


async def binance_symbols() -> list:
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
    data = await http_get(f"{BINANCE}/fapi/v1/ticker/24hr")
    if not data:
        return {}
    return {x["symbol"]: x for x in data if x.get("symbol")}


async def klines(symbol: str, interval: str, limit: int = 100) -> list:
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
        "volume": current_volume,
        "quote_volume": current_quote_volume,
        "average_volume": avg_volume,
        "volume_ratio": volume_ratio,
        "price_move": price_move,
        "taker_buy": taker_buy,
        "taker_sell": taker_sell,
        "buy_ratio": buy_ratio,
    }
