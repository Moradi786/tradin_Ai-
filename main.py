import os
import asyncio
import time
from typing import Optional

import aiohttp
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

LWC_LIMIT = int(
    os.getenv("LWC_LIMIT", "100")
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


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Crypto AI Signal Bot"
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

dominance_cache = {
    "timestamp": 0,
    "data": None
}


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
                print(
                    "HTTP ERROR",
                    response.status,
                    url
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
                print(
                    "HTTP POST ERROR",
                    response.status,
                    url
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

        result[symbol] = {
            "volume": num(
                item.get("volume")
            ),
            "market_cap": num(
                item.get("cap")
            ),
            "vol_to_mcap": num(
                item.get(
                    "volToMcap"
                )
            ),
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

    if not CRYPTOMETER_API_KEY:
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
        print(
            "CryptoMeter flow unavailable"
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
# CMC / MARKET DOMINANCE
# ============================================================

async def get_cmc_global():

    now = time.time()

    if (
        dominance_cache["data"]
        and now
        - dominance_cache["timestamp"]
        < CMC_INTERVAL
    ):
        return dominance_cache["data"]

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

    # TOTAL2:
    # Total market cap excluding BTC
    total2 = (
        total_market_cap
        * (1 - btc_d / 100)
    )

    # TOTAL3:
    # Total market cap excluding BTC + ETH
    total3 = (
        total_market_cap
        * (
            1
            - (
                btc_d
                + eth_d
            ) / 100
        )
    )

    result = {
        "btc_d": btc_d,
        "eth_d": eth_d,
        "total_market_cap":
            total_market_cap,
        "total2": total2,
        "total3": total3,
        "timestamp": time.time()
    }

    dominance_cache[
        "timestamp"
    ] = now

    dominance_cache[
        "data"
    ] = result

    return result


# ============================================================
# USDT DOMINANCE
# ============================================================

async def get_usdt_dominance():

    # CoinGecko global data gives market-cap
    # percentages for major assets, including USDT
    # when available.

    data = await http_get(
        "https://api.coingecko.com/api/v3/global"
    )

    if not data:
        return None

    market = data.get(
        "data",
        {}
    )

    percentages = (
        market.get(
            "market_cap_percentage",
            {}
        )
    )

    usdt_d = num(
        percentages.get(
            "usdt"
        )
    )

    if usdt_d <= 0:
        return None

    return usdt_d


# ============================================================
# DOMINANCE SNAPSHOT
# ============================================================

async def get_dominance():

    cmc = await get_cmc_global()

    if not cmc:
        return None

    usdt_d = await get_usdt_dominance()

    if usdt_d is None:
        usdt_d = 0.0

    total = cmc[
        "total_market_cap"
    ]

    # CMC altcoin market cap gives a broad
    # non-BTC market measure.
    #
    # OTHERS.D here is an analytical approximation,
    # not a claim that it exactly equals TradingView
    # CRYPTOCAP:OTHERS.D.

    others_cap = max(
        0,
        cmc["total3"]
    )

    others_d = (
        others_cap
        / total
        * 100
        if total
        else 0
    )

    return {
        "BTC.D":
            cmc["btc_d"],

        "USDT.D":
            usdt_d,

        "OTHERS.D":
            others_d,

        "TOTAL2":
            cmc["total2"],

        "TOTAL3":
            cmc["total3"],

        "TOTAL":
            total,

        "timestamp":
            cmc["timestamp"]
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

    if ratio >= MIN_FLOW_RATIO_SIGNAL:
        return "BULLISH"

    if ratio <= -MIN_FLOW_RATIO_SIGNAL:
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
                >= EARLY_FLOW_RATIO
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
    market
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
        long_market
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
        short_market
    ]):

        return "SHORT"

    return None


# ============================================================
# AI
# ============================================================

async def ai_analysis(data):

    if not openai_client:

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

        return (
            "تحلیل AI در دسترس نبود."
        )


# ============================================================
# TELEGRAM
# ============================================================

async def telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        return

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    await http_post(
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
        return "CryptoMeter: unavailable"

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

    return (
        f"{direction}\n"
        f"Inflow: ${inflow:,.0f}\n"
        f"Outflow: ${outflow:,.0f}\n"
        f"Netflow: ${netflow:,.0f}"
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
    ai
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

<b>LIVECOINWATCH</b>

{lwc_text}

━━━━━━━━━━━━━━

<b>CRYPTOMETER</b>

{flow_text(flow)}

━━━━━━━━━━━━━━

<b>BTC PAIR</b>

{btc['pair']}
Direction:
<b>{btc['direction']}</b>

Relative:
{btc['change']:+.2f}%

━━━━━━━━━━━━━━

<b>MARKET DOMINANCE</b>

{market_text(
    market,
    direction
)}

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
    flow
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

<b>CRYPTOMETER</b>

{flow_text(flow)}

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

    flow = await cryptometer_flow()

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

        flow_coin = flow.get(
            base
        )

        if not lwc_coin and not flow_coin:
            continue

        candidates.append(
            (
                symbol,
                quote_volume,
                lwc_coin,
                flow_coin
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
        lwc_coin,
        flow_coin
    ) in candidates:

        try:

            volume = (
                await volume_analysis(
                    symbol
                )
            )

            if not volume:
                continue

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
                            flow_coin or {}
                        )
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
                market
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

                "cryptometer":
                    flow_coin,

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
                    ai
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


@app.on_event("startup")
async def startup():

    asyncio.create_task(
        scanner_loop()
    )


@app.on_event("shutdown")
async def shutdown():

    global http_session

    if (
        http_session
        and not http_session.closed
    ):
        await http_session.close()


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

        "cryptometer":
            bool(
                CRYPTOMETER_API_KEY
            ),

        "coinmarketcap":
            True,

        "openai":
            bool(
                OPENAI_API_KEY
            )
    }