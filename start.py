import requests
from pykrx import stock
import pandas as pd
from datetime import datetime, timedelta, timezone

# 🔴 디스코드 웹후크 URL
WEBHOOK_URL = "https://discord.com/api/webhooks/1466732864392397037/roekkL5WS9fh8uQnm6Bjcul4C8MDo1gsr1ZmzGh8GfuomzlJ5vpZdVbCaY--_MZOykQ4"

def send_discord_message(msg_content):
    """디스코드로 메시지를 전송하는 함수"""
    payload = {"content": msg_content}
    try:
        response = requests.post(WEBHOOK_URL, json=payload)
        if response.status_code == 204:
            print("✅ 디스코드 알림 전송 완료!")
        else:
            print(f"⚠️ 디스코드 전송 실패 (상태 코드: {response.status_code})")
    except Exception as e:
        print(f"❌ 디스코드 전송 중 에러 발생: {e}")

def main():
    # 1. 깃허브 서버(UTC) 시간을 한국 시간(KST)으로 변환
    KST = timezone(timedelta(hours=9))
    today_dt = datetime.now(KST)
    target_date = today_dt.strftime("%Y%m%d")
    start_date = (today_dt - timedelta(days=50)).strftime("%Y%m%d")
    
    print(f"📅 실행일시: {today_dt.strftime('%Y-%m-%d %H:%M:%S')} (KST)")

    # 2. 주말(토, 일) 체크 및 디스코드 보고
    if today_dt.weekday() >= 5:
        msg = f"💤 **[{today_dt.strftime('%Y-%m-%d')}]** 오늘은 주말(토/일)입니다. 주도주 탐색을 쉬어갑니다!"
        print(msg)
        send_discord_message(msg)  # 디스코드로 알림 쏘기!
        return # 프로그램 종료
    
    try:
        # 3. 오늘 ETF 시세 한 번에 가져오기 (공휴일 체크 및 디스코드 보고)
        df_today = stock.get_etf_ohlcv_by_ticker(target_date)
        
        if df_today.empty:
            msg = f"💤 **[{today_dt.strftime('%Y-%m-%d')}]** 오늘 거래 데이터가 없습니다. (공휴일 등 휴장일로 판단되어 탐색을 쉬어갑니다!)"
            print(msg)
            send_discord_message(msg)  # 디스코드로 알림 쏘기!
            return

        exclude_filters = [
            '미국', '차이나', '중국', '일본', '나스닥', 'S&P', '글로벌', 'MSCI', '인도', '베트남', 
            '필라델피아', '레버리지', '인버스', '블룸버그', '항셍', '니케이', '빅테크', 'TSMC', 
            '대만', '유로', '스톡스', '선물'
        ]
        
        candidates = []
        
        # 4. 오늘 10억 이상 터진 알짜배기 1차 필터링
        for ticker, row in df_today.iterrows():
            name = stock.get_etf_ticker_name(ticker)
            if any(word in name for word in exclude_filters): continue
            
            try:
                today_amt = row['거래대금']
            except:
                today_amt = row.iloc[3] * row.iloc[4] # 종가 * 거래량
            
            if today_amt >= 1_000_000_000: 
                candidates.append((ticker, name, today_amt))
                
        print(f"🔍 1차 필터링: 후보 {len(candidates)}개 압축 완료. 과거 데이터 분석 중...")
        
        results = []
        
        # 5. 과거 데이터 비교 (당일 거래대금 폭발력 계산)
        for ticker, name, today_amt in candidates:
            df = stock.get_market_ohlcv_by_date(start_date, target_date, ticker)
            
            if df.empty or len(df) < 10: continue
            
            past_df = df.iloc[:-1].tail(20)
            past_amts = past_df['종가'] * past_df['거래량']
            avg_amt = past_amts.mean()
            
            if avg_amt > 0:
                ratio = today_amt / avg_amt
                results.append({
                    '종목명': name,
                    '폭발력(배)': round(ratio, 2),
                    '오늘대금(억)': round(today_amt / 100_000_000, 1),
                    '20일평균대금(억)': round(avg_amt / 100_000_000, 1)
                })

        # 6. 결과 정렬 및 디스코드 전송
        if results:
            final_df = pd.DataFrame(results).sort_values(by='폭발력(배)', ascending=False).head(10)
            
            # 터미널 출력용
            print("\n" + "=" * 80)
            print(f"🔥 [순수 국내 섹터 주도주 TOP 10]")
            print("-" * 80)
            print(final_df.to_string(index=False))
            print("=" * 80)
            
            # 디스코드 메시지 포맷팅
            discord_msg = f"🔥 **[국내 주도주 ETF 탐지기]** ({today_dt.strftime('%Y-%m-%d')} 마감 기준)\n"
            discord_msg += "```text\n"
            discord_msg += final_df.to_string(index=False) + "\n"
            discord_msg += "```\n"
            discord_msg += "💡 해당 ETF들이 어떤 종목들이 포함된 ETF인지 분석해줘"
            
            send_discord_message(discord_msg)
            
        else:
            print("조건에 맞는 주도주 종목이 없습니다.")

    except Exception as e:
        print(f"❌ 오류 발생: {e}")

if __name__ == "__main__":
    main()
