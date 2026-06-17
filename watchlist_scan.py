# -*- coding: utf-8 -*-
"""
워치리스트 거래량 폭증 스캔 (yfinance 데모) — Polygon 키 없이 도는 축소판
-------------------------------------------------------------------------
scanner.py 의 폭증 로직(최신일 거래량 ÷ 직전 N거래일 중앙값)을 yfinance 로
재현하되, '전체 시장'이 아니라 아래 고정 워치리스트 안에서만 계산한다.

⚠ 한계: 워치리스트는 사람이 고른 목록이라 종목선택 편향이 있고, 목록 밖의
   진짜 폭증주는 잡지 못한다. 전체 시장 스캔은 Polygon 키로 scanner.py 를 써야 한다.
   결과는 매매 신호가 아니라 '이 목록 안에서 거래량이 튄 후보'일 뿐이다.
"""

import sys
import datetime as dt
from statistics import median

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LOOKBACK = 7          # 비교 거래일 수 (scanner 기본과 동일)
WATCH_X = 10.0        # '관찰' 기준 배율
MIN_LATEST_VOL = 300_000
MIN_BASELINE_VOL = 50_000

# 섹터를 두루 섞은 중소형/리테일 인기 종목 고정 목록 (편향 최소화 시도, 그래도 편향 있음)
UNIVERSE = [
    # 리테일/밈 성향
    "GME", "AMC", "BBAI", "SOFI", "PLTR", "LCID", "RIVN", "CHPT", "PLUG", "FCEL",
    # 바이오/제약 소형
    "SAVA", "OCGN", "VTVT", "ATAI", "CRSP", "EDIT", "BNGO", "INO", "NVAX", "MNMD",
    # 기술/반도체 소형
    "MARA", "RIOT", "CLSK", "IONQ", "RGTI", "QBTS", "SMCI", "AMD", "INTC", "WOLF",
    # 에너지/소재/광물
    "DNN", "UEC", "UUUU", "MP", "TMC", "AMPX", "FSLR", "RUN", "NIO", "XPEV",
    # 소비/기타 소형
    "WKHS", "GOEV", "NKLA", "HOOD", "DKNG", "CVNA", "AFRM", "UPST", "OPEN", "RKT",
]


def main():
    import yfinance as yf
    print(f"[1/2] yfinance 워치리스트 데이터 수집 ({len(UNIVERSE)} 종목)...")
    raw = yf.download(UNIVERSE, period=f"{LOOKBACK + 8}d", interval="1d",
                      auto_adjust=False, progress=False, group_by="ticker", threads=True)

    print("[2/2] 거래량 폭증 배율 계산...")
    rows = []
    for t in UNIVERSE:
        try:
            sub = raw[t].dropna(subset=["Volume", "Close"])
        except Exception:
            continue
        if len(sub) < 4:
            continue
        vols = sub["Volume"].tolist()
        latest_vol = float(vols[-1])
        prior = [float(v) for v in vols[-(LOOKBACK + 1):-1]]
        if not prior:
            continue
        base = median(prior)
        if base < MIN_BASELINE_VOL or latest_vol < MIN_LATEST_VOL:
            continue
        ratio = latest_vol / base if base > 0 else 0
        close = float(sub["Close"].iloc[-1])
        prev_close = float(sub["Close"].iloc[-2])
        chg = (close - prev_close) / prev_close * 100 if prev_close else 0
        rows.append({
            "ticker": t,
            "surge_x": round(ratio, 1),
            "last_close": round(close, 2),
            "day_chg_%": round(chg, 1),
            "latest_vol_M": round(latest_vol / 1e6, 2),
            "baseline_vol_M": round(base / 1e6, 2),
            "meets_10x": "✔" if ratio >= WATCH_X else "",
        })

    if not rows:
        print("  조건을 만족하는 종목이 없습니다.")
        return
    res = pd.DataFrame(rows).sort_values("surge_x", ascending=False).reset_index(drop=True)
    last_date = raw.index[-1].date()

    print("\n" + "=" * 76)
    print(f"  워치리스트 거래량 폭증 후보  (기준일 {last_date}, 비교 {LOOKBACK}거래일)")
    print("=" * 76)
    with pd.option_context("display.width", 200):
        print(res.head(15).to_string(index=False))
    print("-" * 76)
    print("  ⚠ 고정 워치리스트 한정 데모 — 전체 시장 스캔 아님(편향 있음). 매매 신호 아님.")
    print("  ⚠ 단일 소스(yfinance)라 교차검증 안 됨. 폭증주는 하루 -30%도 흔함.")


if __name__ == "__main__":
    main()
