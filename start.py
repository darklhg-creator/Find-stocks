"""
추세 모멘텀 전략 봇 (MACD + DMI/ADX + 이격도)
"""

import time
import requests
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# ──────────────────────────────────────────
# 설정값
# ──────────────────────────────────────────
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1466732864392397037/roekkL5WS9fh8uQnm6Bjcul4C8MDo1gsr1ZmzGh8GfuomzlJ5vpZdVbCaY--_MZOykQ4"

DISPARITY_MIN   = 100.0
DISPARITY_MAX   = 103.0
MA_PERIOD       = 20
MACD_FAST       = 12
MACD_SLOW       = 26
MACD_SIGNAL     = 9
ADX_PERIOD      = 14
ADX_MIN         = 25
ADX_RISING_DAYS = 3
MIN_VOLUME_20D  = 100_000
MAX_WORKERS     = 5
DATA_PERIOD     = 120
GOLDEN_CROSS_WINDOW = 3

# ──────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────
def get_date_range(days: int = DATA_PERIOD):
    end   = datetime.today()
    start = end - timedelta(days=days * 2)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

def today_str():
    return datetime.today().strftime("%Y-%m-%d")

# ──────────────────────────────────────────
# 지표 계산
# ──────────────────────────────────────────
def calc_macd(close):
    ema_fast = close.ewm(span=MACD_FAST,  adjust=False).mean()
    ema_slow = close.ewm(span=MACD_SLOW,  adjust=False).mean()
    macd     = ema_fast - ema_slow
    signal   = macd.ewm(span=MACD_SIGNAL, adjust=False).mean()
    return macd, signal

def calc_dmi_adx(high, low, close, period=ADX_PERIOD):
    tr_list, pdi_list, mdi_list = [], [], []
    for i in range(1, len(close)):
        h, l, pc = high.iloc[i], low.iloc[i], close.iloc[i-1]
        tr  = max(h - l, abs(h - pc), abs(l - pc))
        pdm = max(h - high.iloc[i-1], 0)
        mdm = max(low.iloc[i-1] - l, 0)
        if pdm < mdm: pdm = 0
        if mdm < pdm: mdm = 0
        tr_list.append(tr)
        pdi_list.append(pdm)
        mdi_list.append(mdm)
    tr_s  = pd.Series(tr_list)
    pdi_s = pd.Series(pdi_list)
    mdi_s = pd.Series(mdi_list)
    atr = tr_s.ewm(span=period, adjust=False).mean()
    pdi = 100 * pdi_s.ewm(span=period, adjust=False).mean() / atr
    mdi = 100 * mdi_s.ewm(span=period, adjust=False).mean() / atr
    dx  = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, 1e-9)
    adx = dx.ewm(span=period, adjust=False).mean()
    return pdi, mdi, adx

def calc_disparity(close, period=MA_PERIOD):
    ma = close.rolling(period).mean()
    return (close / ma * 100).iloc[-1]

# ──────────────────────────────────────────
# 종목 리스트 수집
# ──────────────────────────────────────────
def get_stock_list() -> list:
    results = []

    try:
        kospi = fdr.StockListing("KOSPI")
        cap_col = None
        for c in ["Marcap", "시가총액", "MarketCap"]:
            if c in kospi.columns:
                cap_col = c
                break
        if cap_col:
            kospi = kospi.sort_values(cap_col, ascending=False).head(500)
        else:
            kospi = kospi.head(500)
        for _, row in kospi.iterrows():
            ticker = str(row.get("Code", row.get("Symbol", ""))).zfill(6)
            name   = str(row.get("Name", ""))
            if ticker and name:
                results.append((ticker, name))
        print(f"[INFO] KOSPI 수집: {len(results)}개")
    except Exception as e:
        print(f"[WARN] KOSPI 수집 실패: {e}")

    try:
        kosdaq = fdr.StockListing("KOSDAQ")
        cap_col = None
        for c in ["Marcap", "시가총액", "MarketCap"]:
            if c in kosdaq.columns:
                cap_col = c
                break
        if cap_col:
            kosdaq = kosdaq.sort_values(cap_col, ascending=False).head(1000)
        else:
            kosdaq = kosdaq.head(1000)
        kosdaq_list = []
        for _, row in kosdaq.iterrows():
            ticker = str(row.get("Code", row.get("Symbol", ""))).zfill(6)
            name   = str(row.get("Name", ""))
            if ticker and name:
                kosdaq_list.append((ticker, name))
        results.extend(kosdaq_list)
        print(f"[INFO] KOSDAQ 수집: {len(kosdaq_list)}개")
    except Exception as e:
        print(f"[WARN] KOSDAQ 수집 실패: {e}")

    print(f"[INFO] 총 분석 대상 종목 수: {len(results)}")
    return results

# ──────────────────────────────────────────
# 종목 분석
# ──────────────────────────────────────────
def analyze_ticker(ticker: str, name: str):
    try:
        start, end = get_date_range()
        df = fdr.DataReader(ticker, start, end)
        if df is None or len(df) < MACD_SLOW + MACD_SIGNAL + ADX_PERIOD + 10:
            return None

        df = df.dropna(subset=["Close", "High", "Low", "Volume"]).sort_index()
        close  = df["Close"].astype(float)
        high   = df["High"].astype(float)
        low    = df["Low"].astype(float)
        volume = df["Volume"].astype(float)

        if volume.iloc[-20:].mean() < MIN_VOLUME_20D:
            return None

        macd, signal = calc_macd(close)
        if len(macd) < GOLDEN_CROSS_WINDOW + 2:
            return None

        golden_cross_found = False
        for i in range(1, GOLDEN_CROSS_WINDOW + 1):
            if len(macd) < i + 2:
                break
            if macd.iloc[-i-1] <= signal.iloc[-i-1] and macd.iloc[-i] > signal.iloc[-i]:
                golden_cross_found = True
                break
        if not golden_cross_found:
            return None

        golden_cross_today = (macd.iloc[-2] <= signal.iloc[-2] and macd.iloc[-1] > signal.iloc[-1])

        pdi, mdi, adx = calc_dmi_adx(high, low, close)
        if len(adx) < ADX_RISING_DAYS + 1:
            return None

        pdi_now = pdi.iloc[-1]
        mdi_now = mdi.iloc[-1]
        adx_now = adx.iloc[-1]

        if pdi_now <= mdi_now:
            return None
        if adx_now < ADX_MIN:
            return None
        if not all(adx.iloc[-i] > adx.iloc[-i-1] for i in range(1, ADX_RISING_DAYS + 1)):
            return None

        if len(close) < MA_PERIOD:
            return None
        disparity = calc_disparity(close)
        if not (DISPARITY_MIN <= disparity <= DISPARITY_MAX):
            return None

        return {
            "ticker"      : ticker,
            "name"        : name,
            "price"       : int(close.iloc[-1]),
            "disparity"   : round(disparity, 2),
            "macd"        : round(macd.iloc[-1], 4),
            "signal"      : round(signal.iloc[-1], 4),
            "pdi"         : round(pdi_now, 2),
            "mdi"         : round(mdi_now, 2),
            "adx"         : round(adx_now, 2),
            "golden_cross": golden_cross_today,
            "avg_vol"     : int(volume.iloc[-20:].mean()),
        }
    except Exception:
        return None

# ──────────────────────────────────────────
# Discord
# ──────────────────────────────────────────
def send_discord(content: str):
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
        if resp.status_code not in (200, 204):
            print(f"[WARN] Discord 전송 실패: {resp.status_code}")
        else:
            print("[INFO] Discord 전송 성공")
    except Exception as e:
        print(f"[ERROR] Discord 오류: {e}")

def format_discord_message(results: list) -> list:
    today = today_str()
    header = (
        f"📈 **추세 모멘텀 전략 알림** | {today}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"조건: MACD골든크로스(3일이내) + PDI>MDI + ADX≥{ADX_MIN}(상승) + 이격도 {DISPARITY_MIN}~{DISPARITY_MAX}%\n"
        f"총 {len(results)}개 종목 발견\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if not results:
        return [header + "⚠️ 조건을 충족하는 종목이 없습니다."]

    messages = [header]
    chunk = ""
    for r in results:
        cross_tag = "🔥오늘골든크로스" if r["golden_cross"] else "✅3일이내골든크로스"
        line = (
            f"\n**{r['name']}** ({r['ticker']})\n"
            f"  💰 현재가: {r['price']:,}원  |  📊 이격도: {r['disparity']}%\n"
            f"  {cross_tag}  |  PDI {r['pdi']} > MDI {r['mdi']}  |  ADX {r['adx']}\n"
            f"  MACD: {r['macd']} / Signal: {r['signal']}\n"
            f"  거래량(20일평균): {r['avg_vol']:,}\n"
        )
        if len(chunk) + len(line) > 1800:
            messages.append(chunk)
            chunk = line
        else:
            chunk += line
    if chunk:
        messages.append(chunk)
    return messages

# ──────────────────────────────────────────
# 메인
# ──────────────────────────────────────────
def main():
    print(f"[START] 추세 모멘텀 전략 봇 시작 | {today_str()}")
    start_time = time.time()

    stock_list = get_stock_list()
    if not stock_list:
        send_discord("❌ 종목 리스트를 가져오지 못했습니다.")
        return

    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(analyze_ticker, ticker, name): (ticker, name)
            for ticker, name in stock_list
        }
        for future in as_completed(futures):
            done += 1
            if done % 100 == 0:
                print(f"  진행: {done}/{len(stock_list)}")
            result = future.result()
            if result:
                results.append(result)

    results.sort(key=lambda x: x["adx"], reverse=True)
    elapsed = round(time.time() - start_time, 1)
    print(f"[DONE] 소요시간: {elapsed}초 | 조건 충족: {len(results)}개")

    for msg in format_discord_message(results):
        send_discord(msg)
        time.sleep(0.5)

    print("\n── 결과 요약 ──────────────────────────")
    for r in results:
        print(f"  {r['name']:12s} ({r['ticker']}) | 이격도 {r['disparity']:6.2f}% | ADX {r['adx']:5.1f} | PDI {r['pdi']:5.1f} > MDI {r['mdi']:5.1f}")

if __name__ == "__main__":
    main()
