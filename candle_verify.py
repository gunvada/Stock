# -*- coding: utf-8 -*-
"""
캔들-베이스 교차검증 레이어  (본장 후보 → 캔들이론으로 재검증·축소)
====================================================================
거래량 폭증 눌림목 후보(pullback_<date>.csv)를 캔들매매 이론
(docs/STRATEGY_NOTES.md)으로 교차검증해 '둘 다 만족하는' 소수만 남긴다.
→ 후보 축소 + 신뢰성 확보. 데이터는 yfinance 다년 일봉(API 키 불필요).

캔들이론 정량 체크(각 0/1, 합 0~5점):
  1) enough_history : 상장기간 충분(바 수 ≥ MIN_BARS)        ← 해석제외 #4
  2) deep_decline   : 현재가 ≤ 기간고점×(1-DECLINE)          ← 큰 하락 구간
  3) near_base      : 현재가 ≤ 기간저점×NEAR_BASE_MULT        ← 해석제외 #1·#6(베이스 근처)
  4) sideways_base  : 베이스 구간 종가 max/min ≤ SIDEWAYS     ← 수평적 파동
  5) bullish_candle : 최근 일봉이 상승성질 캔들               ← 캔들 신호(candle_patterns)

PASS 기준: 점수 ≥ PASS_MIN (기본 4). 임계값은 모두 튜닝 가능.

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

# 임계값 (튜닝 가능)
MIN_BARS = 500            # ≈ 2년
DECLINE_FROM_HIGH = 0.5   # 현재가 ≤ 고점의 50%
NEAR_BASE_MULT = 1.5      # 현재가 ≤ 저점 ×1.5 (저점 대비 +50% 이내)
SIDEWAYS_MAX_RATIO = 3.0  # 베이스 구간 종가 max/min
BASE_WINDOW = 252         # 베이스 판단 구간(≈1년)
RECENT_EXCLUDE = 10       # 베이스 판단 시 최근 N봉(급등) 제외
PASS_MIN = 4              # PASS 점수 기준


def score_candle_base(m):
    """metrics dict → (checks dict, score). 순수 함수(테스트 용이)."""
    checks = {
        "enough_history": m["bars"] >= MIN_BARS,
        "deep_decline": m["hi_all"] > 0 and m["last"] <= m["hi_all"] * (1 - DECLINE_FROM_HIGH),
        "near_base": m["lo_all"] > 0 and m["last"] <= m["lo_all"] * NEAR_BASE_MULT,
        "sideways_base": m["base_ratio"] is not None and m["base_ratio"] <= SIDEWAYS_MAX_RATIO,
        "bullish_candle": bool(m["bullish"]),
    }
    return checks, sum(1 for v in checks.values() if v)


def _metrics_from_df(df):
    """yfinance 일봉 DataFrame → metrics dict."""
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    bars = len(df)
    if bars == 0:
        return None
    hi_all = float(df["High"].max())
    lo_all = float(df["Low"].min())
    last = float(df["Close"].iloc[-1])
    # 베이스 구간: 최근 RECENT_EXCLUDE봉(급등) 제외 후 마지막 BASE_WINDOW봉
    base = df.iloc[:-RECENT_EXCLUDE] if bars > RECENT_EXCLUDE else df
    base = base.tail(BASE_WINDOW)
    base_ratio = None
    if len(base) >= 20:
        cmin = float(base["Close"].min())
        if cmin > 0:
            base_ratio = float(base["Close"].max()) / cmin
    o, h, l, c = (float(df[k].iloc[-1]) for k in ["Open", "High", "Low", "Close"])
    return {
        "bars": bars, "hi_all": hi_all, "lo_all": lo_all, "last": last,
        "base_ratio": base_ratio,
        "from_low_mult": (last / lo_all) if lo_all > 0 else None,
        "down_from_high_%": (1 - last / hi_all) * 100 if hi_all > 0 else None,
        "bullish": cp.has_bullish_signal(o, h, l, c),
        "candle": ",".join(cp.detect(o, h, l, c)) or "-",
    }


def evaluate_ticker(ticker):
    """yfinance 3년 일봉으로 캔들-베이스 점수 산출."""
    import yfinance as yf
    try:
        df = yf.Ticker(ticker).history(period="3y", interval="1d", auto_adjust=False)
    except Exception as e:
        return {"ticker": ticker, "error": f"{type(e).__name__}: {str(e)[:60]}"}
    if df is None or df.empty:
        return {"ticker": ticker, "error": "데이터 없음"}
    m = _metrics_from_df(df)
    if m is None:
        return {"ticker": ticker, "error": "유효 일봉 없음"}
    checks, score = score_candle_base(m)
    return {
        "ticker": ticker, "score": score, "pass": score >= PASS_MIN,
        "bars": m["bars"],
        "down_from_high_%": round(m["down_from_high_%"], 0) if m["down_from_high_%"] is not None else None,
        "from_low_x": round(m["from_low_mult"], 1) if m["from_low_mult"] is not None else None,
        "base_ratio": round(m["base_ratio"], 1) if m["base_ratio"] is not None else None,
        "candle": m["candle"],
        **{k: int(v) for k, v in checks.items()},
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

    print(f"[교차검증] {len(tickers)}종목 (yfinance 3년 일봉)  기준일 {date}")
    rows = [evaluate_ticker(t) for t in tickers]
    ok = [r for r in rows if "error" not in r]
    err = [r for r in rows if "error" in r]

    res = pd.DataFrame(ok).sort_values("score", ascending=False) if ok else pd.DataFrame()
    if date != "adhoc":
        res.to_csv(os.path.join(OUT, f"candle_verified_{date}.csv"), index=False, encoding="utf-8-sig")

    print("\n" + "=" * 84)
    print(f"  캔들-베이스 교차검증 (PASS 기준 점수 ≥ {PASS_MIN}/5)")
    print("=" * 84)
    if not res.empty:
        show = ["ticker", "score", "pass", "down_from_high_%", "from_low_x", "base_ratio",
                "candle", "enough_history", "deep_decline", "near_base", "sideways_base", "bullish_candle"]
        print(res[show].to_string(index=False))
        passed = res[res["pass"] == True]["ticker"].tolist()
        print("-" * 84)
        print(f"  통과(둘 다 만족): {len(passed)}/{len(ok)}  →  {', '.join(passed) if passed else '없음'}")
    if err:
        print("  조회실패: " + ", ".join(f"{e['ticker']}({e['error']})" for e in err))
    print("=" * 84)
    print("  ※ 거래량폭증(본장)과 캔들베이스는 철학이 달라 통과가 적은 게 정상.")
    print("    통과 0이면 '오늘 surge 후보 중 캔들베이스 적합 종목 없음'이라는 유의미한 신호.")


if __name__ == "__main__":
    main()
