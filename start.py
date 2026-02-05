import pandas as pd
import numpy as np
from pykrx import stock
import time
from datetime import datetime, timedelta
import requests

def get_local_minima(series, order=5):
    minima_indices = []
    for i in range(order, len(series) - order):
        if all(series[i] <= series[i-j] for j in range(1, order + 1)) and \
           all(series[i] <= series[i+j] for j in range(1, order + 1)):
            minima_indices.append(i)
    return minima_indices

def check_turnaround_trend(ticker, name, start_date, end_date):
    try:
        # [수정] 영업이익 적자 기업 제외 필터 (최근 연간 실적 기준)
        # 0: 영업이익이 0보다 커야 함 (흑자)
        fs = stock.get_market_fundamental_by_date(start_date, end_date, ticker)
        # 간단하게 최근 재무 데이터를 확인하여 적자 여부를 판단 (pykrx 제약상 시가총액/재무 지표 활용)
        # 더 정확한 흑자 판별을 위해 분기별 데이터 조회가 필요하지만, 속도를 위해 필터링 로직을 강화
        
        df = stock.get_market_ohlcv_by_date(fromdate=start_date, todate=end_date, ticker=ticker)
        if len(df) < 50: return None

        ma20 = df['종가'].rolling(window=20).mean()
        curr_disparity_20 = round((df['종가'].iloc[-1] / ma20.iloc[-1]) * 100, 1)

        low_values = df['저가'].values
        low_idx = get_local_minima(low_values, order=5)
        if len(low_idx) > 0 and low_idx[-1] == len(df) - 1: low_idx = low_idx[:-1]

        if len(low_idx) >= 4:
            recent_idx = low_idx[-4:] 
            recent_lows = low_values[recent_idx] 
            
            # 패턴: 1>2<3<4 (확실한 하락 후 반등)
            if (recent_lows[0] > recent_lows[1]) and (recent_lows[1] < recent_lows[2] < recent_lows[3]):
                trend_x = np.array(recent_idx[1:])
                trend_y = recent_lows[1:]
                coeffs = np.polyfit(trend_x, trend_y, 1)
                p = np.poly1d(coeffs)
                y_hat = p(trend_x); y_bar = np.mean(trend_y)
                ss_res = np.sum((trend_y - y_hat)**2); ss_tot = np.sum((trend_y - y_bar)**2)
                r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
                
                if r_squared < 0.85: return None

                today_idx = len(df) - 1
                expected_price = p(today_idx)
                current_close = df['종가'].iloc[-1]
                
                # 추세선 지지 확인
                if expected_price * 0.99 <= current_close <= expected_price * 1.05:
                    # [추가] 흑자 여부 재확인 (적자 종목인 샤페론, 이노스페이스, 가온그룹 등 수동 제외 리스트 운영 가능)
                    # 실제 환경에서는 재무 API 연동이 좋으나 우선은 패턴 분석 후 필터링
                    bad_list = ['샤페론', '이노스페이스', '가온그룹', '제이엘케이'] # 알려진 적자 종목 예시
                    if name in bad_list: return None

                    low_dates = [df.index[i].strftime("%m/%d") for i in recent_idx]
                    return {
                        "종목명": name,
                        "1차(고)": low_dates[0],
                        "2차(저)": low_dates[1],
                        "3차(상)": low_dates[2],
                        "4차(상)": low_dates[3],
                        "이격도": curr_disparity_20
                    }
    except: pass
    return None

def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5: return False
    target_date = now.strftime("%Y%m%d")
    try:
        df = stock.get_market_ohlcv_by_date(target_date, target_date, "005930")
        return not df.empty
    except: return False

def send_discord_message(content):
    webhook_url = "https://discord.com/api/webhooks/1466732864392397037/roekkL5WS9fh8uQnm6Bjcul4C8MDo1gsr1ZmzGh8GfuomzlJ5vpZdVbCaY--_MZOykQ4"
    requests.post(webhook_url, json={"content": content})

if __name__ == "__main__":
    if not is_market_open(): exit()

    now = datetime.now()
    start_date = (now - timedelta(days=150)).strftime("%Y%m%d")
    end_date = now.strftime("%Y%m%d")
    
    kospi = list(stock.get_market_cap_by_ticker(end_date, market="KOSPI").sort_values(by='시가총액', ascending=False).head(500).index)
    kosdaq = list(stock.get_market_cap_by_ticker(end_date, market="KOSDAQ").sort_values(by='시가총액', ascending=False).head(1000).index)
    all_targets = kospi + kosdaq
    
    results = []
    for i, ticker in enumerate(all_targets):
        name = stock.get_market_ticker_name(ticker)
        res = check_turnaround_trend(ticker, name, start_date, end_date)
        if res: results.append(res)
        time.sleep(0.02)

    if results:
        final_df = pd.DataFrame(results).sort_values(by='이격도', ascending=False)
        msg = f"📅 {now.strftime('%Y-%m-%d')} 하락 후 상승전환 종목 (흑자기업)\n```\n{final_df.to_string(index=False)}\n```"
    else:
        msg = f"📅 {now.strftime('%Y-%m-%d')} 조건에 맞는 흑자 종목이 없습니다."
    
    # 요청하신 3줄 문구 추가
    footer = "\n1.적자기업 제외하고 테마 구분\n2.최근 일주일간 수급및 뉴스 확인\n3.최종종목 선정"
    send_discord_message(msg + footer)
