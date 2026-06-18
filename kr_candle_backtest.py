# -*- coding: utf-8 -*-
"""
PRIME 셋업 백테스트 (KR Candle/Wave PRIME Backtest)
=====================================================
kr_candle_verify 의 'PRIME' 셋업(거래량 폭증 ∩ 상승 캔들신호 ∩ 다년 베이스
후반부)이 캔들이론 주장대로 중장기(+100~200%)로 가는지 한국 과거 데이터로
look-ahead 없이 검증한다. 데이터: yfinance(.KS/.KQ), 유니버스: FinanceDataReader.

신호일 D 기준 (전부 D '시점까지'의 정보로만 판정 — 미래참조 없음):
  1) 거래량 폭증 : vol[D] / median(직전 LOOKBACK일) ≥ WATCH_X
  2) 상승 캔들   : candle_patterns 가 D 봉에서 상승 신호 탐지
  3) 다년 베이스 : D 이전까지 완성된 주봉으로 wave_base = 베이스(근접/완만) & 과상승 아님
진입: D 종가.  성과: D+h 종가/ D 종가 (h=20/60/120/250 거래일) + 최대상승(MFE)·최대하락(MAE).

⚠ 한계: yfinance 는 '현재 상장' 종목만 → 상장폐지 종목 누락(생존편향, 성과 과대평가).
   거래비용 미반영. 특정 유니버스·기간 결과일 뿐 미래 보장 아님. 매매 신호 아님.
"""

import sys
import datetime as dt
from statistics import median, mean

import numpy as np
import pandas as pd

import candle_patterns as cp
import wave_base as wb

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

LOOKBACK = 7              # 거래량 비교 거래일
WATCH_X = 10.0           # 폭증 기준 배율
MIN_BASELINE_VOL = 30000
HORIZONS = [20, 60, 120, 250]   # forward 성과 측정 지점(거래일)
MAX_H = max(HORIZONS)
COOLDOWN = 20            # 같은 종목 재진입 최소 간격(거래일)
UNIVERSE_TOP = 150       # FDR 거래량 상위 N 종목으로 제한(런타임)
YEARS = "6y"
CHUNK = 50


def get_universe(n):
    import FinanceDataReader as fdr
    lst = fdr.StockListing("KRX")
    lst = lst[lst["Market"].isin(["KOSPI", "KOSDAQ"])]
    lst = lst[lst["Code"].str.endswith("0")]
    lst = lst.sort_values("Volume", ascending=False).head(n)
    suf = {"KOSPI": ".KS", "KOSDAQ": ".KQ"}
    syms = [c + suf[m] for c, m in zip(lst["Code"], lst["Market"])]
    names = dict(zip([c + suf[m] for c, m in zip(lst["Code"], lst["Market"])], lst["Name"]))
    return syms, names


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
                if len(sub) > 300:
                    data[sm] = sub
            except Exception:
                pass
        print(f"  ...{min(i+chunk,len(syms))}/{len(syms)} 수신 (누적 {len(data)})")
    return data


def scan_ticker(sym, df):
    """한 종목의 과거 전체를 훑어 PRIME 신호일과 forward 성과를 수집."""
    df = df.reset_index()
    n = len(df)
    o = df["Open"].values; h = df["High"].values
    l = df["Low"].values;  c = df["Close"].values
    v = df["Volume"].values
    dates = pd.to_datetime(df.iloc[:, 0])  # 첫 컬럼 = Date

    # 주봉(베이스용) — 일봉에서 리샘플(주 종료 일요일 라벨)
    wk = df.set_index(dates)[["High", "Low", "Close"]].resample("W").agg(
        {"High": "max", "Low": "min", "Close": "last"}).dropna()

    out = []
    last_entry = -10 ** 9
    # i: 신호일. 베이스 판정 위해 충분한 과거 + forward 최소 1개 horizon 필요
    start = max(LOOKBACK + 1, 60)
    for i in range(start, n - HORIZONS[0]):
        if i - last_entry < COOLDOWN:
            continue
        # 1) 거래량 폭증 (직전 LOOKBACK일 중앙값)
        prior = v[i - LOOKBACK:i]
        base_v = median(prior) if len(prior) else 0
        if base_v < MIN_BASELINE_VOL or base_v <= 0:
            continue
        if v[i] / base_v < WATCH_X:
            continue
        # 2) 상승 캔들 신호 (D 봉)
        if not cp.has_bullish_signal(o[i], h[i], l[i], c[i]):
            continue
        # 3) 다년 베이스 — D 이전 '완성된' 주봉만(미래참조 차단)
        wkx = wk[wk.index <= dates.iloc[i]]
        if len(wkx) < wb.MIN_BARS:
            continue
        b = wb.classify_base(wkx["High"].tolist(), wkx["Low"].tolist(), wkx["Close"].tolist())
        if not b["is_base"]:
            continue
        # PRIME 진입(D 종가). forward 성과
        entry = c[i]
        rec = {"sym": sym, "date": dates.iloc[i].date(), "entry": round(float(entry), 1),
               "base": b["label"], "drop_peak_%": b["drop_peak_%"]}
        for hh in HORIZONS:
            j = i + hh
            rec[f"r{hh}_%"] = round((c[j] / entry - 1) * 100, 1) if j < n else None
        # 최대 상승/하락(보유 250일 내)
        end = min(i + MAX_H, n - 1)
        window = c[i + 1:end + 1]
        if len(window):
            rec["MFE_%"] = round((window.max() / entry - 1) * 100, 1)
            rec["MAE_%"] = round((window.min() / entry - 1) * 100, 1)
        out.append(rec)
        last_entry = i
    return out


def summarize(df, col):
    s = df[col].dropna()
    if s.empty:
        return None
    wins = (s > 0).mean() * 100
    return {
        "n": len(s),
        "mean_%": round(s.mean(), 1),
        "median_%": round(s.median(), 1),
        "win_%": round(wins, 0),
        ">=+50%": int((s >= 50).sum()),
        ">=+100%": int((s >= 100).sum()),
        ">=+200%": int((s >= 200).sum()),
    }


def main():
    print(f"[1/3] 유니버스 수집 (FDR 거래량 상위 {UNIVERSE_TOP})...")
    syms, names = get_universe(UNIVERSE_TOP)
    print(f"[2/3] yfinance {YEARS} 일봉 수집 ({len(syms)} 종목)...")
    data = download(syms, YEARS, CHUNK)
    if not data:
        sys.exit("[오류] 데이터 수집 실패.")

    print(f"[3/3] PRIME 신호 스캔 + forward 성과 ({len(data)} 종목, look-ahead 차단)...")
    rows = []
    for sym, df in data.items():
        try:
            rows.extend(scan_ticker(sym, df))
        except Exception as e:
            print(f"  [{sym}] 스킵: {type(e).__name__}")
    if not rows:
        print("  PRIME 신호가 없습니다. (희귀 셋업 + 생존편향 유니버스 한계)")
        return

    res = pd.DataFrame(rows)
    res["name"] = res["sym"].map(names)
    stamp = dt.date.today().isoformat()
    out_path = f"output/kr_prime_backtest_{stamp}.csv"
    res.to_csv(out_path, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 84)
    print(f"  PRIME 셋업 백테스트  (신호 {len(res)}건 · 종목 {res['sym'].nunique()} · 유니버스 {len(data)} · {YEARS})")
    print("  PRIME = 거래량폭증 ∩ 상승캔들 ∩ 다년베이스 후반부 (D종가 진입, look-ahead 차단)")
    print("=" * 84)
    print(f"  {'horizon':>8} | {'n':>4} {'평균%':>7} {'중앙%':>7} {'승률%':>6} | {'≥+50':>5} {'≥+100':>6} {'≥+200':>6}")
    print("  " + "-" * 70)
    for hh in HORIZONS:
        s = summarize(res, f"r{hh}_%")
        if s:
            print(f"  {('D+'+str(hh)):>8} | {s['n']:>4} {s['mean_%']:>7} {s['median_%']:>7} "
                  f"{s['win_%']:>6} | {s['>=+50%']:>5} {s['>=+100%']:>6} {s['>=+200%']:>6}")
    mfe = summarize(res, "MFE_%"); mae = res["MAE_%"].dropna()
    print("  " + "-" * 70)
    if mfe:
        print(f"  보유250일 최대상승(MFE) 평균 {mfe['mean_%']}% / 중앙 {mfe['median_%']}% "
              f"| +100%도달 {mfe['>=+100%']}건 / +200% {mfe['>=+200%']}건")
    if not mae.empty:
        print(f"  보유250일 최대하락(MAE) 평균 {mae.mean():.1f}% / 중앙 {mae.median():.1f}% (손절 필요성)")
    print("-" * 84)
    print(f"  저장: {out_path}")
    print("=" * 84)
    print("  ⚠ 생존편향(상장폐지 종목 누락→과대평가) + 거래비용 미반영 + 단일 유니버스/기간.")
    print("    이론의 '+100~200%'는 MFE(최대상승)·장기보유 가정이며, 고정 horizon 성과와 구분할 것.")
    print("    매매 신호 아님 — 분할매수·손절(MAE 참고)·위치 재확인은 본인 판단.")


if __name__ == "__main__":
    main()
