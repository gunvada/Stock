# -*- coding: utf-8 -*-
"""
단기(단타) 캔들/파동 스캔 — 일봉·분봉 타임프레임  (KR Short-TF Candle Scan)
=============================================================================
캔들이론(거래량 폭증 ∩ 상승 캔들신호 ∩ 베이스 후반부)을 '주봉' 대신 **일봉 또는
분봉(30m/15m)** 으로 보고 짧은 보유(단타~단기 스윙)용 후보를 고른다. 데이터는
yfinance(.KS/.KQ), 유니버스는 FinanceDataReader 거래량 상위.

⚠️ 원전 경고(반드시 인지): 캔들매매법 교재는 **"1시간 미만 차트의 캔들 신호는
   대부분 무의미"**, **"캔들매매법은 1~6개월 보유하는 스윙/포지션 기법"** 이라고
   명시한다. 즉 30m/15m 단타 적용은 *이론에 반하는* 사용이다(노이즈↑, 신뢰성↓).
   일봉(1d)은 원전이 '주식 메인 차트'로 인정 → 그나마 정합적. 본 스캔은 가능성을
   보여줄 뿐, 짧은 타임프레임일수록 결과를 더 보수적으로 의심해야 한다.

타임프레임 프리셋(폭증/베이스 임계는 봉 수에 맞춰 축소):
  1d  : 6개월 일봉   — 베이스=최근 수개월, 보유 수일(단기 스윙)
  30m : 60일 30분봉  — 베이스=최근 수일, 보유 당일~1일 (원전 비권장)
  15m : 60일 15분봉  — 〃 더 짧음 (원전 비권장)
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

# 타임프레임별 프리셋: period, lookback(폭증비교 봉수), base_min_bars, base_window
PRESETS = {
    "1d":  {"period": "1y",  "lookback": 7,  "min_bars": 120, "base_window": 60,  "label": "일봉(단기스윙)"},
    "30m": {"period": "60d", "lookback": 13, "min_bars": 150, "base_window": 80,  "label": "30분봉(단타·원전비권장)"},
    "15m": {"period": "60d", "lookback": 26, "min_bars": 300, "base_window": 160, "label": "15분봉(단타·원전비권장)"},
}
WATCH_X = 8.0            # 단기는 폭증 기준을 약간 낮춤(봉당 거래량 변동 큼)
MIN_BASELINE_VOL = 5000
UNIVERSE_TOP = 200
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


def download(syms, period, interval, chunk):
    import yfinance as yf
    data = {}
    for i in range(0, len(syms), chunk):
        part = syms[i:i + chunk]
        try:
            raw = yf.download(part, period=period, interval=interval, auto_adjust=True,
                              progress=False, group_by="ticker", threads=True)
        except Exception:
            continue
        for sm in part:
            try:
                sub = raw[sm].dropna(subset=["Open", "High", "Low", "Close", "Volume"])
                if len(sub) > 30:
                    data[sm] = sub
            except Exception:
                pass
    return data


def evaluate(sym, df, ps):
    o = df["Open"].values; h = df["High"].values
    l = df["Low"].values;  c = df["Close"].values; v = df["Volume"].values
    n = len(c)
    if n < ps["lookback"] + 2:
        return None
    prior = v[-(ps["lookback"] + 1):-1]
    base_v = median(prior) if len(prior) else 0
    if base_v < MIN_BASELINE_VOL or base_v <= 0:
        return None
    surge = v[-1] / base_v
    if surge < WATCH_X:
        return None
    if not cp.has_bullish_signal(o[-1], h[-1], l[-1], c[-1]):
        return None
    sig = cp.detect(o[-1], h[-1], l[-1], c[-1])
    sig = [s for s in sig if s in cp.BULLISH_LABELS]
    b = wb.classify_base(h.tolist(), l.tolist(), c.tolist(),
                         min_bars=ps["min_bars"], base_window=ps["base_window"])
    if b["label"] == "과상승":
        verdict = "⛔ EXCLUDE"
    elif b["is_base"]:
        verdict = "✅✅ PRIME"
    else:
        verdict = "✅ PASS"
    chg = (c[-1] / c[-2] - 1) * 100 if n >= 2 and c[-2] else 0
    return {
        "sym": sym, "verdict": verdict,
        "surge_x": round(float(surge), 1),
        "last": round(float(c[-1]), 1),
        "bar_chg_%": round(float(chg), 1),
        "signals": ", ".join(sig),
        "base": b["label"],
        "drop_peak_%": b["drop_peak_%"],
        "pos_in_base_%": b["pos_in_base_%"],
    }


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "1d"
    if tf not in PRESETS:
        sys.exit(f"[오류] 타임프레임은 {list(PRESETS)} 중 하나. (입력 {tf})")
    ps = PRESETS[tf]

    print(f"[1/3] 유니버스 수집 (FDR 거래량 상위 {UNIVERSE_TOP})...")
    syms, names = get_universe(UNIVERSE_TOP)
    print(f"[2/3] yfinance {ps['period']} {tf} 수집 ({len(syms)} 종목)...")
    data = download(syms, ps["period"], tf, CHUNK)
    if not data:
        sys.exit("[오류] 데이터 수집 실패.")

    print(f"[3/3] 폭증 ∩ 상승캔들 ∩ 베이스({tf}) 판정...")
    rows = []
    for sym, df in data.items():
        try:
            r = evaluate(sym, df, ps)
        except Exception:
            r = None
        if r:
            r["name"] = names.get(sym, "")
            rows.append(r)

    if not rows:
        print(f"  조건을 만족하는 종목이 없습니다 ({tf}). (단기일수록 폭증·베이스 동시충족 드뭄)")
        return
    res = pd.DataFrame(rows)
    order = {"✅✅ PRIME": 0, "✅ PASS": 1, "⛔ EXCLUDE": 2}
    res["_o"] = res["verdict"].map(order).fillna(3)
    res = res.sort_values(["_o", "surge_x"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)

    stamp = dt.date.today().isoformat()
    out_path = f"output/kr_short_{tf}_{stamp}.csv"
    res.to_csv(out_path, index=False, encoding="utf-8-sig")

    nprime = (res["verdict"] == "✅✅ PRIME").sum()
    print("\n" + "=" * 84)
    print(f"  단기 캔들/파동 스캔 [{ps['label']}]  (기준 {stamp}, PRIME {nprime} / 후보 {len(res)})")
    print("=" * 84)
    cols = ["name", "verdict", "surge_x", "last", "bar_chg_%", "signals", "base", "drop_peak_%", "pos_in_base_%"]
    with pd.option_context("display.width", 220, "display.unicode.east_asian_width", True):
        print(res[cols].head(20).to_string(index=False))
    print("-" * 84)
    print(f"  저장: {out_path}")
    print("=" * 84)
    if tf != "1d":
        print("  ⚠⚠ 원전 경고: 캔들매매법은 1시간 미만 차트 신호를 '대부분 무의미'로 본다.")
        print("     30m/15m 결과는 노이즈가 크다 — 참고용. 일봉(1d)이 그나마 정합적.")
    print("  ⚠ 매매 신호 아님. 폭증주는 상·하한가 극심. 분할매수·손절·실시간 호가 확인은 본인 판단.")


if __name__ == "__main__":
    main()
