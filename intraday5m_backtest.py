# -*- coding: utf-8 -*-
"""
5분봉 인트라데이 백테스트 (당일 청산, 오버나잇 없음)  — 페니주 단타 검증
=========================================================================
캔들 신호(candle_patterns)를 **5분봉**에 적용해, 신호 → 다음 봉 진입 →
당일 TP/SL 또는 종가 청산했을 때의 수익을 검증한다. 회원 조건(최대 1일 이내)에 부합.

데이터: yfinance 5분봉(최근 ~60일, 정규장 09:30~16:00 ET). API 키 불필요.
유니버스: 기존 백테스트 종목(pullback_backtest_detail.csv) 상위 N개(기본 20).

페니주 스프레드가 결정적이므로 **비용 0/1/2/3% 민감도**를 함께 출력한다.

사용법:
  python intraday5m_backtest.py [N=20] [tp=5] [sl=3]
"""
import os
import re
import sys

import pandas as pd

import candle_patterns as cp

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
DETAIL = os.path.join(OUT, "pullback_backtest_detail.csv")


def simulate_intraday(day_bars, tp_pct, sl_pct):
    """하루치 5분봉 [(o,h,l,c),...] → 거래별 gross 수익률 리스트 (순수 함수).
    상승 캔들 신호봉 다음 봉 시가 진입, 같은날 TP/SL 터치(보수적 손절우선) or 종가 청산.
    한 번에 한 포지션, 청산 후 이어서 스캔."""
    n = len(day_bars)
    trades = []
    i = 0
    while i < n - 1:
        o, h, l, c = day_bars[i]
        if cp.has_bullish_signal(o, h, l, c):
            entry = day_bars[i + 1][0]
            if entry <= 0:
                i += 1
                continue
            tp_px, sl_px = entry * (1 + tp_pct / 100), entry * (1 - sl_pct / 100)
            ret, j = None, i + 1
            while j < n:
                _, bh, bl, bc = day_bars[j]
                if bl <= sl_px:
                    ret = -sl_pct
                    break
                if bh >= tp_px:
                    ret = tp_pct
                    break
                j += 1
            if ret is None:
                ret = (day_bars[-1][3] - entry) / entry * 100
                j = n - 1
            trades.append(ret)
            i = j + 1
        else:
            i += 1
    return trades


def stats(rets):
    n = len(rets)
    if n == 0:
        return None
    wins = [r for r in rets if r > 0]
    s = sorted(rets)
    med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    return {"n": n, "win_%": round(len(wins) / n * 100, 0),
            "avg_%": round(sum(rets) / n, 2), "median_%": round(med, 2),
            "best_%": round(max(rets), 1), "worst_%": round(min(rets), 1)}


def load_universe(top_n):
    if not os.path.exists(DETAIL):
        sys.exit(f"[오류] {DETAIL} 없음.")
    d = pd.read_csv(DETAIL)
    freq = d["ticker"].value_counts()       # 자주 등장한(=자주 셋업난) 종목 우선
    return list(freq.index[:top_n])


def fetch_5m_days(ticker):
    """yfinance 5분봉 → {날짜: [(o,h,l,c),...]} (정규장만, NY tz)."""
    import yfinance as yf
    try:
        df = yf.Ticker(ticker).history(period="60d", interval="5m",
                                       prepost=False, auto_adjust=False)
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df = df.set_index(df.index.tz_convert("America/New_York"))
    df = df.between_time("09:30", "15:55")
    days = {}
    for d, g in df.groupby(df.index.strftime("%Y-%m-%d")):
        days[d] = [tuple(float(x) for x in row)
                   for row in zip(g["Open"], g["High"], g["Low"], g["Close"])]
    return days


def main():
    args = sys.argv[1:]
    nums = [a for a in args if a.replace(".", "").isdigit()]
    top_n = int(nums[0]) if len(nums) > 0 else 20
    tp = float(nums[1]) if len(nums) > 1 else 5.0
    sl = float(nums[2]) if len(nums) > 2 else 3.0

    universe = load_universe(top_n)
    print(f"[5분봉 인트라데이 BT] 종목 {len(universe)}개 · TP +{tp:.0f}% / SL -{sl:.0f}% · 당일청산")
    all_rets, per_ticker, n_days, fetched = [], [], 0, 0
    for t in universe:
        days = fetch_5m_days(t)
        if not days:
            continue
        fetched += 1
        n_days += len(days)
        rets = []
        for d, bars in days.items():
            rets += simulate_intraday(bars, tp, sl)
        all_rets += rets
        st = stats(rets)
        if st:
            per_ticker.append({"ticker": t, **st})

    print(f"  조회성공 {fetched}/{len(universe)}종목 · 거래일 {n_days} · 총 거래 {len(all_rets)}")
    ov = stats(all_rets)
    if not ov:
        print("  거래 없음."); return

    print("\n" + "=" * 78)
    print(f"  [전체] gross 평균 {ov['avg_%']:+.2f}% · 중앙 {ov['median_%']:+.2f}% · 승률 {ov['win_%']:.0f}%"
          f" · 최고 {ov['best_%']:+.0f}% / 최저 {ov['worst_%']:+.0f}%  (표본 {ov['n']})")
    print("=" * 78)
    print("  [왕복비용 민감도] — 페니주 스프레드가 핵심")
    for cost in (0, 1, 2, 3):
        net = [r - cost for r in all_rets]
        s = stats(net)
        print(f"    비용 {cost}% → 순익평균 {s['avg_%']:+.2f}% · 승률(>0) {s['win_%']:.0f}%")
    print("-" * 78)
    pt = pd.DataFrame(per_ticker).sort_values("avg_%", ascending=False)
    pt.to_csv(os.path.join(OUT, "intraday5m_by_ticker.csv"), index=False, encoding="utf-8-sig")
    print("  종목별 상위 5 / 하위 5 (gross 평균):")
    print(pt.head(5).to_string(index=False))
    print("   ...")
    print(pt.tail(5).to_string(index=False))
    print("=" * 78)
    print("  ※ gross가 +라도 비용 2~3% 넣으면 음전될 수 있음 → 페니 스프레드가 단타 성패의 핵심.")


if __name__ == "__main__":
    main()
