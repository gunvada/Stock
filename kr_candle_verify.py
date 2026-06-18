# -*- coding: utf-8 -*-
"""
한국 후보 캔들/파동 교차검증 (KR Candle & Wave Verify) — 검증 옵션 +1
=====================================================================
kr_scanner.py 가 뽑은 한국 거래량 폭증 후보(output/kr_surge_<date>.csv)를
회원 드라이브의 '캔들매매법(파동·캔들군·캔들)' 이론으로 재검증한다.
데이터는 yfinance 일봉(.KS/.KQ, 키 불필요).

이론 반영(요약 — 출처: 캔들개론·캔들(군)신호·파동연상 / docs/STRATEGY_NOTES.md):
  A. 캔들 신호 : 최근 일봉에 상승 성질 캔들/캔들군 출현?
       - 단일: 양봉스프링·위꼬리양봉·작은몸통양꼬리양봉 (candle_patterns)
       - 다중: 상승펀치·상승다람쥐·꼬리군            (candle_patterns.detect_seq)
  B. 파동 위치(다년 주봉) : wave_base 가 '큰 하락 → 수평 보합(다년) → 후반부 저점권'
       구조를 근사 분류. 해석제외(#1 +50% / #3 10배 / #4 상장기간)도 여기서 판정.

판정 (위치를 verdict 에 반영):
  ✅✅ PRIME  : 과상승 아님 + 다년 베이스 후반부(수평·저점권) + 상승 캔들신호 (정석 위치)
  ✅ PASS     : 상승 캔들신호 있으나 베이스 미확정/이탈
  ⚠ CHECK    : 최근 상승 캔들 신호 없음
  ⛔ EXCLUDE  : 저점대비 과상승(+50%/10배) — 캔들이론상 해석 대상 아님

사용법:
  python kr_candle_verify.py                  # 최신 kr_surge_<date>.csv 검증
  python kr_candle_verify.py 005930.KS ...    # 임의 심볼 직접 평가(디버그)
"""

import os
import re
import sys
import glob
from statistics import median

import pandas as pd

import candle_patterns as cp
import wave_base as wb

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

LOOKBACK_SIGNAL = 5     # 최근 며칠 봉에서 캔들 신호를 찾을지
# 과상승(#1·#3)·상장기간(#4)·수평 베이스(후반부) 판정은 wave_base 가 다년 주봉으로 담당.


def find_latest_csv():
    fs = [f for f in glob.glob(os.path.join(OUTPUT_DIR, "kr_surge_*.csv"))
          if re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(f))]
    return sorted(fs)[-1] if fs else None


def recent_bullish(ohlc, lookback=LOOKBACK_SIGNAL):
    """최근 lookback봉에서 상승 캔들(단일) + 다중 캔들군 신호 라벨을 모은다."""
    labels = []
    window = ohlc[-lookback:] if lookback else ohlc
    for i, bar in enumerate(window):
        for lbl in cp.detect(*bar):
            if lbl in cp.BULLISH_LABELS:
                labels.append(lbl)
    # 다중 캔들군은 최근 구간 끝에서 판정
    for lbl in cp.detect_seq(ohlc[-(lookback + 2):]):
        labels.append(lbl)
    # 중복 제거(순서 유지)
    seen, out = set(), []
    for x in labels:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def evaluate(sym, daily, weekly):
    """daily(1년 일봉)=캔들 신호, weekly(다년 주봉)=파동 베이스 위치로 판정."""
    daily = daily.dropna(subset=["Open", "High", "Low", "Close"]) if daily is not None else pd.DataFrame()
    if daily.empty or len(daily) < 4:
        return {"sym": sym, "verdict": "⚠ CHECK", "reason": "일봉 없음",
                "signals": "-", "base": "-", "drop_peak_%": None,
                "pos_in_base_%": None, "from_low_%": None}
    ohlc = [tuple(float(x) for x in row)
            for row in zip(daily["Open"], daily["High"], daily["Low"], daily["Close"])]
    last_candle = ",".join(cp.detect(*ohlc[-1])) or "-"
    sigs = recent_bullish(ohlc)

    # 다년 주봉으로 베이스(수평적 파동) 위치 분류
    if weekly is not None and not weekly.dropna(subset=["Close"]).empty:
        w = weekly.dropna(subset=["High", "Low", "Close"])
        b = wb.classify_base(w["High"].tolist(), w["Low"].tolist(), w["Close"].tolist())
    else:
        b = {"label": "데이터부족", "is_base": False, "drop_peak_%": None,
             "pos_in_base_%": None, "from_low_%": None}

    # 판정: 과상승 제외 → (신호 + 베이스확정)=PRIME → 신호만=PASS → 무신호=CHECK
    if b["label"] == "과상승":
        verdict, reason = "⛔ EXCLUDE", f"과상승(저점대비 +{b['from_low_%']:.0f}%)"
    elif not sigs:
        verdict, reason = "⚠ CHECK", "최근 상승캔들 없음"
    elif b["is_base"]:
        verdict, reason = "✅✅ PRIME", f"베이스 후반부 + 캔들신호 {len(sigs)}종"
    elif b["label"] == "데이터부족":
        verdict, reason = "✅ PASS", f"캔들신호 {len(sigs)}종 (베이스 판정불가)"
    else:
        verdict, reason = "✅ PASS", f"캔들신호 {len(sigs)}종 (위치={b['label']})"

    return {
        "sym": sym,
        "verdict": verdict,
        "reason": reason,
        "signals": ", ".join(sigs) if sigs else "-",
        "last_candle": last_candle,
        "base": b["label"],
        "drop_peak_%": b["drop_peak_%"],
        "pos_in_base_%": b["pos_in_base_%"],
        "from_low_%": b["from_low_%"],
    }


def main():
    args = sys.argv[1:]
    name_of = {}
    if args:
        syms, stamp = args, "adhoc"
    else:
        path = find_latest_csv()
        if not path:
            sys.exit("[오류] output/kr_surge_*.csv 없음. 먼저 python kr_scanner.py 실행.")
        stamp = re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(path)).group(1)
        base = pd.read_csv(path, dtype={"code": str})
        # code(6자리) + 시장 → yfinance 심볼
        suf = {"KOSPI": ".KS", "KOSDAQ": ".KQ"}
        syms = []
        for _, r in base.iterrows():
            sm = str(r["code"]).zfill(6) + suf.get(r.get("market", ""), ".KS")
            syms.append(sm)
            name_of[sm] = r.get("name", "")
        print(f"[캔들/파동 검증] 기준 파일: {os.path.basename(path)}  ({len(syms)} 종목)")

    import yfinance as yf
    print(f"[1/3] yfinance 1년 일봉 수집 (캔들 신호용, {len(syms)} 종목)...")
    daily = yf.download(syms, period="1y", interval="1d", auto_adjust=False,
                        progress=False, group_by="ticker", threads=True)
    print(f"[2/3] yfinance 5년 주봉 수집 (다년 베이스 위치용)...")
    weekly = yf.download(syms, period="5y", interval="1wk", auto_adjust=False,
                         progress=False, group_by="ticker", threads=True)

    def sub_of(raw, sm):
        try:
            return raw[sm] if len(syms) > 1 else raw
        except Exception:
            return None

    print(f"[3/3] 캔들 신호 + 다년 베이스(수평적 파동) 위치 판정...")
    rows = []
    for sm in syms:
        r = evaluate(sm, sub_of(daily, sm), sub_of(weekly, sm))
        r["name"] = name_of.get(sm, "")
        rows.append(r)

    res = pd.DataFrame(rows)
    order = {"✅✅ PRIME": 0, "✅ PASS": 1, "⚠ CHECK": 2, "⛔ EXCLUDE": 3}
    res["_o"] = res["verdict"].map(order).fillna(4)
    res = res.sort_values("_o").drop(columns="_o").reset_index(drop=True)

    if stamp != "adhoc":
        out_path = os.path.join(OUTPUT_DIR, f"kr_candle_verified_{stamp}.csv")
        res.to_csv(out_path, index=False, encoding="utf-8-sig")

    nprime = (res["verdict"] == "✅✅ PRIME").sum()
    npass = (res["verdict"] == "✅ PASS").sum()
    nexcl = (res["verdict"] == "⛔ EXCLUDE").sum()
    print("\n" + "=" * 88)
    print(f"  캔들/파동 교차검증  (PRIME {nprime} / PASS {npass} / EXCLUDE {nexcl} / 전체 {len(res)})")
    print("=" * 88)
    cols = [c for c in ["sym", "name", "verdict", "signals", "base",
                        "drop_peak_%", "pos_in_base_%", "from_low_%"]
            if c in res.columns]
    with pd.option_context("display.width", 220, "display.unicode.east_asian_width", True):
        print(res[cols].head(40).to_string(index=False))
    print("-" * 88)
    prime = res[res["verdict"] == "✅✅ PRIME"]
    if not prime.empty:
        names = [f"{r['name']}({r['sym']})" for _, r in prime.iterrows()]
        print("  ✅✅ PRIME (다년 베이스 후반부 + 상승 캔들신호): " + ", ".join(names))
    else:
        print("  ✅✅ PRIME 없음 — 폭증주가 다년 베이스 후반부에 있는 경우는 드뭄(이론상 자연스러움).")
    if stamp != "adhoc":
        print(f"  저장: output/kr_candle_verified_{stamp}.csv")
    print("=" * 88)
    print("  ※ PRIME=큰하락 후 다년 수평베이스 저점권 + 상승 캔들신호(이론상 정석 위치).")
    print("    PASS=캔들신호 있으나 베이스 미확정/이탈.  EXCLUDE=저점대비 과상승(해석제외 #1·#3).")
    print("    base/pos_in_base_%/drop_peak_%는 주봉 근사 — 위치 100% 객관화는 원전도 불가. 매매신호 아님.")


if __name__ == "__main__":
    main()
