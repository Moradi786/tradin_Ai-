

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
# MONEY FLOW (Binance futures - رایگان)
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
    # وگرنه به‌صورت رایگان از مشتقات بایننس خوانده می‌شود.
    base = symbol.replace("USDT", "")

    cryptometer = await cryptometer_flow()
    if cryptometer and base in cryptometer:
        return cryptometer[base]

    return await binance_flow(symbol)


# ============================================================
# OPEN INTEREST (Binance futures - رایگان)
# ============================================================


async def binance_open_interest(symbol: str) -> Optional[dict]:
    """تغییر پوزیشن باز. OI صعودی = پول جدید وارد شده."""
    now = time.time()
    cached = oi_cache.get(symbol)
    if cached and now - cached["timestamp"] < FLOW_INTERVAL:
        return cached["data"]

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
        snapshot = await source()
        if snapshot:
            global_cache["timestamp"] = now
            global_cache["data"] = snapshot
            return snapshot
        log.warning("dominance source failed: %s", source.__name__)

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
    # آستانهٔ CryptoMeter و حجم taker بایننس هم‌مقیاس نیستند.
    if flow and flow.get("source") == "binance-taker":
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
