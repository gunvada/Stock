# -*- coding: utf-8 -*-
"""
국장 픽 평가점수 (KR Pick Scoring)
===================================
kr_candle_verify(베이스·신호) + kr_surge(폭증) 결과에 손절라인을 붙이고,
**투명한 가중 점수(0~100)** 로 후보를 평가·랭킹한다. 수익 보장이 아니라
'우리 기준에 얼마나 부합하는가' 의 점수다.

────────────────────────── 점수 구성 (합 100%) ──────────────────────────
A. 위치점수  (30%) — 다년 베이스 위치. 깊은하락+수평+바닥권일수록 高.
     label 점수: 베이스근접100 / 베이스(완만)80 / 비전형40 / 상승이탈20 / 하락중20 / 과상승0 / 데이터부족30
     위치 보정: 바닥권(pos 낮음)일수록 加  →  0.6*label + 0.4*(100 - pos_in_base)
B. 신호점수  (25%) — 상승 캔들/캔들군 강도. 라벨별 가중합(cap 100):
     양봉스프링40 · 꼬리군40 · 상승펀치35 · 상승다람쥐35 · 위꼬리양봉25 · 작은몸통양꼬리양봉20
C. 폭증점수  (20%) — 거래량 폭증배율(로그). 50배≈100 / 10배≈59 / 5배≈43 / 3배≈28
D. 리스크점수(15%) — 손절이 가까울수록 高. 100 − 위험%×6 (위험5%→70, 10%→40, 15%→10)
E. 모멘텀점수(10%) — 당일 방향. 양봉 加, 단 +30% 상한가는 추격위험 → 감점(25)
        +0~+10%: 60~100 / 음봉: 60+등락×5(하한20) / 상한가(≥+29%): 25
총점 = 0.30A + 0.25B + 0.20C + 0.15D + 0.10E.  등급: A≥75 · B 60~74 · C 45~59 · D<45
─────────────────────────────────────────────────────────────────────────
"""

import os
import re
import sys
import glob
import math

import pandas as pd

import candle_patterns as cp

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
STOP_BUFFER = 0.02
SIGNAL_LOOKBACK = 5
TOP_N = 15

LABEL_SCORE = {"베이스근접": 100, "베이스(완만)": 80, "비전형": 40,
               "상승이탈": 20, "하락중": 20, "과상승": 0, "데이터부족": 30}
SIGNAL_W = {"양봉스프링": 40, "꼬리군": 40, "상승펀치": 35, "상승다람쥐": 35,
            "위꼬리양봉": 25, "작은몸통양꼬리양봉": 20}
WEIGHTS = {"위치": 0.30, "신호": 0.25, "폭증": 0.20, "리스크": 0.15, "모멘텀": 0.10}


def latest(pattern):
    fs = [f for f in glob.glob(os.path.join(OUT, pattern))
          if re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(f))]
    return sorted(fs)[-1] if fs else None


def signal_stop(sym):
    import yfinance as yf
    try:
        df = yf.Ticker(sym).history(period="3mo", interval="1d", auto_adjust=False)
    except Exception:
        return None, None
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if df.empty:
        return None, None
    o, h, l, c = (df["Open"].values, df["High"].values, df["Low"].values, df["Close"].values)
    entry = float(c[-1])
    sig_low = None
    for k in range(len(c) - 1, max(-1, len(c) - 1 - SIGNAL_LOOKBACK), -1):
        if cp.has_bullish_signal(o[k], h[k], l[k], c[k]):
            sig_low = float(l[k]); break
    if sig_low is None:
        sig_low = float(l[-1])
    return round(entry, 1), round(sig_low * (1 - STOP_BUFFER), 1)


# ----------------------------- 영역별 점수 --------------------------------- #
def score_position(base_label, pos):
    if base_label == "과상승":
        return 0.0
    lbl = LABEL_SCORE.get(base_label, 40)
    posv = pos if pos is not None and pos == pos else 50
    return round(0.6 * lbl + 0.4 * (100 - posv), 1)


def score_signal(signals_str):
    s = 0
    for lab in [x.strip() for x in str(signals_str).split(",") if x.strip() and x.strip() != "-"]:
        s += SIGNAL_W.get(lab, 15)
    return float(min(100, s))


def score_surge(x):
    if not x or x <= 1:
        return 0.0
    return round(min(100, max(0, math.log10(x) / math.log10(50) * 100)), 1)


def score_risk(risk_pct):
    return round(max(0, min(100, 100 - risk_pct * 6)), 1)


def score_momentum(day_chg):
    if day_chg >= 29:
        return 25.0                      # 상한가 추격 감점
    if day_chg >= 0:
        return round(min(100, 60 + day_chg * 4), 1)
    return round(max(20, 60 + day_chg * 5), 1)


def grade(total):
    return "A" if total >= 75 else "B" if total >= 60 else "C" if total >= 45 else "D"


def main():
    sp, vp = latest("kr_surge_*.csv"), latest("kr_candle_verified_*.csv")
    if not sp or not vp:
        sys.exit("[오류] kr_surge_*.csv / kr_candle_verified_*.csv 필요.")
    s = pd.read_csv(sp, dtype={"code": str}); v = pd.read_csv(vp)
    s["code"] = s["code"].str.zfill(6)
    v["code"] = v["sym"].astype(str).str.split(".").str[0].str.zfill(6)
    m = s.merge(v[["code", "sym", "verdict", "signals", "base", "pos_in_base_%", "drop_peak_%"]],
                on="code", how="inner")
    m = m[m["verdict"].isin(["✅✅ PRIME", "✅ PASS"])].copy()
    m = m.sort_values("ratio", ascending=False).head(TOP_N)

    print(f"[평가] 후보 {len(m)}종 점수 산출 (손절·리스크 계산 위해 일봉 조회)...")
    rows = []
    for _, r in m.iterrows():
        entry, stop = signal_stop(r["sym"])
        if entry is None or stop is None or stop >= entry:
            continue
        risk = (entry - stop) / entry * 100
        A = score_position(r["base"], r["pos_in_base_%"])
        B = score_signal(r["signals"])
        C = score_surge(float(r["ratio"]))
        D = score_risk(risk)
        E = score_momentum(float(r["day_chg_%"]))
        total = round(WEIGHTS["위치"]*A + WEIGHTS["신호"]*B + WEIGHTS["폭증"]*C
                      + WEIGHTS["리스크"]*D + WEIGHTS["모멘텀"]*E, 1)
        rows.append({
            "종목": r["name"], "시장": r["market"], "총점": total, "등급": grade(total),
            "위치": A, "신호": B, "폭증": C, "리스크": D, "모멘텀": E,
            "진입": entry, "손절": stop, "위험%": round(risk, 1),
            "폭증배": r["ratio"], "당일%": r["day_chg_%"], "베이스": r["base"],
        })
    if not rows:
        print("  유효 후보 없음."); return
    res = pd.DataFrame(rows).sort_values("총점", ascending=False).reset_index(drop=True)
    res.insert(0, "순위", res.index + 1)
    stamp = re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(sp)).group(1)
    res.to_csv(os.path.join(OUT, f"kr_score_{stamp}.csv"), index=False, encoding="utf-8-sig")

    print("\n" + "=" * 100)
    print(f"  국장 픽 평가점수  (기준일 {stamp})   총점=0.30위치+0.25신호+0.20폭증+0.15리스크+0.10모멘텀")
    print("=" * 100)
    cols = ["순위", "종목", "시장", "총점", "등급", "위치", "신호", "폭증", "리스크", "모멘텀",
            "진입", "손절", "위험%", "폭증배", "당일%"]
    with pd.option_context("display.width", 260, "display.unicode.east_asian_width", True):
        print(res[cols].to_string(index=False))
    print("-" * 100)
    print("  · 각 영역 0~100점 → 가중합 = 총점. 등급 A≥75 / B 60~74 / C 45~59 / D<45")
    print("  · 손절=신호캔들 저가 −2%. 위험%=진입→손절 손실폭(이걸로 종목당 투입액 사이징).")
    print("  · 점수는 '우리 기준 부합도'일 뿐 수익 보장 아님 — 상한가/음봉/저폭증은 자동 감점됨.")
    print("=" * 100)


if __name__ == "__main__":
    main()
