# -*- coding: utf-8 -*-
"""
거래량 폭증주 스캐너 (Volume Surge Scanner)
-------------------------------------------------
Polygon.io 의 'grouped daily' 엔드포인트로 미국 증시 전 종목의 일봉을
하루 1회 호출로 받아와, 최근 N거래일 동안 거래량이 평소 대비 몇 배
폭증했는지 계산해 소형주/페니주 위주로 후보를 골라낸다.

매매 신호가 아니라 '후보 종목 스캐너'다. 결과 종목은 변동성이 극심하므로
반드시 본인 판단으로 검증 후 소액·손절 기준을 정해 대응할 것.
"""

import os
import sys
import json
import time
import datetime as dt
from statistics import median

import requests
import pandas as pd

# Windows 콘솔 한글 깨짐 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

POLY_GROUPED = "https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks/{date}"
FINNHUB_QUOTE = "https://finnhub.io/api/v1/quote"


# --------------------------------------------------------------------------- #
# 설정 로드
# --------------------------------------------------------------------------- #
def load_config():
    if not os.path.exists(CONFIG_PATH):
        sys.exit(
            "[오류] config.json 이 없습니다.\n"
            "       config.example.json 을 config.json 으로 복사하고 "
            "Polygon API 키를 채워주세요."
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # 환경변수가 있으면 우선 적용 (키를 파일에 두기 싫을 때)
    cfg["polygon_api_key"] = os.environ.get("POLYGON_API_KEY", cfg.get("polygon_api_key", "")).strip()
    cfg["finnhub_api_key"] = os.environ.get("FINNHUB_API_KEY", cfg.get("finnhub_api_key", "")).strip()

    if not cfg["polygon_api_key"] or "여기에" in cfg["polygon_api_key"]:
        sys.exit("[오류] config.json 의 polygon_api_key 가 비어 있습니다.")
    return cfg


# --------------------------------------------------------------------------- #
# Polygon: 특정 날짜의 전 종목 일봉
# --------------------------------------------------------------------------- #
def fetch_grouped_day(date_str, api_key, session, rate_sleep):
    """해당 날짜의 전 종목 일봉을 받아온다. 휴장일이면 빈 리스트."""
    url = POLY_GROUPED.format(date=date_str)
    params = {"adjusted": "true", "apiKey": api_key}
    for attempt in range(4):
        try:
            r = session.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            print(f"  [{date_str}] 네트워크 오류: {e} (재시도)")
            time.sleep(2)
            continue

        if r.status_code == 429:  # rate limit
            wait = 15 * (attempt + 1)
            print(f"  [{date_str}] 호출 제한(429). {wait}s 대기 후 재시도...")
            time.sleep(wait)
            continue
        if r.status_code != 200:
            print(f"  [{date_str}] HTTP {r.status_code}: {r.text[:120]}")
            return []

        data = r.json()
        results = data.get("results", []) or []
        time.sleep(rate_sleep)  # 무료 티어 호출 제한(5/분) 보호
        return results

    print(f"  [{date_str}] 재시도 초과. 건너뜀.")
    return []


def collect_recent_days(cfg, session):
    """최근 거래일 N일치 데이터를 모은다. (주말/휴장일은 자동으로 빈 응답)
    거래량 폭증(lookback) + 평균거래대금(dollar_baseline_days) 둘 다 커버하도록
    충분히 수집한다."""
    lookback = cfg["scan"]["lookback_trading_days"]
    dol_days = cfg["scan"].get("dollar_baseline_days", 10)
    n_days = max(lookback, dol_days + 1)   # 평균거래대금 10일치엔 직전 10거래일 필요
    api_key = cfg["polygon_api_key"]

    # 무료 티어는 5호출/분 → 호출당 ~13초. 유료면 config로 조정 가능.
    rate_sleep = cfg["scan"].get("rate_sleep_seconds", 13)

    collected = {}  # date_str -> results
    # 데이터 지연(EOD 반영)을 감안해 어제부터 거꾸로 탐색
    cursor = dt.date.today() - dt.timedelta(days=1)
    max_calendar_days = n_days + 12  # 주말/휴일 여유분
    scanned = 0

    print(f"[1/3] Polygon grouped daily 수집 (목표 {n_days} 거래일)...")
    while len(collected) < n_days and scanned < max_calendar_days:
        # 주말은 호출 자체를 건너뜀
        if cursor.weekday() < 5:  # 0=월 ... 4=금
            ds = cursor.isoformat()
            res = fetch_grouped_day(ds, api_key, session, rate_sleep)
            if res:
                collected[ds] = res
                print(f"  [{ds}] {len(res):,} 종목 수신  ({len(collected)}/{n_days})")
            else:
                print(f"  [{ds}] 데이터 없음(휴장/지연)")
        cursor -= dt.timedelta(days=1)
        scanned += 1

    if len(collected) < 2:
        sys.exit("[오류] 비교에 필요한 거래일 데이터가 부족합니다(2일 미만).")
    return collected


# --------------------------------------------------------------------------- #
# 거래량 폭증 계산
# --------------------------------------------------------------------------- #
def build_dataframe(collected):
    """{date: results} -> long DataFrame[ticker, date, v, c]"""
    rows = []
    for ds, results in collected.items():
        for it in results:
            rows.append(
                {
                    "ticker": it.get("T"),
                    "date": ds,
                    "volume": it.get("v", 0) or 0,
                    "close": it.get("c", 0) or 0,
                    "open": it.get("o", 0) or 0,
                    "high": it.get("h", 0) or 0,
                    "low": it.get("l", 0) or 0,
                }
            )
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["ticker"])
    df = df.sort_values(["ticker", "date"])
    return df


def compute_surge(df, cfg):
    import candle_signals  # 일봉 캔들 신호 필터 (파동연상/캔들개론 기반)

    sc = cfg["scan"]
    method = sc.get("baseline_method", "median")
    lookback = sc.get("lookback_trading_days", 7)
    dol_days = sc.get("dollar_baseline_days", 10)
    latest_date = df["date"].max()

    # 캔들 신호 필터 설정 (없어도 동작 — 기본은 주석만, 필터 미적용)
    cf = sc.get("candle_filter", {})
    cf_lookback = cf.get("lookback", lookback)
    cf_require = cf.get("require_verdicts", [])  # 예: ["강한매수","매수관심"] 면 그 외 제외

    out = []
    for ticker, g in df.groupby("ticker"):
        g = g.sort_values("date")
        latest = g[g["date"] == latest_date]
        if latest.empty:
            continue
        latest = latest.iloc[0]
        prior = g[g["date"] < latest_date]
        if len(prior) < 2:
            continue  # 비교 기준 부족

        # 거래량 폭증 배율: 직전 (lookback-1)거래일 거래량 기준 (수집량 늘려도 동일 유지)
        vol_prior = prior.tail(max(2, lookback - 1))["volume"].tolist()
        baseline = median(vol_prior) if method == "median" else (sum(vol_prior) / len(vol_prior))
        if baseline <= 0:
            continue

        latest_vol = float(latest["volume"])
        latest_close = float(latest["close"])
        ratio = latest_vol / baseline
        dollar_vol = latest_vol * latest_close

        # 신호일 갭(전일종가 대비 시초): 특성분석상 갭하락 후보가 다음날 최악(-4.7%).
        prev_close = float(prior.iloc[-1]["close"])
        signal_gap = ((float(latest["open"]) - prev_close) / prev_close * 100
                      if prev_close > 0 and latest["open"] else 0.0)

        # 평균 거래대금(직전 dol_days 거래일) + 거래대금 폭증 배율
        dprior = prior.tail(dol_days)
        d_series = (dprior["volume"] * dprior["close"])
        avg_dollar_vol = float(d_series.mean()) if len(dprior) else 0.0
        dollar_surge_x = (dollar_vol / avg_dollar_vol) if avg_dollar_vol > 0 else 0.0

        # 가격대 필터 (소형주/페니주)
        if not (sc["price_min"] <= latest_close <= sc["price_max"]):
            continue
        # 노이즈 제거 필터
        if baseline < sc["min_baseline_avg_volume"]:
            continue
        if latest_vol < sc["min_latest_volume"]:
            continue
        if dollar_vol < sc["min_latest_dollar_volume"]:
            continue
        # 갭 하한 필터(옵션): min_signal_gap_pct 가 설정되면 신호일 갭하락/약갭 후보 제외.
        # 기본 None(미적용). 특성분석(feature_analysis) 근거 — 갭상승 코호트 승률 우위.
        min_gap = sc.get("min_signal_gap_pct", None)
        if min_gap is not None and signal_gap < min_gap:
            continue

        day_change = 0.0
        if latest["open"]:
            day_change = (latest_close - latest["open"]) / latest["open"] * 100

        # 캔들 신호 평가 (최신봉 형태 + 하이로우 기준선상 위치)
        sig = candle_signals.evaluate(g, lookback=cf_lookback)
        if cf_require and sig["verdict"] not in cf_require:
            continue  # 요구 판정에 미달 → 후보에서 제외

        out.append(
            {
                "ticker": ticker,
                "ratio": round(ratio, 1),
                "latest_close": round(latest_close, 3),
                "latest_volume": int(latest_vol),
                "baseline_volume": int(baseline),
                "dollar_volume_M": round(dollar_vol / 1e6, 2),
                "avg_dollar_vol_10d_M": round(avg_dollar_vol / 1e6, 2),
                "dollar_surge_x": round(dollar_surge_x, 1),
                "signal_gap_%": round(signal_gap, 1),
                "intraday_chg_%": round(day_change, 1),
                "candle_signal": sig["verdict"],
                "candle_shape": sig["shape"],
                "candle_pos": sig["position"],
                "close_pos": sig["close_pos"],
                "candle_score": sig["score"],
                "latest_date": latest_date,
            }
        )

    res = pd.DataFrame(out).sort_values("ratio", ascending=False)
    return res, latest_date


# --------------------------------------------------------------------------- #
# Finnhub: 상위 후보 실시간(프리마켓) 시세 보강 (선택)
# --------------------------------------------------------------------------- #
def enrich_with_finnhub(df, cfg, session):
    key = cfg.get("finnhub_api_key", "")
    if not key or df.empty:
        return df
    print("[3/3] Finnhub 실시간 시세 보강(상위 후보)...")
    cur, pct = [], []
    for t in df["ticker"].tolist():
        try:
            r = session.get(FINNHUB_QUOTE, params={"symbol": t, "token": key}, timeout=15)
            q = r.json() if r.status_code == 200 else {}
        except requests.RequestException:
            q = {}
        cur.append(q.get("c"))
        pct.append(q.get("dp"))
        time.sleep(1.1)  # 60/분 제한 보호
    df = df.copy()
    df["live_price"] = cur
    df["live_chg_%"] = pct
    return df


# --------------------------------------------------------------------------- #
# 메인
# --------------------------------------------------------------------------- #
def main():
    cfg = load_config()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    session = requests.Session()

    collected = collect_recent_days(cfg, session)

    print("[2/3] 거래량 폭증 비율 계산...")
    df = build_dataframe(collected)
    res, latest_date = compute_surge(df, cfg)

    sc = cfg["scan"]
    top_n = sc.get("top_n", 40)
    res_top = res.head(top_n)

    surged = res[res["ratio"] >= sc["volume_surge_threshold"]]
    watch = res[(res["ratio"] >= sc["watch_threshold"]) & (res["ratio"] < sc["volume_surge_threshold"])]

    # 상위 후보만 Finnhub 보강
    res_top = enrich_with_finnhub(res_top, cfg, session)

    stamp = latest_date
    csv_path = os.path.join(OUTPUT_DIR, f"surge_{stamp}.csv")
    res.to_csv(csv_path, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 70)
    print(f"  거래량 폭증주 스캔 결과  (기준일: {latest_date})")
    print(f"  비교기간: 최근 {sc['lookback_trading_days']} 거래일 / "
          f"가격대 ${sc['price_min']}~${sc['price_max']}")
    print("=" * 70)
    print(f"  {sc['volume_surge_threshold']:.0f}배 이상 폭증: {len(surged)} 종목")
    print(f"  {sc['watch_threshold']:.0f}~{sc['volume_surge_threshold']:.0f}배 관찰: {len(watch)} 종목")
    print("-" * 70)

    show_cols = ["ticker", "ratio", "latest_close", "dollar_volume_M",
                 "avg_dollar_vol_10d_M", "dollar_surge_x", "intraday_chg_%",
                 "candle_signal", "candle_pos", "close_pos"]
    if "live_price" in res_top.columns:
        show_cols += ["live_price", "live_chg_%"]

    if not res_top.empty:
        with pd.option_context("display.max_rows", None, "display.width", 200):
            print(res_top[show_cols].to_string(index=False))
    else:
        print("  조건을 만족하는 종목이 없습니다. config.json 임계값을 낮춰보세요.")

    print("-" * 70)
    print(f"  전체 결과 CSV 저장: {csv_path}")
    print("=" * 70)
    print("  ⚠ 본 목록은 매매 신호가 아닙니다. 폭증주는 변동성이 극심합니다.")
    print("    소액·손절선 설정 등 리스크 관리를 반드시 본인 판단으로 하세요.")


if __name__ == "__main__":
    main()
