import requests
import json
import pandas as pd
from pykrx import stock
from datetime import datetime, timedelta
import time

# ==========================================
# 1. 사용자 설정 (범위 확장 버전)
# ==========================================
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1466732864392397037/roekkL5WS9fh8uQnm6Bjcul4C8MDo1gsr1ZmzGh8GfuomzlJ5vpZdVbCaY--_MZOykQ4"

TARGET_DATE = datetime.now().strftime("%Y%m%d")

# [A. 기준봉 조건: 과거 30일간 힘을 썼는가?]
CHECK_PAST_DAYS = 30      # 최근 30일 이내 (한 달)
BIG_RISE_THRESHOLD = 12.0 # 12% 이상 급등 (마크로젠이 13%였으므로 12%로 설정)

# [B. 눌림목 조건: 지금은 쉬고 있는가?]
MA_WINDOW = 20            # 20일선 기준
MIN_DISPARITY = 95.0      # 20일선 살짝 깨도 인정 (95% 이상)
MAX_DISPARITY = 110.0     # 20일선 위 (110% 이하)
VOL_DROP_RATE = 1.0       # 거래량이 전일보다 줄었거나 같으면 통과

# [C. 수급 조건]
SUPPLY_CHECK_DAYS = 5     # 최근 5일 수급 합계

print(f"[{TARGET_DATE}] 'N자형 눌림목' 분석 시작 (범위 확대: 코스닥 1000위)")
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
    """코스피 500위 + 코스닥 1000위 (총 1500개)"""
    print("1. 검색 대상(우량주+중소형주) 리스트 확보 중...")
    try:
        # 코스피 상위 500개
        df_kospi = stock.get_market_cap(date, market="KOSPI")
        top_kospi = df_kospi.sort_values(by='시가총액', ascending=False).head(500).index.tolist()
        
        # 코스닥 상위 1000개 (범위 확대!)
        df_kosdaq = stock.get_market_cap(date, market="KOSDAQ")
        top_kosdaq = df_kosdaq.sort_values(by='시가총액', ascending=False).head(1000).index.tolist()
        
        total_tickers = top_kospi + top_kosdaq
        
        # ETF/ETN 제외
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
print("2. 30일 기준봉 및 눌림목 패턴 분석 시작...")

count = 0
for ticker in tickers:
    count += 1
    if count % 100 == 0: print(f"   ... {count}개 완료")

    try:
        # 데이터 가져오기 (30일 전 급등을 찾으려면 넉넉히 90일치는 가져와야 함)
        start_date = (datetime.strptime(TARGET_DATE, "%Y%m%d") - timedelta(days=90)).strftime("%Y%m%d")
        ohlcv = stock.get_market_ohlcv_by_date(start_date, TARGET_DATE, ticker)
        
        if len(ohlcv) < 40: continue # 데이터 너무 적으면 패스

        curr_close = ohlcv['종가'].iloc[-1]
        prev_close = ohlcv['종가'].iloc[-2]
        curr_vol = ohlcv['거래량'].iloc[-1]
        prev_vol = ohlcv['거래량'].iloc[-2]

        # ---------------------------------------------------------
        # [Step 1] 오늘 캔들 모양 (거래량 감소 & 주가 안정)
        # ---------------------------------------------------------
        if curr_close > prev_close * 1.04: continue # 4% 이상 급등 중이면 눌림목 아님
        if curr_vol > prev_vol * VOL_DROP_RATE: continue # 거래량 늘어나면 탈락

        # ---------------------------------------------------------
        # [Step 2] ★기준봉 찾기★ (과거 30일간 대량거래 장대양봉)
        # ---------------------------------------------------------
        # 오늘 제외하고 과거 30일 데이터 추출
        past_data = ohlcv.iloc[-(CHECK_PAST_DAYS+1):-1] 
        
        has_flagpole = False
        max_rise = 0.0
        
        for i in range(len(past_data)):
            # 기준일(D-i)의 전일 종가 대비 당일 고가/종가 등락률 계산
            # 인덱싱 주의: past_data의 i번째 날의 '전날'은 ohlcv 전체에서 찾아야 함
            target_idx = -(CHECK_PAST_DAYS+1) + i
            yesterday_close = ohlcv['종가'].iloc[target_idx - 1]
            today_high = past_data['고가'].iloc[i]
            
            if yesterday_close > 0:
                rise_rate = (today_high - yesterday_close) / yesterday_close * 100
                if rise_rate >= BIG_RISE_THRESHOLD:
                    has_flagpole = True
                    max_rise = rise_rate
                    break 
        
        if not has_flagpole: continue

        # ---------------------------------------------------------
        # [Step 3] 20일선 지지 확인
        # ---------------------------------------------------------
        ma20 = ohlcv['종가'].rolling(window=MA_WINDOW).mean().iloc[-1]
        disparity = (curr_close / ma20) * 100

        if not (MIN_DISPARITY <= disparity <= MAX_DISPARITY): continue

        # ---------------------------------------------------------
        # [Step 4] 수급 확인 & 저장
        # ---------------------------------------------------------
        supply_start = (datetime.strptime(TARGET_DATE, "%Y%m%d") - timedelta(days=7)).strftime("%Y%m%d")
        supply_df = stock.get_market_net_purchases_of_equities_by_date(supply_start, TARGET_DATE, ticker)
        recent_supply = supply_df.tail(SUPPLY_CHECK_DAYS)
        
        inst_sum = int(recent_supply['기관합계'].sum())
        for_sum = int(recent_supply['외국인'].sum())

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
# 4. 결과 전송
# ==========================================
print("\n" + "="*70)
print(f"📊 분석 완료 ({len(results)}개 발견). 디스코드 전송 중...")

if len(results) > 0:
    res_df = pd.DataFrame(results)
    res_df = res_df.sort_values(by='이격도', ascending=True)

    discord_msg = f"## 🚀 {TARGET_DATE} 30일 기준봉 N자형 패턴\n"
    discord_msg += f"**범위:** 코스닥1000위+코스피500위 | **조건:** 30일내 {int(BIG_RISE_THRESHOLD)}%급등\n\n"
    
    # 상위 20개 전송
    for idx, row in res_df.head(20).iterrows():
        icon = "💤"
        if row['기관수급'] > 0 and row['외인수급'] > 0: icon = "🔥"
        elif row['기관수급'] > 0: icon = "🔴"
        elif row['외인수급'] > 0: icon = "🔵"

        discord_msg += (
            f"**{idx+1}. {row['종목명']}** {icon}\n"
            f"> 가격: {row['현재가']:,}원 (이격도 {row['이격도']}%)\n"
            f"> 기준봉: {row['기준봉']} 발생 → 거래량 {row['거래량변동']} 📉\n"
            f"> 수급: 기 {row['기관수급']:,} / 외 {row['외인수급']:,}\n\n"
        )
    
    send_discord_message(DISCORD_WEBHOOK_URL, discord_msg)
    print("✅ 디스코드 전송 완료!")

else:
    msg = f"## 📉 {TARGET_DATE} 분석 결과\n범위를 넓혔으나 조건에 맞는 종목이 없습니다.\n시장이 조정장이거나, 기준봉 이후 눌림을 주는 종목이 드뭅니다."
    send_discord_message(DISCORD_WEBHOOK_URL, msg)
    print("검색된 종목 없음.")
