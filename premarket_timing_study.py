# -*- coding: utf-8 -*-
"""
프리마켓 최적 타점 타이밍 통계 검증  (Pre-market Entry-Timing Study)
====================================================================
미장 프리마켓 최근 120거래일(기본)을 대상으로, **어느 시간대(타점)에 진입했을 때
가장 실질적 이익이 났는지**를 통계적으로 검증한다. 캔들 신호(파동연상/캔들개론
기반, candle_signals.py)와 결합해 ET 30분 버킷별 기대수익을 집계한다.

설계(확정):
  · 청산   : 프리마켓 창 안에서 +TP%/-STOP% 먼저 터치한 쪽으로 청산,
             둘 다 미터치면 09:30 개장가(ET) 청산. (왕복비용 차감)
             같은 분봉서 고·저 둘 다 터치 시 보수적으로 손절 우선.
  · 타점   : ET 절대 시간대 30분 버킷(05:30/06:00/…/09:00) × 캔들 신호 결합.
  · 유니버스: ① 폭증 후보 전체  vs  ② 캔들신호+갭 부합 프리마켓 추천 픽 — 둘 다 비교.
  · 데이터 : Polygon 분봉 애그리거트(확장시간 포함, 2년 history, 무료 5req/분).
             ※ yfinance 1분봉은 ~7일만 제공 → 120일 불가하여 Polygon 사용.
             grouped daily / 분봉 모두 output/cache 에 캐싱(재실행 시 무호출).

산출:
  output/timing_study_detail.csv   (후보×버킷 단위 시뮬 결과)
  output/timing_study_buckets.csv  (버킷×유니버스×캔들신호 집계)
  콘솔: 유니버스별 최적 타점 버킷 + 캔들신호 결합 표

사용법:
  python premarket_timing_study.py            # 최근 120거래일 통계 검증(키 필요)
  python premarket_timing_study.py 60         # 창을 60거래일로
  python premarket_timing_study.py selftest   # 합성 분봉으로 로직 자체검증(키 불필요)
"""
import os
import sys
import json
import time
import datetime as dt
from statistics import median

import pandas as pd

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:                       # 최후 폴백(보통 불필요)
    ET = None

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

POLY_MIN = "https://api.polygon.io/v2/aggs/ticker/{t}/range/1/minute/{f}/{to}"

# 진입 가능 30분 버킷(ET). 09:00 버킷은 09:30 개장까지 30분 보유.
DEFAULT_BUCKETS = ["05:30", "06:00", "06:30", "07:00", "07:30",
                   "08:00", "08:30", "09:00"]
OPEN_ET = "09:30"


# --------------------------------------------------------------------------- #
# 설정
# --------------------------------------------------------------------------- #
def ts_config(cfg):
    ts = cfg.setdefault("timing_study", {})
    ts.setdefault("lookback_trading_days", 120)
    ts.setdefault("universe_top_n", 20)        # 신호일별 폭증 상위 N만 평가
    ts.setdefault("tp_pct", 10.0)
    ts.setdefault("stop_pct", 8.0)
    ts.setdefault("cost_pct", 2.5)             # 왕복 비용
    ts.setdefault("gap_min_pct", 5.0)          # 추천 픽 갭 기준(05:30 기준가 vs 전일종가)
    ts.setdefault("require_verdicts", ["강한매수", "매수관심"])
    ts.setdefault("buckets", DEFAULT_BUCKETS)
    return ts


# --------------------------------------------------------------------------- #
# 타이밍 시뮬레이션 (순수 함수 — API 불필요, 합성 검증 가능)
# --------------------------------------------------------------------------- #
def _hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def simulate_bucket(bars, bucket, tp_pct, stop_pct, cost_pct, open_px):
    """
    bars: [{'min':'HH:MM','o','h','l','c'}, ...] 프리마켓 분봉(시간 오름차순, <09:30)
    bucket: 진입 버킷 시작 'HH:MM'.  진입가 = 버킷 시작 이후 첫 봉의 시가.
    창 안에서 TP/STOP 먼저 터치한 쪽으로 청산, 미터치면 open_px(09:30 개장가)로 청산.
    같은 봉서 둘 다 터치 시 손절 우선(보수적).
    반환: dict(entry, outcome, gross_%, net_%)  또는 None(진입 불가).
    """
    bstart = _hm(bucket)
    seq = [b for b in bars if _hm(b["min"]) >= bstart]
    if not seq:
        return None
    entry = float(seq[0]["o"])
    if entry <= 0:
        return None
    tp_px = entry * (1 + tp_pct / 100)
    sl_px = entry * (1 - stop_pct / 100)

    outcome, gross = "open", None
    for b in seq:
        hi, lo = float(b["h"]), float(b["l"])
        hit_tp, hit_sl = hi >= tp_px, lo <= sl_px
        if hit_sl:                      # 손절 우선(같은 봉 양쪽 터치 포함)
            outcome, gross = "stop", -stop_pct
            break
        if hit_tp:
            outcome, gross = "tp", tp_pct
            break
    if gross is None:                   # 미터치 → 개장가 청산
        exit_px = float(open_px) if open_px else float(seq[-1]["c"])
        gross = (exit_px - entry) / entry * 100
    net = gross - cost_pct
    return {"entry": round(entry, 4), "outcome": outcome,
            "gross_%": round(gross, 2), "net_%": round(net, 2)}


def simulate_candidate(bars, open_px, ts):
    """후보 1건을 모든 버킷에서 시뮬 → [{bucket, ...}] 리스트."""
    rows = []
    for bk in ts["buckets"]:
        r = simulate_bucket(bars, bk, ts["tp_pct"], ts["stop_pct"],
                            ts["cost_pct"], open_px)
        if r:
            r["bucket"] = bk
            rows.append(r)
    return rows


# --------------------------------------------------------------------------- #
# 집계
# --------------------------------------------------------------------------- #
def aggregate(detail, label):
    """detail DataFrame → 버킷별 집계(거래수/순익평균/승률/TP·SL률)."""
    if detail.empty:
        return pd.DataFrame()
    g = detail.groupby("bucket")
    agg = g.agg(
        거래수=("net_%", "size"),
        순익평균=("net_%", "mean"),
        승률=("net_%", lambda s: (s > 0).mean() * 100),
        TP률=("outcome", lambda s: (s == "tp").mean() * 100),
        SL률=("outcome", lambda s: (s == "stop").mean() * 100),
    ).reset_index()
    agg.insert(0, "유니버스", label)
    for c in ["순익평균", "승률", "TP률", "SL률"]:
        agg[c] = agg[c].round(1)
    # 버킷 시간순 정렬
    agg["_o"] = agg["bucket"].map(_hm)
    return agg.sort_values("_o").drop(columns="_o").reset_index(drop=True)


def summarize(detail_all, detail_filt, ts):
    """콘솔 출력 + 집계 CSV용 DataFrame 생성."""
    a_all = aggregate(detail_all, "폭증후보전체")
    a_filt = aggregate(detail_filt, "캔들+갭부합픽")
    buckets = pd.concat([a_all, a_filt], ignore_index=True)

    # 캔들신호 결합: 버킷×신호 (필터 전 전체 기준 — 신호별 타점 비교)
    byverdict = pd.DataFrame()
    if not detail_all.empty and "verdict" in detail_all.columns:
        gv = detail_all.groupby(["bucket", "verdict"])
        byverdict = gv.agg(거래수=("net_%", "size"),
                           순익평균=("net_%", "mean"),
                           승률=("net_%", lambda s: (s > 0).mean() * 100)).reset_index()
        byverdict["순익평균"] = byverdict["순익평균"].round(1)
        byverdict["승률"] = byverdict["승률"].round(1)
        byverdict["_o"] = byverdict["bucket"].map(_hm)
        byverdict = byverdict.sort_values(["_o", "verdict"]).drop(columns="_o").reset_index(drop=True)
    return buckets, byverdict


def print_report(buckets, byverdict, ts, span):
    print("\n" + "=" * 80)
    print(f"  프리마켓 최적 타점 타이밍 통계 검증  —  {span}")
    print(f"  청산: TP +{ts['tp_pct']:.0f}% / SL -{ts['stop_pct']:.0f}% 우선, 미터치 09:30 개장가 / "
          f"왕복비용 {ts['cost_pct']:.1f}%")
    print("=" * 80)
    if buckets.empty:
        print("  집계할 거래가 없습니다.")
        return
    for label in buckets["유니버스"].unique():
        sub = buckets[buckets["유니버스"] == label]
        print(f"\n  [{label}]  (버킷별 ET 진입시각)")
        print(sub[["bucket", "거래수", "순익평균", "승률", "TP률", "SL률"]].to_string(index=False))
        best = sub.loc[sub["순익평균"].idxmax()]
        print(f"   → 최적 타점: {best['bucket']} ET  (순익평균 {best['순익평균']:+.1f}% · "
              f"승률 {best['승률']:.0f}% · n={int(best['거래수'])})")
    if not byverdict.empty:
        print("\n  [버킷 × 캔들신호 결합]  (폭증후보전체 기준)")
        print(byverdict.to_string(index=False))
    print("\n" + "-" * 80)
    print("  ※ 과거 통계는 미래를 보장하지 않습니다. 프리마켓은 유동성이 얇아 실제 체결가가")
    print("    시뮬 가정과 다를 수 있습니다(슬리피지·미체결). 참고용 타점 가이드입니다.")


# --------------------------------------------------------------------------- #
# 데이터 계층 (Polygon) — 키 있을 때만 실행
# --------------------------------------------------------------------------- #
def _cache_dir():
    d = os.path.join(scanner.OUTPUT_DIR, "cache")
    os.makedirs(d, exist_ok=True)
    return d


def cached_grouped(ds, cfg, session):
    path = os.path.join(_cache_dir(), f"grouped_{ds}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    res = scanner.fetch_grouped_day(ds, cfg["polygon_api_key"], session,
                                    cfg["scan"].get("rate_sleep_seconds", 13))
    if res:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(res, f)
    return res


def cached_premkt_minutes(ticker, day, cfg, session):
    """(ticker, day) 프리마켓 분봉을 [{'min','o','h','l','c'}]로. 캐싱. 09:30 개장가도."""
    path = os.path.join(_cache_dir(), f"min_{ticker}_{day}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    url = POLY_MIN.format(t=ticker, f=day, to=day)
    params = {"adjusted": "true", "sort": "asc", "limit": 50000,
              "apiKey": cfg["polygon_api_key"]}
    try:
        r = session.get(url, params=params, timeout=30)
    except Exception:
        return None
    if r.status_code == 429:
        time.sleep(15)
        try:
            r = session.get(url, params=params, timeout=30)
        except Exception:
            return None
    if r.status_code != 200:
        return None
    results = r.json().get("results", []) or []
    time.sleep(cfg["scan"].get("rate_sleep_seconds", 13))
    bars, open_px = [], None
    for it in results:
        t_ms = it.get("t")
        if t_ms is None or ET is None:
            continue
        et = dt.datetime.fromtimestamp(t_ms / 1000, tz=ET)
        if et.strftime("%Y-%m-%d") != day:
            continue
        hm = et.strftime("%H:%M")
        if hm == OPEN_ET and open_px is None:
            open_px = it.get("o")
        if _hm("04:00") <= _hm(hm) < _hm(OPEN_ET):
            bars.append({"min": hm, "o": it.get("o"), "h": it.get("h"),
                         "l": it.get("l"), "c": it.get("c")})
    out = {"bars": bars, "open_px": open_px}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    return out


def collect_daily_panel(cfg, session, ts):
    """surge 재계산용 일봉 패널 + 신호일→평가일 맵 구성."""
    need = ts["lookback_trading_days"] + cfg["scan"].get("lookback_trading_days", 7) + 6
    days = []
    cursor = dt.date.today() - dt.timedelta(days=1)
    collected = {}
    print(f"[1/4] grouped daily 수집(캐시 우선, 목표 {need} 거래일)...")
    scanned = 0
    while len(collected) < need and scanned < need + 20:
        if cursor.weekday() < 5:
            dsx = cursor.isoformat()
            res = cached_grouped(dsx, cfg, session)
            if res:
                collected[dsx] = res
                days.append(dsx)
        cursor -= dt.timedelta(days=1)
        scanned += 1
    days = sorted(collected.keys())
    rows = []
    for dsx in days:
        for it in collected[dsx]:
            rows.append({"ticker": it.get("T"), "date": dsx,
                         "open": it.get("o", 0) or 0, "high": it.get("h", 0) or 0,
                         "low": it.get("l", 0) or 0, "close": it.get("c", 0) or 0,
                         "volume": it.get("v", 0) or 0})
    panel = pd.DataFrame(rows).dropna(subset=["ticker"]).sort_values(["ticker", "date"])
    return panel, days


def candidates_for_day(panel, days, idx, cfg, ts):
    """days[idx]를 신호일로 그날 폭증 상위 N 후보 + 캔들신호 산출."""
    sc = cfg["scan"]
    sig_day = days[idx]
    lb = sc.get("lookback_trading_days", 7)
    lo = max(0, idx - lb)
    win_days = days[lo:idx + 1]
    sub = panel[panel["date"].isin(win_days)]
    out = []
    for ticker, g in sub.groupby("ticker"):
        g = g.sort_values("date")
        latest = g[g["date"] == sig_day]
        if latest.empty:
            continue
        latest = latest.iloc[0]
        prior = g[g["date"] < sig_day]
        if len(prior) < 2:
            continue
        vols = prior["volume"].tolist()
        baseline = median(vols)
        if baseline <= 0:
            continue
        lv, lc = float(latest["volume"]), float(latest["close"])
        ratio = lv / baseline
        if not (sc["price_min"] <= lc <= sc["price_max"]):
            continue
        if baseline < sc["min_baseline_avg_volume"] or lv < sc["min_latest_volume"]:
            continue
        if lv * lc < sc["min_latest_dollar_volume"]:
            continue
        sig = candle_signals.evaluate(g, lookback=lb)
        out.append({"ticker": ticker, "ratio": ratio, "prior_close": lc,
                    "verdict": sig["verdict"], "candle_pos": sig["position"]})
    out = sorted(out, key=lambda r: r["ratio"], reverse=True)[:ts["universe_top_n"]]
    return sig_day, out


def run_live(cfg, ts):
    import requests
    session = requests.Session()
    panel, days = collect_daily_panel(cfg, session, ts)
    if len(days) < 5:
        sys.exit("[오류] 거래일 데이터 부족. Polygon 키/네트워크를 확인하세요.")

    # 평가 대상: 마지막 lookback 거래일을 신호일로, 그 다음 거래일을 평가일로
    start = max(1, len(days) - ts["lookback_trading_days"])
    rows_all, rows_filt = [], []
    print(f"[2/4] 신호일별 후보 산출 + 프리마켓 분봉 시뮬...")
    for idx in range(start, len(days) - 1):
        sig_day, cands = candidates_for_day(panel, days, idx, cfg, ts)
        eval_day = days[idx + 1]
        for c in cands:
            md = cached_premkt_minutes(c["ticker"], eval_day, cfg, session)
            if not md or not md.get("bars"):
                continue
            bars, open_px = md["bars"], md.get("open_px")
            # 갭(05:30 기준가 vs 전일종가)
            ref = next((b["o"] for b in bars if _hm(b["min"]) >= _hm("05:30")), None)
            gap = ((ref - c["prior_close"]) / c["prior_close"] * 100) if ref else None
            for r in simulate_candidate(bars, open_px, ts):
                rec = {"signal_day": sig_day, "eval_day": eval_day,
                       "ticker": c["ticker"], "ratio": round(c["ratio"], 1),
                       "verdict": c["verdict"], "candle_pos": c["candle_pos"],
                       "gap_%": round(gap, 1) if gap is not None else None, **r}
                rows_all.append(rec)
                if (c["verdict"] in ts["require_verdicts"]
                        and gap is not None and gap >= ts["gap_min_pct"]):
                    rows_filt.append(rec)
    return pd.DataFrame(rows_all), pd.DataFrame(rows_filt), f"{days[start]} ~ {days[-1]}"


# --------------------------------------------------------------------------- #
# 합성 자체검증 (API 불필요)
# --------------------------------------------------------------------------- #
def selftest():
    import random
    rnd = random.Random(11)
    ts = ts_config({"scan": {}})
    detail_all, detail_filt = [], []
    verds = ["강한매수", "매수관심", "중립", "매도주의"]
    for d in range(60):
        for k in range(5):
            # 종목별 프리마켓 분봉 합성: 05:30~09:29
            base = rnd.uniform(2, 12)
            drift = rnd.uniform(-0.03, 0.05)   # 종목별 추세
            bars, px = [], base
            for m in range(_hm("05:30"), _hm("09:30")):
                hm = f"{m // 60:02d}:{m % 60:02d}"
                o = px
                px = max(0.1, px * (1 + rnd.gauss(drift / 60, 0.004)))
                hi, lo = max(o, px) * (1 + abs(rnd.gauss(0, 0.003))), min(o, px) * (1 - abs(rnd.gauss(0, 0.003)))
                bars.append({"min": hm, "o": o, "h": hi, "l": lo, "c": px})
            open_px = px * (1 + rnd.gauss(0, 0.01))
            verdict = rnd.choice(verds)
            gap = rnd.uniform(0, 15)
            for r in simulate_candidate(bars, open_px, ts):
                rec = {"ticker": f"T{k}", "verdict": verdict, "gap_%": gap, **r}
                detail_all.append(rec)
                if verdict in ts["require_verdicts"] and gap >= ts["gap_min_pct"]:
                    detail_filt.append(rec)
    da, df_ = pd.DataFrame(detail_all), pd.DataFrame(detail_filt)
    buckets, byverdict = summarize(da, df_, ts)
    print_report(buckets, byverdict, ts, "SELFTEST (합성 60일×5종목)")
    print(f"\n[자체검증] detail_all={len(da)}행, filtered={len(df_)}행 — 로직 정상 동작.")


# --------------------------------------------------------------------------- #
# 메인
# --------------------------------------------------------------------------- #
def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg == "selftest":
        selftest()
        return

    cfg = scanner.load_config()
    ts = ts_config(cfg)
    if arg and arg.isdigit():
        ts["lookback_trading_days"] = int(arg)

    detail_all, detail_filt, span = run_live(cfg, ts)
    print("[3/4] 집계...")
    buckets, byverdict = summarize(detail_all, detail_filt, ts)

    os.makedirs(scanner.OUTPUT_DIR, exist_ok=True)
    detail_all.to_csv(os.path.join(scanner.OUTPUT_DIR, "timing_study_detail.csv"),
                      index=False, encoding="utf-8-sig")
    buckets.to_csv(os.path.join(scanner.OUTPUT_DIR, "timing_study_buckets.csv"),
                   index=False, encoding="utf-8-sig")
    print("[4/4] 리포트")
    print_report(buckets, byverdict, ts, span)
    print(f"\n  저장: output/timing_study_detail.csv · output/timing_study_buckets.csv")


# 지연 import (selftest 시 무거운 의존 회피)
import scanner            # noqa: E402
import candle_signals     # noqa: E402

if __name__ == "__main__":
    main()
