from pykrx import stock
from datetime import datetime

today = datetime.today().strftime("%Y%m%d")

print("=== KOSPI 컬럼 확인 ===")
df = stock.get_market_cap_by_ticker(today, market="KOSPI")
print("컬럼명:", df.columns.tolist())
print("첫 3행:")
print(df.head(3))
