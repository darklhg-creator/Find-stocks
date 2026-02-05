import pandas as pd
import numpy as np
from pykrx import stock
import time
from datetime import datetime, timedelta
import requests

# --- [추가] 시장 개장 여부 확인 함수 ---
def is_market_open():
    now = datetime.now()
    # 1. 주말 체크 (5: 토요일, 6: 일요일)
    if now.weekday() >= 5:
        return False
    
    # 2. 공휴일 체크 (오늘 날짜의 데이터가 있는지 확인)
    # pykrx의 get_nearest_business_day를 활용해 오늘이 영업일인지 판단
    target_date = now.strftime("%Y%m%d")
    try:
        # 오늘 날짜를 포함한 최근 영업일 1일을 가져와서 오늘과 같은지 비교
        business_days = stock.get_market_ohlcv_by_date(target_date, target_date, "005930") # 삼성전자 기준
        if business_days.empty:
            return False
    except:
        return False
        
    return True

# (기존 get_local_minima, check_linear_trend 함수 등은 동일하게 유지)
# ... [중략] ...

if __name__ == "__main__":
    # 시장이 열리는 날이 아니면 종료
    if not is_market_open():
        print("오늘은 시장이 열리지 않는 날이므로 분석을 종료합니다.")
        exit()

    now = datetime.now()
    end_date = now.strftime("%Y%m%d")
    start_date = (now - timedelta(days=90)).strftime("%Y%m%d")
    
    # (종목 스캔 및 결과 생성 로직 동일)
    # ... [중략] ...
    
    # 결과 전송
    if results:
        final_df = pd.DataFrame(results).sort_values(by='이격률(%)')
        msg = f"📅 {datetime.now().strftime('%Y-%m-%d')} [이효근표] 추세선 지지 종목\n```\n{final_df.to_string(index=False)}\n```"
        send_discord_message(msg)
