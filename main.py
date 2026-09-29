import os
import asyncio
import time
from typing import Optional

import aiohttp
import uvicorn
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv
from openai import AsyncOpenAI


# ============================================================
# ENV
# ============================================================

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")

# Gemini (Google AI Studio) به‌عنوان provider
# جایگزین. اگر کلید Gemini موجود باشد، اولویت
# با آن است و در غیر این صورت OpenAI استفاده می‌شود.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.8-flash"
)

# Groq - پلن رایگان، API سازگار با OpenAI.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "llama-3.3-70b-versatile"
)

# OpenRouter - مدل‌های :free هم دارد.
OPENROUTER_API_KEY = os.getenv(
    "OPENROUTER_API_KEY", ""
)
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "meta-llama/llama-3.3-70b-instruct:free"
)

# اختیاری: اگر ست شود، این provider اول
# امتحان می‌شود و بقیه fallback می‌شوند.
AI_PROVIDER = os.getenv("AI_PROVIDER", "")

LIVECOINWATCH_API_KEY = os.getenv(
    "LIVECOINWATCH_API_KEY", ""
)

CRYPTOMETER_API_KEY = os.getenv(
    "CRYPTOMETER_API_KEY", ""
)

COINMARKETCAP_API_KEY = os.getenv(
    "COINMARKETCAP_API_KEY", ""
)

SCAN_INTERVAL = int(
    os.getenv("SCAN_INTERVAL", "120")
)

MAX_SYMBOLS = int(
    os.getenv("MAX_SYMBOLS", "100")
)

VOLUME_MULTIPLIER = float(
    os.getenv("VOLUME_MULTIPLIER", "2.0")
)

MAX_PRICE_MOVE = float(
    os.getenv("MAX_PRICE_MOVE", "1.5")
)

VOLUME_LOOKBACK = int(
    os.getenv("VOLUME_LOOKBACK", "20")
)

LONG_RSI_15M = float(
    os.getenv("LONG_RSI_15M", "35")
)

LONG_RSI_1H = float(
    os.getenv("LONG_RSI_1H", "40")
)

LONG_RSI_4H = float(
    os.getenv("LONG_RSI_4H", "45")
)

SHORT_RSI_15M = float(
    os.getenv("SHORT_RSI_15M", "65")
)

SHORT_RSI_1H = float(
    os.getenv("SHORT_RSI_1H", "60")
)

SHORT_RSI_4H = float(
    os.getenv("SHORT_RSI_4H", "55")
)

SIGNAL_COOLDOWN = int(
    os.getenv("SIGNAL_COOLDOWN", "1800")
)

CRYPTOMETER_FLOW_INTERVAL = int(
    os.getenv(
        "CRYPTOMETER_FLOW_INTERVAL",
        "600"
    )
)

CRYPTOMETER_TIMEFRAME = os.getenv(
    "CRYPTOMETER_TIMEFRAME",
    "15m"
)

LWC_INTERVAL = int(
    os.getenv("LWC_INTERVAL", "120")
)

CMC_INTERVAL = int(
    os.getenv("CMC_INTERVAL", "300")
)

# TTL دادهٔ Global Market.
#
# مهم: عمداً کمتر از SCAN_INTERVAL (۱۲۰ ثانیه)
# است تا هر اسکن دادهٔ تازه ببیند. اگر این مقدار
# بزرگ‌تر از SCAN_INTERVAL باشد، دو اسکن پشت‌سرهم
# دادهٔ یکسان می‌بینند و market_alignment همیشه
# ۰/۵ می‌شود؛ یعنی شرط market >= 3 هرگز برقرار
# نمی‌شود و سیگنال نهایی شلیک نمی‌شود.
DOMINANCE_INTERVAL = int(
    os.getenv("DOMINANCE_INTERVAL", "60")
)

LWC_LIMIT = int(
    os.getenv("LWC_LIMIT", "100")
)

# ------------------------------------------------------------
# OPEN INTEREST
# ------------------------------------------------------------

OI_PERIOD = os.getenv("OI_PERIOD", "15m")

OI_LOOKBACK = int(
    os.getenv("OI_LOOKBACK", "5")
)

# اگر true شود، LONG فقط با OI صعودی
# و SHORT فقط با OI نزولی صادر می‌شود.
REQUIRE_OI_RISING = (
    os.getenv(
        "REQUIRE_OI_RISING", "false"
    ).lower()
    in ("1", "true", "yes")
)

# ------------------------------------------------------------
# FEAR & GREED (alternative.me - رایگان)
# ------------------------------------------------------------

FEAR_GREED_INTERVAL = int(
    os.getenv(
        "FEAR_GREED_INTERVAL", "3600"
    )
)

# 0 = غیرفعال. اگر >0 باشد، در هیجان
# افراطی جلوی سیگنال گرفته می‌شود.
FEAR_GREED_MAX_LONG = float(
    os.getenv("FEAR_GREED_MAX_LONG", "0")
)

FEAR_GREED_MIN_SHORT = float(
    os.getenv("FEAR_GREED_MIN_SHORT", "0")
)

EARLY_FLOW_RATIO = float(
    os.getenv("EARLY_FLOW_RATIO", "0.10")
)

EARLY_VOLUME_RATIO = float(
    os.getenv("EARLY_VOLUME_RATIO", "1.5")
)

MIN_FLOW_RATIO_SIGNAL = float(
    os.getenv("MIN_FLOW_RATIO_SIGNAL", "0.15")
)

# Money Flow از مشتقات بایننس (رایگان) خوانده می‌شود.
# بایننس این داده را هر ۵ دقیقه آپدیت می‌کند.
FLOW_INTERVAL = int(
    os.getenv("FLOW_INTERVAL", "300")
)

FLOW_PERIOD = os.getenv(
    "FLOW_PERIOD",
    "15m"
)

# آستانهٔ مخصوص حجم taker بایننس.
# مقیاس این داده با CryptoMeter فرق دارد:
# نسبت خرید/فروش بایننس طبیعتاً نزدیک ۵۰٪ است،
# پس آستانهٔ ۰.۱۵ آن را همیشه NEUTRAL می‌کرد.
BINANCE_FLOW_MIN_RATIO = float(
    os.getenv(
        "BINANCE_FLOW_MIN_RATIO",
        "0.06"
    )
)


# ============================================================
# LIFESPAN
# ============================================================

# مرجع به تسک اسکنر تا از garbage collection
# شدن آن توسط asyncio جلوگیری شود.
scanner_task: Optional[
    asyncio.Task
] = None


@asynccontextmanager
async def lifespan(app_instance: FastAPI):

    global scanner_task, http_session

    # بررسی زودهنگام کلیدها / توکن‌ها.
    # توابع پایین فایل تعریف شده‌اند و
    # در زمان اجرا resolve می‌شوند.
    await startup_diagnostics()

    scanner_task = asyncio.create_task(
        scanner_loop()
    )

    print(
        "Scanner task started."
    )

    try:

        yield

    finally:

        scanner_task.cancel()

        await asyncio.gather(
            scanner_task,
            return_exceptions=True
        )

        if (
            http_session
            and not http_session.closed
        ):
            await http_session.close()


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Crypto AI Signal Bot",
    lifespan=lifespan
)


# ============================================================
# CLIENTS / CACHE
# ============================================================

http_session: Optional[
    aiohttp.ClientSession
] = None

openai_client = (
    AsyncOpenAI(
        api_key=OPENAI_API_KEY
    )
    if OPENAI_API_KEY
    else None
)


last_signals = {}

previous_dominance = None

lwc_cache = {
    "timestamp": 0,
    "data": {}
}

cryptometer_cache = {
    "timestamp": 0,
    "data": {}
}

# کش Money Flow هر نماد. بایننس این داده را
# per-symbol می‌دهد، نه با یک درخواست سراسری.
flow_cache = {}

# کش Open Interest هر نماد.
oi_cache = {}

# کش دادهٔ Global Market (CoinGecko/Coinpaprika/CMC)
global_cache = {
    "timestamp": 0,
    "data": None
}

# کش Fear & Greed (روزی یکبار آپدیت می‌شود).
fear_greed_cache = {
    "timestamp": 0,
    "data": None
}

dominance_cache = {
    "timestamp": 0,
    "data": None
}

# اگر CryptoMeter endpoint پولی باشد،
# بعد از اولین خطا غیرفعال می‌شود.
cryptometer_disabled = False


# ============================================================
# HTTP
# ============================================================

async def get_session():

    global http_session

    if (
        http_session is None
        or http_session.closed
    ):
        http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(
                total=20
            )
        )

    return http_session


async def http_get(
    url,
    params=None,
    headers=None
):

    session = await get_session()

    try:

        async with session.get(
            url,
            params=params,
            headers=headers
        ) as response:

            if response.status != 200:

                body = await response.text()

                print(
                    "HTTP ERROR",
                    response.status,
                    url,
                    body[:300]
                )
                return None

            return await response.json()

    except Exception as e:

        print(
            "REQUEST ERROR:",
            url,
            e
        )

        return None


async def http_post(
    url,
    payload,
    headers=None
):

    session = await get_session()

    try:

        async with session.post(
            url,
            json=payload,
            headers=headers
        ) as response:

            if response.status != 200:

                body = await response.text()

                print(
                    "HTTP POST ERROR",
                    response.status,
                    url,
                    body[:300]
                )
                return None

            return await response.json()

    except Exception as e:

        print(
            "POST ERROR:",
            url,
            e
        )

        return None


# ============================================================
# HELPERS
# ============================================================

def num(value, default=0.0):

    try:
        return float(value)
    except Exception:
        return default


def check(value):
    return "✅" if value else "❌"


# ============================================================
# BINANCE
# ============================================================

BINANCE = "https://fapi.binance.com"


async def binance_symbols():

    data = await http_get(
        f"{BINANCE}/fapi/v1/exchangeInfo"
    )

    if not data:
        return []

    result = []

    for item in data.get(
        "symbols",
        []
    ):

        if item.get("status") != "TRADING":
            continue

        if item.get("contractType") != "PERPETUAL":
            continue

        if item.get("quoteAsset") != "USDT":
            continue

        result.append(
            item["symbol"]
        )

    return result


async def binance_tickers():

    data = await http_get(
        f"{BINANCE}/fapi/v1/ticker/24hr"
    )

    if not data:
        return {}

    return {
        x["symbol"]: x
        for x in data
        if x.get("symbol")
    }


async def klines(
    symbol,
    interval,
    limit=100
):

    data = await http_get(
        f"{BINANCE}/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    return data or []


# ============================================================
# RSI
# ============================================================

def rsi(closes, period=14):

    if len(closes) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(closes)):

        diff = (
            closes[i]
            - closes[i - 1]
        )

        gains.append(
            max(diff, 0)
        )

        losses.append(
            max(-diff, 0)
        )

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = (
        avg_gain
        / avg_loss
    )

    return (
        100
        - (
            100
            / (1 + rs)
        )
    )


async def get_rsi(
    symbol,
    interval
):

    data = await klines(
        symbol,
        interval,
        100
    )

    if not data:
        return None

    closes = [
        num(x[4])
        for x in data
    ]

    return rsi(closes)


async def all_rsi(symbol):

    values = await asyncio.gather(
        get_rsi(symbol, "15m"),
        get_rsi(symbol, "1h"),
        get_rsi(symbol, "4h")
    )

    return {
        "15m": values[0],
        "1h": values[1],
        "4h": values[2]
    }


# ============================================================
# BINANCE VOLUME
# ============================================================

async def volume_analysis(symbol):

    data = await klines(
        symbol,
        "15m",
        max(
            VOLUME_LOOKBACK + 5,
            30
        )
    )

    if len(data) < (
        VOLUME_LOOKBACK + 2
    ):
        return None

    # آخرین کندل کامل
    candle = data[-2]

    previous = data[
        -(VOLUME_LOOKBACK + 2):-2
    ]

    current_volume = num(
        candle[5]
    )

    current_quote_volume = num(
        candle[7]
    )

    avg_volume = (
        sum(
            num(x[5])
            for x in previous
        )
        / len(previous)
    )

    volume_ratio = (
        current_volume
        / avg_volume
        if avg_volume
        else 0
    )

    open_price = num(
        candle[1]
    )

    close_price = num(
        candle[4]
    )

    price_move = (
        (
            close_price
            - open_price
        )
        / open_price
        * 100
        if open_price
        else 0
    )

    taker_buy = num(
        candle[10]
    )

    taker_sell = (
        current_quote_volume
        - taker_buy
    )

    buy_ratio = (
        taker_buy
        / current_quote_volume
        if current_quote_volume
        else 0.5
    )

    return {
        "volume": current_volume,
        "quote_volume": current_quote_volume,
        "average_volume": avg_volume,
        "volume_ratio": volume_ratio,
        "price_move": price_move,
        "taker_buy": taker_buy,
        "taker_sell": taker_sell,
        "buy_ratio": buy_ratio
    }


# ============================================================
# LIVECOINWATCH
# ============================================================

async def livecoinwatch():

    if not LIVECOINWATCH_API_KEY:
        return {}

    now = time.time()

    if (
        now
        - lwc_cache["timestamp"]
        < LWC_INTERVAL
    ):
        return lwc_cache["data"]

    data = await http_post(
        "https://api.livecoinwatch.com/coins/list",
        {
            "currency": "USD",
            "sort": "volume",
            "order": "descending",
            "offset": 0,
            "limit": LWC_LIMIT,
            "meta": True
        },
        {
            "content-type":
                "application/json",
            "x-api-key":
                LIVECOINWATCH_API_KEY
        }
    )

    if not isinstance(data, list):
        return {}

    result = {}

    for item in data:

        symbol = str(
            item.get("code")
            or ""
        ).upper()

        if not symbol:
            continue

        delta = (
            item.get("delta")
            or {}
        )

        volume = num(
            item.get("volume")
        )

        market_cap = num(
            item.get("cap")
        )

        # API فعلی LiveCoinWatch فیلد volToMcap را
        # برنمی‌گرداند؛ در صورت نبودن، خودمان
        # Volume / MarketCap را حساب می‌کنیم.
        vol_to_mcap = num(
            item.get(
                "volToMcap"
            )
        )

        if not vol_to_mcap and market_cap:
            vol_to_mcap = (
                volume / market_cap
            )

        result[symbol] = {
            "volume": volume,
            "market_cap": market_cap,
            "vol_to_mcap": vol_to_mcap,
            "liquidity": num(
                item.get(
                    "liquidity"
                )
            ),
            "pressure": num(
                item.get(
                    "pressure"
                )
            ),
            "change_1h": num(
                delta.get("hour")
            ),
            "change_24h": num(
                delta.get("day")
            )
        }

    lwc_cache["timestamp"] = now
    lwc_cache["data"] = result

    return result


# ============================================================
# CRYPTOMETER
# ============================================================

async def cryptometer_flow():

    global cryptometer_disabled

    if not CRYPTOMETER_API_KEY:
        return {}

    if cryptometer_disabled:
        return {}

    now = time.time()

    if (
        now
        - cryptometer_cache["timestamp"]
        < CRYPTOMETER_FLOW_INTERVAL
    ):
        return cryptometer_cache["data"]

    data = await http_get(
        "https://api.cryptometer.io/volume-flow/",
        {
            "timeframe":
                CRYPTOMETER_TIMEFRAME,
            "api_key":
                CRYPTOMETER_API_KEY
        }
    )

    if not data:
        return {}

    success = data.get(
        "success"
    )

    if success not in (
        True,
        "true",
        1,
        "1"
    ):

        error = str(
            data.get("error")
            or "unknown error"
        )

        print(
            "CryptoMeter flow unavailable:",
            error
        )

        # اگر endpoint پولی/غیرفعال باشد دیگر
        # در هر اسکن دوباره درخواست نمی‌فرستیم.
        if "paid" in error.lower():

            cryptometer_disabled = True

            print(
                "CryptoMeter disabled: "
                "volume-flow is a paid endpoint."
            )

        return {}

    raw = data.get(
        "data",
        {}
    )

    result = {}

    def ensure(symbol):

        if symbol not in result:

            result[symbol] = {
                "inflow": 0.0,
                "outflow": 0.0,
                "netflow": 0.0
            }

        return result[symbol]

    for row in raw.get(
        "inflow",
        []
    ):

        symbol = str(
            row.get("to")
            or ""
        ).upper()

        if symbol:

            ensure(symbol)[
                "inflow"
            ] += num(
                row.get("volume")
            )

    for row in raw.get(
        "outflow",
        []
    ):

        symbol = str(
            row.get("from")
            or ""
        ).upper()

        if symbol:

            ensure(symbol)[
                "outflow"
            ] += num(
                row.get("volume")
            )

    for symbol, value in result.items():

        value["netflow"] = (
            value["inflow"]
            - value["outflow"]
        )

    cryptometer_cache[
        "timestamp"
    ] = now

    cryptometer_cache[
        "data"
    ] = result

    return result


# ============================================================
# MONEY FLOW (Binance futures)
# ============================================================

# جایگزین رایگان CryptoMeter volume-flow.
#
# حجم واقعی خرید (buyVol) و فروش (sellVol)
# توسط taker ها، دقیقاً همان مفهوم
# ورود/خروج پول را می‌دهد.

async def binance_flow(symbol):

    now = time.time()

    cached = flow_cache.get(
        symbol
    )

    if (
        cached
        and now - cached["timestamp"]
        < FLOW_INTERVAL
    ):
        return cached["data"]

    rows = await http_get(
        f"{BINANCE}/futures/data/"
        "takerlongshortRatio",
        {
            "symbol": symbol,
            "period": FLOW_PERIOD,
            "limit": 1
        }
    )

    if not isinstance(
        rows, list
    ) or not rows:
        return None

    row = rows[-1]

    inflow = num(
        row.get("buyVol")
    )

    outflow = num(
        row.get("sellVol")
    )

    if inflow <= 0 and outflow <= 0:
        return None

    total = inflow + outflow

    data = {
        "inflow": inflow,
        "outflow": outflow,
        "netflow": inflow - outflow,

        # این دو مقدار مستقیماً قابل استفاده‌اند و
        # به واحد پول وابسته نیستند.
        "ratio": (
            (inflow - outflow) / total
            if total
            else 0.0
        ),
        "buy_share": (
            inflow / total
            if total
            else 0.5
        ),

        "source": "binance-taker"
    }

    flow_cache[symbol] = {
        "timestamp": now,
        "data": data
    }

    return data


async def money_flow(symbol):

    # اگر پلن پولی CryptoMeter فعال باشد از آن
    # استفاده می‌شود، وگرنه به‌صورت رایگان از
    # بازار مشتقات بایننس خوانده می‌شود.
    base = symbol.replace(
        "USDT",
        ""
    )

    cryptometer = (
        await cryptometer_flow()
    )

    if (
        cryptometer
        and base in cryptometer
    ):
        return cryptometer[base]

    return await binance_flow(
        symbol
    )


# ============================================================
# OPEN INTEREST (Binance futures - رایگان)
# ============================================================

async def binance_open_interest(symbol):

    """
    تغییر پوزیشن باز.

    OI صعودی = پول جدید وارد شده.
    OI نزولی = پوزیشن‌ها بسته شده‌اند.
    """

    now = time.time()

    cached = oi_cache.get(symbol)

    if (
        cached
        and now - cached["timestamp"]
        < FLOW_INTERVAL
    ):
        return cached["data"]

    rows = await http_get(
        f"{BINANCE}/futures/data/"
        "openInterestHist",
        {
            "symbol": symbol,
            "period": OI_PERIOD,
            "limit": OI_LOOKBACK
        }
    )

    if not isinstance(
        rows, list
    ) or len(rows) < 2:
        return None

    first = num(
        rows[0].get("sumOpenInterest")
    )

    last = num(
        rows[-1].get("sumOpenInterest")
    )

    if first <= 0:
        return None

    data = {
        "current": last,

        "change_pct":
            (last - first) / first * 100,

        "candles": len(rows),
        "period": OI_PERIOD
    }

    oi_cache[symbol] = {
        "timestamp": now,
        "data": data
    }

    return data


# ============================================================
# FEAR & GREED (alternative.me - رایگان)
# ============================================================

async def fear_greed():

    now = time.time()

    if (
        fear_greed_cache["data"]
        and now
        - fear_greed_cache["timestamp"]
        < FEAR_GREED_INTERVAL
    ):
        return fear_greed_cache["data"]

    data = await http_get(
        "https://api.alternative.me/fng/",
        {"limit": 1}
    )

    if not data:
        return None

    rows = data.get("data") or []

    if not rows:
        return None

    result = {
        "value": int(
            num(rows[0].get("value"))
        ),
        "label": str(
            rows[0].get(
                "value_classification"
            )
            or ""
        )
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
# علت: پلن رایگان CoinMarketCap حدود ۱۰٬۰۰۰ درخواست
# در ماه می‌دهد و ربات با بازهٔ ۳۰۰ ثانیه نزدیک
# ۸٬۶۴۰ درخواست مصرف می‌کرد؛ یعنی در آستانهٔ
# محدود شدن. CoinGecko همان داده را رایگان می‌دهد.

async def coinmarketcap_global_snapshot():

    headers = {}

    # اگر API key موجود باشد از API استاندارد استفاده می‌کنیم.
    # در غیر این صورت Public API استفاده می‌شود.
    if COINMARKETCAP_API_KEY:

        url = (
            "https://pro-api.coinmarketcap.com/"
            "v1/global-metrics/quotes/latest"
        )

        headers = {
            "X-CMC_PRO_API_KEY":
                COINMARKETCAP_API_KEY
        }

    else:

        url = (
            "https://pro-api.coinmarketcap.com/"
            "public-api/v1/global-metrics/"
            "quotes/latest"
        )

    data = await http_get(
        url,
        {
            "convert": "USD"
        },
        headers
    )

    if not data:
        return None

    result = data.get(
        "data"
    )

    if not result:
        return None

    quote = (
        result
        .get("quote", {})
        .get("USD", {})
    )

    total_market_cap = num(
        quote.get(
            "total_market_cap"
        )
    )

    btc_d = num(
        result.get(
            "btc_dominance"
        )
    )

    eth_d = num(
        result.get(
            "eth_dominance"
        )
    )

    return {
        "btc_d": btc_d,
        "eth_d": eth_d,

        # CMC مقدار USDT را نمی‌دهد.
        "usdt_d": 0.0,

        "total_market_cap":
            total_market_cap,

        "source": "coinmarketcap"
    }


# ============================================================
# FREE GLOBAL SNAPSHOTS
# ============================================================

async def coingecko_global_snapshot():

    data = await http_get(
        "https://api.coingecko.com/api/v3/global"
    )

    if not data:
        return None

    market = data.get("data") or {}

    percentages = (
        market.get(
            "market_cap_percentage"
        ) or {}
    )

    totals = (
        market.get("total_market_cap")
        or {}
    )

    total = num(
        totals.get("usd")
    )

    btc_d = num(
        percentages.get("btc")
    )

    if not total or not btc_d:
        return None

    return {
        "btc_d": btc_d,
        "eth_d": num(
            percentages.get("eth")
        ),
        "usdt_d": num(
            percentages.get("usdt")
        ),
        "total_market_cap": total,
        "source": "coingecko"
    }


async def coinpaprika_global_snapshot():

    data = await http_get(
        "https://api.coinpaprika.com/v1/global"
    )

    if not data:
        return None

    total = num(
        data.get("market_cap_usd")
    )

    btc_d = num(
        data.get(
            "bitcoin_dominance_percentage"
        )
    )

    if not total or not btc_d:
        return None

    # Coinpaprika فقط dominance بیت‌کوین را
    # می‌دهد، پس ETH و USDT صفر می‌مانند.
    return {
        "btc_d": btc_d,
        "eth_d": 0.0,
        "usdt_d": 0.0,
        "total_market_cap": total,
        "source": "coinpaprika"
    }


async def market_global():

    now = time.time()

    if (
        global_cache["data"]
        and now
        - global_cache["timestamp"]
        < DOMINANCE_INTERVAL
    ):
        return global_cache["data"]

    sources = (
        coingecko_global_snapshot,
        coinpaprika_global_snapshot,
        coinmarketcap_global_snapshot
    )

    for source in sources:

        snapshot = await source()

        if snapshot:

            global_cache["timestamp"] = now
            global_cache["data"] = snapshot

            return snapshot

        print(
            "dominance source failed:",
            source.__name__
        )

    return None


# ============================================================
# DOMINANCE SNAPSHOT
# ============================================================

async def get_dominance():

    global_data = await market_global()

    if not global_data:
        return None

    btc_d = global_data["btc_d"]
    eth_d = global_data["eth_d"]
    usdt_d = global_data["usdt_d"]

    total = global_data[
        "total_market_cap"
    ]

    # TOTAL2: کل بازار بدون بیت‌کوین
    total2 = (
        total * (1 - btc_d / 100)
    )

    # TOTAL3: کل بازار بدون بیت‌کوین و اتریوم
    total3 = (
        total
        * (
            1
            - (btc_d + eth_d) / 100
        )
    )

    # OTHERS.D تقریبی از بازار آلت‌کوین‌ها
    # بدون BTC، ETH و استیبل‌کوین‌های اصلی.
    #
    # اگر منبع مقدار USDT را نداشته باشد
    # (مثل Coinpaprika) به تخمین بدون USDT
    # برمی‌گردیم.
    if usdt_d:
        others_d = max(
            0.0,
            100 - btc_d - eth_d - usdt_d
        )
    else:
        others_d = max(
            0.0,
            100 - btc_d - eth_d
        )

    return {
        "BTC.D":
            btc_d,

        "USDT.D":
            usdt_d,

        "OTHERS.D":
            others_d,

        "TOTAL2":
            total2,

        "TOTAL3":
            total3,

        "TOTAL":
            total,

        "SOURCE":
            global_data["source"],

        "timestamp":
            time.time()
    }


# ============================================================
# MARKET ALIGNMENT
# ============================================================

def market_alignment(
    current,
    previous
):

    if not current or not previous:

        return {
            "long": 0,
            "short": 0,
            "total": 5,
            "long_details": {
                "BTC.D": False,
                "USDT.D": False,
                "OTHERS.D": False,
                "TOTAL2": False,
                "TOTAL3": False
            },
            "short_details": {
                "BTC.D": False,
                "USDT.D": False,
                "OTHERS.D": False,
                "TOTAL2": False,
                "TOTAL3": False
            }
        }

    long_details = {}
    short_details = {}

    # LONG:
    # BTC.D down
    long_details["BTC.D"] = (
        current["BTC.D"]
        < previous["BTC.D"]
    )

    short_details["BTC.D"] = (
        current["BTC.D"]
        > previous["BTC.D"]
    )

    # LONG:
    # USDT.D down
    long_details["USDT.D"] = (
        current["USDT.D"]
        < previous["USDT.D"]
    )

    short_details["USDT.D"] = (
        current["USDT.D"]
        > previous["USDT.D"]
    )

    # OTHERS.D up = alt strength
    long_details["OTHERS.D"] = (
        current["OTHERS.D"]
        > previous["OTHERS.D"]
    )

    short_details["OTHERS.D"] = (
        current["OTHERS.D"]
        < previous["OTHERS.D"]
    )

    # TOTAL2 up
    long_details["TOTAL2"] = (
        current["TOTAL2"]
        > previous["TOTAL2"]
    )

    short_details["TOTAL2"] = (
        current["TOTAL2"]
        < previous["TOTAL2"]
    )

    # TOTAL3 up
    long_details["TOTAL3"] = (
        current["TOTAL3"]
        > previous["TOTAL3"]
    )

    short_details["TOTAL3"] = (
        current["TOTAL3"]
        < previous["TOTAL3"]
    )

    long_count = sum(
        long_details.values()
    )

    short_count = sum(
        short_details.values()
    )

    return {
        "long":
            long_count,

        "short":
            short_count,

        "total":
            5,

        "long_details":
            long_details,

        "short_details":
            short_details
    }


# ============================================================
# BTC PAIR
# ============================================================

async def btc_pair(symbol):

    base = symbol.replace(
        "USDT",
        ""
    )

    pair = f"{base}BTC"

    direct = await http_get(
        f"{BINANCE}/fapi/v1/ticker/24hr",
        {
            "symbol": pair
        }
    )

    if direct:

        change = num(
            direct.get(
                "priceChangePercent"
            )
        )

        return {
            "pair":
                f"{base}/BTC",

            "direction":
                (
                    "BULLISH"
                    if change > 0
                    else
                    "BEARISH"
                    if change < 0
                    else
                    "NEUTRAL"
                ),

            "change":
                change
        }

    # Synthetic ALT/BTC
    alt = await http_get(
        f"{BINANCE}/fapi/v1/ticker/24hr",
        {
            "symbol": symbol
        }
    )

    btc = await http_get(
        f"{BINANCE}/fapi/v1/ticker/24hr",
        {
            "symbol": "BTCUSDT"
        }
    )

    if not alt or not btc:

        return {
            "pair":
                f"{base}/BTC",

            "direction":
                "UNKNOWN",

            "change":
                None
        }

    relative = (
        num(
            alt.get(
                "priceChangePercent"
            )
        )
        -
        num(
            btc.get(
                "priceChangePercent"
            )
        )
    )

    return {
        "pair":
            f"{base}/BTC",

        "direction":
            (
                "BULLISH"
                if relative > 0
                else
                "BEARISH"
                if relative < 0
                else
                "NEUTRAL"
            ),

        "change":
            relative
    }


# ============================================================
# FLOW DIRECTION
# ============================================================

def flow_threshold(flow, fallback):

    # آستانهٔ CryptoMeter و حجم taker بایننس
    # هم‌مقیاس نیستند، پس هر منبع آستانهٔ خودش
    # را لازم دارد.
    if (
        flow
        and flow.get("source")
        == "binance-taker"
    ):
        return BINANCE_FLOW_MIN_RATIO

    return fallback


def flow_direction(flow):

    if not flow:
        return "UNKNOWN"

    inflow = num(
        flow.get("inflow")
    )

    outflow = num(
        flow.get("outflow")
    )

    netflow = num(
        flow.get("netflow")
    )

    total = (
        inflow
        + outflow
    )

    if total <= 0:
        return "UNKNOWN"

    ratio = (
        netflow
        / total
    )

    threshold = flow_threshold(
        flow,
        MIN_FLOW_RATIO_SIGNAL
    )

    if ratio >= threshold:
        return "BULLISH"

    if ratio <= -threshold:
        return "BEARISH"

    return "NEUTRAL"


# ============================================================
# EARLY WATCH
# ============================================================

def early_watch(
    volume,
    lwc,
    flow
):

    if not volume:
        return False

    if (
        volume["volume_ratio"]
        < EARLY_VOLUME_RATIO
    ):
        return False

    if (
        abs(
            volume["price_move"]
        )
        > MAX_PRICE_MOVE
    ):
        return False

    flow_ok = False

    if flow:

        total = (
            num(
                flow.get("inflow")
            )
            +
            num(
                flow.get("outflow")
            )
        )

        if total:

            ratio = abs(
                num(
                    flow.get(
                        "netflow"
                    )
                )
            ) / total

            flow_ok = (
                ratio
                >= flow_threshold(
                    flow,
                    EARLY_FLOW_RATIO
                )
            )

    lwc_ok = bool(lwc)

    return (
        flow_ok
        or lwc_ok
    )


# ============================================================
# FINAL SIGNAL
# ============================================================

def detect_signal(
    rsi_data,
    volume,
    flow,
    btc,
    market,
    oi=None,
    fg=None
):

    if not rsi_data or not volume:
        return None

    r15 = rsi_data["15m"]
    r1h = rsi_data["1h"]
    r4h = rsi_data["4h"]

    if None in (
        r15,
        r1h,
        r4h
    ):
        return None

    flow_dir = flow_direction(
        flow
    )

    # ---------------- OI / SENTIMENT ----------------
    #
    # این دو شرط پیش‌فرض غیرفعال‌اند تا سیگنال
    # بیش از حد سخت‌گیرانه نشود. با متغیرهای
    # REQUIRE_OI_RISING و FEAR_GREED_* فعال می‌شوند.

    oi_ok_long = True
    oi_ok_short = True

    if REQUIRE_OI_RISING and oi:

        oi_ok_long = (oi["change_pct"] > 0)
        oi_ok_short = (oi["change_pct"] < 0)

    fg_ok_long = True
    fg_ok_short = True

    if fg:

        if FEAR_GREED_MAX_LONG > 0:

            fg_ok_long = (
                fg["value"]
                < FEAR_GREED_MAX_LONG
            )

        if FEAR_GREED_MIN_SHORT > 0:

            fg_ok_short = (
                fg["value"]
                > FEAR_GREED_MIN_SHORT
            )

    # ---------------- LONG ----------------

    long_rsi = (
        r15 <= LONG_RSI_15M
        and r1h <= LONG_RSI_1H
        and r4h <= LONG_RSI_4H
    )

    long_volume = (
        volume["volume_ratio"]
        >= VOLUME_MULTIPLIER
    )

    long_money = (
        flow_dir == "BULLISH"
        or volume["buy_ratio"]
        >= 0.55
    )

    long_btc = (
        btc["direction"]
        == "BULLISH"
    )

    long_market = (
        market["long"]
        >= 3
    )

    if all([
        long_rsi,
        long_volume,
        long_money,
        long_btc,
        long_market,
        oi_ok_long,
        fg_ok_long
    ]):

        return "LONG"

    # ---------------- SHORT ----------------

    short_rsi = (
        r15 >= SHORT_RSI_15M
        and r1h >= SHORT_RSI_1H
        and r4h >= SHORT_RSI_4H
    )

    short_volume = (
        volume["volume_ratio"]
        >= VOLUME_MULTIPLIER
    )

    short_money = (
        flow_dir == "BEARISH"
        or volume["buy_ratio"]
        <= 0.45
    )

    short_btc = (
        btc["direction"]
        == "BEARISH"
    )

    short_market = (
        market["short"]
        >= 3
    )

    if all([
        short_rsi,
        short_volume,
        short_money,
        short_btc,
        short_market,
        oi_ok_short,
        fg_ok_short
    ]):

        return "SHORT"

    return None


# ============================================================
# AI
# ============================================================

def ai_providers():

    # ترتیب provider ها. اگر AI_PROVIDER ست شده
    # باشد، آن اول امتحان می‌شود و بقیه به‌عنوان
    # fallback می‌آیند.
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


async def openai_compatible(
    url,
    api_key,
    model,
    prompt,
    label
):

    # Groq و OpenRouter هر دو API سازگار با OpenAI
    # دارند، پس با یک تابع پوشش داده می‌شوند.
    data = await http_post(
        url,
        {
            "model": model,

            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        },
        {
            "content-type":
                "application/json",

            "Authorization":
                f"Bearer {api_key}"
        }
    )

    if not data:
        return None

    try:

        text = (
            data["choices"][0]
            ["message"]["content"]
            .strip()
        )

        return text or None

    except (
        KeyError,
        IndexError,
        TypeError,
        AttributeError
    ) as e:

        print(
            f"{label} PARSE ERROR:",
            e,
            str(data)[:200]
        )

        return None


async def openai_analysis(prompt):

    if not openai_client:
        return None

    try:

        response = await openai_client.responses.create(
            model=OPENAI_MODEL,
            input=prompt
        )

        return response.output_text.strip()

    except Exception as e:

        print(
            "OPENAI ERROR:",
            e
        )

        return None


async def gemini_analysis(prompt):

    if not GEMINI_API_KEY:
        return None

    url = (
        "https://generativelanguage"
        ".googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
    )

    data = await http_post(
        url,
        {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ]
        },
        {
            "content-type":
                "application/json",

            "x-goog-api-key":
                GEMINI_API_KEY
        }
    )

    if not data:
        return None

    try:

        parts = (
            data["candidates"][0]
            ["content"]["parts"]
        )

        text = "".join(
            p.get("text", "")
            for p in parts
        ).strip()

        return text or None

    except (
        KeyError,
        IndexError,
        TypeError
    ) as e:

        print(
            "GEMINI PARSE ERROR:",
            e,
            str(data)[:200]
        )

        return None


async def call_provider(provider, prompt):

    if provider == "gemini":

        return await gemini_analysis(
            prompt
        )

    if provider == "groq":

        return await openai_compatible(
            "https://api.groq.com/openai/v1/"
            "chat/completions",
            GROQ_API_KEY,
            GROQ_MODEL,
            prompt,
            "GROQ"
        )

    if provider == "openrouter":

        return await openai_compatible(
            "https://openrouter.ai/api/v1/"
            "chat/completions",
            OPENROUTER_API_KEY,
            OPENROUTER_MODEL,
            prompt,
            "OPENROUTER"
        )

    if provider == "openai":

        return await openai_analysis(
            prompt
        )

    return None


async def ai_check():

    providers = ai_providers()

    if not providers:

        print(
            "AI: no provider configured. Set one "
            "of GEMINI_API_KEY / GROQ_API_KEY / "
            "OPENROUTER_API_KEY / OPENAI_API_KEY."
        )

        return

    print(
        "AI providers:",
        " -> ".join(providers)
    )

    for provider in providers:

        text = await call_provider(
            provider,
            "Reply with exactly: OK"
        )

        if text:

            print(
                f"AI check: {provider} OK ->",
                text[:40]
            )

            return

        print(
            f"AI check: {provider} FAILED "
            "(bad key, quota, or model)"
        )

    print(
        "AI check: *** ALL PROVIDERS FAILED ***"
    )


async def ai_analysis(data):

    providers = ai_providers()

    if not providers:

        return (
            "AI فعال نیست؛ "
            "تحلیل عددی در پیام موجود است."
        )

    prompt = f"""
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

    # اگر provider اول جواب نداد (مثلاً quota یا
    # خطای موقت)، بعدی امتحان می‌شود.
    for provider in providers:

        text = await call_provider(
            provider,
            prompt
        )

        if text:

            return text

        print(
            f"AI: provider '{provider}' failed,"
            " trying next..."
        )

    return (
        "تحلیل AI در دسترس نبود."
    )


# ============================================================
# TELEGRAM
# ============================================================

async def telegram(message):

    if not TELEGRAM_BOT_TOKEN:

        print(
            "TELEGRAM SKIPPED: "
            "TELEGRAM_BOT_TOKEN is empty."
        )

        return

    if not TELEGRAM_CHAT_ID:

        print(
            "TELEGRAM SKIPPED: "
            "TELEGRAM_CHAT_ID is empty."
        )

        return

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    result = await http_post(
        url,
        {
            "chat_id":
                TELEGRAM_CHAT_ID,

            "text":
                message,

            "parse_mode":
                "HTML",

            "disable_web_page_preview":
                True
        }
    )

    if not result or not result.get("ok"):

        print(
            "TELEGRAM SEND FAILED:",
            (
                result.get("description")
                if isinstance(result, dict)
                else "no response"
            )
        )


# ============================================================
# COOLDOWN
# ============================================================

def can_send(key):

    now = time.time()

    previous = last_signals.get(
        key,
        0
    )

    if (
        now - previous
        < SIGNAL_COOLDOWN
    ):
        return False

    last_signals[key] = now

    return True


# ============================================================
# MARKET FORMAT
# ============================================================

def market_text(
    market,
    direction
):

    if direction == "LONG":

        details = market[
            "long_details"
        ]

        count = market["long"]

    else:

        details = market[
            "short_details"
        ]

        count = market["short"]

    return (
        f"{check(details['BTC.D'])} BTC.D\n"
        f"{check(details['USDT.D'])} USDT.D\n"
        f"{check(details['OTHERS.D'])} OTHERS.D\n"
        f"{check(details['TOTAL2'])} TOTAL2\n"
        f"{check(details['TOTAL3'])} TOTAL3\n"
        f"\n<b>Alignment: "
        f"{count}/5</b>"
    )


def flow_text(flow):

    if not flow:
        return "Money Flow: unavailable"

    inflow = num(
        flow.get("inflow")
    )

    outflow = num(
        flow.get("outflow")
    )

    netflow = num(
        flow.get("netflow")
    )

    direction = (
        "🟢 INFLOW"
        if netflow > 0
        else
        "🔴 OUTFLOW"
        if netflow < 0
        else
        "⚪ NEUTRAL"
    )

    total = inflow + outflow

    share = (
        inflow / total * 100
        if total
        else 0
    )

    return (
        f"{direction}\n"
        f"Buy volume: {inflow:,.0f}\n"
        f"Sell volume: {outflow:,.0f}\n"
        f"Net: {netflow:,.0f}\n"
        f"Buy share: {share:.1f}%"
    )


# ============================================================
# OPEN INTEREST / SENTIMENT TEXT
# ============================================================

def oi_text(oi):

    if not oi:
        return "Open Interest: unavailable"

    change = oi["change_pct"]

    if change > 0:

        arrow = "🟢"
        note = "new money entering"

    elif change < 0:

        arrow = "🔴"
        note = "positions closing"

    else:

        arrow = "⚪"
        note = "flat"

    return (
        f"{arrow} {change:+.2f}% "
        f"({oi['candles']}x{oi['period']})\n"
        f"Open Interest: "
        f"{oi['current']:,.0f}\n"
        f"{note}"
    )


def fg_text(fg):

    if not fg:
        return "Fear & Greed: unavailable"

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

    return (
        f"{emoji} {value} - {fg['label']}"
    )


# ============================================================
# SIGNAL MESSAGE
# ============================================================

def signal_message(
    direction,
    symbol,
    rsi_data,
    volume,
    lwc,
    flow,
    btc,
    market,
    ai,
    oi=None,
    fg=None
):

    emoji = (
        "🟢"
        if direction == "LONG"
        else "🔴"
    )

    lwc_text = "Unavailable"

    if lwc:

        lwc_text = (
            f"Volume: "
            f"${lwc['volume']:,.0f}\n"
            f"Vol/MCap: "
            f"{lwc['vol_to_mcap']:.2f}\n"
            f"Liquidity: "
            f"${lwc['liquidity']:,.0f}\n"
            f"Pressure: "
            f"{lwc['pressure']:.2f}\n"
            f"1H: "
            f"{lwc['change_1h']:+.2f}%\n"
            f"24H: "
            f"{lwc['change_24h']:+.2f}%"
        )

    return f"""
<b>{emoji} {direction} SIGNAL</b>

<b>COIN:</b> {symbol}

━━━━━━━━━━━━━━

<b>RSI</b>

15m: {rsi_data['15m']:.2f}
1H: {rsi_data['1h']:.2f}
4H: {rsi_data['4h']:.2f}

━━━━━━━━━━━━━━

<b>BINANCE VOLUME</b>

Volume: {volume['volume_ratio']:.2f}x
Price move: {volume['price_move']:+.2f}%
Buy pressure: {volume['buy_ratio'] * 100:.1f}%

━━━━━━━━━━━━━━

<b>OPEN INTEREST</b>

{oi_text(oi)}

━━━━━━━━━━━━━━

<b>LIVECOINWATCH</b>

{lwc_text}

━━━━━━━━━━━━━━

<b>MONEY FLOW</b>

{flow_text(flow)}

━━━━━━━━━━━━━━

<b>BTC PAIR</b>

{btc['pair']}
Direction:
<b>{btc['direction']}</b>

Relative:
{btc['change'] if btc['change'] is not None else 0:+.2f}%

━━━━━━━━━━━━━━

<b>MARKET DOMINANCE</b>

{market_text(
    market,
    direction
)}

━━━━━━━━━━━━━━

<b>SENTIMENT</b>

{fg_text(fg)}

━━━━━━━━━━━━━━

<b>AI ANALYSIS</b>

{ai}

━━━━━━━━━━━━━━

⚠️ Signal only.
No trade execution.
"""


# ============================================================
# EARLY MESSAGE
# ============================================================

def early_message(
    symbol,
    volume,
    lwc,
    flow,
    oi=None,
    fg=None
):

    return f"""
<b>🟡 EARLY WATCH</b>

<b>{symbol}</b>

حجم غیرعادی وارد شده،
اما قیمت هنوز حرکت بزرگی نکرده است.

یعنی:
<b>Volume + Money Flow</b>
قبل از حرکت بزرگ دیده شده است.

━━━━━━━━━━━━━━

<b>BINANCE</b>

Volume:
{volume['volume_ratio']:.2f}x

Price:
{volume['price_move']:+.2f}%

Buy pressure:
{volume['buy_ratio'] * 100:.1f}%

━━━━━━━━━━━━━━

<b>OPEN INTEREST</b>

{oi_text(oi)}

━━━━━━━━━━━━━━

<b>LIVECOINWATCH</b>

Volume:
${lwc.get('volume', 0):,.0f}

Vol/MCap:
{lwc.get('vol_to_mcap', 0):.2f}

Liquidity:
${lwc.get('liquidity', 0):,.0f}

Pressure:
{lwc.get('pressure', 0):.2f}

━━━━━━━━━━━━━━

<b>MONEY FLOW</b>

{flow_text(flow)}

━━━━━━━━━━━━━━

<b>SENTIMENT</b>

{fg_text(fg)}

━━━━━━━━━━━━━━

🟡 هنوز LONG/SHORT نهایی نیست.

⚠️ Signal only.
No trade execution.
"""


# ============================================================
# SCANNER
# ============================================================

async def scan():

    global previous_dominance

    print(
        "Scanning market..."
    )

    # ------------------------------
    # DOMINANCE
    # ------------------------------

    dominance = (
        await get_dominance()
    )

    market = market_alignment(
        dominance,
        previous_dominance
    )

    if dominance:
        previous_dominance = dominance

    # ------------------------------
    # EXTERNAL DATA
    # ------------------------------

    lwc = await livecoinwatch()

    # Money Flow حالا per-symbol و رایگان از بایننس
    # خوانده می‌شود، پس داخل حلقهٔ اسکن می‌آید.
    cryptometer = await cryptometer_flow()

    # Fear & Greed سراسری است و روزی یکبار
    # آپدیت می‌شود، پس یکبار در هر اسکن کافی است.
    fg = await fear_greed()

    have_external_data = (
        bool(lwc) or bool(cryptometer)
    )

    if not have_external_data:

        print(
            "WARNING: LiveCoinWatch returned no "
            "data. Falling back to top-volume "
            "symbols only."
        )

    # ------------------------------
    # BINANCE
    # ------------------------------

    symbols = (
        await binance_symbols()
    )

    tickers = (
        await binance_tickers()
    )

    candidates = []

    for symbol in symbols:

        ticker = tickers.get(
            symbol
        )

        if not ticker:
            continue

        quote_volume = num(
            ticker.get(
                "quoteVolume"
            )
        )

        if quote_volume <= 0:
            continue

        base = symbol.replace(
            "USDT",
            ""
        )

        lwc_coin = lwc.get(
            base
        )

        if not lwc_coin:

            # بدون هیچ دادهٔ خارجی هم اسکن متوقف
            # نشود؛ فقط اگر داده موجود باشد و برای
            # این کوین چیزی نبود، رد می‌شود.
            if have_external_data:
                continue

        candidates.append(
            (
                symbol,
                quote_volume,
                lwc_coin
            )
        )

    candidates.sort(
        key=lambda x: x[1],
        reverse=True
    )

    candidates = candidates[
        :MAX_SYMBOLS
    ]

    print(
        "Candidates:",
        len(candidates)
    )

    # ------------------------------
    # COIN SCAN
    # ------------------------------

    for (
        symbol,
        _,
        lwc_coin
    ) in candidates:

        try:

            volume = (
                await volume_analysis(
                    symbol
                )
            )

            if not volume:
                continue

            # ورود/خروج پول همین نماد
            flow_coin = await money_flow(
                symbol
            )

            # تغییر پوزیشن باز همین نماد
            oi = await binance_open_interest(
                symbol
            )

            # ==========================
            # EARLY WATCH
            # ==========================

            if early_watch(
                volume,
                lwc_coin,
                flow_coin
            ):

                key = (
                    f"EARLY:{symbol}"
                )

                if can_send(key):

                    await telegram(
                        early_message(
                            symbol,
                            volume,
                            lwc_coin or {},
                            flow_coin or {},
                            oi,
                            fg
                        )
                    )

                    print(
                        "EARLY WATCH:",
                        symbol
                    )

            # ==========================
            # FINAL SIGNAL
            # ==========================

            if (
                volume["volume_ratio"]
                < VOLUME_MULTIPLIER
            ):
                continue

            rsi_data = (
                await all_rsi(
                    symbol
                )
            )

            btc = await btc_pair(
                symbol
            )

            direction = detect_signal(
                rsi_data,
                volume,
                flow_coin,
                btc,
                market,
                oi,
                fg
            )

            if not direction:
                continue

            key = (
                f"{direction}:{symbol}"
            )

            if not can_send(key):
                continue

            signal_data = {
                "symbol":
                    symbol,

                "direction":
                    direction,

                "rsi":
                    rsi_data,

                "volume":
                    volume,

                "livecoinwatch":
                    lwc_coin,

                "money_flow":
                    flow_coin,

                "open_interest":
                    oi,

                "fear_greed":
                    fg,

                "btc_pair":
                    btc,

                "market":
                    market
            }

            ai = await ai_analysis(
                signal_data
            )

            await telegram(
                signal_message(
                    direction,
                    symbol,
                    rsi_data,
                    volume,
                    lwc_coin,
                    flow_coin,
                    btc,
                    market,
                    ai,
                    oi,
                    fg
                )
            )

            print(
                "SIGNAL:",
                direction,
                symbol
            )

            await asyncio.sleep(
                0.25
            )

        except Exception as e:

            print(
                "SCAN ERROR",
                symbol,
                e
            )


# ============================================================
# BACKGROUND
# ============================================================

async def scanner_loop():

    await asyncio.sleep(10)

    while True:

        try:
            await scan()

        except Exception as e:

            print(
                "GLOBAL SCANNER ERROR:",
                e
            )

        await asyncio.sleep(
            SCAN_INTERVAL
        )


# ============================================================
# STARTUP DIAGNOSTICS
# ============================================================

async def startup_diagnostics():

    print("=" * 55)
    print("Crypto AI Signal Bot - startup check")
    print("PORT:", os.getenv("PORT", "<not set>"))
    print(
        "TELEGRAM_BOT_TOKEN:",
        "set" if TELEGRAM_BOT_TOKEN
        else "*** MISSING ***"
    )
    print(
        "TELEGRAM_CHAT_ID:",
        "set" if TELEGRAM_CHAT_ID
        else "*** MISSING ***"
    )
    print(
        "OPENAI_API_KEY:",
        "set" if OPENAI_API_KEY
        else "not set"
    )
    print(
        "GEMINI_API_KEY:",
        "set" if GEMINI_API_KEY
        else "not set"
    )
    print(
        "GROQ_API_KEY:",
        "set" if GROQ_API_KEY
        else "not set"
    )
    print(
        "OPENROUTER_API_KEY:",
        "set" if OPENROUTER_API_KEY
        else "not set"
    )
    print(
        "LIVECOINWATCH_API_KEY:",
        "set" if LIVECOINWATCH_API_KEY
        else "*** MISSING ***"
    )
    print(
        "CRYPTOMETER_API_KEY:",
        "set" if CRYPTOMETER_API_KEY
        else "not set"
    )
    print(
        "MONEY FLOW:",
        "CryptoMeter if paid plan active, "
        "else Binance futures taker (free)"
    )
    print(
        "COINMARKETCAP_API_KEY:",
        "set (last-resort fallback)"
        if COINMARKETCAP_API_KEY
        else "not set (not needed)"
    )
    print(
        "DOMINANCE SOURCE:",
        "CoinGecko -> Coinpaprika"
        + (
            " -> CoinMarketCap"
            if COINMARKETCAP_API_KEY
            else ""
        )
    )
    print(
        "DOMINANCE_INTERVAL:",
        DOMINANCE_INTERVAL,
        "s | SCAN_INTERVAL:",
        SCAN_INTERVAL,
        "s"
    )
    print("=" * 55)

    # بررسی واقعی provider هوش مصنوعی
    await ai_check()

    if not TELEGRAM_BOT_TOKEN:

        print(
            "ERROR: TELEGRAM_BOT_TOKEN is missing. "
            "No message can be sent. Set it in the "
            "Render dashboard -> Environment."
        )

        return

    # اعتبارسنجی توکن ربات تلگرام
    me = await http_get(
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/getMe"
    )

    if not me or not me.get("ok"):

        print(
            "ERROR: TELEGRAM_BOT_TOKEN is invalid ->",
            (
                me.get("description")
                if isinstance(me, dict)
                else "no response"
            )
        )

        return

    print(
        "Telegram bot OK:",
        me["result"].get("username")
    )

    # اعتبارسنجی chat id
    chat = await http_get(
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/getChat",
        {
            "chat_id":
                TELEGRAM_CHAT_ID
        }
    )

    if not chat or not chat.get("ok"):

        print(
            "ERROR: TELEGRAM_CHAT_ID is invalid ->",
            (
                chat.get("description")
                if isinstance(chat, dict)
                else "no response"
            )
        )

    else:

        print(
            "Telegram chat OK:",
            chat["result"].get("type")
        )


@app.get("/")
async def health():

    return {
        "status":
            "online",

        "execution":
            False,

        "binance":
            True,

        "livecoinwatch":
            bool(
                LIVECOINWATCH_API_KEY
            ),

        "money_flow":
            "binance-futures-taker",

        "dominance":
            "coingecko -> coinpaprika",

        "open_interest":
            "binance-futures",

        "sentiment":
            "alternative.me",

        "coinmarketcap":
            bool(
                COINMARKETCAP_API_KEY
            ),

        "ai":
            ai_providers()
    }


# ============================================================
# ENTRYPOINT (Render / Uvicorn)
# ============================================================

# این فایل قبلاً هیچ entrypoint نداشت. یعنی
# `python main.py` فقط ماژول را import می‌کرد،
# اپ FastAPI ساخته می‌شد و پروسه بلافاصله با
# کد خروج 0 تمام می‌شد:
#
#   * هیچ پورتی باز نمی‌شد
#   * حلقهٔ اسکنر هیچ‌وقت اجرا نمی‌شد
#   * Render خطای «no open ports detected» می‌داد
#
# Render متغیر PORT را خودش تعیین می‌کند و اپ
# باید روی 0.0.0.0 گوش بدهد (نه 127.0.0.1).

if __name__ == "__main__":

    port = int(
        os.getenv("PORT", "8000")
    )

    print(
        "Starting uvicorn on "
        f"0.0.0.0:{port}"
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
