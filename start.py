import pandas as pd
import numpy as np
from pykrx import stock
import time
from datetime import datetime, timedelta
import requests  # 디스코드 전송을 위해 필요

# --- 기존 분석 함수들 (get_local_minima, check_linear_trend 등) ---
def get_local_minima(series, order=5):
    minima_indices = []
    for i in range(order, len(series) - order):
        if all(series[i] <= series[i-j] for j in range(1, order + 1)) and \
           all(series[i] <= series[i+j] for j in range(1, order + 1)):
            minima_indices.append(i)
    return minima_indices

def check_linear_trend(ticker, name, start_date, end_date):
    try:
        df = stock.get_market_ohlcv_by_date(fromdate=start_date, todate=end_date, ticker=ticker)
        if len(df) < 30: return None
        low_values = df['저가'].values
        low_idx = get_local_minima(low_values, order=5)
        if len(low_idx) > 0 and low_idx[-1] == len(df) - 1: low_idx = low_idx[:-1]
        if len(low_idx) >= 3:
            recent_x = np.array(low_idx[-3:])
            recent_y = low_values[recent_x]
            if not (recent_y[0] < recent_y[1] < recent_y[2]): return None
            coeffs = np.polyfit(recent_x, recent_y, 1)
            p = np.poly1d(coeffs)
            y_hat = p(recent_x); y_bar = np.mean(recent_y)
            ss_res = np.sum((recent_y - y_hat)**2); ss_tot = np.sum((recent_y - y_bar)**2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
            if r_squared < 0.85: return None
            today_idx = len(df) - 1; expected_price = p(today_idx)
            current_close = df['종가'].iloc[-1]
            lower_limit = expected_price * 0.99; upper_limit = expected_price * 1.05
            if lower_limit <= current_close <= upper_limit:
                return {"종목명": name, "현재가": int(current_close), "신뢰도(R2)": round(r_squared, 3), "이격률(%)": round(((current_close - expected_price) / expected_price) * 100, 2)}
    except: pass
    return None

def get_top_tickers(market_name, count):
    now = datetime.now()
    df = stock.get_market_cap_by_ticker(now.strftime("%Y%m%d"), market=market_name)
    while df.empty:
        now -= timedelta(days=1)
        df = stock.get_market_cap_by_ticker(now.strftime("%Y%m%d"), market=market_name)
    return df.sort_values(by='시가총액', ascending=False).head(count).index

# --- 디스코드 전송 함수 ---
def send_discord_message(content):
    webhook_url = "https://discord.com/api/webhooks/1466732864392397037/roekkL5WS9fh8uQnm6Bjcul4C8MDo1gsr1ZmzGh8GfuomzlJ5vpZdVbCaY--_MZOykQ4"
    payload = {"content": content}
    requests.post(webhook_url, json=payload)

if __name__ == "__main__":
    now = datetime.now()
    end_date = now.strftime("%Y%m%d")
    start_date = (now - timedelta(days=90)).strftime("%Y%m%d")
    
    kospi = list(get_top_tickers("KOSPI", 500))
    kosdaq = list(get_top_tickers("KOSDAQ", 1000))
    all_targets = kospi + kosdaq
    
    results = []
    for ticker in all_targets:
        name = stock.get_market_ticker_name(ticker)
        res = check_linear_trend(ticker, name, start_date, end_date)
        if res: results.append(res)
        time.sleep(0.02)

    if results:
        final_df = pd.DataFrame(results).sort_values(by='이격률(%)')
        msg = f"📅 {datetime.now().strftime('%Y-%m-%d')} 분석 결과\n```\n{final_df.to_string(index=False)}\n```"
    else:
        msg = f"📅 {datetime.now().strftime('%Y-%m-%d')} 분석 결과: 조건에 맞는 종목이 없습니다."
    
    send_discord_message(msg)
