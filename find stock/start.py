import FinanceDataReader as fdr
import requests
import pandas as pd
from datetime import datetime
import os

# 디스코드 설정
IGYEOK_WEBHOOK_URL = "https://discord.com/api/webhooks/1461902939139604684/ZdCdITanTb3sotd8LlCYlJzSYkVLduAsjC6CD2h26X56wXoQRw7NY72kTNzxTI6UE4Pi"

def main():
    print("🚀 [1단계] 계단식 이격도 분석 시작 (KOSPI 500 + KOSDAQ 500)")
    
    try:
        # 1. 대상 종목 리스트 확보
        df_kospi = fdr.StockListing('KOSPI').head(500)
        df_kosdaq = fdr.StockListing('KOSDAQ').head(500)
        df_total = pd.concat([df_kospi, df_kosdaq])
        
        all_analyzed = []
        print(f"📡 총 {len(df_total)}개 종목 데이터 수집 중...")

        for idx, row in df_total.iterrows():
            code = row['Code']
            name = row['Name']
            try:
                df = fdr.DataReader(code).tail(30)
                if len(df) < 20: continue
                
                current_price = df['Close'].iloc[-1]
                ma20 = df['Close'].rolling(window=20).mean().iloc[-1]
                
                if ma20 == 0 or pd.isna(ma20): continue
                    
                disparity = round((current_price / ma20) * 100, 1)
                all_analyzed.append({'name': name, 'code': code, 'disparity': disparity})
            except:
                continue

        # 2. 계단식 필터링 로직
        results = [r for r in all_analyzed if r['disparity'] <= 90.0]
        filter_level = "90% 이하 (초과대낙폭)"

        if not results:
            print("💡 이격도 90% 이하 종목이 없어 범위를 95%로 확대합니다.")
            results = [r for r in all_analyzed if r['disparity'] <= 95.0]
            filter_level = "95% 이하 (일반낙폭)"

        # 3. 결과 처리 및 전송
        if results:
            results = sorted(results, key=lambda x: x['disparity'])
            
            # 리포트 제목 및 본문 구성
            report = f"### 📊 이격도 분석 결과 ({filter_level})\n"
            for r in results[:50]:
                report += f"· **{r['name']}({r['code']})**: {r['disparity']}%\n"
            
            # --- 요청하신 체크리스트 문구 추가 ---
            report += "1.영업이익 적자기업 제외하고 테마별로 표로 분류하고 \n"
            report += "2.1번에서 정리한 기업들 오늘 장마감 기준으로 기관 외국인 연기금 수급 분석\n"
            report += "3.2번에서 나온 기업들 오늘 기준으로 일주일간 뉴스 검색\n"
            # -----------------------------------
            
            # 디스코드 전송
            requests.post(IGYEOK_WEBHOOK_URL, json={'content': report})
            
            # 차례대로 targets.txt 저장
            with open("targets.txt", "w", encoding="utf-8") as f:
                lines = [f"{r['code']},{r['name']}" for r in results]
                f.write("\n".join(lines))
            
            print(f"✅ {filter_level} 조건으로 {len(results)}개 추출 완료.")
        else:
            msg = "🔍 95% 이하 조건에도 해당되는 종목이 없습니다."
            print(msg)
            requests.post(IGYEOK_WEBHOOK_URL, json={'content': msg})

    except Exception as e:
        print(f"❌ 에러 발생: {e}")

if __name__ == "__main__":
    main()
