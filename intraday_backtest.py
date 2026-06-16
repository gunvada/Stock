# -*- coding: utf-8 -*-
"""
전략 재설계 백테스트 (Intraday strategy backtest)
----------------------------------------------------
예측력 검증 결론 ―'시초가 추격 = 마이너스 기대값, 큰 갭일수록 악화'― 을 받아,
"추격하지 말고 장중 확인 + 손절"로 기대값이 +로 도는지 10분봉으로 시뮬레이션한다.

대상 모집단 : predict_population.csv 중 갭 ≥ GAP_MIN%  (급등주 핵심)
세션        : 정규장 13:30~20:00 UTC (09:30~16:00 ET, EDT 기준)
10분봉      : output/cache/bars_*.json 캐시 (재실행 무료)

비교 전략:
  S1 추격        : 시초가 매수 → 종가 매도 (기존)
  S2 확인진입    : 10:00(3봉) 시점 시초가 위 & 상승추세면 다음봉 시초가 매수 → 종가
  S3 확인+트레일 : S2 진입 + 고점대비 -TRAIL% 이탈 시 청산
  S4 확인+브래킷 : S2 진입 + (+TP% 익절 / -STOP% 손절) 먼저 닿는 쪽
  S5 초반차익    : 시초가 매수 → 10:00 청산 (오프닝 팝만)
"""

import os
import sys
import json
import time
import datetime as dt
from statistics import mean, median

import requests
import pandas as pd

import scanner

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CACHE = os.path.join(scanner.OUTPUT_DIR, "cache")
AGG = "https://api.polygon.io/v2/aggs/ticker/{t}/range/10/minute/{d}/{d}"
REG_START, REG_END = 13.5, 20.0

GAP_MIN = 20.0     # 대상: 갭 ≥ 20%
TRAIL = 15.0       # S3 트레일링 스톱 %
TP, STOP = 15.0, 10.0  # S4 익절/손절 %


def fetch_bars_cached(ticker, date, cfg, session):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"bars_{ticker}_{date}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    url = AGG.format(t=ticker, d=date)
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": cfg["polygon_api_key"]}
    for _ in range(3):
        r = session.get(url, params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(15); continue
        res = r.json().get("results", []) or [] if r.status_code == 200 else []
        with open(path, "w", encoding="utf-8") as f:
            json.dump(res, f)
        time.sleep(cfg["scan"].get("rate_sleep_seconds", 13))
        return res
    return []


def regular_bars(bars):
    out = []
    for b in bars:
        d = dt.datetime.utcfromtimestamp(b["t"] / 1000)
        h = d.hour + d.minute / 60.0
        if REG_START <= h < REG_END:
            out.append(b)
    return out


def simulate(reg):
    """한 종목-일에 대해 전략별 수익률(%) 반환. 미진입은 None."""
    if len(reg) < 5:
        return None
    op = reg[0]["o"]
    cl = reg[-1]["c"]
    r = {}

    # S1 추격
    r["S1_추격"] = (cl - op) / op * 100

    # 확인 조건: 3봉째(약 10:00) 종가가 시초가 위 + 직전봉 위(상승추세)
    confirmed = reg[2]["c"] > op and reg[2]["c"] > reg[1]["c"]
    if not confirmed:
        r["S2_확인진입"] = None
        r["S3_확인트레일"] = None
        r["S4_확인브래킷"] = None
    else:
        entry = reg[3]["o"]
        post = reg[3:]
        # S2: 종가 청산
        r["S2_확인진입"] = (cl - entry) / entry * 100

        # S3: 트레일링 스톱
        peak = entry; exitp = cl
        for b in post:
            peak = max(peak, b["h"])
            if (peak - b["l"]) / peak * 100 >= TRAIL:
                exitp = peak * (1 - TRAIL / 100)  # 스톱가 근사 체결
                break
        r["S3_확인트레일"] = (exitp - entry) / entry * 100

        # S4: 브래킷 (보수적 — 같은 봉서 둘 다 닿으면 손절 우선)
        tp_px = entry * (1 + TP / 100)
        st_px = entry * (1 - STOP / 100)
        exitp = cl
        for b in post:
            hit_stop = b["l"] <= st_px
            hit_tp = b["h"] >= tp_px
            if hit_stop:
                exitp = st_px; break
            if hit_tp:
                exitp = tp_px; break
        r["S4_확인브래킷"] = (exitp - entry) / entry * 100

    # S5 초반차익: 시초가 → 10:00(3봉째 종가) 청산
    r["S5_초반차익"] = (reg[2]["c"] - op) / op * 100
    return r


def agg(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return None
    wins = [x for x in v if x > 0]
    big = [x for x in v if x >= 10]
    return {"진입수": len(v), "평균%": round(mean(v), 1), "중앙%": round(median(v), 1),
            "승률%": round(len(wins) / len(v) * 100, 0),
            "+10%달성%": round(len(big) / len(v) * 100, 0),
            "최대익": round(max(v), 0), "최대손": round(min(v), 0)}


def main():
    cfg = scanner.load_config()
    session = requests.Session()
    pop_path = os.path.join(scanner.OUTPUT_DIR, "predict_population.csv")
    if not os.path.exists(pop_path):
        sys.exit("predict_population.csv 없음. 먼저 python predict_test.py 실행.")
    pop = pd.read_csv(pop_path)
    pop = pop[pop["gap_%"] >= GAP_MIN].copy()
    print(f"대상: 갭≥{GAP_MIN:.0f}% 종목 {len(pop)}건 — 10분봉 수집(캐시 우선)...")

    results = {k: [] for k in ["S1_추격", "S2_확인진입", "S3_확인트레일", "S4_확인브래킷", "S5_초반차익"]}
    done = 0
    for _, row in pop.iterrows():
        t, d = row["ticker"], row["date"]
        bars = fetch_bars_cached(t, d, cfg, session)
        reg = regular_bars(bars)
        sim = simulate(reg)
        if sim is None:
            continue
        for k in results:
            results[k].append(sim[k])
        done += 1
        if done % 10 == 0:
            print(f"  ...{done}건 처리")
    print(f"  완료: {done}건\n")

    rows = []
    total = done
    for k, vals in results.items():
        a = agg(vals)
        if a:
            a = {"전략": k, "진입률%": round(a["진입수"] / total * 100, 0), **a}
            rows.append(a)
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(scanner.OUTPUT_DIR, "strategy_backtest.csv"), index=False, encoding="utf-8-sig")

    print("=" * 96)
    print(f"  전략 재설계 백테스트  (갭≥{GAP_MIN:.0f}% 모집단 {total}건, 수수료·슬리피지 차감 전)")
    print("=" * 96)
    print(out.to_string(index=False))
    print("-" * 96)
    print(f"  S3 트레일 {TRAIL:.0f}% / S4 익절{TP:.0f}%·손절{STOP:.0f}%")
    print("  진입률% = 확인조건 충족해 실제 매수한 비율 (S2~S4)")
    print("  저장: output/strategy_backtest.csv")
    print("=" * 96)


if __name__ == "__main__":
    main()
