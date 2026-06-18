# -*- coding: utf-8 -*-
"""
추천 후보 + 손절라인 (KR Picks with Stop-loss)
===============================================
'망원경' 역할: kr_candle_verify 가 통과시킨 후보(PRIME 우선)에 **진입 기준가·
손절라인·위험%** 를 붙여 표로 제시한다. 수익 보장이 아니라 '후보 + 리스크 한도'.

손절라인 규칙 (캔들 교재 그대로):
  손절 = **신호 캔들의 저가 살짝 아래**(기본 −2%). 이 선이 깨지면 가설이 틀린 것 → 정리.
진입 기준가 = 최근 종가(다음날 시초가 부근에서 대응).
위험% = (진입 − 손절)/진입 × 100  → 한 종목에 넣을 금액은 '위험%' 로 사이징.

데이터: yfinance(.KS/.KQ). 입력: output/kr_surge_*.csv + output/kr_candle_verified_*.csv
"""

import os
import re
import sys
import glob

import pandas as pd

import candle_patterns as cp

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
STOP_BUFFER = 0.02      # 신호 캔들 저가 아래 여유(−2%)
SIGNAL_LOOKBACK = 5     # 최근 며칠 봉에서 신호 캔들을 찾을지
TOP_N = 12


def latest(pattern):
    fs = [f for f in glob.glob(os.path.join(OUT, pattern))
          if re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(f))]
    return sorted(fs)[-1] if fs else None


def signal_stop(sym):
    """최근 신호 캔들의 저가로 손절라인 계산. 반환 (entry_ref, signal_low, stop)."""
    import yfinance as yf
    try:
        df = yf.Ticker(sym).history(period="3mo", interval="1d", auto_adjust=False)
    except Exception:
        return None, None, None
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if df.empty:
        return None, None, None
    o, h, l, c = (df["Open"].values, df["High"].values, df["Low"].values, df["Close"].values)
    entry_ref = float(c[-1])
    # 최근 SIGNAL_LOOKBACK봉 중 '가장 최근' 상승 신호 캔들의 저가
    sig_low = None
    for k in range(len(c) - 1, max(-1, len(c) - 1 - SIGNAL_LOOKBACK), -1):
        if cp.has_bullish_signal(o[k], h[k], l[k], c[k]):
            sig_low = float(l[k])
            break
    if sig_low is None:
        sig_low = float(l[-1])              # 신호 못찾으면 최신봉 저가로 대체
    stop = round(sig_low * (1 - STOP_BUFFER), 1)
    return round(entry_ref, 1), round(sig_low, 1), stop


def main():
    sp, vp = latest("kr_surge_*.csv"), latest("kr_candle_verified_*.csv")
    if not sp or not vp:
        sys.exit("[오류] kr_surge_*.csv / kr_candle_verified_*.csv 필요. 먼저 스캔·검증 실행.")
    s = pd.read_csv(sp, dtype={"code": str})
    v = pd.read_csv(vp)
    s["code"] = s["code"].str.zfill(6)
    v["code"] = v["sym"].astype(str).str.split(".").str[0].str.zfill(6)
    m = s.merge(v[["code", "sym", "verdict", "signals", "base", "pos_in_base_%", "drop_peak_%"]],
                on="code", how="inner")

    # PRIME 우선, 없으면 PASS. 폭증배율 순. 상한가(+30% 근처)는 추격위험 표시.
    order = {"✅✅ PRIME": 0, "✅ PASS": 1}
    m = m[m["verdict"].isin(order)].copy()
    m["_o"] = m["verdict"].map(order)
    m = m.sort_values(["_o", "ratio"], ascending=[True, False]).head(TOP_N)

    print(f"[손절라인 계산] 후보 {len(m)}종 (yfinance 최근 일봉)...")
    rows = []
    for _, r in m.iterrows():
        entry, sig_low, stop = signal_stop(r["sym"])
        if entry is None or stop is None or stop >= entry:
            continue
        risk = (entry - stop) / entry * 100
        rows.append({
            "종목": r["name"], "시장": r["market"], "판정": r["verdict"],
            "폭증": r["ratio"], "당일%": r["day_chg_%"],
            "진입기준가": entry, "손절라인": stop, "위험%": round(risk, 1),
            "신호": r["signals"], "베이스위치%": r["pos_in_base_%"],
            "상한가추격": "⚠상한가" if r["day_chg_%"] >= 29 else "",
        })
    if not rows:
        print("  유효한 손절라인 후보가 없습니다.")
        return
    res = pd.DataFrame(rows)
    stamp = re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(sp)).group(1)
    res.to_csv(os.path.join(OUT, f"kr_picks_{stamp}.csv"), index=False, encoding="utf-8-sig")

    print("\n" + "=" * 92)
    print(f"  추천 후보 + 손절라인  (기준일 {stamp})   ※ 망원경 역할 — 매수 신호 아님")
    print("=" * 92)
    cols = ["종목", "시장", "판정", "폭증", "당일%", "진입기준가", "손절라인", "위험%", "신호", "상한가추격"]
    with pd.option_context("display.width", 240, "display.unicode.east_asian_width", True):
        print(res[cols].to_string(index=False))
    print("-" * 92)
    print("  · 손절라인 = 신호 캔들 저가 살짝 아래(−2%). 이 선 깨지면 정리(가설 틀림).")
    print("  · 위험% = 진입가→손절가 손실폭. 한 종목 투입액은 이 위험%로 사이징(예: 계좌 1%만 위험).")
    print("  · ⚠상한가 = 당일 +30% 잠김 → 다음날 추격은 특히 위험(백테스트상 추격 단타는 무엣지).")
    print("=" * 92)


if __name__ == "__main__":
    main()
