import requests
from pykrx import stock
import pandas as pd
from datetime import datetime, timedelta, timezone

# 🔴 디스코드 웹후크 URL
WEBHOOK_URL = "https://discord.com/api/webhooks/1466732864392397037/roekkL5WS9fh8uQnm6Bjcul4C8MDo1gsr1ZmzGh8GfuomzlJ5vpZdVbCaY--_MZOykQ4"

EXCLUDE_KEYWORDS = [
    '미국', '차이나', '중국', '일본', '나스닥', 'S&P', '글로벌', 'MSCI', '인도', '베트남', 
    '필라델피아', '레버리지', '인버스', '블룸버그', '항셍', '니케이', '빅테크', 'TSMC', 
    '대만', '유로', '스톡스', '선물', '채권', '국고채', '머니마켓', 'KOFR', 'CD금리', '달러', '엔화'
]

def send_discord_message(msg_content):
    payload = {"content": msg_content}
    try:
        requests.post(WEBHOOK_URL, json=payload)
    except Exception as e:
        print(f"❌ 전송 에러: {e}")

def main():
    KST = timezone(timedelta(hours=9))
    today_dt = datetime.now(KST)
    target_date = today_dt.strftime("%Y%m%d")
    
    # 주말 작동 방지
    if today_dt.weekday() >= 5:
        print("💤 주말입니다. 분석을 쉬어갑니다.")
        return

    try:
        # 1. 영업일 조회 (KODEX 200 데이터 활용 - 에러 없는 가장 안전한 방식)
        dt_start = (today_dt - timedelta(days=10)).strftime("%Y%m%d")
        df_days = stock.get_market_ohlcv(dt_start, target_date, "069500")
        
        if df_days.empty or len(df_days) < 2:
            print("❌ 장이 열린 날짜 데이터를 확인할 수 없습니다.")
            return
            
        b_days = df_days.index.strftime("%Y%m%d").tolist()
        curr_date = b_days[-1] # 오늘(또는 가장 최근 영업일)
        prev_date = b_days[-2] # 어제(또는 그 직전 영업일)
        
        print(f"📡 데이터 조회: 오늘({curr_date}) / 어제({prev_date})")

        # 2. 어제와 오늘 데이터 각각 통째로 가져오기
        df_curr = stock.get_etf_ohlcv_by_ticker(curr_date)
        df_prev = stock.get_etf_ohlcv_by_ticker(prev_date)
        
        if df_curr.empty or df_prev.empty:
            print("❌ 시세 데이터를 불러오지 못했습니다.")
            return

        results = []

        # 3. [유저 아이디어 반영] 직관적이고 확실한 직접 계산 로직
        for ticker in df_curr.index:
            # 어제 데이터가 없는 신규 상장 종목 등은 패스
            if ticker not in df_prev.index:
                continue
                
            name = stock.get_etf_ticker_name(ticker)
            
            # 필터링
            if any(word in name for word in EXCLUDE_KEYWORDS): 
                continue
            
            # 어제 종가, 오늘 종가, 오늘 거래대금 추출
            prev_close = float(df_prev.loc[ticker, '종가'])
            curr_close = float(df_curr.loc[ticker, '종가'])
            curr_amt = float(df_curr.loc[ticker, '거래대금'])
            
            if prev_close == 0: continue # 에러 방지
            
            # 등락률 직접 계산
            change_rate = ((curr_close - prev_close) / prev_close) * 100
            
            # 상승한 종목만 담기
            if change_rate > 0:
                results.append({
                    '종목명': name,
                    '상승률': change_rate,
                    '거래대금(억)': round(curr_amt / 100_000_000, 1)
                })

        # 4. 결과 정렬 및 전송
        if results:
            final_df = pd.DataFrame(results).sort_values(by='상승률', ascending=False).head(10)
            
            # 소수점 2자리 포맷팅
            final_df['상승률'] = final_df['상승률'].map(lambda x: f"{x:.2f}%")

            discord_msg = f"🚀 **[오늘의 국내 ETF 상승률 TOP 10]** ({today_dt.strftime('%Y-%m-%d')})\n"
            discord_msg += "```text\n"
            discord_msg += final_df.to_string(index=False) + "\n"
            discord_msg += "```\n"
            
            send_discord_message(discord_msg)
            print("✅ 분석 및 디스코드 전송 완료!")
            print(final_df)
        else:
            print("⚠️ 조건에 맞는 상승 종목이 없습니다.")

    except Exception as e:
        print(f"❌ 최종 오류 발생: {e}")

if __name__ == "__main__":
    main()
