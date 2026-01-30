import requests
import json
import pandas as pd
from pykrx import stock
from datetime import datetime, timedelta, timezone
import time
import sys

# ==========================================
# 0. 사용자 설정
# ==========================================
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1466732864392397037/roekkL5WS9fh8uQnm6Bjcul4C8MDo1gsr1ZmzGh8GfuomzlJ5vpZdVbCaY--_MZOykQ4"

# [핵심 수정] 시스템 시간이 아닌 '한국 시간(KST)'을 강제로 계산
# UTC 시간에 9시간을 더해 한국 시간을 구합니다.
KST_TIMEZONE = timezone(timedelta(hours=9))
CURRENT_KST = datetime.now(KST_TIMEZONE)
TARGET_DATE = CURRENT_KST.strftime("%Y%m%d")

# [공통 조건]
CHECK_DAYS = 30           # 30일 이내 탐색
DISPARITY_LIMIT = 95.0    # 이격도 95% 이하 (과대낙폭)
QUIET_VOL_RATIO = 0.5     # 거래량 침묵 (기준봉 대비 50% 이하 유지)

# [조건 A: 일반형 (Standard)]
COND_A_PRICE = 10.0       # 10% 이상 상승
COND_A_VOL = 2.0          # 200%(2배) 이상 폭발

# [조건 B: 강력형 (High-Power)] - 우선순위 높음
COND_B_PRICE = 15.0       # 15% 이상 급등
COND_B_VOL = 3.0          # 300%(3배) 이상 폭발

print(f"[{TARGET_DATE}] 주식 분석 프로그램 가동 시작 (한국시간 기준)")
print("-" * 60)

# ==========================================
# [중요] 휴장일(주말/공휴일) 필터링 로직
# ==========================================
# 1. 주말 체크 (월:0 ~ 일:6)
# TARGET_DATE가 이미 한국 시간으로 설정되었으므로 정확히 요일을 판단합니다.
dt = datetime.strptime(TARGET_DATE, "%Y%m%d")
weekday = dt.weekday()

if weekday >= 5:
    print(f"⏹️ 오늘은 주말(토/일)입니다. 프로그램을 종료합니다.")
    sys.exit()

# 2. 공휴일 체크 (삼성전자 데이터로 개장 여부 확인)
try:
    # 삼성전자(005930)의 오늘 데이터가 없으면 휴장일로 간주
    check_open = stock.get_market_ohlcv_by_date(TARGET_DATE, TARGET_DATE, "005930")
    if check_open.empty:
        print(f"⏹️ 오늘은 공휴일(장 휴무)입니다. 프로그램을 종료합니다.")
        sys.exit()
except Exception as e:
    # 인터넷 문제 등으로 확인 어려우면 안전하게 종료
    print(f"⚠️ 장 운영 여부 확인 실패 ({e}). 프로그램을 종료합니다.")
    sys.exit()

print(f"✅ 정상 개장일입니다. 분석을 시작합니다...")


# ==========================================
# 함수 정의
# ==========================================
def send_discord_message(webhook_url, content):
    """디스코드 메시지 전송 (길면 나눠서 보냄)"""
    if len(content) > 1900:
        chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
        for chunk in chunks:
            data = {"content": chunk}
            headers = {"Content-Type": "application/json"}
            try:
                requests.post(webhook_url, data=json.dumps(data), headers=headers)
                time.sleep(0.5)
            except: pass
    else:
        data = {"content": content}
        headers = {"Content-Type": "application/json"}
        try:
            requests.post(webhook_url, data=json.dumps(data), headers=headers)
        except: pass

def get_top_tickers(date):
    """코스피 500 + 코스닥 500 (유동성 확보용)"""
    print("1. 종목 리스트 확보 중...")
    try:
        # 시가총액 데이터는 안전하게 '하루 전' 기준으로 가져옴 (장중 에러 방지)
        # 한국 시간 기준으로 하루 전 날짜 계산
        safe_date = (datetime.strptime(date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        
        kospi = stock.get_market_cap(safe_date, market="KOSPI").sort_values(by='시가총액', ascending=False).head(500).index.tolist()
        kosdaq = stock.get_market_cap(safe_date, market="KOSDAQ").sort_values(by='시가총액', ascending=False).head(500).index.tolist()
        tickers = kospi + kosdaq
        
        etfs = stock.get_etf_ticker_list(safe_date)
        etns = stock.get_etn_ticker_list(safe_date)
        exclude = set(etfs + etns)
        
        return [t for t in tickers if t not in exclude]
    except:
        return []

# ==========================================
# 메인 로직
# ==========================================
tickers = get_top_tickers(TARGET_DATE)
print(f"2. 정밀 분석 시작 (대상: {len(tickers)}개)")

# 결과 저장소
tier1_results = [] # 강력형
tier2_results = [] # 일반형

count = 0
for ticker in tickers:
    count += 1
    if count % 100 == 0: print(f"   ... {count}개 완료")

    try:
        # [1] 데이터 가져오기 (주가는 '오늘' 기준)
        start_date = (datetime.strptime(TARGET_DATE, "%Y%m%d") - timedelta(days=60)).strftime("%Y%m%d")
        ohlcv = stock.get_market_ohlcv_by_date(start_date, TARGET_DATE, ticker)
        
        if len(ohlcv) < 40: continue

        curr_close = ohlcv['종가'].iloc[-1]
        ma20 = ohlcv['종가'].rolling(window=20).mean().iloc[-1]
        
        # [2] 이격도 체크
        if ma20 == 0: continue
        disparity = (curr_close / ma20) * 100
        if disparity > DISPARITY_LIMIT: continue # 95% 초과면 탈락

        recent_data = ohlcv.iloc[-(CHECK_DAYS+1):]

        # ---------------------------------------------------------
        # [3] 티어 분류 로직
        # ---------------------------------------------------------
        is_tier1 = False
        trigger_date_b = ""
        
        # 역순 탐색 (최근 기준봉 우선)
        for i in range(len(recent_data)-1, 0, -1):
            curr_row = recent_data.iloc[i]
            prev_row = recent_data.iloc[i-1]
            if prev_row['종가'] == 0 or prev_row['거래량'] == 0: continue

            rise = (curr_row['고가'] - prev_row['종가']) / prev_row['종가'] * 100
            vol_rate = curr_row['거래량'] / prev_row['거래량']

            # B 조건 (1티어: 강력형)
            if rise >= COND_B_PRICE and vol_rate >= COND_B_VOL:
                check_range = recent_data.iloc[i+1:]
                if len(check_range) == 0: continue
                
                trigger_vol = curr_row['거래량']
                is_quiet = True
                for vol in check_range['거래량']:
                    if vol > (trigger_vol * QUIET_VOL_RATIO):
                        is_quiet = False; break
                
                if is_quiet:
                    is_tier1 = True
                    trigger_date_b = recent_data.index[i].strftime("%Y-%m-%d")
                    
                    # 수급 확인
                    s_start = (datetime.strptime(TARGET_DATE, "%Y%m%d") - timedelta(days=7)).strftime("%Y%m%d")
                    try:
                        supply = stock.get_market_net_purchases_of_equities_by_date(s_start, TARGET_DATE, ticker)
                        inst = int(supply.tail(5)['기관합계'].sum())
                        fore = int(supply.tail(5)['외국인'].sum())
                    except:
                        inst = 0; fore = 0
                    
                    name = stock.get_market_ticker_name(ticker)
                    tier1_results.append({
                        '종목명': name, '현재가': curr_close, '이격도': round(disparity,1),
                        '기준일': trigger_date_b, '기관': inst, '외인': fore
                    })
                    break 

        if is_tier1: continue # 1티어 선정 시 다음 종목으로

        # A 조건 (2티어: 일반형)
        for i in range(len(recent_data)-1, 0, -1):
            curr_row = recent_data.iloc[i]
            prev_row = recent_data.iloc[i-1]
            if prev_row['종가'] == 0 or prev_row['거래량'] == 0: continue

            rise = (curr_row['고가'] - prev_row['종가']) / prev_row['종가'] * 100
            vol_rate = curr_row['거래량'] / prev_row['거래량']

            if rise >= COND_A_PRICE and vol_rate >= COND_A_VOL:
                check_range = recent_data.iloc[i+1:]
                if len(check_range) == 0: continue
                
                trigger_vol = curr_row['거래량']
                is_quiet = True
                for vol in check_range['거래량']:
                    if vol > (trigger_vol * QUIET_VOL_RATIO):
                        is_quiet = False; break
                
                if is_quiet:
                    s_start = (datetime.strptime(TARGET_DATE, "%Y%m%d") - timedelta(days=7)).strftime("%Y%m%d")
                    try:
                        supply = stock.get_market_net_purchases_of_equities_by_date(s_start, TARGET_DATE, ticker)
                        inst = int(supply.tail(5)['기관합계'].sum())
                        fore = int(supply.tail(5)['외국인'].sum())
                    except:
                        inst = 0; fore = 0
                    
                    name = stock.get_market_ticker_name(ticker)
                    tier2_results.append({
                        '종목명': name, '현재가': curr_close, '이격도': round(disparity,1),
                        '기준일': recent_data.index[i].strftime("%Y-%m-%d"), '기관': inst, '외인': fore
                    })
                    break 

    except: continue

# ==========================================
# 결과 전송
# ==========================================
print("\n" + "="*70)
print(f"📊 분석 완료. 1티어({len(tier1_results)}개), 2티어({len(tier2_results)}개) 발견.")

msg = f"## 🚀 {TARGET_DATE} 차트 올인 검색 (실적무관)\n"
msg += f"**조건:** 이격도95↓ | 침묵(50%↓) | 실적 조건 OFF\n\n"

# [1티어 결과]
if len(tier1_results) > 0:
    df1 = pd.DataFrame(tier1_results).sort_values(by='이격도', ascending=True)
    msg += f"### 🔥 [1티어] 강력 세력주 (15%↑ / 300%↑)\n"
    for _, row in df1.iterrows():
        icon = "✅"
        if row['기관'] > 0 and row['외인'] > 0: icon = "👑(쌍끌이)"
        elif row['기관'] > 0: icon = "🔴(기관)"
        elif row['외인'] > 0: icon = "🔵(외인)"
        
        msg += (f"**{row['종목명']}** {icon}\n"
                f"> {row['현재가']:,}원 (이격도 {row['이격도']}%)\n"
                f"> {row['기준일']} 폭발\n\n")
else:
    msg += f"### 🔥 [1티어] 강력 세력주\n검색된 종목 없음\n\n"

msg += "-"*20 + "\n\n"

# [2티어 결과]
if len(tier2_results) > 0:
    df2 = pd.DataFrame(tier2_results).sort_values(by='이격도', ascending=True)
    msg += f"### 🛡️ [2티어] 일반 눌림목 (10%↑ / 200%↑)\n"
    for _, row in df2.head(15).iterrows():
        icon = ""
        if row['기관'] > 0: icon = "🔴"
        
        msg += (f"**{row['종목명']}** {icon}\n"
                f"> {row['현재가']:,}원 (이격도 {row['이격도']}%)\n"
                f"> {row['기준일']} 기준봉\n\n")
    if len(df2) > 15:
        msg += f"*외 {len(df2)-15}개 종목 추가 검색됨*"
else:
    msg += f"### 🛡️ [2티어] 일반 눌림목\n검색된 종목 없음\n"

# 체크리스트 추가
msg += "\n" + "="*25 + "\n"
msg += "📝 **[Self Check List]**\n"
msg += "1. 영업이익 적자기업 제외 & 테마별 분류\n"
msg += "2. 수급 & 최근 일주일 뉴스 체크\n"
msg += "3. 테마/수급/전망 종합하여 최종 선정\n"

send_discord_message(DISCORD_WEBHOOK_URL, msg)
print("✅ 디스코드 전송 완료!")
