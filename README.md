# 🤖 Crypto AI Signal Bot

ربات سیگنال کریپتو برای فیوچرز بایننس — **فقط سیگنال می‌دهد و هیچ معامله‌ای اجرا نمی‌کند.**

سیگنال‌ها (LONG / SHORT و EARLY WATCH) به همراه تحلیل هوش مصنوعی به تلگرام ارسال می‌شوند.

## ✨ قابلیت‌ها

- اسکن همزمان‌ی تمام جفت‌ارزهای USDT perpetual بایننس
- تحلیل چندلایه:
  - **RSI** در سه تایم‌فریم (15m / 1h / 4h)
  - **حجم غیرعادی** و فشار خرید/فروش taker
  - **Money Flow** از دادهٔ رایگان taker بایننس (یا CryptoMeter پولی)
  - **Open Interest** (ورود/خروج پول جدید)
  - **BTC Pair** (قدرت نسبی آلت در برابر بیت‌کوین)
  - **Dominance** (BTC.D / USDT.D / OTHERS.D / TOTAL2 / TOTAL3) از CoinGecko/Coinpaprika — رایگان
  - **Fear & Greed Index** از alternative.me
- **EARLY WATCH**: هشدار ورود حجم قبل از حرکت بزرگ قیمت
- تحلیل فارسی با AI و fallback خودکار بین provider ها:
  Gemini → Groq → OpenRouter → OpenAI
- Cooldown ضد اسپم برای سیگنال‌های تکراری
- Health check روی `/` برای مانیتورینگ

## 🚀 راه‌اندازی

```bash
pip install -r requirements.txt
cp .env.example .env   # سپس مقادیر را پر کنید
python main.py
```

### متغیرهای الزامی

| متغیر | توضیح |
|---|---|
| `TELEGRAM_BOT_TOKEN` | توکن ربات تلگرام (از @BotFather) |
| `TELEGRAM_CHAT_ID` | آیدی چت/کانال مقصد |
| حداقل یکی از کلیدهای AI | `GEMINI_API_KEY` / `GROQ_API_KEY` / `OPENROUTER_API_KEY` / `OPENAI_API_KEY` |
| `LIVECOINWATCH_API_KEY` | دادهٔ بازار هر کوین |

فهرست کامل تنظیمات در [`.env.example`](.env.example) آمده است.

## ☁️ دیپلوی روی Render

1. یک **Web Service** جدید بسازید و مخزن را وصل کنید.
2. Build command: `pip install -r requirements.txt`
3. Start command: `python main.py`
4. متغیرهای محیطی را در داشبورد Render → **Environment** وارد کنید (**هرگز `.env` را commit نکنید**).

## ⚠️ امنیت

- کلیدها را فقط در `.env` (محلی) یا Environment Variables سرویس‌دهنده نگه دارید.
- `.env` در `.gitignore` قرار دارد و نباید هرگز به مخزن push شود.

## ⚠️ سلب مسئولیت

این ربات صرفاً ابزار تحلیل و ارسال سیگنال است و توصیهٔ مالی محسوب نمی‌شود. مسئولیت هر معامله با کاربر است.
