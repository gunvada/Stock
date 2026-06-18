# -*- coding: utf-8 -*-
"""
일봉 셋업 출구 규칙 백테스트 (KR Exit-Rule Backtest)
=====================================================
kr_short_backtest 에서 확인한 '추격 단타는 시간청산 시 중앙값 손실, 그러나 MFE 중앙
+8% / MAE 중앙 −10% 의 비대칭' 을 **출구 규칙(익절·손절·트레일링)** 으로 실제 +기대값
으로 바꿀 수 있는지 검증한다.

방법:
  1) 일봉 셋업 신호(폭증 ∩ 상승캔들 ∩ 일봉 베이스 후반부, look-ahead 차단) 수집,
     각 신호의 **진입(D+1 시가) 이후 MAXHOLD 일의 H/L/C 경로** 를 저장.
  2) 경로 위에서 출구 전략을 봉 단위로 시뮬레이션:
       · 브래킷(+TP%/−SL%)  · 트레일링(고점대비 −X%)  · 시간청산(D+N)
     같은 날 TP·SL 동시 터치는 **보수적으로 SL 우선** 가정.
  3) **왕복 거래비용 COST_RT% 차감** 후 전략별 기대값·중앙·승률·손익비(PF)·
     순차 손익곡선 MDD 비교.

⚠ 생존편향(상폐 누락→과대평가). 일봉 H/L 기반이라 장중 선후·갭은 근사. 매매 신호 아님.
"""

import sys
import datetime as dt
from statistics import median

import numpy as np
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
BASE_MIN_BARS = 120
BASE_WINDOW = 60
MAXHOLD = 20
COOLDOWN = 10
UNIVERSE_TOP = 150
YEARS = "3y"
CHUNK = 50
COST_RT = 0.7         # 왕복 거래비용(%) — 세금+수수료+슬리피지(소형주 보수적)


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
                if len(sub) > BASE_MIN_BARS + MAXHOLD + 10:
                    data[sm] = sub
            except Exception:
                pass
        print(f"  ...{min(i+chunk,len(syms))}/{len(syms)} (누적 {len(data)})")
    return data


def collect_paths(data):
    """신호별 (date, entry, H[], L[], C[]) 경로 수집. entry=D+1 시가."""
    paths = []
    for sym, df in data.items():
        df = df.reset_index()
        o = df["Open"].values; h = df["High"].values
        l = df["Low"].values;  c = df["Close"].values; v = df["Volume"].values
        dates = pd.to_datetime(df.iloc[:, 0])
        n = len(c)
        last = -10 ** 9
        for i in range(BASE_MIN_BARS, n - MAXHOLD - 1):
            if i - last < COOLDOWN:
                continue
            prior = v[i - LOOKBACK:i]
            bv = median(prior) if len(prior) else 0
            if bv < MIN_BASELINE_VOL or bv <= 0 or v[i] / bv < WATCH_X:
                continue
            if not cp.has_bullish_signal(o[i], h[i], l[i], c[i]):
                continue
            b = wb.classify_base(h[:i + 1].tolist(), l[:i + 1].tolist(), c[:i + 1].tolist(),
                                 min_bars=BASE_MIN_BARS, base_window=BASE_WINDOW)
            if b["label"] == "과상승" or not b["is_base"]:
                continue
            e = o[i + 1]
            if e <= 0:
                continue
            s = slice(i + 1, i + 1 + MAXHOLD)
            paths.append({"sym": sym, "date": dates.iloc[i].date(), "entry": float(e),
                          "H": h[s].astype(float), "L": l[s].astype(float), "C": c[s].astype(float)})
            last = i
    return paths


# ----------------------------- 출구 전략 ----------------------------------- #
def exit_bracket(p, tp, sl):
    e = p["entry"]
    up, dn = e * (1 + tp / 100), e * (1 - sl / 100)
    for k in range(len(p["C"])):
        hit_sl = p["L"][k] <= dn
        hit_tp = p["H"][k] >= up
        if hit_sl:                 # 동시 터치 시 SL 우선(보수적)
            return -sl
        if hit_tp:
            return tp
    return (p["C"][-1] / e - 1) * 100


def exit_trailing(p, trail, init_sl):
    e = p["entry"]
    peak = e
    stop = e * (1 - init_sl / 100)
    for k in range(len(p["C"])):
        if p["L"][k] <= stop:
            return (stop / e - 1) * 100
        peak = max(peak, p["H"][k])
        stop = max(stop, peak * (1 - trail / 100))
    return (p["C"][-1] / e - 1) * 100


def exit_time(p, days):
    e = p["entry"]
    j = min(days - 1, len(p["C"]) - 1)
    return (p["C"][j] / e - 1) * 100


def stats(rets):
    a = np.array(rets, dtype=float)
    net = a - COST_RT
    wins = net[net > 0]; losses = net[net < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    eq = np.cumprod(1 + net / 100)
    mdd = ((eq / np.maximum.accumulate(eq)) - 1).min() * 100
    return {
        "n": len(a),
        "mean_%": round(net.mean(), 2),
        "median_%": round(float(np.median(net)), 2),
        "win_%": round((net > 0).mean() * 100, 0),
        "PF": round(pf, 2),
        "expR_%": round(net.mean(), 2),
        "MDD_%": round(mdd, 0),
    }


def main():
    print(f"[1/3] 유니버스 (FDR 거래량 상위 {UNIVERSE_TOP})...")
    syms, names = get_universe(UNIVERSE_TOP)
    print(f"[2/3] yfinance {YEARS} 일봉 ({len(syms)} 종목)...")
    data = download(syms, YEARS, CHUNK)
    if not data:
        sys.exit("[오류] 데이터 수집 실패.")
    print(f"[3/3] 신호 경로 수집 + 출구 전략 시뮬레이션...")
    paths = collect_paths(data)
    if not paths:
        print("  신호 없음.")
        return

    strategies = []
    # 브래킷 그리드
    for tp, sl in [(8, 7), (10, 7), (10, 10), (15, 8), (15, 10), (20, 10), (12, 5)]:
        strategies.append((f"브래킷 +{tp}/-{sl}", [exit_bracket(p, tp, sl) for p in paths]))
    # 트레일링
    for tr, isl in [(8, 8), (10, 8), (12, 10)]:
        strategies.append((f"트레일 -{tr}(초기-{isl})", [exit_trailing(p, tr, isl) for p in paths]))
    # 시간청산 베이스라인
    for d in [5, 10, 20]:
        strategies.append((f"시간청산 D+{d}", [exit_time(p, d) for p in paths]))

    table = []
    for name, rets in strategies:
        s = stats(rets); s["전략"] = name
        table.append(s)
    res = pd.DataFrame(table).sort_values("expR_%", ascending=False)

    stamp = dt.date.today().isoformat()
    out_path = f"output/kr_exit_backtest_{stamp}.csv"
    res.to_csv(out_path, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 84)
    print(f"  일봉 셋업 출구 규칙 백테스트  (신호 {len(paths)}건 · 비용 왕복 {COST_RT}% 반영)")
    print(f"  진입=D+1 시가, 보유 최대 {MAXHOLD}일, 같은날 TP·SL 동시→SL 우선(보수적)")
    print("=" * 84)
    cols = ["전략", "n", "mean_%", "median_%", "win_%", "PF", "MDD_%"]
    with pd.option_context("display.width", 200, "display.unicode.east_asian_width", True):
        print(res[cols].to_string(index=False))
    print("-" * 84)
    best = res.iloc[0]
    print(f"  기대값 1위: {best['전략']}  (거래당 평균 {best['mean_%']}% / PF {best['PF']} / MDD {best['MDD_%']}%)")
    pos = res[res["mean_%"] > 0]
    print(f"  비용 후 +기대값 전략: {len(pos)}/{len(res)}")
    print(f"  저장: {out_path}")
    print("=" * 84)
    print("  ⚠ 생존편향(상폐 누락→과대평가)·일봉 H/L 근사·단일 유니버스/기간. 거래당 기대값이")
    print("    비용 차감 후에도 뚜렷이 +이고 PF>1.3, MDD 감당 가능할 때만 의미. 매매신호 아님.")


if __name__ == "__main__":
    main()
