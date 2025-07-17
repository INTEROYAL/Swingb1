import krakenex
import pandas as pd
import time
import requests
from ta.momentum import RSIIndicator
import csv
import os
from datetime import datetime

# === CONFIGURATION ===
API_KEY = "faQmax9O8dmYoA2Q+2GlAuW6NtrbFiG+WvopkXpLYX0V8oqs2STHTaBn"
API_SECRET = "bTfZT+vKY/I6pu8poxqGn4Vg52IDC59CkLvnElFN92Dr017mPgWvbwwkH0xdSTswjbz0werg2ld6GPr3huyh0A=="
PAIR = 'XRPUSD'
TRADE_AMOUNT_USD = 200
RSI_BUY = 45
RSI_SELL = 60
STOP_LOSS_PCT = 4
TAKE_PROFIT_PCT = 1.5
CHECK_INTERVAL = 60  # seconds
MAX_TRADES_PER_DAY = 6
LOG_FILE = 'xrp_trade_log.csv'

# === KRAKEN SETUP ===
k = krakenex.API()
k.key = API_KEY
k.secret = API_SECRET

# === STATE TRACKING ===
bought_price = None
bought_volume = 0
trade_count = 0
current_day = datetime.now().date()

# === LOGGING ===
def log_trade(action, price, volume, gain=None):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(['Timestamp', 'Action', 'Price', 'Volume', 'Gain'])
        writer.writerow([datetime.now(), action, price, volume, f"{gain:.2f}%" if gain else ''])

# === FUNCTIONS ===
def fetch_ohlc():
    try:
        url = f'https://api.kraken.com/0/public/OHLC?pair={PAIR}&interval=60'
        response = requests.get(url).json()
        raw = response['result'][list(response['result'].keys())[0]]
        df = pd.DataFrame(raw, columns=[
            'time', 'open', 'high', 'low', 'close',
            'vwap', 'volume', 'count'
        ])
        df['close'] = df['close'].astype(float)
        return df
    except Exception as e:
        print(f"[ERROR] Failed to fetch OHLC: {e}")
        return None

def compute_rsi(df):
    rsi = RSIIndicator(df['close'], window=14)
    return rsi.rsi().iloc[-1]

def get_balance(asset='ZUSD'):
    try:
        balance_data = k.query_private('Balance')
        return float(balance_data['result'].get(asset, 0.0))
    except Exception as e:
        print(f"[ERROR] Fetching balance: {e}")
        return 0.0

def buy_xrp():
    usd_balance = get_balance('ZUSD')
    if usd_balance >= TRADE_AMOUNT_USD:
        price = float(k.query_public('Ticker', {'pair': PAIR})['result']['XXRPZUSD']['c'][0])
        volume = TRADE_AMOUNT_USD / price
        print(f"[TRADE] Buying XRP at ${price:.4f} using ${TRADE_AMOUNT_USD}")
        log_trade('BUY', price, volume)
        return k.query_private('AddOrder', {
            'pair': PAIR,
            'type': 'buy',
            'ordertype': 'market',
            'volume': f"{volume:.4f}"
        }), price, volume
    else:
        print(f"[SKIP] Not enough USD. Available: ${usd_balance:.2f}")
        return None, None, None

def sell_xrp(volume, bought_price, reason=""):
    current_price = float(k.query_public('Ticker', {'pair': PAIR})['result']['XXRPZUSD']['c'][0])
    gain = ((current_price - bought_price) / bought_price) * 100
    print(f"[TRADE] Selling XRP at ${current_price:.4f} | Gain: {gain:.2f}% {reason}")
    log_trade(f'SELL {reason}', current_price, volume, gain)
    return k.query_private('AddOrder', {
        'pair': PAIR,
        'type': 'sell',
        'ordertype': 'market',
        'volume': f"{volume:.4f}"
    })

# === MAIN BOT LOOP ===
print("=== XRP Swing Trading Bot Started ===")

while True:
    if datetime.now().date() != current_day:
        trade_count = 0
        current_day = datetime.now().date()

    if trade_count >= MAX_TRADES_PER_DAY:
        print(f"[HALT] Max trades ({MAX_TRADES_PER_DAY}) reached today.")
        time.sleep(CHECK_INTERVAL)
        continue

    df = fetch_ohlc()
    if df is None:
        time.sleep(CHECK_INTERVAL)
        continue

    rsi = compute_rsi(df)
    current_price = df['close'].iloc[-1]
    print(f"[INFO] RSI: {rsi:.2f} | Current Price: ${current_price:.4f}")

    try:
        if not bought_price and rsi < RSI_BUY:
            result, bought_price, bought_volume = buy_xrp()
            if result:
                trade_count += 1

        elif bought_price:
            gain_pct = ((current_price - bought_price) / bought_price) * 100
            print(f"[INFO] Unrealized Gain: {gain_pct:.2f}%")

            if gain_pct >= TAKE_PROFIT_PCT or rsi > RSI_SELL:
                sell_xrp(bought_volume, bought_price, reason="(TP or RSI)")
                bought_price = None
                bought_volume = 0
                trade_count += 1

            elif gain_pct <= -STOP_LOSS_PCT:
                sell_xrp(bought_volume, bought_price, reason="(Stop-Loss)")
                bought_price = None
                bought_volume = 0
                trade_count += 1

    except Exception as e:
        print(f"[ERROR] Trade failed: {e}")
        if 'Insufficient funds' in str(e) or 'EOrder:Insufficient funds' in str(e):
            print("[RESET] Detected no XRP in account. Resetting position state.")
            bought_price = None
            bought_volume = 0

    time.sleep(CHECK_INTERVAL)
