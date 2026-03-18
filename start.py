"""
추세 모멘텀 전략 봇 (MACD + DMI/ADX + 이격도)
=============================================
전략 조건:
  1단계) MACD 골든크로스: MACD선이 시그널선을 상향 돌파 (오늘 크로스 발생)
  2단계) PDI > MDI: 매수세가 매도세 위에 있음
  3단계) ADX 상승 + 20 이상: 추세가 강화되고 있음
  추가)  이격도 95~105%: 거품 없이 추세 초입 구간

실행 방법:
  pip install pykrx finance-datareader pandas requests
  python trend_momentum_bot.py

GitHub Actions 환경변수:
  DISCORD_WEBHOOK_URL : Discord 웹훅 URL
"""

import os
import time
import requests
import pandas as pd
import FinanceDataReader as fdr
from pykrx import stock
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# ──────────────────────────────────────────
# 설정값
# ──────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.environ.get(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1466732864392397037/roekkL5WS9fh8uQnm6Bjcul4C8MDo1gsr1ZmzGh8GfuomzlJ5vpZdVbCaY--_MZOykQ4"
)

# 이격도 범위
DISPARITY_MIN = 95.0
DISPARITY_MAX = 105.0
MA_PERIOD = 20           # 이격도 기준 이동평균

# MACD 파라미터
MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIGNAL = 9

# ADX 파라미터
ADX_PERIOD     = 14
ADX_MIN        = 20      # ADX가 이 값 이상이어야 추세 인정
ADX_RISING_DAYS = 3      # 최근 N일 연속 ADX가 상승해야 함

# 기타 필터
MIN_VOLUME_20D = 100_000  # 20일 평균 거래량 최소치
MAX_WORKERS    = 5        # 멀티스레딩 워커 수
DATA_PERIOD    = 120      # 지표 계산에 필요한 캔들 수 (영업일)

# ──────────────────────────────────────────
# 유틸: 날짜 계산
# ──────────────────────────────────────────
def get_date_range(days: int = DATA_PERIOD):
    """오늘부터 days 영업일 전 날짜 반환 (넉넉하게 캘린더 기준 2배 확보)"""
    end   = datetime.today()
    start = end - timedelta(days=days * 2)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

def today_str():
    return datetime.today().strftime("%Y-%m-%d")

# ──────────────────────────────────────────
# 지표 계산 함수
# ──────────────────────────────────────────
def calc_macd(close: pd.Series):
    """MACD, Signal, Histogram 반환"""
    ema_fast   = close.ewm(span=MACD_FAST,   adjust=False).mean()
    ema_slow   = close.ewm(span=MACD_SLOW,   adjust=False).mean()
    macd       = ema_fast - ema_slow
    signal     = macd.ewm(span=MACD_SIGNAL, adjust=False).mean()
    histogram  = macd - signal
    return macd, signal, histogram


def calc_dmi_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = ADX_PERIOD):
    """PDI, MDI, ADX 반환"""
    tr_list, pdi_list, mdi_list = [], [], []

    for i in range(1, len(close)):
        h, l, pc = high.iloc[i], low.iloc[i], close.iloc[i - 1]
        tr  = max(h - l, abs(h - pc), abs(l - pc))
        pdm = max(h - high.iloc[i - 1], 0)
        mdm = max(low.iloc[i - 1] - l, 0)
        if pdm < mdm: pdm = 0
        if mdm < pdm: mdm = 0
        tr_list.append(tr)
        pdi_list.append(pdm)
        mdi_list.append(mdm)

    tr_s   = pd.Series(tr_list)
    pdi_s  = pd.Series(pdi_list)
    mdi_s  = pd.Series(mdi_list)

    atr    = tr_s.ewm(span=period, adjust=False).mean()
    pdi    = 100 * pdi_s.ewm(span=period, adjust=False).mean() / atr
    mdi    = 100 * mdi_s.ewm(span=period, adjust=False).mean() / atr

    dx     = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, 1e-9)
    adx    = dx.ewm(span=period, adjust=False).mean()

    return pdi, mdi, adx


def calc_disparity(close: pd.Series, period: int = MA_PERIOD):
    """이격도(%) = 현재가 / MA * 100"""
    ma = close.rolling(period).mean()
    return (close / ma * 100).iloc[-1]


# ──────────────────────────────────────────
# 종목 분석 핵심 로직
# ──────────────────────────────────────────
def analyze_ticker(ticker: str, name: str) -> dict | None:
    """
    단일 종목을 분석해 조건 충족 시 결과 dict 반환, 미충족 시 None
    """
    try:
        start, end = get_date_range()
        df = fdr.DataReader(ticker, start, end)
        if df is None or len(df) < MACD_SLOW + MACD_SIGNAL + ADX_PERIOD + 10:
            return None

        df = df.dropna(subset=["Close", "High", "Low", "Volume"])
        df = df.sort_index()

        close  = df["Close"].astype(float)
        high   = df["High"].astype(float)
        low    = df["Low"].astype(float)
        volume = df["Volume"].astype(float)

        # ── 거래량 필터 ──────────────────────
        avg_vol = volume.iloc[-20:].mean()
        if avg_vol < MIN_VOLUME_20D:
            return None

        # ── MACD 계산 ────────────────────────
        macd, signal, hist = calc_macd(close)
        if len(macd) < 2:
            return None

        # 최근 3일 이내 골든크로스 확인
        # 조건: i일 전에 macd <= signal 이었다가 그 다음날 macd > signal 로 전환된 적이 있는지
        GOLDEN_CROSS_WINDOW = 3
        golden_cross_found = False
        for i in range(1, GOLDEN_CROSS_WINDOW + 1):
            if len(macd) < i + 2:
                break
            # -i-1 일: 크로스 전 (macd <= signal)
            # -i   일: 크로스 발생 (macd > signal)
            before = macd.iloc[-i - 1] <= signal.iloc[-i - 1]
            after  = macd.iloc[-i]      > signal.iloc[-i]
            if before and after:
                golden_cross_found = True
                break

        if not golden_cross_found:
            return None

        # 골든크로스 발생일 기록 (Discord 표시용)
        golden_cross_today = (macd.iloc[-2] <= signal.iloc[-2] and macd.iloc[-1] > signal.iloc[-1])

        # ── DMI / ADX 계산 ───────────────────
        pdi, mdi, adx = calc_dmi_adx(high, low, close)
        if len(adx) < ADX_RISING_DAYS + 1:
            return None

        pdi_now = pdi.iloc[-1]
        mdi_now = mdi.iloc[-1]
        adx_now = adx.iloc[-1]

        # 2단계: PDI > MDI
        if pdi_now <= mdi_now:
            return None

        # 3단계: ADX >= 20 & 연속 상승
        if adx_now < ADX_MIN:
            return None
        adx_rising = all(
            adx.iloc[-i] > adx.iloc[-i - 1]
            for i in range(1, ADX_RISING_DAYS + 1)
        )
        if not adx_rising:
            return None

        # ── 이격도 계산 ──────────────────────
        if len(close) < MA_PERIOD:
            return None
        disparity = calc_disparity(close)
        if not (DISPARITY_MIN <= disparity <= DISPARITY_MAX):
            return None

        current_price = close.iloc[-1]

        return {
            "ticker"      : ticker,
            "name"        : name,
            "price"       : int(current_price),
            "disparity"   : round(disparity, 2),
            "macd"        : round(macd.iloc[-1], 4),
            "signal"      : round(signal.iloc[-1], 4),
            "pdi"         : round(pdi_now, 2),
            "mdi"         : round(mdi_now, 2),
            "adx"         : round(adx_now, 2),
            "golden_cross": golden_cross_today,
            "avg_vol"     : int(avg_vol),
        }

    except Exception:
        return None


# ──────────────────────────────────────────
# 종목 리스트 수집
# ──────────────────────────────────────────
def get_stock_list() -> list[tuple[str, str]]:
    """KOSPI 상위 500 + KOSDAQ 상위 1000 종목 반환 (ticker, name)"""
    today = datetime.today().strftime("%Y%m%d")
    results = []

    try:
        # KOSPI 시가총액 상위 500
        kospi_cap = stock.get_market_cap_by_ticker(today, market="KOSPI")
        kospi_cap = kospi_cap.sort_values("시가총액", ascending=False).head(500)
        for ticker in kospi_cap.index:
            try:
                name = stock.get_market_ticker_name(ticker)
                results.append((ticker, name))
            except Exception:
                pass
    except Exception as e:
        print(f"[WARN] KOSPI 리스트 수집 실패: {e}")

    try:
        # KOSDAQ 시가총액 상위 1000
        kosdaq_cap = stock.get_market_cap_by_ticker(today, market="KOSDAQ")
        kosdaq_cap = kosdaq_cap.sort_values("시가총액", ascending=False).head(1000)
        for ticker in kosdaq_cap.index:
            try:
                name = stock.get_market_ticker_name(ticker)
                results.append((ticker, name))
            except Exception:
                pass
    except Exception as e:
        print(f"[WARN] KOSDAQ 리스트 수집 실패: {e}")

    print(f"[INFO] 총 분석 대상 종목 수: {len(results)}")
    return results


# ──────────────────────────────────────────
# Discord 알림
# ──────────────────────────────────────────
def send_discord(content: str):
    if not DISCORD_WEBHOOK_URL:
        print("[WARN] DISCORD_WEBHOOK_URL 환경변수가 없습니다. 콘솔에만 출력합니다.")
        print(content)
        return
    payload = {"content": content}
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code not in (200, 204):
            print(f"[WARN] Discord 전송 실패: {resp.status_code}")
    except Exception as e:
        print(f"[ERROR] Discord 전송 오류: {e}")


def format_discord_message(results: list[dict]) -> list[str]:
    """결과를 Discord 메시지 리스트로 변환 (2000자 제한 분할)"""
    today = today_str()
    header = (
        f"📈 **추세 모멘텀 전략 알림** | {today}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"조건: MACD골든크로스 + PDI>MDI + ADX≥{ADX_MIN}(상승) + 이격도 {DISPARITY_MIN}~{DISPARITY_MAX}%\n"
        f"총 {len(results)}개 종목 발견\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    if not results:
        return [header + "⚠️ 조건을 충족하는 종목이 없습니다."]

    messages = [header]
    chunk = ""

    for r in results:
        cross_tag = "🔥골든크로스" if r["golden_cross"] else "✅MACD↑"
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
# 메인 실행
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

    # ADX 내림차순 정렬 (추세 강도 높은 순)
    results.sort(key=lambda x: x["adx"], reverse=True)

    elapsed = round(time.time() - start_time, 1)
    print(f"[DONE] 소요시간: {elapsed}초 | 조건 충족: {len(results)}개")

    messages = format_discord_message(results)
    for msg in messages:
        send_discord(msg)
        time.sleep(0.5)  # Discord rate limit 방지

    # 콘솔 요약 출력
    print("\n── 결과 요약 ──────────────────────────")
    for r in results:
        print(
            f"  {r['name']:12s} ({r['ticker']}) | "
            f"이격도 {r['disparity']:6.2f}% | "
            f"ADX {r['adx']:5.1f} | "
            f"PDI {r['pdi']:5.1f} > MDI {r['mdi']:5.1f}"
        )


if __name__ == "__main__":
    main()
