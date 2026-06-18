# -*- coding: utf-8 -*-
"""
한국 거래량 폭증주 스캐너 (KR Volume Surge Scanner)
-------------------------------------------------------------
미국용 scanner.py(Polygon) 의 한국판. Polygon 은 미국 시장만 커버하므로,
한국은 두 개의 무료·키불필요 소스를 조합해 '전 종목' 스캔을 구현한다.

  1) 유니버스 + 당일 스냅샷 : FinanceDataReader.StockListing('KRX')
     → 코스피/코스닥 전 종목의 코드·이름·시장·시총·당일 거래량을 한 번에.
       (KRX 가 OHLCV API 를 로그인 인증제로 바꿔 pykrx 전종목 시세는 막혔다.
        그래서 유니버스/프리필터는 FDR, 과거 거래량은 yfinance 로 분리.)
  2) 과거 일별 거래량 : yfinance 배치 (코드+.KS/.KQ)
     → 프리필터로 추린 후보만 받아 폭증 배율(최신/직전중앙값)을 계산.

폭증 배율 = 최신일 거래량 / 직전 N거래일 거래량의 중앙값.  scanner.py 와 동일.

⚠ 매매 신호가 아니라 후보 스캐너다. 폭증주는 변동성이 극심하다(상·하한가).
   소액·손절선 등 리스크 관리는 반드시 본인 판단으로.
"""

import os
import sys
import json
import datetime as dt
from statistics import median

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

MARKET_SUFFIX = {"KOSPI": ".KS", "KOSDAQ": ".KQ"}


# --------------------------------------------------------------------------- #
# 설정 (scanner.load_config 패턴 — config 의 "kr_scan" 섹션, 전부 선택)
# --------------------------------------------------------------------------- #
def load_config():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    s = cfg.setdefault("kr_scan", {})
    s.setdefault("lookback_trading_days", 7)
    s.setdefault("volume_surge_threshold", 50.0)
    s.setdefault("watch_threshold", 10.0)
    s.setdefault("price_min", 1000)            # 원
    s.setdefault("price_max", 200000)          # 원
    s.setdefault("min_baseline_avg_volume", 30000)     # 주
    s.setdefault("min_latest_volume", 100000)          # 주
    s.setdefault("min_latest_trade_value", 500_000_000)  # 원(거래대금)
    s.setdefault("markets", ["KOSPI", "KOSDAQ"])
    s.setdefault("prefilter_top_by_volume", 700)   # yfinance 부하 제한용 후보 상한
    s.setdefault("yf_chunk", 150)                  # yfinance 배치 분할 크기
    s.setdefault("top_n", 40)
    return cfg


# --------------------------------------------------------------------------- #
# 1) 유니버스 — FDR 전 종목 + 당일 스냅샷으로 1차 추림
# --------------------------------------------------------------------------- #
def build_universe(cfg):
    import FinanceDataReader as fdr
    s = cfg["kr_scan"]
    print("[1/3] FinanceDataReader 전 종목 유니버스 수집...")
    lst = fdr.StockListing("KRX")
    lst = lst[lst["Market"].isin(s["markets"])].copy()
    # 보통주 위주(우선주/기타클래스는 코드 끝자리가 0이 아닌 경우가 많음)
    lst = lst[lst["Code"].str.endswith("0")]
    # 당일 스냅샷 기준 1차 노이즈 컷 (가격대 + 최소 거래량)
    lst = lst[(lst["Close"] >= s["price_min"]) & (lst["Close"] <= s["price_max"])]
    lst = lst[lst["Volume"] >= s["min_latest_volume"]]
    # yfinance 부하 제한: 당일 거래량 상위 N개만 (유동성 있는 종목 우선)
    lst = lst.sort_values("Volume", ascending=False).head(s["prefilter_top_by_volume"])

    suf = MARKET_SUFFIX
    lst["ysym"] = [c + suf[m] for c, m in zip(lst["Code"], lst["Market"])]
    print(f"      → 프리필터 통과 {len(lst)} 종목 (가격 {s['price_min']:,}~{s['price_max']:,}원, "
          f"당일거래량 ≥ {s['min_latest_volume']:,}주)")
    return lst[["Code", "Name", "Market", "ysym"]].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# 2) 과거 거래량 — yfinance 배치(분할)
# --------------------------------------------------------------------------- #
def fetch_history(syms, lookback, chunk):
    import yfinance as yf
    period = f"{lookback + 8}d"
    data = {}
    print(f"[2/3] yfinance 과거 거래량 수집 ({len(syms)} 종목, {len(range(0, len(syms), chunk))} 배치)...")
    for i in range(0, len(syms), chunk):
        part = syms[i:i + chunk]
        try:
            raw = yf.download(part, period=period, interval="1d", auto_adjust=False,
                              progress=False, group_by="ticker", threads=True)
        except Exception as e:
            print(f"      배치 {i//chunk+1} 실패: {e}")
            continue
        for sm in part:
            try:
                sub = raw[sm] if len(part) > 1 else raw
                sub = sub.dropna(subset=["Volume", "Close"])
                if not sub.empty:
                    data[sm] = sub
            except Exception:
                pass
        print(f"      배치 {i//chunk+1}: 누적 {len(data)} 종목 수신")
    return data


# --------------------------------------------------------------------------- #
# 3) 폭증 배율 계산 (scanner.compute_surge 와 동일 로직)
# --------------------------------------------------------------------------- #
def compute_surge(uni, data, cfg):
    s = cfg["kr_scan"]
    look = s["lookback_trading_days"]
    name_of = dict(zip(uni["ysym"], uni["Name"]))
    code_of = dict(zip(uni["ysym"], uni["Code"]))
    mkt_of = dict(zip(uni["ysym"], uni["Market"]))

    out = []
    for sm, sub in data.items():
        vols = sub["Volume"].tolist()
        if len(vols) < 4:
            continue
        latest_vol = float(vols[-1])
        prior = [float(v) for v in vols[-(look + 1):-1]]
        if not prior:
            continue
        base = median(prior)
        if base < s["min_baseline_avg_volume"] or latest_vol < s["min_latest_volume"]:
            continue
        close = float(sub["Close"].iloc[-1])
        if not (s["price_min"] <= close <= s["price_max"]):
            continue
        trade_value = latest_vol * close
        if trade_value < s["min_latest_trade_value"]:
            continue
        ratio = latest_vol / base if base > 0 else 0
        prev_close = float(sub["Close"].iloc[-2])
        chg = (close - prev_close) / prev_close * 100 if prev_close else 0
        out.append({
            "code": code_of.get(sm, ""),
            "name": name_of.get(sm, ""),
            "market": mkt_of.get(sm, ""),
            "ratio": round(ratio, 1),
            "last_close": round(close, 0),
            "day_chg_%": round(chg, 1),
            "latest_vol": int(latest_vol),
            "baseline_vol": int(base),
            "trade_value_억": round(trade_value / 1e8, 1),
        })
    return pd.DataFrame(out).sort_values("ratio", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# 메인
# --------------------------------------------------------------------------- #
def main():
    cfg = load_config()
    s = cfg["kr_scan"]
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    uni = build_universe(cfg)
    if uni.empty:
        sys.exit("[오류] 프리필터를 통과한 종목이 없습니다. kr_scan 임계값을 낮춰보세요.")

    data = fetch_history(uni["ysym"].tolist(), s["lookback_trading_days"], s["yf_chunk"])
    if not data:
        sys.exit("[오류] yfinance 과거 데이터를 받지 못했습니다.")

    print("[3/3] 거래량 폭증 배율 계산...")
    res = compute_surge(uni, data, cfg)

    stamp = dt.date.today().isoformat()
    csv_path = os.path.join(OUTPUT_DIR, f"kr_surge_{stamp}.csv")
    res.to_csv(csv_path, index=False, encoding="utf-8-sig")

    surged = res[res["ratio"] >= s["volume_surge_threshold"]]
    watch = res[(res["ratio"] >= s["watch_threshold"]) &
                (res["ratio"] < s["volume_surge_threshold"])]

    print("\n" + "=" * 84)
    print(f"  한국 거래량 폭증주 스캔  (기준일 {stamp}, 비교 {s['lookback_trading_days']}거래일)")
    print(f"  유니버스 {len(uni)} → 데이터 {len(data)} → 필터통과 {len(res)} 종목")
    print("=" * 84)
    print(f"  {s['volume_surge_threshold']:.0f}배 이상 폭증: {len(surged)} 종목 / "
          f"{s['watch_threshold']:.0f}~{s['volume_surge_threshold']:.0f}배 관찰: {len(watch)} 종목")
    print("-" * 84)
    if res.empty:
        print("  조건을 만족하는 종목이 없습니다. (폭증은 원래 희귀합니다)")
    else:
        with pd.option_context("display.width", 220, "display.unicode.east_asian_width", True):
            print(res.head(s["top_n"]).to_string(index=False))
    print("-" * 84)
    print(f"  CSV 저장: {csv_path}")
    print("=" * 84)
    print("  ⚠ 본 목록은 매매 신호가 아닙니다. 폭증주는 상·하한가 등 변동성이 극심합니다.")
    print("  ⚠ 데이터 소스: 유니버스=FinanceDataReader, 과거거래량=yfinance (둘 다 무료·비공식).")


if __name__ == "__main__":
    main()
