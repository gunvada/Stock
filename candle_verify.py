# -*- coding: utf-8 -*-
"""
캔들 교차검증 레이어  (본장 후보 → '캔들 시그널·모양'으로 재검증·축소)
====================================================================
거래량 폭증 눌림목 후보(pullback_<date>.csv)를, 위치/베이스 지표는 보지 않고
**오로지 캔들 시그널과 모양**으로 교차검증한다 — 최근 N거래일 일봉 중
상승 성질 캔들(양봉스프링·위꼬리양봉·양봉팽이/긴위아래꼬리 작은양봉 등)이
출현했는지 본다. 데이터는 yfinance 최근 일봉(API 키 불필요).

PASS = 최근 LOOKBACK일 안에 상승 캔들 신호/모양이 하나라도 출현.
(저점대비 배수·베이스비율·깊은하락 등 위치 지표는 사용하지 않음 — 사용자 정의)

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
LOOKBACK = 5   # 최근 며칠 봉에서 '모양'을 찾을지 (튜닝 가능)


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


def evaluate_ticker(ticker):
    """yfinance 최근 일봉으로 '캔들 시그널·모양'만 평가."""
    import yfinance as yf
    try:
        df = yf.Ticker(ticker).history(period="3mo", interval="1d", auto_adjust=False)
    except Exception as e:
        return {"ticker": ticker, "error": f"{type(e).__name__}: {str(e)[:60]}"}
    if df is None or df.empty:
        return {"ticker": ticker, "error": "데이터 없음"}
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    ohlc = list(zip(df["Open"], df["High"], df["Low"], df["Close"]))
    ohlc = [tuple(float(x) for x in row) for row in ohlc]
    if not ohlc:
        return {"ticker": ticker, "error": "유효 일봉 없음"}
    sigs = recent_bullish_signals(ohlc)
    last = ohlc[-1]
    return {
        "ticker": ticker,
        "pass": bool(sigs),
        "n_signals": len(sigs),
        "recent_signals": _fmt_signals(sigs),
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

    print("\n" + "=" * 80)
    print(f"  캔들 시그널·모양 교차검증 (최근 {LOOKBACK}일 내 상승 캔들 출현 = PASS)")
    print("=" * 80)
    if not res.empty:
        print(res[["ticker", "pass", "n_signals", "recent_signals", "last_candle"]].to_string(index=False))
        passed = res[res["pass"] == True]["ticker"].tolist()
        print("-" * 80)
        print(f"  통과(캔들신호 있음): {len(passed)}/{len(ok)}  →  {', '.join(passed) if passed else '없음'}")
    if err:
        print("  조회실패: " + ", ".join(f"{e['ticker']}({e['error']})" for e in err))
    print("=" * 80)
    print("  ※ 위치/베이스 지표는 보지 않음. 오로지 상승 캔들 시그널·모양 기준.")


if __name__ == "__main__":
    main()
