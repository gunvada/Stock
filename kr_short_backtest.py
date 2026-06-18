# -*- coding: utf-8 -*-
"""
일봉 단기 셋업 백테스트 (KR Daily Short-hold Backtest)
=======================================================
kr_short_scan.py 의 '일봉' 셋업(거래량 폭증 ∩ 상승 캔들신호 ∩ 일봉 베이스 후반부)을
**짧은 보유(단타~단기 스윙)** 로 검증한다. look-ahead 없음. 데이터: yfinance.

현실적 진입 가정 (중요):
  신호일 D 의 폭증·캔들은 **D 종가에 확정**된다. 그런데 신호가 +30% 상한가 종가에
  뜨면 그 종가엔 매수 불가 → **다음날 D+1 시초가에 추격 진입**이 현실적이다.
  따라서 진입가 = D+1 시가. 성과 = (D+1+h 종가 / D+1 시가 − 1).
  (즉, 신호 다음날 갭은 '못 먹는' 구간이며, 추격의 실제 손익만 측정한다.)

보유 horizon: 당일(D+1 시→종) · +3 · +5 · +10 · +20 거래일.
판정 전부 D 시점까지 정보로만(미래참조 차단). 베이스는 D 이전 일봉으로 판정.

⚠ 생존편향(상장폐지 누락→과대평가) + 거래비용 미반영 + 단일 유니버스/기간. 매매 신호 아님.
"""

import sys
import datetime as dt
from statistics import median

import pandas as pd

import candle_patterns as cp
import wave_base as wb

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

LOOKBACK = 7
WATCH_X = 8.0
MIN_BASELINE_VOL = 5000
BASE_MIN_BARS = 120      # 일봉 베이스 최소(≈6개월)
BASE_WINDOW = 60         # 수평성 판단(≈3개월)
HOLDS = [1, 3, 5, 10, 20]   # D+1 시초가 진입 후 보유 거래일
MAX_H = max(HOLDS)
COOLDOWN = 10
UNIVERSE_TOP = 150
YEARS = "3y"
CHUNK = 50


def get_universe(n):
    import FinanceDataReader as fdr
    lst = fdr.StockListing("KRX")
    lst = lst[lst["Market"].isin(["KOSPI", "KOSDAQ"])]
    lst = lst[lst["Code"].str.endswith("0")]
    lst = lst.sort_values("Volume", ascending=False).head(n)
    suf = {"KOSPI": ".KS", "KOSDAQ": ".KQ"}
    rows = [(c + suf[m], nm) for c, m, nm in zip(lst["Code"], lst["Market"], lst["Name"])]
    return [r[0] for r in rows], dict(rows)


def download(syms, period, chunk):
    import yfinance as yf
    data = {}
    for i in range(0, len(syms), chunk):
        part = syms[i:i + chunk]
        try:
            raw = yf.download(part, period=period, interval="1d", auto_adjust=True,
                              progress=False, group_by="ticker", threads=True)
        except Exception:
            continue
        for sm in part:
            try:
                sub = raw[sm].dropna(subset=["Open", "High", "Low", "Close", "Volume"])
                if len(sub) > BASE_MIN_BARS + MAX_H + 10:
                    data[sm] = sub
            except Exception:
                pass
        print(f"  ...{min(i+chunk,len(syms))}/{len(syms)} (누적 {len(data)})")
    return data


def scan_ticker(sym, df):
    df = df.reset_index()
    o = df["Open"].values; h = df["High"].values
    l = df["Low"].values;  c = df["Close"].values; v = df["Volume"].values
    dates = pd.to_datetime(df.iloc[:, 0])
    n = len(c)
    out = []
    last_entry = -10 ** 9
    for i in range(BASE_MIN_BARS, n - MAX_H - 1):   # D+1 진입 + 최대보유 여유
        if i - last_entry < COOLDOWN:
            continue
        prior = v[i - LOOKBACK:i]
        base_v = median(prior) if len(prior) else 0
        if base_v < MIN_BASELINE_VOL or base_v <= 0:
            continue
        if v[i] / base_v < WATCH_X:
            continue
        if not cp.has_bullish_signal(o[i], h[i], l[i], c[i]):
            continue
        b = wb.classify_base(h[:i + 1].tolist(), l[:i + 1].tolist(), c[:i + 1].tolist(),
                             min_bars=BASE_MIN_BARS, base_window=BASE_WINDOW)
        if b["label"] == "과상승" or not b["is_base"]:
            continue
        entry = o[i + 1]            # D+1 시초가 추격 진입
        if entry <= 0:
            continue
        rec = {"sym": sym, "date": dates.iloc[i].date(),
               "gap_%": round((o[i + 1] / c[i] - 1) * 100, 1),   # 신호 다음날 갭(못 먹는 구간)
               "base": b["label"]}
        for hh in HOLDS:
            j = i + hh             # 진입(i+1) 기준 보유 hh-1일 뒤? -> 통일: D+hh 종가
            rec[f"h{hh}_%"] = round((c[i + 1 + (hh - 1)] / entry - 1) * 100, 1) if (i + hh) < n else None
        end = min(i + 1 + MAX_H, n - 1)
        win = c[i + 1:end + 1]
        if len(win):
            rec["MFE_%"] = round((win.max() / entry - 1) * 100, 1)
            rec["MAE_%"] = round((win.min() / entry - 1) * 100, 1)
        out.append(rec)
        last_entry = i
    return out


def summarize(s):
    s = s.dropna()
    if s.empty:
        return None
    return {"n": len(s), "mean": round(s.mean(), 1), "median": round(s.median(), 1),
            "win": round((s > 0).mean() * 100, 0)}


def main():
    print(f"[1/3] 유니버스 (FDR 거래량 상위 {UNIVERSE_TOP})...")
    syms, names = get_universe(UNIVERSE_TOP)
    print(f"[2/3] yfinance {YEARS} 일봉 ({len(syms)} 종목)...")
    data = download(syms, YEARS, CHUNK)
    if not data:
        sys.exit("[오류] 데이터 수집 실패.")
    print(f"[3/3] 일봉 셋업 신호 스캔 + D+1 시초가 진입 성과 ({len(data)} 종목)...")
    rows = []
    for sym, df in data.items():
        try:
            rows.extend(scan_ticker(sym, df))
        except Exception:
            pass
    if not rows:
        print("  신호 없음.")
        return
    res = pd.DataFrame(rows)
    res["name"] = res["sym"].map(names)
    stamp = dt.date.today().isoformat()
    out_path = f"output/kr_short_backtest_{stamp}.csv"
    res.to_csv(out_path, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 80)
    print(f"  일봉 단기 셋업 백테스트  (신호 {len(res)}건 · 종목 {res['sym'].nunique()} · {YEARS})")
    print("  셋업=폭증∩상승캔들∩일봉베이스 후반부, 진입=D+1 시초가(추격), look-ahead 차단")
    print("=" * 80)
    g = summarize(res["gap_%"])
    if g:
        print(f"  신호 다음날 갭(못 먹는 구간): 평균 {g['mean']}% / 중앙 {g['median']}%")
    print("  " + "-" * 66)
    print(f"  {'보유':>6} | {'n':>4} {'평균%':>7} {'중앙%':>7} {'승률%':>6}")
    print("  " + "-" * 66)
    for hh in HOLDS:
        s = summarize(res[f"h{hh}_%"])
        if s:
            lbl = "D+1(당일)" if hh == 1 else f"D+{hh}"
            print(f"  {lbl:>6} | {s['n']:>4} {s['mean']:>7} {s['median']:>7} {s['win']:>6}")
    print("  " + "-" * 66)
    mfe = summarize(res["MFE_%"]); mae = summarize(res["MAE_%"])
    if mfe and mae:
        print(f"  보유20일 최대상승(MFE) 평균 {mfe['mean']}% / 중앙 {mfe['median']}%")
        print(f"  보유20일 최대하락(MAE) 평균 {mae['mean']}% / 중앙 {mae['median']}%  (손절 기준 참고)")
    print("-" * 80)
    print(f"  저장: {out_path}")
    print("=" * 80)
    print("  ⚠ 생존편향(상폐 누락→과대평가)+거래비용 미반영. D+1 갭은 진입가에 이미 반영(못 먹음).")
    print("    중앙값<0 이면 '추격 단타'는 전형적으로 손실 — 손절/승자보유 규칙 없이는 위험.")


if __name__ == "__main__":
    main()
