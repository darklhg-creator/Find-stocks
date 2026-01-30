import requests
import json
import pandas as pd
from pykrx import stock
from datetime import datetime, timedelta
import time

# ==========================================
# 0. 설정값 (사용자 요청 사항 반영)
# ==========================================
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1466732864392397037/roekkL5WS9fh8uQnm6Bjcul4C8MDo1gsr1ZmzGh8GfuomzlJ5vpZdVbCaY--_MZOykQ4"
TARGET_DATE = datetime.now().strftime("%Y%m%d")

# [1단계 조건: 기준봉]
CHECK_DAYS = 30           # 30일 이내
FLAG_HIGH_RATE = 10.0     # 고가 기준 10% 이상 상승
FLAG_VOL_RATE = 2.0       # 전일 대비 거래량 200%(2배) 이상

# [2단계 조건: 이격도]
DISPARITY_LIMIT = 95.0    # 20일선 이격도 95% 이하 (과대낙폭)

# [3단계 조건: 거래량 침묵]
QUIET_VOL_RATIO = 0.5     # 기준봉 거래량 대비 50% 이하 유지

print(f"[{TARGET_DATE}] 3단계 정밀 분석 시작 (코스피/닥 시총 상위 500개)")
print("-" * 60)

# ==========================================
# 함수 정의
# ==========================================
def send_discord_message(webhook_url, content):
    """디스코드 메시지를 끊어서 전송 (2000자 제한 방지)"""
    if len(content) > 1900:
        chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
        for chunk in chunks:
            data = {"content": chunk}
            headers = {"Content-Type": "application/json"}
            requests.post(webhook_url, data=json.dumps(data), headers=headers)
            time.sleep(0.5)
    else:
        data = {"content": content}
        headers = {"Content-Type": "application/json"}
        try:
            requests.post(webhook_url, data=json.dumps(data), headers=headers)
        except:
            pass

def get_top_tickers(date):
    """코스피 500 + 코스닥 500 (ETF 제외)"""
    print("0. 종목 리스트 확보 중...")
    try:
        kospi = stock.get_market_cap(date, market="KOSPI").sort_values(by='시가총액', ascending=False).head(500).index.tolist()
        kosdaq = stock.get_market_cap(date, market="KOSDAQ").sort_values(by='시가총액', ascending=False).head(500).index.tolist()
        
        tickers = kospi + kosdaq
        etfs = stock.get_etf_ticker_list(date)
        etns = stock.get_etn_ticker_list(date)
        exclude = set(etfs + etns)
        
        return [t for t in tickers if t not in exclude]
    except:
        return []

# ==========================================
# 메인 로직
# ==========================================
tickers = get_top_tickers(TARGET_DATE)
print(f"-> 총 검사 대상: {len(tickers)}개")

# 결과 저장용 리스트
step1_list = [] # 기준봉 발견
step2_list = [] # 이격도 95 이하
step3_list = [] # 거래량 침묵 (최종)

count = 0
for ticker in tickers:
    count += 1
    if count % 100 == 0: print(f"... {count}개 분석 중")

    try:
        # 데이터 가져오기 (이평선 계산 위해 60일치)
        start_date = (datetime.strptime(TARGET_DATE, "%Y%m%d") - timedelta(days=60)).strftime("%Y%m%d")
        ohlcv = stock.get_market_ohlcv_by_date(start_date, TARGET_DATE, ticker)
        
        if len(ohlcv) < 40: continue

        # 최근 30일 데이터 슬라이싱 (오늘 포함)
        recent_data = ohlcv.iloc[-(CHECK_DAYS+1):]
        
        # ---------------------------------------------------
        # [Step 1] 기준봉 찾기 (30일 내 10% 상승 & 200% 거래량)
        # ---------------------------------------------------
        found_flag = False
        trigger_date_idx = -1   # 기준봉 날짜의 인덱스
        trigger_vol = 0         # 기준봉 거래량
        trigger_name = ""

        # 가장 '최근'에 발생한 기준봉을 찾음
        for i in range(len(recent_data)-1, 0, -1): # 역순 탐색
            curr_row = recent_data.iloc[i]
            prev_row = recent_data.iloc[i-1]
            
            # 전일 종가 (0이면 패스)
            prev_close = prev_row['종가']
            if prev_close == 0 or prev_row['거래량'] == 0: continue

            # 조건: 고가 기준 10% 이상 상승 AND 거래량 200%(2배) 이상
            high_rate = (curr_row['고가'] - prev_close) / prev_close * 100
            vol_rate = curr_row['거래량'] / prev_row['거래량']

            if high_rate >= FLAG_HIGH_RATE and vol_rate >= FLAG_VOL_RATE:
                found_flag = True
                trigger_date_idx = i
                trigger_vol = curr_row['거래량']
                break # 최근 기준봉 하나 찾으면 중단

        if found_flag:
            name = stock.get_market_ticker_name(ticker)
            step1_list.append(name) # 1단계 통과
        else:
            continue # 1단계 탈락이면 다음 종목으로

        # ---------------------------------------------------
        # [Step 2] 이격도 95% 이하 확인 (1단계 통과한 놈만)
        # ---------------------------------------------------
        # 오늘 종가 / 20일 이동평균선 * 100
        curr_close = ohlcv['종가'].iloc[-1]
        ma20 = ohlcv['종가'].rolling(window=20).mean().iloc[-1]
        
        if ma20 == 0: continue
        disparity = (curr_close / ma20) * 100

        if disparity <= DISPARITY_LIMIT:
            step2_list.append(f"{name}({round(disparity,1)}%)") # 2단계 통과
        else:
            continue # 2단계 탈락

        # ---------------------------------------------------
        # [Step 3] 거래량 침묵 확인 (2단계 통과한 놈만)
        # ---------------------------------------------------
        # 기간: 기준봉 다음날 ~ 오늘
        # 기준봉이 오늘이면(방금 터진거면) 눌림목 기간이 없으므로 제외할 수도 있으나,
        # 여기선 데이터가 없으므로 자동 통과 or 제외 선택. 보통 제외함.
        
        # 기준봉이 recent_data 내에서의 인덱스가 trigger_date_idx
        # 검사 구간: trigger_date_idx + 1 부터 끝까지
        check_range = recent_data.iloc[trigger_date_idx+1 : ]
        
        if len(check_range) == 0: 
            continue # 기준봉이 오늘 터진거라 눌림목 확인 불가 -> 제외

        is_quiet = True
        for vol in check_range['거래량']:
            # 하루라도 기준봉 거래량의 50%를 넘으면 탈락
            if vol > (trigger_vol * QUIET_VOL_RATIO):
                is_quiet = False
                break
        
        if is_quiet:
            step3_list.append(f"{name}") # 3단계 최종 통과!

    except Exception as e:
        continue

# ==========================================
# 결과 전송
# ==========================================
print("\n분석 완료. 디스코드 전송 중...")

msg = f"## 🎯 {TARGET_DATE} 3단계 조건 검색 결과\n"
msg += f"(대상: 코스피/닥 시총상위 500개)\n\n"

# 1번 결과
msg += f"**1️⃣ 기준봉 발생 ({len(step1_list)}개)**\n"
msg += f"> 조건: 30일내 고가10%↑ & 거래량200%↑\n"
if len(step1_list) > 0:
    msg += f"Running list: {', '.join(step1_list[:30])}..." if len(step1_list) > 30 else f"{', '.join(step1_list)}"
else:
    msg += "없음"
msg += "\n\n"

# 2번 결과
msg += f"**2️⃣ 과대낙폭 필터 ({len(step2_list)}개)**\n"
msg += f"> 조건: 1번 중 이격도 95% 이하\n"
if len(step2_list) > 0:
    msg += f"{', '.join(step2_list)}"
else:
    msg += "없음"
msg += "\n\n"

# 3번 결과
msg += f"**3️⃣ 거래량 침묵 (최종 Pick) ({len(step3_list)}개)** 🏆\n"
msg += f"> 조건: 2번 중 거래량 50% 이하 유지\n"
if len(step3_list) > 0:
    for item in step3_list:
        msg += f"- 💎 **{item}**\n"
else:
    msg += "조건을 모두 만족하는 종목이 없습니다."

send_discord_message(DISCORD_WEBHOOK_URL, msg)
print("✅ 전송 완료")
