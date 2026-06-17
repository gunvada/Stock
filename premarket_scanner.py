# -*- coding: utf-8 -*-
"""
프리마켓 갭상승+거래량 모멘텀 스캐너  (본장 파이프라인과 분리)
================================================================
설계:
  · 유니버스 : 본장 스캐너 산출물(output/surge_*.csv 또는 pullback_*.csv) 상위 N개.
               (무료로는 '전 종목 프리마켓 일괄 조회'가 불가 → 본장에서 좁힌 후보만 평가)
  · 데이터   : 각 후보의 프리마켓을 yfinance(prepost=True)로 조회. API 키 불필요.
  · 셋업     : 전일 종가 대비 '갭상승' + '프리마켓 거래량 동반' (개장 모멘텀 연결 노림).
  · 매매창   : KST 18:30–22:00  =  ET 05:30–09:00 (EDT).

본장(눌림목)과 별개 파이프라인이다. 출력/장부/워크플로 모두 분리:
  출력 : output/premarket_<날짜>.csv
  채점 : premarket_verify.py → output/premarket_ledger.csv

사용법:
  python premarket_scanner.py              # 오늘 프리마켓 스캔(라이브)
  python premarket_scanner.py 2026-06-16   # 특정일 프리마켓 평가(과거 검증용)
"""
import os
import sys
import glob
import datetime as dt

import pandas as pd

import scanner  # load_config, OUTPUT_DIR 재사용 (공통 데이터층)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 프리마켓 창 (America/New_York). 회원 우선순위 창과 일치.
PM_START, PM_END = "05:30", "09:00"


def pm_config(cfg):
    """config.json['premarket'] 기본값 채우기 (섹션 없어도 동작)."""
    pm = cfg.setdefault("premarket", {})
    pm.setdefault("universe_top_n", 6)       # 본장 후보 중 상위 N개만 평가(엣지가 상위에 집중)
    pm.setdefault("gap_min_pct", 5.0)        # 전일종가 대비 최소 갭상승 %
    # 야후는 프리마켓 '거래량'을 제공하지 않으므로(1분봉 Volume=0),
    # 프리마켓 1분봉 '개수'를 활동량(유동성) 프록시로 사용한다. 정밀 거래량은 유료 필요.
    pm.setdefault("min_pm_bars", 30)         # 프리마켓 최소 활동 분봉 수
    pm.setdefault("price_min", 0.50)
    pm.setdefault("price_max", 20.0)
    pm.setdefault("tp_pct", 10.0)
    pm.setdefault("stop_pct", 8.0)
    pm.setdefault("performance_lookback_days", 60)  # 성과 관리 집계 창(달력일)
    # 캔들 신호 부합 종목만 추천 픽으로 (surge CSV의 candle_signal 기준).
    # 빈 리스트면 필터 미적용(전 후보). 컬럼 없으면 자동 통과.
    pm.setdefault("require_verdicts", ["강한매수", "매수관심"])
    # 타이밍 스터디(20거래일, 06:30 ET 진입이 +3.0%/거래로 최적)로 확정한 권장 진입 시각.
    pm.setdefault("entry_time_et", "06:30")   # KST 19:30
    return pm


def load_universe(top_n, require_verdicts=None):
    """가장 최근 본장 산출물에서 (ticker, prior_close, signal_date) 유니버스 구성.
    require_verdicts 가 주어지고 surge CSV에 candle_signal 컬럼이 있으면 신호 부합 종목만."""
    files = sorted(glob.glob(os.path.join(scanner.OUTPUT_DIR, "surge_*.csv")) +
                   glob.glob(os.path.join(scanner.OUTPUT_DIR, "pullback_*.csv")))
    # 날짜형 파일만 (pullback_backtest_*.csv 등 제외)
    import re
    files = [f for f in files
             if re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(f))]
    if not files:
        sys.exit("[오류] 본장 산출물(surge_*/pullback_*.csv)이 없습니다. 본장 스캐너 먼저 실행.")
    src = files[-1]
    sig_date = re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(src)).group(1)
    df = pd.read_csv(src)
    # surge: ticker,ratio,latest_close / pullback: ticker,c
    close_col = "latest_close" if "latest_close" in df.columns else "c"

    # Polygon 테스트 심볼 제외(recommend.py 와 동일)
    TEST_TICKERS = {"ZVZZT", "ZWZZT", "ZXYZ.A", "ZBZX", "ZJZZT", "ZTST", "ZXZZT", "ZVV"}
    df = df[~df["ticker"].isin(TEST_TICKERS)]

    # 캔들 신호 필터 (컬럼 존재 시에만)
    note = ""
    if require_verdicts and "candle_signal" in df.columns:
        before = len(df)
        df = df[df["candle_signal"].isin(require_verdicts)]
        note = f" · 캔들신호 {require_verdicts} 부합 {len(df)}/{before}"
    elif require_verdicts:
        note = " · (candle_signal 컬럼 없음 → 신호필터 미적용)"

    # 정렬: recommend.py 와 동일한 '종합점수'(마감강도+신호형태+추세위치+폭증배율)로 통일.
    # candle_score 가 있으면 rank_score = candle_score + log10(ratio), 없으면 ratio 폴백.
    import numpy as np
    if "candle_score" in df.columns and "ratio" in df.columns:
        df = df.copy()
        df["rank_score"] = (df["candle_score"]
                            + np.log10(df["ratio"].clip(lower=1))).round(2)
        df = df.sort_values("rank_score", ascending=False)
        note += " · 정렬=종합점수"
    else:
        rank_col = "ratio" if "ratio" in df.columns else ("vol_ratio" if "vol_ratio" in df.columns else None)
        if rank_col:
            df = df.sort_values(rank_col, ascending=False)

    keep_cols = ["ticker", close_col]
    if "candle_signal" in df.columns:
        keep_cols.append("candle_signal")
    uni = df[keep_cols].head(top_n).rename(columns={close_col: "prior_close"})
    print(f"[1/3] 유니버스: {os.path.basename(src)} 상위 {len(uni)}개 (신호일 {sig_date}){note}")
    return uni, sig_date, src


def fetch_pm(tickers, target_date):
    """yfinance 1분봉(prepost)으로 target_date 프리마켓 구간 일괄 조회 → {t: DataFrame(NY tz)}."""
    import yfinance as yf
    start = dt.date.fromisoformat(target_date)
    end = start + dt.timedelta(days=1)
    raw = yf.download(tickers, start=start.isoformat(), end=end.isoformat(),
                      interval="1m", prepost=True, group_by="ticker",
                      threads=True, progress=False, auto_adjust=False)
    out = {}
    for t in tickers:
        try:
            sub = raw[t] if len(tickers) > 1 else raw
            sub = sub.dropna(how="all")
            if sub.empty:
                continue
            sub = sub.set_index(sub.index.tz_convert("America/New_York"))
            sub = sub[sub.index.strftime("%Y-%m-%d") == target_date]
            pm = sub.between_time("04:00", "09:29")  # 프리마켓 전체(개장 전)
            if not pm.empty:
                out[t] = pm
        except Exception:
            continue
    return out


def main():
    cfg = scanner.load_config()
    pm = pm_config(cfg)
    arg_date = sys.argv[1] if len(sys.argv) > 1 else None

    uni, sig_date, _ = load_universe(pm["universe_top_n"], pm.get("require_verdicts"))
    # 평가 대상일: 인자 우선, 없으면 '신호일 다음 거래일'(주말 건너뜀)
    if arg_date:
        target = arg_date
    else:
        d = dt.date.fromisoformat(sig_date)
        d += dt.timedelta(days=1)
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        target = d.isoformat()

    print(f"[2/3] {target} 프리마켓 조회 (yfinance, {len(uni)}종목)...")
    frames = fetch_pm(list(uni["ticker"]), target)

    rows = []
    pc_map = dict(zip(uni["ticker"], uni["prior_close"]))
    cs_map = dict(zip(uni["ticker"], uni["candle_signal"])) if "candle_signal" in uni.columns else {}
    for t, f in frames.items():
        prior_close = float(pc_map.get(t, 0) or 0)
        if prior_close <= 0:
            continue
        pm_last = float(f["Close"].iloc[-1])
        pm_high = float(f["High"].max())
        pm_low = float(f["Low"].min())
        pm_bars = int(len(f))  # 활동량 프록시 (야후 프리마켓 거래량 미제공)
        gap = (pm_last - prior_close) / prior_close * 100
        if gap < pm["gap_min_pct"]:
            continue
        if pm_bars < pm["min_pm_bars"]:
            continue
        if not (pm["price_min"] <= pm_last <= pm["price_max"]):
            continue
        rows.append({
            "ticker": t,
            "candle_signal": cs_map.get(t, ""),
            "prior_close": round(prior_close, 3),
            "pm_price": round(pm_last, 3),
            "gap_%": round(gap, 1),
            "pm_high": round(pm_high, 3),
            "pm_bars": pm_bars,
            "매수참고": round(pm_last, 3),
            "손절": round(pm_last * (1 - pm["stop_pct"] / 100), 3),
            "익절목표": round(pm_last * (1 + pm["tp_pct"] / 100), 3),
        })

    out = pd.DataFrame(rows).sort_values("gap_%", ascending=False) if rows else pd.DataFrame()
    path = os.path.join(scanner.OUTPUT_DIR, f"premarket_{target}.csv")
    out.to_csv(path, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 80)
    print(f"  프리마켓 갭상승+거래량 모멘텀  —  {target} (창 KST 18:30–22:00 / ET 05:30–09:00)")
    print(f"  필터: 갭 ≥{pm['gap_min_pct']:.0f}% · 프리마켓활동 ≥{pm['min_pm_bars']}분봉 · "
          f"${pm['price_min']}~{pm['price_max']}")
    print(f"  ★ 권장 진입: {pm['entry_time_et']} ET (KST 19:30) — 타이밍 스터디 확정 최적 타점")
    print("=" * 80)
    if out.empty:
        print("  조건 충족 종목 없음. (해당일 프리마켓 갭상승 모멘텀 없음 — 정상)")
    else:
        print(out[["ticker", "prior_close", "pm_price", "gap_%", "pm_bars",
                   "매수참고", "손절", "익절목표"]].to_string(index=False))
    print("-" * 80)
    print(f"  저장: {path}")
    print("  ※ 진입=프리마켓 강세 확인 후 매수참고가 부근, 익절/손절은 컬럼값, 창 마감(09:00 ET) 전 청산.")
    print("  ※ 프리마켓은 유동성이 얇아 슬리피지·미체결 위험이 큼. 참고용 후보.")


if __name__ == "__main__":
    main()
