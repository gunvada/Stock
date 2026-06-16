# -*- coding: utf-8 -*-
"""
진입 타이밍 검증 — '어제 신호 블라인드' vs '프리마켓 추이 보고'
----------------------------------------------------------------
눌림목(흡수) 신호(D일 종가 확정)를 다음날(D+1) 어떻게 진입하느냐 비교:
  A 블라인드시초 : D+1 시초가 매수 → 종가 (어제 데이터만 믿고 진입)
  B 프리마켓강세 : D+1 프리마켓이 전일종가 위(≥0%)일 때만 진입
  C 급갭다운회피 : D+1 프리마켓 -5%보다 더 빠지면 진입 안 함
  D VWAP회복진입 : 개장 후 VWAP 회복(종가>VWAP) 첫 봉에 진입 → 종가
모두 종가 청산. +10% 도달 여부도 집계.
"""
import os
import sys
import json
import time
import datetime as dt
from statistics import mean

import pandas as pd
import requests

import scanner
from analyze_winners import build_panel

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CACHE = os.path.join(scanner.OUTPUT_DIR, "cache")
MIN10 = "https://api.polygon.io/v2/aggs/ticker/{t}/range/10/minute/{d}/{d}"


def bars_cached(ticker, date, cfg, session):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f"bars_{ticker}_{date}.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    url = MIN10.format(t=ticker, d=date)
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": cfg["polygon_api_key"]}
    for _ in range(3):
        r = session.get(url, params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(15); continue
        res = r.json().get("results", []) or [] if r.status_code == 200 else []
        json.dump(res, open(p, "w", encoding="utf-8"))
        time.sleep(cfg["scan"].get("rate_sleep_seconds", 13))
        return res
    return []


def split(bars):
    pm, reg = [], []
    for b in bars:
        d = dt.datetime.utcfromtimestamp(b["t"] / 1000)
        h = d.hour + d.minute / 60.0
        if 8.0 <= h < 13.5:
            pm.append(b)
        elif 13.5 <= h < 20.0:
            reg.append(b)
    return pm, reg


def main():
    cfg = scanner.load_config()
    session = requests.Session()
    df = build_panel(cfg, session).sort_values(["ticker", "date"])
    g = df.groupby("ticker")
    df["base_vol"] = g["v"].transform(lambda s: s.shift(1).rolling(7, min_periods=3).median())
    df["c_m2"] = g["c"].shift(2)
    df["next_date"] = g["date"].shift(-1)
    df = df[(df["c"] > 0) & (df["base_vol"] > 0) & (df["o"] > 0) & (df["h"] > df["l"])]
    df["vol_ratio"] = df["v"] / df["base_vol"]
    df["oc"] = (df["c"] - df["o"]) / df["o"] * 100
    df["run2d"] = (df["c"] / df["c_m2"] - 1) * 100
    df["dol_M"] = df["v"] * df["c"] / 1e6

    sig = df[(df["vol_ratio"] >= 10) & (df["oc"].between(-15, -5))
             & (df["c"].between(0.3, 20)) & (df["dol_M"] >= 2)
             & (df["run2d"] < 100) & (df["next_date"].notna())]
    sig = sig[["ticker", "date", "next_date", "c"]].rename(columns={"c": "sig_close"})
    print(f"눌림목 신호 {len(sig)}건 — 다음날 분봉 수집(캐시 우선, 최대 ~{len(sig)*13//60+1}분)...")

    rows = []
    for i, r in enumerate(sig.itertuples(index=False), 1):
        bars = bars_cached(r.ticker, r.next_date, cfg, session)
        pm, reg = split(bars)
        if len(reg) < 5:
            continue
        prev_close = r.sig_close
        op, cl = reg[0]["o"], reg[-1]["c"]
        hi = max(b["h"] for b in reg)
        pm_ret = ((pm[-1]["c"] - prev_close) / prev_close * 100) if pm else 0.0
        pm_vol = sum(b["v"] for b in pm)

        # VWAP 회복 진입가
        cum_pv = cum_v = 0.0
        vwap_entry = None
        for b in reg:
            cum_pv += b["c"] * b["v"]; cum_v += b["v"]
            vwap = cum_pv / cum_v if cum_v else b["c"]
            if b["c"] > vwap:
                vwap_entry = b["c"]; break

        def ret(entry):
            return (cl - entry) / entry * 100 if entry else None

        def tp10(entry):
            return (hi - entry) / entry * 100 >= 10 if entry else False

        rows.append({
            "pm_ret": pm_ret, "pm_vol": pm_vol,
            "A": ret(op), "A_tp": tp10(op),
            "B": ret(op) if pm_ret >= 0 else None, "B_tp": tp10(op) if pm_ret >= 0 else None,
            "C": ret(op) if pm_ret > -5 else None, "C_tp": tp10(op) if pm_ret > -5 else None,
            "D": ret(vwap_entry), "D_tp": tp10(vwap_entry),
        })
        if i % 10 == 0:
            print(f"  ...{i}/{len(sig)}")

    res = pd.DataFrame(rows)

    def summ(name, col, tpcol):
        v = res[col].dropna()
        if len(v) < 3:
            return {"룰": name, "진입수": len(v), "비고": "표본부족"}
        tp = res[tpcol][res[col].notna()]
        return {"룰": name, "진입수": len(v),
                "진입률%": round(len(v) / len(res) * 100, 0),
                "평균%": round(v.mean(), 1), "중앙%": round(v.median(), 1),
                "승률%": round((v > 0).mean() * 100, 0),
                "+10%도달%": round(tp.mean() * 100, 0)}

    table = pd.DataFrame([
        summ("A 블라인드시초", "A", "A_tp"),
        summ("B 프리마켓강세(≥0%)", "B", "B_tp"),
        summ("C 급갭다운회피(>-5%)", "C", "C_tp"),
        summ("D VWAP회복진입", "D", "D_tp"),
    ])

    print("\n" + "=" * 84)
    print(f"  진입 타이밍 비교 (눌림목 신호 {len(res)}건, 다음날, 수수료 전)")
    print("=" * 84)
    print(table.to_string(index=False))
    print("-" * 84)
    # 프리마켓 방향별 결과 (핵심 인사이트)
    up = res[res["pm_ret"] >= 0]["A"].dropna()
    dn = res[res["pm_ret"] < 0]["A"].dropna()
    print("  [프리마켓 방향이 다음날 본장을 예고하나? — 시초→종가 기준]")
    if len(up) >= 3:
        print(f"    프리마켓 강세(≥0%) {len(up)}건: 평균 {up.mean():+.1f}%  승률 {(up>0).mean()*100:.0f}%")
    if len(dn) >= 3:
        print(f"    프리마켓 약세(<0%) {len(dn)}건: 평균 {dn.mean():+.1f}%  승률 {(dn>0).mean()*100:.0f}%")
    res.to_csv(os.path.join(scanner.OUTPUT_DIR, "entry_timing.csv"), index=False, encoding="utf-8-sig")
    print("  저장: output/entry_timing.csv")
    print("=" * 84)


if __name__ == "__main__":
    main()
