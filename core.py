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
# OKX RATE LIMIT
# ------------------------------------------------------------

# endpoint روبیک OKX ریت‌لیمیت خیلی کمی دارد (≈۲۰ درخواست در ۲ ثانیه).
# وقتی 429 بدهد، این مدت دیگر درخواستی به OKX نمی‌فرستیم.
OKX_BLOCK_PAUSE = _int("OKX_BLOCK_PAUSE", "300")

# حداکثر درخواست همزمان به OKX تا 429 نگیریم.
OKX_CONCURRENCY = _int("OKX_CONCURRENCY", "3")

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
