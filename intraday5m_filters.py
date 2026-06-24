# -*- coding: utf-8 -*-
"""
5분봉 인트라데이 — 맥락 필터 & 신호 선별 비교 하니스
=====================================================
intraday5m_backtest의 단순 신호(엣지 없음)에 '맥락 필터'와 '신호 선별'을 적용해
어떤 조합이 엣지를 살리는지 한 번에 비교한다. (캔들이론: 형태보다 위치/맥락)

맥락 필터:
  · first_hour : 개장 후 첫 1시간(09:30~10:30)에 난 신호만
  · above_vwap : 신호봉 종가가 당일 VWAP 위
  · vol_surge  : 신호봉 거래량이 직전 평균의 K배 이상
신호 선별(mode):
  · single     : 단일 상승 캔들(기준선)
  · consecutive: 2봉 연속 상승 캔들
  · multi      : 다중 패턴(상승펀치/상승다람쥐/양봉팽이군/꼬리군)이 신호봉에서 완성

데이터: yfinance 5분봉(60일, 정규장). API 키 불필요.
사용법: python intraday5m_filters.py [N=12] [tp=5] [sl=3]
"""
import os
import sys

import pandas as pd

import candle_patterns as cp
from intraday5m_backtest import load_universe, stats

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
VOL_SURGE_K = 2.0      # 거래량 급증 배수
VOL_M = 12             # 거래량 비교 구간(직전 12봉=1시간)
FIRST_HOUR_BARS = 12   # 개장 후 첫 1시간 = 5분봉 12개


def enrich_day(raw):
    """raw: [(o,h,l,c,vol), ...] 정규장 순서 → 봉별 dict(vwap·first_hour·vol_surge) + ohlc.
    순수 함수."""
    dicts, ohlc = [], []
    cum_pv = cum_v = 0.0
    vols = []
    for i, (o, h, l, c, v) in enumerate(raw):
        v = max(0.0, float(v or 0))
        typ = (h + l + c) / 3
        cum_pv += typ * v
        cum_v += v
        vwap = (cum_pv / cum_v) if cum_v > 0 else c
        if len(vols) >= 3:
            s = sorted(vols[-VOL_M:])
            med = s[len(s) // 2]
            vs = med > 0 and v >= VOL_SURGE_K * med
        else:
            vs = False
        dicts.append({"c": c, "vwap": vwap, "fh": i < FIRST_HOUR_BARS, "vs": bool(vs)})
        ohlc.append((o, h, l, c))
        vols.append(v)
    return dicts, ohlc


def signal_at(ohlc, i, mode):
    """신호봉 판정(순수). offset 0 = 신호가 i봉에서 완성."""
    o, h, l, c = ohlc[i]
    if mode == "single":
        return cp.has_bullish_signal(o, h, l, c)
    if mode == "consecutive":
        if not cp.has_bullish_signal(o, h, l, c):
            return False
        if i < 1:
            return False
        return cp.has_bullish_signal(*ohlc[i - 1])
    if mode == "multi":
        w = ohlc[max(0, i - 5):i + 1]
        return any(m["offset"] == 0 for m in cp.detect_multi(w, lookback=6))
    raise ValueError(mode)


def context_ok(bar, filters):
    """맥락 필터 통과 여부(순수)."""
    if filters.get("first_hour") and not bar["fh"]:
        return False
    if filters.get("above_vwap") and not (bar["c"] >= bar["vwap"]):
        return False
    if filters.get("vol_surge") and not bar["vs"]:
        return False
    return True


def simulate_f(dicts, ohlc, tp_pct, sl_pct, mode, filters):
    """필터 적용 인트라데이 시뮬 → gross 수익률 리스트(순수)."""
    n = len(ohlc)
    trades, i = [], 0
    while i < n - 1:
        if signal_at(ohlc, i, mode) and context_ok(dicts[i], filters):
            entry = ohlc[i + 1][0]
            if entry <= 0:
                i += 1
                continue
            tp_px, sl_px = entry * (1 + tp_pct / 100), entry * (1 - sl_pct / 100)
            ret, j = None, i + 1
            while j < n:
                _, bh, bl, bc = ohlc[j]
                if bl <= sl_px:
                    ret = -sl_pct
                    break
                if bh >= tp_px:
                    ret = tp_pct
                    break
                j += 1
            if ret is None:
                ret = (ohlc[-1][3] - entry) / entry * 100
                j = n - 1
            trades.append(ret)
            i = j + 1
        else:
            i += 1
    return trades


def fetch_days_ohlcv(ticker):
    """yfinance 5분봉 → {날짜: [(o,h,l,c,vol),...]} 정규장만(NY tz)."""
    import yfinance as yf
    try:
        df = yf.Ticker(ticker).history(period="60d", interval="5m",
                                       prepost=False, auto_adjust=False)
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df = df.set_index(df.index.tz_convert("America/New_York")).between_time("09:30", "15:55")
    days = {}
    for d, g in df.groupby(df.index.strftime("%Y-%m-%d")):
        days[d] = [tuple(float(x) for x in row)
                   for row in zip(g["Open"], g["High"], g["Low"], g["Close"], g["Volume"])]
    return days


# 비교할 설정들
CONFIGS = [
    ("기준(single)",            "single",      {}),
    ("+첫1시간",                "single",      {"first_hour": True}),
    ("+VWAP위",                 "single",      {"above_vwap": True}),
    ("+거래량급증",             "single",      {"vol_surge": True}),
    ("연속신호",                "consecutive", {}),
    ("다중패턴",                "multi",       {}),
    ("다중+VWAP+첫1시간",       "multi",       {"above_vwap": True, "first_hour": True}),
    ("다중+VWAP+거래량+첫1시간", "multi",      {"above_vwap": True, "vol_surge": True, "first_hour": True}),
]


def main():
    nums = [a for a in sys.argv[1:] if a.replace(".", "").isdigit()]
    top_n = int(nums[0]) if nums else 12
    tp = float(nums[1]) if len(nums) > 1 else 5.0
    sl = float(nums[2]) if len(nums) > 2 else 3.0

    universe = load_universe(top_n)
    print(f"[5분봉 필터 비교] 종목 {len(universe)} · TP+{tp:.0f}/SL-{sl:.0f} · 당일청산 · 데이터 수집중...")
    data = []   # (dicts, ohlc) per day
    fetched = 0
    for t in universe:
        days = fetch_days_ohlcv(t)
        if days:
            fetched += 1
        for d, raw in days.items():
            data.append(enrich_day(raw))
    print(f"  조회성공 {fetched}/{len(universe)}종목 · 거래일 {len(data)}\n")

    rows = []
    for label, mode, filt in CONFIGS:
        rets = []
        for dicts, ohlc in data:
            rets += simulate_f(dicts, ohlc, tp, sl, mode, filt)
        st = stats(rets)
        if not st:
            rows.append({"설정": label, "거래": 0, "승률%": "-", "gross%": "-", "net@1%": "-", "net@2%": "-"})
            continue
        rows.append({"설정": label, "거래": st["n"], "승률%": st["win_%"],
                     "gross%": st["avg_%"], "net@1%": round(st["avg_%"] - 1, 2),
                     "net@2%": round(st["avg_%"] - 2, 2)})

    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(OUT, "intraday5m_filter_compare.csv"), index=False, encoding="utf-8-sig")
    print("=" * 84)
    print("  설정별 비교 (gross=비용0 평균수익률, net@x=비용 x% 차감)")
    print("=" * 84)
    print(res.to_string(index=False))
    print("=" * 84)
    print("  ※ 거래수↓ 신뢰성 주의. gross가 +로 의미있게 올라가는 필터가 '맥락'이 먹힌다는 신호.")


if __name__ == "__main__":
    main()
