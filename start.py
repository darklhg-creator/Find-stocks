import requests
from pykrx import stock
import pandas as pd
from datetime import datetime, timedelta, timezone

# 🔴 디스코드 웹후크 URL (사용하시는 URL로 확인해 주세요)
WEBHOOK_URL = "https://discord.com/api/webhooks/1466732864392397037/roekkL5WS9fh8uQnm6Bjcul4C8MDo1gsr1ZmzGh8GfuomzlJ5vpZdVbCaY--_MZOykQ4"

def send_discord_message(msg_content):
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
    KST = timezone(timedelta(hours=9))
    today_dt = datetime.now(KST)
    target_date = today_dt.strftime("%Y%m%d")
    
    print(f"📅 조회 기준일: {target_date}")

    try:
        # 1. 오늘 전체 ETF 시세 가져오기
        df_today = stock.get_etf_ohlcv_by_ticker(target_date)
        
        if df_today.empty:
            send_discord_message(f"⚠️ [{target_date}] 데이터를 불러올 수 없습니다. (휴장일 또는 데이터 미업데이트)")
            return

        # 2. 제외 필터 (해외/채권/인버스 등 순수 국내 섹터가 아닌 것들)
        exclude_filters = [
            '미국', '차이나', '중국', '일본', '나스닥', 'S&P', '글로벌', 'MSCI', '인도', '베트남', 
            '필라델피아', '레버리지', '인버스', '블룸버그', '항셍', '니케이', '빅테크', 'TSMC', 
            '대만', '유로', '스톡스', '선물', '채권', '국고채', '머니마켓', 'KOFR', 'CD금리'
        ]
        
        results = []
        
        # 3. 데이터 수집 및 이름 필터링
        for ticker, row in df_today.iterrows():
            name = stock.get_etf_ticker_name(ticker)
            
            # 필터링 키워드 포함 시 제외
            if any(word in name for word in exclude_filters): continue
            
            results.append({
                '종목명': name,
                '상승률': row['등락률'],
                '거래대금(억)': round(row['거래대금'] / 100_000_000, 1)
            })

        # 4. 상승률 기준 정렬 및 상위 10개 추출
        if results:
            final_df = pd.DataFrame(results).sort_values(by='상승률', ascending=False).head(10)
            
            # 상승률 표시 포맷 변경 (예: 5.23%)
            final_df['상승률'] = final_df['상승률'].map(lambda x: f"{x:.2f}%")

            # 디스코드 메시지 포맷팅
            discord_msg = f"🚀 **[오늘의 국내 ETF 상승률 TOP 10]** ({today_dt.strftime('%Y-%m-%d')})\n"
            discord_msg += "```text\n"
            discord_msg += final_df.to_string(index=False) + "\n"
            discord_msg += "```\n"
            discord_msg += "💡 오늘 가장 강했던 섹터들입니다. 구성 종목을 확인해 보세요!"
            
            send_discord_message(discord_msg)
            print(final_df)
        else:
            send_discord_message(f"🔍 [{target_date}] 조건에 맞는 상승 종목이 없습니다.")

    except Exception as e:
        print(f"❌ 오류 발생: {e}")

if __name__ == "__main__":
    main()
