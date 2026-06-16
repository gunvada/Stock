# -*- coding: utf-8 -*-
"""
교차 검증 + 프리마켓 시세 (Cross-Validation & Pre-market)
----------------------------------------------------------
scanner.py 가 만든 최신 결과(output/surge_*.csv)의 상위 후보를 받아,
서로 독립적인 무료 채널로 같은 값을 다시 계산해 신뢰도를 점검한다.

채널:
  1) Polygon      : scanner 결과(기준값)
  2) Yahoo(yfinance) : 독립 일별 거래량 재계산 + 프리마켓/실시간 시세  (키 불필요)
  3) Stooq        : 일별 거래량 3차 대조  (키 불필요, 마이크로캡은 없을 수 있음 → 베스트에포트)
  4) Finnhub      : 실시간 시세 한 채널 더  (config 에 무료 키 있으면)

판정:
  ✅ CONFIRMED : Yahoo 가 폭증을 독립 확인 + 거래량 채널 간 편차가 허용치 이내
  ⚠ CHECK     : 채널 불일치 / 데이터 누락 → 사람이 직접 재확인 필요
"""

import os
import sys
import io
import json
import time
import glob
from statistics import median

import requests
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
FINNHUB_QUOTE = "https://finnhub.io/api/v1/quote"
STOOQ_CSV = "https://stooq.com/q/d/l/?s={sym}.us&i=d"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["finnhub_api_key"] = os.environ.get("FINNHUB_API_KEY", cfg.get("finnhub_api_key", "")).strip()
    v = cfg.setdefault("verify", {})
    v.setdefault("top_n_verify", 25)
    v.setdefault("vol_tolerance_pct", 25.0)   # Polygon↔Yahoo 거래량 허용 편차
    v.setdefault("lookback_trading_days", cfg.get("scan", {}).get("lookback_trading_days", 7))
    v.setdefault("watch_threshold", cfg.get("scan", {}).get("watch_threshold", 10.0))
    v.setdefault("use_stooq", True)
    return cfg


def find_latest_csv():
    files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "surge_*.csv")))
    if not files:
        sys.exit("[오류] output/surge_*.csv 가 없습니다. 먼저 python scanner.py 를 실행하세요.")
    return files[-1]


# ----------------------------- 채널 2: Yahoo ------------------------------- #
def yahoo_batch(tickers, lookback):
    """상위 후보의 일별 거래량을 한 번에 받아 {ticker: DataFrame} 으로 반환."""
    import yfinance as yf
    period = f"{lookback + 6}d"
    data = {}
    try:
        df = yf.download(tickers, period=period, interval="1d",
                         group_by="ticker", auto_adjust=False, progress=False, threads=True)
    except Exception as e:
        print(f"  [Yahoo] 배치 다운로드 실패: {e}")
        return data

    for t in tickers:
        try:
            sub = df[t] if len(tickers) > 1 else df
            sub = sub.dropna(subset=["Volume"])
            if not sub.empty:
                data[t] = sub
        except Exception:
            pass
    return data


def yahoo_ratio(sub, lookback):
    """Yahoo 일봉으로 폭증 배율 재계산. (latest_vol, baseline, ratio)"""
    vols = sub["Volume"].tolist()
    if len(vols) < 3:
        return None
    latest = float(vols[-1])
    prior = [float(v) for v in vols[-(lookback + 1):-1]]  # 직전 거래일들
    if not prior:
        return None
    base = median(prior)
    if base <= 0:
        return None
    return latest, base, latest / base


def yahoo_live(ticker):
    """프리마켓/실시간 가격과 전일대비. (price, chg_pct) — 키 불필요."""
    import yfinance as yf
    try:
        fi = yf.Ticker(ticker).fast_info
        price = fi.get("lastPrice")
        prev = fi.get("previousClose")
        if price and prev:
            return price, (price - prev) / prev * 100
        return price, None
    except Exception:
        return None, None


# ----------------------------- 채널 3: Stooq ------------------------------- #
def stooq_latest_vol(ticker, session):
    try:
        r = session.get(STOOQ_CSV.format(sym=ticker.lower()), timeout=15)
        if r.status_code != 200 or "<" in r.text[:1]:
            return None
        sdf = pd.read_csv(io.StringIO(r.text))
        if "Volume" not in sdf.columns or sdf.empty:
            return None
        return float(sdf["Volume"].iloc[-1])
    except Exception:
        return None


# ----------------------------- 채널 4: Finnhub ----------------------------- #
def finnhub_quote(ticker, key, session):
    try:
        r = session.get(FINNHUB_QUOTE, params={"symbol": ticker, "token": key}, timeout=15)
        if r.status_code != 200:
            return None, None
        q = r.json()
        return q.get("c"), q.get("dp")
    except Exception:
        return None, None


# --------------------------------- 메인 ----------------------------------- #
def pct_dev(values):
    """값 리스트의 중앙값 대비 최대 편차(%)."""
    vals = [v for v in values if v]
    if len(vals) < 2:
        return None
    m = median(vals)
    if m <= 0:
        return None
    return max(abs(v - m) / m * 100 for v in vals)


def main():
    cfg = load_config()
    v = cfg["verify"]
    lookback = v["lookback_trading_days"]
    csv_path = find_latest_csv()
    base = pd.read_csv(csv_path)
    top = base.head(v["top_n_verify"]).copy()
    tickers = top["ticker"].tolist()

    print(f"[검증] 기준 파일: {os.path.basename(csv_path)}  (상위 {len(tickers)} 종목)")
    print(f"[1/3] Yahoo 독립 재계산 + 프리마켓 시세 수집...")
    yh = yahoo_batch(tickers, lookback)

    session = requests.Session()
    fk = cfg.get("finnhub_api_key", "")
    use_stooq = v.get("use_stooq", True)
    if fk:
        print("[2/3] Finnhub 실시간 시세 수집...")
    if use_stooq:
        print("[3/3] Stooq 3차 대조(베스트에포트)...")

    rows = []
    for _, r in top.iterrows():
        t = r["ticker"]
        poly_vol = float(r["latest_volume"])
        poly_ratio = float(r["ratio"])

        # Yahoo
        yf_vol = yf_ratio_v = None
        sub = yh.get(t)
        if sub is not None:
            yr = yahoo_ratio(sub, lookback)
            if yr:
                yf_vol, _, yf_ratio_v = yr
        pm_price, pm_chg = yahoo_live(t)

        # Stooq
        st_vol = stooq_latest_vol(t, session) if use_stooq else None
        if use_stooq:
            time.sleep(0.4)

        # Finnhub
        fh_price = fh_chg = None
        if fk:
            fh_price, fh_chg = finnhub_quote(t, fk, session)
            time.sleep(1.1)

        vol_dev = pct_dev([poly_vol, yf_vol, st_vol])
        n_channels = 1 + sum(x is not None for x in [yf_vol, st_vol])

        # 판정
        if yf_ratio_v is None:
            verdict, reason = "⚠ CHECK", "Yahoo 데이터 없음"
        elif yf_ratio_v < v["watch_threshold"]:
            verdict, reason = "⚠ CHECK", f"Yahoo 배율 {yf_ratio_v:.0f}x (기준 미달)"
        elif vol_dev is not None and vol_dev > v["vol_tolerance_pct"]:
            verdict, reason = "⚠ CHECK", f"거래량 편차 {vol_dev:.0f}%"
        else:
            verdict, reason = "✅ CONFIRMED", f"{n_channels}채널 일치"

        rows.append({
            "ticker": t,
            "poly_ratio": round(poly_ratio, 1),
            "yahoo_ratio": round(yf_ratio_v, 1) if yf_ratio_v else None,
            "vol_dev_%": round(vol_dev, 1) if vol_dev is not None else None,
            "channels": n_channels,
            "premkt_px": round(pm_price, 3) if pm_price else None,
            "premkt_chg_%": round(pm_chg, 1) if pm_chg is not None else None,
            "finnhub_px": fh_price,
            "finnhub_chg_%": fh_chg,
            "verdict": verdict,
            "reason": reason,
        })

    res = pd.DataFrame(rows)
    stamp = base["latest_date"].iloc[0] if "latest_date" in base.columns else "latest"
    out_path = os.path.join(OUTPUT_DIR, f"verified_{stamp}.csv")
    res.to_csv(out_path, index=False, encoding="utf-8-sig")

    confirmed = (res["verdict"] == "✅ CONFIRMED").sum()
    print("\n" + "=" * 78)
    print(f"  교차 검증 결과  ({confirmed}/{len(res)} CONFIRMED)")
    print("=" * 78)
    cols = ["ticker", "poly_ratio", "yahoo_ratio", "vol_dev_%", "channels",
            "premkt_px", "premkt_chg_%"]
    if res["finnhub_px"].notna().any():
        cols += ["finnhub_px", "finnhub_chg_%"]
    cols += ["verdict", "reason"]
    with pd.option_context("display.max_rows", None, "display.width", 220):
        print(res[cols].to_string(index=False))
    print("-" * 78)
    print(f"  저장: {out_path}")
    print("  ✅ = Polygon·Yahoo 두 독립 소스가 폭증을 일치 확인 + 거래량 편차 허용치 이내")
    print("  ⚠  = 소스 불일치/누락 → 매매 전 직접 재확인 필요")
    print("=" * 78)


if __name__ == "__main__":
    main()
