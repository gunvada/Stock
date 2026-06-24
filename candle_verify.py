# -*- coding: utf-8 -*-
"""
캔들 교차검증 레이어  (본장 후보 → '캔들 시그널·모양'으로 재검증·축소)
====================================================================
거래량 폭증 눌림목 후보(pullback_<date>.csv)를 **캔들 시그널·모양 + 추세**로
교차검증한다. 데이터는 yfinance 일봉(API 키 불필요).
  · 캔들: 최근 LOOKBACK일 일봉에 상승 성질 캔들(양봉스프링·위꼬리양봉·양봉팽이
          /긴위아래꼬리 작은양봉 등) 출현 여부 (candle_patterns).
  · 추세: 장기 이평 방향+가격 위치로 '구간별 위치' 근사(상승/하락/횡보).

PASS = 최근 상승 캔들 신호 있음 (캔들 시그널·모양 기준).
  · 추세(상승/하락/횡보)는 **참고 표시용 컬럼**이며 PASS를 강제하지 않는다(사용자 정의).
    이유: 캔들이론은 '하락세 최저점 반등'도 노리는데, 단순 이평 추세로 하락세를 일괄
    제외하면 그 바닥 반등까지 걸러지기 때문(최저점 vs 중도 구분은 멀티TF 재량 판단).
주의: 저점대비배수·베이스비율 등 위치 지표는 미사용(사용자 정의).

사용법:
  python candle_verify.py                 # 최신 pullback_<date>.csv 교차검증
  python candle_verify.py AAPL MSFT ...   # 임의 티커 직접 평가(디버그)
"""
import os
import re
import sys
import glob

import pandas as pd

import candle_patterns as cp

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
LOOKBACK = 5         # 최근 며칠 봉에서 '모양'을 찾을지 (튜닝 가능)

# 추세(구간별 위치) 근사용 — 장기 이평 방향 + 가격 위치
TREND_MA = 100          # 장기 이평 일수
TREND_SLOPE_BARS = 20   # 기울기 측정 구간
TREND_FLAT_PCT = 2.0    # 이평 변화 |%| < 이 값이면 '횡보'
# 참고: 추세는 표시용. (상승/횡보가 '유리'한 맥락이나 PASS를 강제하지 않음)


def classify_trend(price, ma_now, ma_prev):
    """장기 이평 기울기 + 가격 위치로 구간 근사. 순수 함수.
    상승: 이평 상승 & 가격≥이평 / 하락: 이평 하락 & 가격≤이평 / 그 외 횡보. 데이터부족=불명."""
    if not ma_now or not ma_prev or ma_now <= 0 or ma_prev <= 0:
        return "불명"
    slope = (ma_now - ma_prev) / ma_prev * 100
    if slope > TREND_FLAT_PCT and price >= ma_now:
        return "상승"
    if slope < -TREND_FLAT_PCT and price <= ma_now:
        return "하락"
    return "횡보"


def recent_bullish_signals(ohlc, lookback=LOOKBACK):
    """ohlc: [(o,h,l,c), ...] 오래된→최신. 최근 lookback봉 중 상승 캔들신호 목록.
    반환: [{'offset': D, 'labels': [...]}], offset=0이 최신봉. 순수 함수."""
    out = []
    window = ohlc[-lookback:] if lookback else ohlc
    n = len(window)
    for i, (o, h, l, c) in enumerate(window):
        labels = [lbl for lbl in cp.detect(o, h, l, c) if lbl in cp.BULLISH_LABELS]
        if labels:
            out.append({"offset": (n - 1 - i), "labels": labels})
    return out


def _fmt_signals(sigs):
    if not sigs:
        return "-"
    return ", ".join(f"{'+'.join(s['labels'])}@D-{s['offset']}" for s in sigs)


def _trend_of(closes):
    """종가 리스트 → (추세라벨). 장기 이평(TREND_MA)과 그 기울기로 근사."""
    n = len(closes)
    if n < TREND_MA + TREND_SLOPE_BARS:
        return "불명"
    ma_now = sum(closes[-TREND_MA:]) / TREND_MA
    prev = closes[-(TREND_MA + TREND_SLOPE_BARS):-TREND_SLOPE_BARS]
    ma_prev = sum(prev) / len(prev)
    return classify_trend(closes[-1], ma_now, ma_prev)


def evaluate_ticker(ticker):
    """yfinance 일봉으로 '캔들 시그널·모양' + '추세(구간별 위치 근사)' 평가.
    PASS = 최근 캔들 신호 있음 AND 추세가 상승/횡보(하락세 신호는 제외)."""
    import yfinance as yf
    try:
        df = yf.Ticker(ticker).history(period="1y", interval="1d", auto_adjust=False)
    except Exception as e:
        return {"ticker": ticker, "error": f"{type(e).__name__}: {str(e)[:60]}"}
    if df is None or df.empty:
        return {"ticker": ticker, "error": "데이터 없음"}
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    ohlc = [tuple(float(x) for x in row)
            for row in zip(df["Open"], df["High"], df["Low"], df["Close"])]
    if not ohlc:
        return {"ticker": ticker, "error": "유효 일봉 없음"}
    sigs = recent_bullish_signals(ohlc)                 # 단일 캔들 신호
    multi = cp.detect_multi(ohlc, lookback=LOOKBACK)    # 다중 캔들 패턴
    trend = _trend_of([float(c) for c in df["Close"]])
    last = ohlc[-1]
    parts = [_fmt_signals(sigs)] if sigs else []
    parts += [f"{m['pattern']}@D-{m['offset']}" for m in multi]
    return {
        "ticker": ticker,
        "pass": bool(sigs) or bool(multi),   # 단일/다중 신호 중 하나라도 (trend는 표시용)
        "n_signals": len(sigs) + len(multi),
        "trend": trend,
        "recent_signals": ", ".join(parts) if parts else "-",
        "last_candle": ",".join(cp.detect(*last)) or "-",
    }


def latest_pullback():
    fs = [f for f in glob.glob(os.path.join(OUT, "pullback_*.csv"))
          if re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(f))]
    return sorted(fs)[-1] if fs else None


def main():
    args = sys.argv[1:]
    if args:
        tickers, date = args, "adhoc"
    else:
        path = latest_pullback()
        if not path:
            sys.exit("[오류] pullback_<date>.csv 없음. 본장 스캔 먼저 실행.")
        date = re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(path)).group(1)
        tickers = list(pd.read_csv(path)["ticker"])

    print(f"[캔들 교차검증] {len(tickers)}종목 (yfinance 최근 일봉, 최근 {LOOKBACK}일 모양)  기준일 {date}")
    rows = [evaluate_ticker(t) for t in tickers]
    ok = [r for r in rows if "error" not in r]
    err = [r for r in rows if "error" in r]

    res = pd.DataFrame(ok).sort_values("n_signals", ascending=False) if ok else pd.DataFrame()
    if date != "adhoc":
        res.to_csv(os.path.join(OUT, f"candle_verified_{date}.csv"), index=False, encoding="utf-8-sig")

    print("\n" + "=" * 84)
    print(f"  캔들 시그널·모양 교차검증 (PASS=최근 {LOOKBACK}일 상승캔들)  +  추세 표시")
    print("=" * 84)
    if not res.empty:
        print(res[["ticker", "pass", "trend", "n_signals", "recent_signals", "last_candle"]].to_string(index=False))
        passed = res[res["pass"] == True]["ticker"].tolist()
        print("-" * 84)
        print(f"  통과(캔들신호): {len(passed)}/{len(ok)}  →  {', '.join(passed) if passed else '없음'}")
    if err:
        print("  조회실패: " + ", ".join(f"{e['ticker']}({e['error']})" for e in err))
    print("=" * 84)
    print("  ※ trend(상승/하락/횡보)는 참고용 — PASS를 강제하지 않음. 캔들이론상 하락세 '바닥'")
    print("    반등도 유효하므로 추세는 회원이 직접 판단(원전도 멀티TF 재량). 상승/횡보가 유리.")


if __name__ == "__main__":
    main()
