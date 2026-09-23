import asyncio
import logging
import os
import sqlite3
import time
from typing import Dict, Any, Optional, List, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import aiohttp
from datetime import datetime, timedelta, timezone

# ==========================================================
# 0. Config
# ==========================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
LOGGER = logging.getLogger("SignalBot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PORT = int(os.getenv("PORT", 8080))

# API URLs
BINANCE_FUTURES_KLINES_URL = os.getenv("BINANCE_FUTURES_KLINES_URL", "https://fapi.binance.com/fapi/v1/klines")
BINANCE_FUTURES_DEPTH_URL = os.getenv("BINANCE_FUTURES_DEPTH_URL", "https://fapi.binance.com/fapi/v1/depth")
BINANCE_FUTURES_TICKER_URL = os.getenv("BINANCE_FUTURES_TICKER_URL", "https://fapi.binance.com/fapi/v1/ticker/24hr")

# Settings
CHECK_INTERVAL_SECONDS = max(5, int(os.getenv("CHECK_INTERVAL_SECONDS", "5")))
MIN_BTC_VOLUME = float(os.getenv("MIN_BTC_VOLUME", "50.0"))
MAX_SL_PERCENT = float(os.getenv("MAX_SL_PERCENT", "2.0"))
SIGNAL_COOLDOWN_MINUTES = int(os.getenv("SIGNAL_COOLDOWN_MINUTES", "360"))

# Strategy 4: Volume Without Movement
S4_MIN_VOLUME_RATIO = float(os.getenv("S4_MIN_VOLUME_RATIO", "2.0"))
S4_MAX_PRICE_MOVE_5C = float(os.getenv("S4_MAX_PRICE_MOVE_5C", "2.0"))
S4_MAX_PRICE_MOVE_10C = float(os.getenv("S4_MAX_PRICE_MOVE_10C", "3.0"))
S4_MIN_ADX = float(os.getenv("S4_MIN_ADX", "15"))

# Dominance Filter
DOMINANCE_MIN_SCORE = int(os.getenv("DOMINANCE_MIN_SCORE", "4"))

# RSI Thresholds
RSI_LONG_MIN = float(os.getenv("RSI_LONG_MIN", "35"))
RSI_LONG_MAX = float(os.getenv("RSI_LONG_MAX", "65"))
RSI_SHORT_MIN = float(os.getenv("RSI_SHORT_MIN", "35"))
RSI_SHORT_MAX = float(os.getenv("RSI_SHORT_MAX", "65"))

# Database
DB_NAME = "signal_bot.db"

# ==========================================================
# 1. Database
# ==========================================================
def db_execute(query: str, params: tuple = ()):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        return cursor.fetchall()

async def init_database():
    queries = [
        """CREATE TABLE IF NOT EXISTS signal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id TEXT UNIQUE,
            symbol TEXT,
            interval TEXT,
            direction TEXT,
            strategy TEXT,
            entry_price REAL,
            stop_loss REAL,
            tp1 REAL,
            tp2 REAL,
            tp3 REAL,
            sl_percent REAL,
            rsi REAL,
            adx REAL,
            dominance_score INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS cooldown (
            symbol TEXT PRIMARY KEY,
            last_signal_time DATETIME
        )"""
    ]
    for q in queries:
        await asyncio.to_thread(db_execute, q)
    LOGGER.info("Database initialized.")

async def check_cooldown(symbol: str) -> bool:
    """Check if symbol is in cooldown period"""
    result = await asyncio.to_thread(
        db_execute,
        "SELECT last_signal_time FROM cooldown WHERE symbol = ?",
        (symbol,)
    )
    if not result:
        return True
    
    last_time = datetime.fromisoformat(result[0][0])
    elapsed = (datetime.now() - last_time).total_seconds() / 60
    return elapsed >= SIGNAL_COOLDOWN_MINUTES

async def update_cooldown(symbol: str):
    """Update last signal time for symbol"""
    await asyncio.to_thread(
        db_execute,
        "INSERT OR REPLACE INTO cooldown (symbol, last_signal_time) VALUES (?, ?)",
        (symbol, datetime.now().isoformat())
    )

async def save_signal(alert_id, symbol, interval, direction, strategy, entry, sl, tp1, tp2, tp3, sl_pct, rsi, adx, dom_score):
    """Save signal to database"""
    await asyncio.to_thread(
        db_execute,
        """INSERT OR IGNORE INTO signal_history 
        (alert_id, symbol, interval, direction, strategy, entry_price, stop_loss, tp1, tp2, tp3, sl_percent, rsi, adx, dominance_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (alert_id, symbol, interval, direction, strategy, entry, sl, tp1, tp2, tp3, sl_pct, rsi, adx, dom_score)
    )

# ==========================================================
# 2. Rate Limiter
# ==========================================================
class RateLimiter:
    def __init__(self, rate=20, per=1):
        self.rate = rate
        self.per = per
        self.tokens = float(rate)
        self.updated_at = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.updated_at
            self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / self.per))
            self.updated_at = now
            if self.tokens < 1:
                wait = (1 - self.tokens) * (self.per / self.rate)
                await asyncio.sleep(wait)
                self.tokens = 0
            else:
                self.tokens -= 1

binance_limiter = RateLimiter(rate=20, per=1)

# ==========================================================
# 3. Fetch Klines
# ==========================================================
async def fetch_klines(session, symbol, interval):
    """Fetch klines from Binance Futures"""
    try:
        await binance_limiter.acquire()
        url = f"{BINANCE_FUTURES_KLINES_URL}?symbol={symbol}&interval={interval}&limit=200"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                data = await r.json()
                if data and len(data) >= 50:
                    return data
    except Exception as e:
        LOGGER.error(f"Fetch klines error for {symbol}: {e}")
    return None

async def fetch_order_book(session, symbol, limit=20):
    """Fetch order book from Binance Futures"""
    try:
        await binance_limiter.acquire()
        url = f"{BINANCE_FUTURES_DEPTH_URL}?symbol={symbol}&limit={limit}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                data = await r.json()
                bids = data.get("bids", [])
                asks = data.get("asks", [])
                if len(bids) >= 5 and len(asks) >= 5:
                    return bids, asks
    except Exception as e:
        LOGGER.error(f"Fetch order book error for {symbol}: {e}")
    return [], []

async def fetch_24h_tickers(session):
    """Fetch 24h ticker data for all symbols"""
    try:
        await binance_limiter.acquire()
        async with session.get(BINANCE_FUTURES_TICKER_URL, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 200:
                return await r.json()
    except Exception as e:
        LOGGER.error(f"Fetch tickers error: {e}")
    return []

# ==========================================================
# 4. Indicators
# ==========================================================
def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(d if d > 0 else 0.0)
        losses.append(abs(d) if d < 0 else 0.0)
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    alpha = 1.0 / period
    for i in range(period, len(gains)):
        ag = alpha * gains[i] + (1 - alpha) * ag
        al = alpha * losses[i] + (1 - alpha) * al
    if al == 0:
        return 100.0
    return round(100.0 - (100.0 / (1.0 + ag / al)), 2)

def calc_atr(highs, lows, closes, period=14):
    if len(highs) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(highs)):
        trs.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return atr

def calc_dmi(highs, lows, closes, period=14):
    if len(highs) < period * 2:
        return 0.0, 0.0, 0.0
    trs, pdm, mdm = [], [], []
    for i in range(1, len(highs)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        up = highs[i] - highs[i-1]
        dn = lows[i-1] - lows[i]
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
        trs.append(tr)
    str_ = sum(trs[:period])
    spdm = sum(pdm[:period])
    smdm = sum(mdm[:period])
    dxs = []
    for i in range(period, len(trs)):
        str_ = str_ - str_/period + trs[i]
        spdm = spdm - spdm/period + pdm[i]
        smdm = smdm - smdm/period + mdm[i]
        pdi = (spdm / str_ * 100) if str_ > 0 else 0
        mdi = (smdm / str_ * 100) if str_ > 0 else 0
        s = pdi + mdi
        dx = (abs(pdi - mdi) / s * 100) if s > 0 else 0
        dxs.append((pdi, mdi, dx))
    if not dxs:
        return 0.0, 0.0, 0.0
    lp, lm, _ = dxs[-1]
    adx = sum(x[2] for x in dxs[:period]) / period if len(dxs) >= period else sum(x[2] for x in dxs) / len(dxs)
    for i in range(period, len(dxs)):
        adx = (adx * (period - 1) + dxs[i][2]) / period
    return round(lp, 2), round(lm, 2), round(adx, 2)

def find_pivots(highs, lows, lr=3):
    ph, pl = [], []
    for i in range(lr, len(highs) - lr - 1):
        if all(highs[i] > highs[i-j] for j in range(1, lr+1)) and all(highs[i] >= highs[i+j] for j in range(1, lr+1)):
            ph.append((i, highs[i]))
        if all(lows[i] < lows[i-j] for j in range(1, lr+1)) and all(lows[i] <= lows[i+j] for j in range(1, lr+1)):
            pl.append((i, lows[i]))
    return ph, pl

def dow_trend(ph, pl):
    if len(ph) < 2 or len(pl) < 2:
        return "NEUTRAL"
    if ph[-1][1] > ph[-2][1] and pl[-1][1] > pl[-2][1]:
        return "BULLISH"
    if ph[-1][1] < ph[-2][1] and pl[-1][1] < pl[-2][1]:
        return "BEARISH"
    return "NEUTRAL"

# ==========================================================
# 5. RSI Multi-Timeframe
# ==========================================================
def analyze_rsi_multi_timeframe(klines_15m, klines_1h, klines_4h):
    """RSI را در 3 تایم‌فریم محاسبه کرده و جهت را تعیین می‌کند"""
    def get_rsi_trend(klines):
        if not klines or len(klines) < 20:
            return 50, "NEUTRAL"
        C = [float(k[4]) for k in klines[:-1]]
        rsi = calc_rsi(C)
        rsi_prev = calc_rsi(C[:-5]) if len(C) > 25 else rsi
        if rsi > rsi_prev + 3:
            trend = "RISING"
        elif rsi < rsi_prev - 3:
            trend = "FALLING"
        else:
            trend = "FLAT"
        return rsi, trend
    
    rsi_15m, trend_15m = get_rsi_trend(klines_15m)
    rsi_1h, trend_1h = get_rsi_trend(klines_1h)
    rsi_4h, trend_4h = get_rsi_trend(klines_4h)
    
    score = 0
    if trend_15m == "RISING":
        score += 1
    if trend_1h == "RISING":
        score += 2
    if trend_4h == "RISING":
        score += 3
    if trend_15m == "FALLING":
        score -= 1
    if trend_1h == "FALLING":
        score -= 2
    if trend_4h == "FALLING":
        score -= 3
    
    if score >= 3:
        overall = "BULLISH"
    elif score <= -3:
        overall = "BEARISH"
    else:
        overall = "NEUTRAL"
    
    return {
        "rsi_15m": rsi_15m, "trend_15m": trend_15m,
        "rsi_1h": rsi_1h, "trend_1h": trend_1h,
        "rsi_4h": rsi_4h, "trend_4h": trend_4h,
        "overall": overall, "score": score
    }

# ==========================================================
# 6. Dominance Analysis
# ==========================================================
async def analyze_pair_trend(session, symbol, timeframe="4h"):
    """تحلیل روند یک جفت ارز"""
    try:
        klines = await fetch_klines(session, symbol, timeframe)
        if not klines or len(klines) < 20:
            return {"trend": "NEUTRAL", "change": 0}
        
        C = [float(k[4]) for k in klines[:-1]]
        current = C[-1]
        sma20 = sum(C[-20:]) / 20
        
        change_24h = (C[-1] / C[-6] - 1) * 100 if len(C) >= 6 else 0
        
        if current > sma20 * 1.01 and change_24h > 1:
            trend = "BULLISH"
        elif current < sma20 * 0.99 and change_24h < -1:
            trend = "BEARISH"
        else:
            trend = "NEUTRAL"
        
        return {"trend": trend, "change": round(change_24h, 2)}
    except:
        return {"trend": "NEUTRAL", "change": 0}

async def check_dominance_alignment(session, symbol, direction):
    """بررسی هم‌جهتی ۵ عامل برای سیگنال"""
    try:
        base = symbol.replace("USDT", "").replace("BUSD", "")
        
        # 1. BTC
        btc = await analyze_pair_trend(session, "BTCUSDT", "4h")
        
        # 2. BTC.D (تخمینی از رفتار BTC vs TOTAL2)
        # اگر BTC صعودی ولی ضعیف‌تر از TOTAL2 → BTC.D نزولی
        total2 = await analyze_pair_trend(session, "ETHUSDT", "4h")  # تقریبی
        
        # 3. ETH/BTC
        eth_btc = await analyze_pair_trend(session, "ETHBTC", "4h")
        
        # 4. ALT/ETH
        alt_eth = await analyze_pair_trend(session, base + "ETH", "4h")
        
        # 5. ALT/BTC
        alt_btc = await analyze_pair_trend(session, base + "BTC", "4h")
        
        score = 0
        details = []
        
        if direction == "SHORT":
            if btc["trend"] == "BEARISH":
                score += 1
                details.append("BTC:BEARISH")
            if total2["trend"] == "BEARISH":
                score += 1
                details.append("TOTAL2:BEARISH")
            if eth_btc["trend"] == "BEARISH":
                score += 1
                details.append("ETH/BTC:BEARISH")
            if alt_eth["trend"] == "BEARISH":
                score += 1
                details.append("ALT/ETH:BEARISH")
            if alt_btc["trend"] == "BEARISH":
                score += 1
                details.append("ALT/BTC:BEARISH")
        else:  # LONG
            if btc["trend"] == "BULLISH":
                score += 1
                details.append("BTC:BULLISH")
            if total2["trend"] == "BULLISH":
                score += 1
                details.append("TOTAL2:BULLISH")
            if eth_btc["trend"] == "BULLISH":
                score += 1
                details.append("ETH/BTC:BULLISH")
            if alt_eth["trend"] == "BULLISH":
                score += 1
                details.append("ALT/ETH:BULLISH")
            if alt_btc["trend"] == "BULLISH":
                score += 1
                details.append("ALT/BTC:BULLISH")
        
        aligned = score >= DOMINANCE_MIN_SCORE
        
        return {
            "aligned": aligned,
            "score": score,
            "btc": btc,
            "total2": total2,
            "eth_btc": eth_btc,
            "alt_eth": alt_eth,
            "alt_btc": alt_btc,
            "details": details
        }
    except Exception as e:
        LOGGER.error(f"Dominance alignment error: {e}")
        return {"aligned": False, "score": 0, "details": []}

# ==========================================================
# 7. Order Book Analysis
# ==========================================================
def analyze_order_book(bids, asks):
    """تحلیل اردربوک"""
    if not bids or not asks:
        return {"imbalance": 0, "spread_pct": 0, "bid_depth": 0, "ask_depth": 0}
    
    bv10 = sum(float(b[1]) for b in bids[:10])
    av10 = sum(float(a[1]) for a in asks[:10])
    tv10 = bv10 + av10 + 1e-9
    imbalance = (bv10 - av10) / tv10
    
    bb = float(bids[0][0])
    ba = float(asks[0][0])
    spread_pct = ((ba - bb) / bb) * 100 if bb > 0 else 0
    
    return {
        "imbalance": round(imbalance, 4),
        "spread_pct": round(spread_pct, 4),
        "bid_depth": round(bv10, 2),
        "ask_depth": round(av10, 2)
    }

# ==========================================================
# 8. Signal Analysis (Strategy 4 Only)
# ==========================================================
def analyze_signal(klines_15m, klines_1h, klines_4h, symbol):
    """تحلیل سیگنال - فقط Strategy 4: Volume Without Movement"""
    if not klines_15m or len(klines_15m) < 80:
        return None
    
    # داده‌های 15m
    closed = klines_15m[:-1]
    O = [float(k[1]) for k in closed]
    H = [float(k[2]) for k in closed]
    L = [float(k[3]) for k in closed]
    C = [float(k[4]) for k in closed]
    V = [float(k[5]) for k in closed]
    
    cc = C[-1]  # آخرین کلوز
    
    # اندیکاتورها
    rsi = calc_rsi(C)
    atr = calc_atr(H, L, C)
    pdi, mdi, adx = calc_dmi(H, L, C)
    
    # روند 4H و 1H
    if klines_4h and len(klines_4h) >= 50:
        H4 = [float(k[2]) for k in klines_4h[:-1]]
        L4 = [float(k[3]) for k in klines_4h[:-1]]
        ph4, pl4 = find_pivots(H4, L4)
        h4_trend = dow_trend(ph4, pl4)
    else:
        h4_trend = "NEUTRAL"
    
    if klines_1h and len(klines_1h) >= 50:
        H1 = [float(k[2]) for k in klines_1h[:-1]]
        L1 = [float(k[3]) for k in klines_1h[:-1]]
        ph1, pl1 = find_pivots(H1, L1)
        h1_trend = dow_trend(ph1, pl1)
    else:
        h1_trend = "NEUTRAL"
    
    # حجم
    avg_v20 = sum(V[-21:-1]) / 20.0 if len(V) >= 21 else max(V[-1], 1.0)
    vol_ratio = V[-1] / avg_v20 if avg_v20 > 0 else 1.0
    
    # Strategy 4: Volume Without Movement
    vol_surge = vol_ratio >= S4_MIN_VOLUME_RATIO
    price_movement_5c = abs(cc - C[-5]) / C[-5] * 100 if len(C) >= 5 else 0
    price_movement_10c = abs(cc - C[-10]) / C[-10] * 100 if len(C) >= 10 else 0
    price_stagnant = price_movement_5c < S4_MAX_PRICE_MOVE_5C and price_movement_10c < S4_MAX_PRICE_MOVE_10C
    
    s4_long = (vol_surge and price_stagnant and cc >= C[-10] * 0.98 and 
               rsi > RSI_LONG_MIN and rsi < RSI_LONG_MAX and pdi >= mdi and adx > S4_MIN_ADX)
    s4_short = (vol_surge and price_stagnant and cc <= C[-10] * 1.02 and 
                rsi < RSI_SHORT_MAX and rsi > RSI_SHORT_MIN and mdi >= pdi and adx > S4_MIN_ADX)
    
    # انتخاب جهت
    direction = None
    if s4_long and h4_trend == "BULLISH" and h1_trend == "BULLISH":
        direction = "LONG"
    elif s4_short and h4_trend == "BEARISH" and h1_trend == "BEARISH":
        direction = "SHORT"
    
    if not direction:
        return None
    
    # محاسبه SL/TP
    if direction == "LONG":
        sl = cc - 1.5 * atr
        risk = cc - sl
        tp1 = cc + 2 * risk
        tp2 = cc + 3 * risk
        tp3 = cc + 4 * risk
    else:
        sl = cc + 1.5 * atr
        risk = sl - cc
        tp1 = cc - 2 * risk
        tp2 = cc - 3 * risk
        tp3 = cc - 4 * risk
    
    sl_pct = (risk / cc) * 100 if cc > 0 else 999
    
    if risk <= 0 or sl_pct > MAX_SL_PERCENT:
        return None
    
    return {
        "direction": direction,
        "strategy": "Volume Without Movement",
        "entry_price": round(cc, 5),
        "stop_loss": round(sl, 5),
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),
        "sl_percent": round(sl_pct, 2),
        "rsi": rsi,
        "adx": round(adx, 2),
        "vol_ratio": round(vol_ratio, 2),
        "h4_trend": h4_trend,
        "h1_trend": h1_trend,
        "price_movement_5c": round(price_movement_5c, 2),
        "price_movement_10c": round(price_movement_10c, 2)
    }

# ==========================================================
# 9. Telegram Notifier
# ==========================================================
class TelegramNotifier:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    async def send_message(self, session, text):
        """ارسال پیام به تلگرام"""
        if not self.token or not self.chat_id:
            LOGGER.warning("Telegram not configured")
            return
        
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown"
            }
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    LOGGER.info("Signal sent to Telegram")
                else:
                    LOGGER.error(f"Telegram error: {r.status}")
        except Exception as e:
            LOGGER.error(f"Telegram send error: {e}")

# ==========================================================
# 10. Main Bot
# ==========================================================
class SignalBot:
    def __init__(self):
        self.notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
        self.symbols_cache = []
        self.cache_time = 0
    
    async def get_top_symbols(self, session):
        """دریافت لیست کوین‌های برتر بر اساس حجم"""
        now = time.time()
        if now - self.cache_time < 300 and self.symbols_cache:  # کش ۵ دقیقه
            return self.symbols_cache
        
        tickers = await fetch_24h_tickers(session)
        if not tickers:
            return []
        
        # فیلتر و مرتب‌سازی بر اساس حجم
        valid_tickers = []
        for t in tickers:
            symbol = t.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue
            if "UP" in symbol or "DOWN" in symbol or "BULL" in symbol or "BEAR" in symbol:
                continue
            
            quote_volume = float(t.get("quoteVolume", 0))
            if quote_volume >= MIN_BTC_VOLUME * 1000000:  # تبدیل به میلیون
                valid_tickers.append({
                    "symbol": symbol,
                    "volume": quote_volume
                })
        
        # مرتب‌سازی بر اساس حجم
        valid_tickers.sort(key=lambda x: x["volume"], reverse=True)
        
        # فقط ۱۰۰ تای برتر
        self.symbols_cache = [t["symbol"] for t in valid_tickers[:100]]
        self.cache_time = now
        
        LOGGER.info(f"Loaded {len(self.symbols_cache)} symbols")
        return self.symbols_cache
    
    async def process_symbol(self, session, symbol):
        """پردازش یک کوین"""
        try:
            # چک کردن کول‌داون
            if not await check_cooldown(symbol):
                return
            
            # دریافت داده‌ها
            klines_15m = await fetch_klines(session, symbol, "15m")
            if not klines_15m:
                return
            
            klines_1h = await fetch_klines(session, symbol, "1h")
            klines_4h = await fetch_klines(session, symbol, "4h")
            
            # تحلیل سیگنال
            signal = analyze_signal(klines_15m, klines_1h, klines_4h, symbol)
            if not signal:
                return
            
            # بررسی Dominance
            dom_check = await check_dominance_alignment(session, symbol, signal["direction"])
            if not dom_check["aligned"]:
                LOGGER.info(f"Dominance failed for {symbol}: {dom_check['score']}/5")
                return
            
            # RSI Multi-TF
            rsi_mtf = analyze_rsi_multi_timeframe(klines_15m, klines_1h, klines_4h)
            if signal["direction"] == "LONG" and rsi_mtf["overall"] == "BEARISH":
                LOGGER.info(f"RSI MTF rejected LONG {symbol}")
                return
            if signal["direction"] == "SHORT" and rsi_mtf["overall"] == "BULLISH":
                LOGGER.info(f"RSI MTF rejected SHORT {symbol}")
                return
            
            # Order Book
            bids, asks = await fetch_order_book(session, symbol)
            ob_data = analyze_order_book(bids, asks)
            
            # بررسی فشار اردربوک
            if signal["direction"] == "LONG" and ob_data["imbalance"] < -0.2:
                LOGGER.info(f"OB rejected LONG {symbol}: imbalance {ob_data['imbalance']}")
                return
            if signal["direction"] == "SHORT" and ob_data["imbalance"] > 0.2:
                LOGGER.info(f"OB rejected SHORT {symbol}: imbalance {ob_data['imbalance']}")
                return
            
            # ساخت پیام
            alert_id = f"{symbol}_{int(time.time())}"
            await self.send_signal(session, symbol, signal, dom_check, rsi_mtf, ob_data, alert_id)
            
            # ذخیره و کول‌داون
            await save_signal(
                alert_id, symbol, "15m", signal["direction"], signal["strategy"],
                signal["entry_price"], signal["stop_loss"], signal["tp1"], signal["tp2"], signal["tp3"],
                signal["sl_percent"], signal["rsi"], signal["adx"], dom_check["score"]
            )
            await update_cooldown(symbol)
            
        except Exception as e:
            LOGGER.error(f"Process symbol error for {symbol}: {e}")
    
    async def send_signal(self, session, symbol, signal, dom_check, rsi_mtf, ob_data, alert_id):
        """ارسال سیگنال"""
        direction_emoji = "🟢" if signal["direction"] == "LONG" else "🔴"
        
        # دلایل سیگنال
        reasons = []
        reasons.append(f"✅ Strategy: {signal['strategy']}")
        reasons.append(f"   └ حجم {signal['vol_ratio']}x ولی قیمت فقط {signal['price_movement_5c']}% حرکت")
        reasons.append(f"✅ Dominance: {dom_check['score']}/5 هم‌جهت")
        for d in dom_check['details']:
            reasons.append(f"   └ {d}")
        reasons.append(f"✅ RSI MTF: {rsi_mtf['overall']}")
        reasons.append(f"   └ 15m:{rsi_mtf['rsi_15m']} 1h:{rsi_mtf['rsi_1h']} 4h:{rsi_mtf['rsi_4h']}")
        reasons.append(f"✅ MTF: 4H={signal['h4_trend']} 1H={signal['h1_trend']}")
        reasons.append(f"✅ Order Book: Imbalance={ob_data['imbalance']}")
        
        msg = f"""🚨 *سیگنال جدید* 🚨

🪙 *{symbol}* | {signal['direction']} {direction_emoji} | 15m
💵 ورود: `{signal['entry_price']}`
🛑 SL: `{signal['stop_loss']}` ({signal['sl_percent']}%)
✅ TP: `{signal['tp1']}` / `{signal['tp2']}` / `{signal['tp3']}`

📊 *دلایل سیگنال:*
{chr(10).join(reasons)}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        
        await self.notifier.send_message(session, msg)
    
    async def run(self):
        """اجرای اصلی ربات"""
        LOGGER.info("Starting Signal Bot...")
        await init_database()
        
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    symbols = await self.get_top_symbols(session)
                    LOGGER.info(f"Scanning {len(symbols)} symbols...")
                    
                    for symbol in symbols:
                        await self.process_symbol(session, symbol)
                        await asyncio.sleep(0.5)  # کمی صبر بین کوین‌ها
                    
                    LOGGER.info(f"Scan complete. Waiting {CHECK_INTERVAL_SECONDS}s...")
                    await asyncio.sleep(CHECK_INTERVAL_SECONDS)
                    
                except Exception as e:
                    LOGGER.error(f"Main loop error: {e}")
                    await asyncio.sleep(60)

# ==========================================================
# 11. Main
# ==========================================================
if __name__ == "__main__":
    bot = SignalBot()
    asyncio.run(bot.run())
