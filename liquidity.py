"""Free multi-exchange order-book liquidity check; not a liquidation heatmap."""
import logging
import time
import aiohttp

log = logging.getLogger("signal-bot.liquidity")
_CACHE = {}
TTL = 20


async def _get(session, url, params=None):
    async with session.get(url, params=params) as response:
        if response.status == 429:
            raise RuntimeError("rate limited")
        response.raise_for_status()
        return await response.json()


async def _fetch(symbol):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as s:
        providers = [
            ("Binance Futures", "https://fapi.binance.com/fapi/v1/depth",
             {"symbol": symbol, "limit": 100}, "binance"),
            ("Bybit Linear", "https://api.bybit.com/v5/market/orderbook",
             {"category": "linear", "symbol": symbol, "limit": 50}, "bybit"),
        ]
        if symbol.endswith("USDT"):
            providers.append(("OKX Swap", "https://www.okx.com/api/v5/market/books",
                              {"instId": symbol[:-4] + "-USDT-SWAP", "sz": 50}, "okx"))
        for name, url, params, kind in providers:
            try:
                data = await _get(s, url, params)
                if kind == "binance":
                    return data["bids"], data["asks"], name
                if kind == "bybit":
                    if str(data.get("retCode")) != "0":
                        raise RuntimeError("Bybit error")
                    return data["result"]["b"], data["result"]["a"], name
                if data.get("code") != "0" or not data.get("data"):
                    raise RuntimeError("OKX error")
                return data["data"][0]["bids"], data["data"][0]["asks"], name
            except Exception as exc:
                log.warning("Liquidity fallback %s failed for %s: %s",
                            name, symbol, type(exc).__name__)
    return None


def _levels(rows, price):
    out = []
    for row in rows or []:
        try:
            p, q = float(row[0]), float(row[1])
            distance = abs(p - price) / price * 100
            if p > 0 and q > 0 and distance <= 2:
                out.append((p, p * q, distance))
        except (ValueError, TypeError, IndexError, ZeroDivisionError):
            pass
    return sorted(out, key=lambda x: x[1], reverse=True)


def _format(levels):
    if not levels:
        return "سفارش بزرگ قابل‌مشاهده پیدا نشد"
    return "؛ ".join(f"{p:.8g} (~${usd:,.0f}, فاصله {d:.2f}٪)"
                     for p, usd, d in levels[:3])


async def liquidity_report(symbol, current_price=None):
    symbol = (symbol or "").upper().strip()
    if not symbol.endswith("USDT") or not symbol.isalnum():
        return "🧭 <b>نقدینگی:</b> نماد USDT معتبر پیدا نشد."
    now = time.time()
    cached = _CACHE.get(symbol)
    if cached and now - cached[0] < TTL:
        result = cached[1]
    else:
        fetched = await _fetch(symbol)
        if not fetched:
            return ("🧭 <b>دفتر سفارشات:</b> Binance، Bybit و OKX در دسترس نبودند؛ "
                    "داده نامشخص است.\n🧲 <b>نقشه لیکوییدیشن:</b> داده معتبر در دسترس نیست.")
        bids, asks, source = fetched
        try:
            price = float(current_price or 0)
        except (ValueError, TypeError):
            price = 0
        if price <= 0:
            try:
                price = (float(bids[0][0]) + float(asks[0][0])) / 2
            except (ValueError, TypeError, IndexError):
                return "🧭 <b>نقدینگی:</b> قیمت معتبر پیدا نشد."
        bid_levels, ask_levels = _levels(bids, price), _levels(asks, price)
        result = {"source": source, "price": price, "bids": bid_levels,
                  "asks": ask_levels, "timestamp": now}
        _CACHE[symbol] = (now, result)
    age = int(max(0, time.time() - result["timestamp"]))
    buy_total = sum(x[1] for x in result["bids"])
    sell_total = sum(x[1] for x in result["asks"])
    if buy_total > sell_total * 1.25:
        balance = "عمق خرید بیشتر است"
    elif sell_total > buy_total * 1.25:
        balance = "عمق فروش بیشتر است"
    else:
        balance = "عمق خرید و فروش نزدیک به هم است"
    return (
        "🧭 <b>نقدینگی دفتر سفارشات (تا فاصله ۲٪)</b>\n"
        f"📚 منبع: <b>{result['source']}</b> · تازگی: {age} ثانیه\n"
        f"⚖️ {balance}\n"
        f"🟢 عمق خرید تقریبی: <code>${buy_total:,.0f}</code>\n"
        f"   ناحیه‌های خرید بزرگ: {_format(result['bids'])}\n"
        f"🔴 عمق فروش تقریبی: <code>${sell_total:,.0f}</code>\n"
        f"   ناحیه‌های فروش بزرگ: {_format(result['asks'])}\n"
        "🧲 <b>لیکوییدیشن زیاد/کم:</b> نقشه تخصصی لیکوییدیشن در این نسخه وصل نیست؛ "
        "دیوار سفارشات را با لیکوییدیشن اشتباه نگیر."
    )
