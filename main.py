import requests
import pandas as pd
import numpy as np
from datetime import datetime
import time
import json

# ================== تنظیمات ==================
TELEGRAM_TOKEN = "YOUR_BOT_TOKEN"  # از @BotFather بگیر
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"   # از @userinfobot بگیر

# تایم‌فریم‌ها
TIMEFRAMES = {
    '15m': '15m',
    '1h': '1h', 
    '4h': '4h'
}

# تنظیمات RSI
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

# تنظیمات حجم (تشخیص پول وارد شده)
VOLUME_SPIKE = 2.0  # حجم ۲ برابر میانگین
PRICE_RANGE = 0.01  # قیمت در محدوده ۱٪ بسته شده

# ================== توابع ==================

def send_telegram(message):
    """ارسال پیام به تلگرام"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending telegram: {e}")

def get_klines(symbol, interval, limit=100):
    """دریافت کندل‌ها از بایننس"""
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_volume', 'taker_buy_quote_volume', 'ignore'
        ])
        
        df['close'] = pd.to_numeric(df['close'])
        df['volume'] = pd.to_numeric(df['volume'])
        df['high'] = pd.to_numeric(df['high'])
        df['low'] = pd.to_numeric(df['low'])
        df['open'] = pd.to_numeric(df['open'])
        
        return df
    except:
        return None

def calculate_rsi(df, period=14):
    """محاسبه RSI"""
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def check_volume_price_action(df):
    """تشخیص پول وارد شده ولی حرکت نکرده"""
    if len(df) < 20:
        return False, "داده کافی نیست"
    
    avg_volume = df['volume'].rolling(20).mean().iloc[-1]
    current_volume = df['volume'].iloc[-1]
    
    # محدوده قیمت در ۵ کندل اخیر
    recent = df.tail(5)
    price_range = (recent['high'].max() - recent['low'].min()) / recent['close'].mean()
    
    volume_spike = current_volume > (avg_volume * VOLUME_SPIKE)
    price_stagnant = price_range < PRICE_RANGE
    
    if volume_spike and price_stagnant:
        return True, f"حجم: {current_volume/avg_volume:.1f}x | نوسان: {price_range*100:.2f}%"
    
    return False, ""

def get_rsi_signals(symbol):
    """بررسی RSI در سه تایم‌فریم"""
    results = {}
    
    for name, interval in TIMEFRAMES.items():
        df = get_klines(symbol, interval, 50)
        if df is not None and len(df) > 14:
            rsi = calculate_rsi(df).iloc[-1]
            results[name] = {
                'rsi': rsi,
                'signal': '✅' if rsi > 50 else '❌'
            }
        else:
            results[name] = {'rsi': 0, 'signal': '❌'}
    
    return results

def check_dominance_alignment():
    """
    بررسی هم‌جهتی دامیننس‌ها
    نکته: این داده‌ها از CoinMarketCap یا TradingView باید گرفته شوند
    اینجا با API عمومی کوین‌مارکت‌کپ
    """
    # در نسخه واقعی، این داده‌ها را از API می‌گیریم
    # اینجا فقط ساختار را نشان می‌دهیم
    
    signals = {
        'BTC.D': {'trend': 'صعودی', 'align_short': True, 'icon': '✅'},
        'USDT.D': {'trend': 'صعودی', 'align_short': True, 'icon': '✅'},
        'BTC': {'trend': 'نزولی', 'align_short': True, 'icon': '✅'},
        'ETH/BTC': {'trend': 'نزولی', 'align_short': True, 'icon': '✅'},
        'ETH.D': {'trend': 'نزولی', 'align_short': True, 'icon': '✅'}
    }
    
    # شمارش هم‌جهتی برای شورت
    short_score = sum(1 for s in signals.values() if s['align_short'])
    
    return signals, short_score

def analyze_symbol(symbol):
    """تحلیل کامل یک نماد"""
    
    # ۱. بررسی حجم و قیمت
    df_1h = get_klines(symbol, '1h', 50)
    if df_1h is None:
        return None
    
    volume_signal, volume_info = check_volume_price_action(df_1h)
    
    # ۲. بررسی RSI
    rsi_results = get_rsi_signals(symbol)
    
    # ۳. بررسی دامیننس
    dom_signals, dom_score = check_dominance_alignment()
    
    # ۴. تعیین جهت احتمالی
    rsi_15m = rsi_results['15m']['rsi']
    rsi_1h = rsi_results['1h']['rsi']
    rsi_4h = rsi_results['4h']['rsi']
    
    # منطق سیگنال
    long_condition = (rsi_15m > 50 and rsi_1h > 50 and rsi_4h > 50)
    short_condition = (rsi_15m < 50 and rsi_1h < 50 and rsi_4h < 50)
    
    # امتیاز کلی
    score = 0
    if volume_signal:
        score += 20
    
    if long_condition:
        score += 40
        direction = "🟢 صعودی"
    elif short_condition:
        score += 40
        direction = "🔴 نزولی"
    else:
        direction = "⚪ خنثی/نامشخص"
    
    score += dom_score * 8  # هر دامیننس هم‌جهت ۸ امتیاز
    
    return {
        'symbol': symbol,
        'direction': direction,
        'score': score,
        'volume_signal': volume_signal,
        'volume_info': volume_info,
        'rsi': rsi_results,
        'dominance': dom_signals,
        'dom_score': dom_score,
        'price': df_1h['close'].iloc[-1]
    }

def format_signal(analysis):
    """قالب‌بندی پیام تلگرام"""
    
    symbol = analysis['symbol']
    direction = analysis['direction']
    score = analysis['score']
    price = analysis['price']
    
    # ایموجی قدرت سیگنال
    if score >= 80:
        strength = "🚨 قوی"
    elif score >= 60:
        strength = "⚡ متوسط"
    else:
        strength = "👀 ضعیف/در حال تشکیل"
    
    message = f"""
<code>{symbol}</code> | {direction} | {strength}
💰 قیمت: {price:.8g}

{'━━━━━━━━━━━━━━━━━━'}
📊 <b>RSI چند تایم‌فریم:</b>
• ۱۵ دقیقه: {analysis['rsi']['15m']['rsi']:.1f} {analysis['rsi']['15m']['signal']}
• ۱ ساعت: {analysis['rsi']['1h']['rsi']:.1f} {analysis['rsi']['1h']['signal']}
• ۴ ساعت: {analysis['rsi']['4h']['rsi']:.1f} {analysis['rsi']['4h']['signal']}

{'━━━━━━━━━━━━━━━━━━'}
💹 <b>دامیننس (۵ بخشی):</b>
• BTC.D: {analysis['dominance']['BTC.D']['icon']} {analysis['dominance']['BTC.D']['trend']}
• USDT.D: {analysis['dominance']['USDT.D']['icon']} {analysis['dominance']['USDT.D']['trend']}
• BTC/USDT: {analysis['dominance']['BTC']['icon']} {analysis['dominance']['BTC']['trend']}
• ETH/BTC: {analysis['dominance']['ETH/BTC']['icon']} {analysis['dominance']['ETH/BTC']['trend']}
• ETH.D: {analysis['dominance']['ETH.D']['icon']} {analysis['dominance']['ETH.D']['trend']}
• امتیاز هم‌جهتی: {analysis['dom_score']}/5

{'━━━━━━━━━━━━━━━━━━'}
📈 <b>حجم و پول:</b>
{'🔥 ' + analysis['volume_info'] if analysis['volume_signal'] else '• حجم عادی'}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""
    
    return message

# ================== اجرای اصلی ==================

def main():
    """اسکن بازار و ارسال سیگنال"""
    
    # لیست نمادهای پرحجم (می‌توانی تغییر بدهی)
    symbols = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT"
    ]
    
    print(f"🔍 شروع اسکن بازار... {datetime.now()}")
    
    for symbol in symbols:
        try:
            analysis = analyze_symbol(symbol)
            
            if analysis and analysis['score'] >= 60:  # فقط سیگنال‌های قوی‌تر
                message = format_signal(analysis)
                send_telegram(message)
                print(f"✅ سیگنال ارسال شد: {symbol}")
                
                time.sleep(1)  # جلوگیری از اسپم
            
            time.sleep(0.5)  # رعایت rate limit
            
        except Exception as e:
            print(f"❌ خطا در {symbol}: {e}")
    
    print("✅ اسکن تکمیل شد")

# اجرا هر ۱۵ دقیقه
if __name__ == "__main__":
    while True:
        main()
        print("⏳ انتظار ۱۵ دقیقه تا اسکن بعدی...")
        time.sleep(900)  # ۱۵ دقیقه
