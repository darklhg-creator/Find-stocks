import requests
import json
import pandas as pd
from pykrx import stock
from datetime import datetime, timedelta
import time

# ==========================================
# 1. 사용자 설정 (마크로젠 사냥용 세팅)
# ==========================================
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1466732864392397037/roekkL5WS9fh8uQnm6Bjcul4C8MDo1gsr1ZmzGh8GfuomzlJ5vpZdVbCaY--_MZOykQ4"

TARGET_DATE = datetime.now().strftime("%Y%m%d")

# [A. 기준봉 조건: 과거에 힘을 썼는가?]
CHECK_PAST_DAYS = 15     # 최근 15일 이내에
BIG_RISE_THRESHOLD = 15.0 # 15% 이상 급등한(고가 기준) 날이 있어야 함

# [B. 눌림목 조건: 지금은 쉬고 있는가?]
MA_WINDOW = 20           # 20일선 기준
MIN_DISPARITY = 95.0     # 20일선 살짝 깨도 인정 (95% 이상)
MAX_DISPARITY = 110.0    # 20일선 위 (110% 이하)
VOL_DROP_RATE = 1.0      # 거래량이 전일보다 줄었거나 같으면 통과 (1.0 이하)

# [C. 수급 조건]
SUPPLY_CHECK_DAYS = 5    # 최근 5일 수급 합계

print(f"[{TARGET_DATE}] '급등 후 눌림목(N자 패턴)' 분석 시작 (시총 상위 1000개)")
print(f"조건: 최근 {CHECK_PAST_DAYS}일내 {BIG_RISE_THRESHOLD}%급등 + 거래량감소 + 20일선지지")
print("-" * 60)

# ==========================================
# 2. 함수 정의
# ==========================================
def send_discord_message(webhook_url, content):
    data = {"content": content}
    headers = {"Content-Type": "application/json"}
    try:
        requests.post(webhook_url, data=json.dumps(data), headers=headers)
    except:
        pass

def get_target_tickers(date):
    """코스피/코스닥 시총 상위 500개씩 (ETF 제외)"""
    print("1. 우량주 리스트 확보 중...")
    try:
        df_kospi = stock.get_market_cap(date, market="KOSPI")
        top_kospi = df_kospi.sort_values(by='시가총액', ascending=False).head(500).index.tolist()
        
        df_kosdaq = stock.get_market_cap(date, market="KOSDAQ")
        top_kosdaq = df_kosdaq.sort_values(by='시가총액', ascending=False).head(500).index.tolist()
        
        total_tickers = top_kospi + top_kosdaq
        
        etfs = stock.get_etf_ticker_list(date)
        etns = stock.get_etn_ticker_list(date)
        exclude_list = set(etfs + etns)
        
        return [t for t in total_tickers if t not in exclude_list]
    except:
        return []

# ==========================================
# 3. 메인 분석 로직
# ==========================================
tickers = get_target_tickers(TARGET_DATE)
print(f"   -> 분석 대상: {len(tickers)}개 종목")

results = []
print("2. 기준봉 및 눌림목 패턴 분석 시작...")

count = 0
for ticker in tickers:
    count += 1
    if count % 100 == 0: print(f"   ... {count}개 완료")

    try:
        # 데이터 넉넉히 가져오기 (이평선 + 과거 탐색용)
        # 🔻 에러 났던 부분: 끝에 )).strftime(...) 이 잘렸었습니다. 복구 완료!
        start_date = (datetime.strptime(TARGET_DATE, "%Y%m%d") - timedelta(days=60)).strftime("%Y%m%d")
        ohlcv = stock.get_market_ohlcv_by_date(start_date, TARGET_DATE, ticker)
        
        if len(ohlcv) < 20: continue

        curr_close = ohlcv['종가'].iloc[-1]
        prev_close = ohlcv['종가'].iloc[-2]
        curr_vol = ohlcv['거래량'].iloc[-1]
        prev_vol = ohlcv['거래량'].iloc[-2]

        # ---------------------------------------------------------
        # [Step 1] 오늘 캔들 모양 (거래량 감소 & 주가 안정)
        # ---------------------------------------------------------
        # 주가가 폭등 중이면 눌림목 아님 (3% 이상 상승 제외)
        if curr_close > prev_close * 1.03: continue
        
        # 거래량이 전일 대비 늘어났으면 탈락 (거래량 말라야 함)
        if curr_vol > prev_vol * VOL_DROP_RATE: continue

        # ---------------------------------------------------------
        # [Step 2] ★기준봉 찾기★ (과거 15일간 대량거래 장대양봉)
        # ---------------------------------------------------------
        # 오늘 제외하고 과거 데이터만 추출
        past_data = ohlcv.iloc[-(CHECK_PAST_DAYS+1):-1] 
        
        has_flagpole = False
        max_rise = 0.0
        
        for i in range(len(past_data)):
            # 고가 기준 등락률 or 종가 기준 등락률 확인
            yesterday_close = ohlcv['종가'].iloc[-(CHECK_PAST_DAYS+1)+i-1]
            today_high = past_data['고가'].iloc[i]
            
            if yesterday_close > 0:
                rise_rate = (today_high - yesterday_close) / yesterday_close * 100
                if rise_rate >= BIG_RISE_THRESHOLD:
                    has_flagpole = True
                    max_rise = rise_rate
                    break # 하나라도 있으면 통과
        
        if not has_flagpole: continue # 기준봉 없으면 탈락 (힘없는 종목)

        # ---------------------------------------------------------
        # [Step 3] 20일선 지지 확인
        # ---------------------------------------------------------
        ma20 = ohlcv['종가'].rolling(window=MA_WINDOW).mean().iloc[-1]
        disparity = (curr_close / ma20) * 100

        if not (MIN_DISPARITY <= disparity <= MAX_DISPARITY): continue

        # ---------------------------------------------------------
        # [Step 4] 수급 확인 (기관/외인) & 결과 저장
        # ---------------------------------------------------------
        supply_start = (datetime.strptime(TARGET_DATE, "%Y%m%d") - timedelta(days=7)).strftime("%Y%m%d")
        supply_df = stock.get_market_net_purchases_of_equities_by_date(supply_start, TARGET_DATE, ticker)
        recent_supply = supply_df.tail(SUPPLY_CHECK_DAYS)
        
        inst_sum = int(recent_supply['기관합계'].sum())
        for_sum = int(recent_supply['외국인'].sum())

        # 저장
        name = stock.get_market_ticker_name(ticker)
        vol_change = round((curr_vol - prev_vol) / prev_vol * 100, 1)
        
        results.append({
            '종목명': name,
            '현재가': curr_close,
            '이격도': round(disparity, 1),
            '거래량변동': f"{vol_change}%",
            '기준봉': f"{round(max_rise,1)}%급등",
            '기관수급': inst_sum,
            '외인수급': for_sum
        })

    except:
        continue

# ==========================================
# 4. 디스코드 전송
# ==========================================
print("\n" + "="*70)
print(f"📊 분석 완료 ({len(results)}개 발견). 디스코드 전송 중...")

if len(results) > 0:
    res_df = pd.DataFrame(results)
    # 이격도 낮은 순(지지선에 가까운 순) 정렬
    res_df = res_df.sort_values(by='이격도', ascending=True)

    discord_msg = f"## 🚀 {TARGET_DATE} 급등주 눌림목(N자형) 발견!\n"
    discord_msg += f"**조건:** 최근15일내 급등(15%↑) | 거래량감소 | 20일선지지\n\n"
    
    for idx, row in res_df.head(15).iterrows():
        icon = "💤" # 쉬고 있음
        if row['기관수급'] > 0 and row['외인수급'] > 0: icon = "🔥(쌍끌이)"
        elif row['기관수급'] > 0: icon = "🔴(기관)"
        elif row['외인수급'] > 0: icon = "🔵(외인)"

        discord_msg += (
            f"**{idx+1}. {row['종목명']}** {icon}\n"
            f"> 가격: {row['현재가']:,}원 (이격도 {row['이격도']}%)\n"
            f"> 패턴: 과거 **{row['기준봉']}** 발생 → 거래량 {row['거래량변동']} 📉\n"
            f"> 수급: 기 {row['기관수급']:,} / 외 {row['외인수급']:,}\n\n"
        )
    
    send_discord_message(DISCORD_WEBHOOK_URL, discord_msg)
    print("✅ 디스코드 전송 완료!")

else:
    msg = f"## 📉 {TARGET_DATE} 분석 결과\n조건(N자형 패턴)에 맞는 종목이 없습니다.\n시장이 너무 약하거나 급등 후 쉬어가는 종목이 없습니다."
    send_discord_message(DISCORD_WEBHOOK_URL, msg)
    print("검색된 종목 없음.")
