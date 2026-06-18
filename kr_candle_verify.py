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
  B. 파동 '해석하지 않는 6가지' 중 정량화 가능한 제외 필터:
       - #1 최저점→고점 +50% 넘은 과상승      → 제외(EXCLUDE)
       - #3 최저점 대비 10배 이상 상승          → 제외(EXCLUDE)
       - #4 상장기간 짧아 캔들 수 부족          → 제외(데이터부족)
  C. 위치(참고) : 1년 저점 대비 위치 + 베이스(수평 보합) 근접도 — 표시용.
       (캔들이론상 '위치'가 핵심이나 완전 자동화는 불가 → PASS 강제 안 함)

판정:
  ✅ PASS    : 과상승/데이터부족 아님 AND 최근 상승 캔들(군) 신호 있음
  ⚠ CHECK   : 신호 없음(캔들 미출현)
  ⛔ EXCLUDE : 과상승(+50%/10배) — 캔들이론상 해석 대상 아님

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

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

LOOKBACK_SIGNAL = 5     # 최근 며칠 봉에서 캔들 신호를 찾을지
MIN_BARS = 60           # 상장기간/캔들수 최소 (해석제외 #4)
OVEREXT_PCT = 50.0      # 1년 저점 대비 +50% 넘으면 과상승 (해석제외 #1)
OVEREXT_MULT = 10.0     # 1년 저점 대비 10배 넘으면 과상승 (해석제외 #3)
BASE_FLAT_PCT = 35.0    # 1년 종가 변동폭(범위/중앙값)이 이 % 이내면 '수평 베이스 근접'


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


def wave_context(closes, lows):
    """파동 위치(참고) + 과상승 제외 판정. 반환 dict."""
    lo = min(lows)
    last = closes[-1]
    over_pct = (last / lo - 1) * 100 if lo > 0 else 0.0
    mult = last / lo if lo > 0 else 0.0
    med = median(closes)
    flat_pct = (max(closes) - min(closes)) / med * 100 if med > 0 else 999
    excluded = over_pct >= OVEREXT_PCT or mult >= OVEREXT_MULT
    return {
        "from_low_%": round(over_pct, 0),
        "x_from_low": round(mult, 1),
        "near_base": flat_pct <= BASE_FLAT_PCT,   # 수평 보합 베이스 근접(표시용)
        "excluded": excluded,
    }


def evaluate(sym, df):
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if df is None or len(df) < 4:
        return {"sym": sym, "verdict": "⚠ CHECK", "reason": "데이터 없음"}
    ohlc = [tuple(float(x) for x in row)
            for row in zip(df["Open"], df["High"], df["Low"], df["Close"])]
    closes = [float(c) for c in df["Close"]]
    lows = [float(x) for x in df["Low"]]

    if len(ohlc) < MIN_BARS:
        return {"sym": sym, "verdict": "⚠ CHECK", "reason": f"캔들수 부족({len(ohlc)}<{MIN_BARS})",
                "signals": "", "from_low_%": None, "near_base": None}

    wc = wave_context(closes, lows)
    sigs = recent_bullish(ohlc)
    last_candle = ",".join(cp.detect(*ohlc[-1])) or "-"

    if wc["excluded"]:
        verdict, reason = "⛔ EXCLUDE", f"과상승(저점대비 +{wc['from_low_%']:.0f}% / {wc['x_from_low']}배)"
    elif sigs:
        verdict, reason = "✅ PASS", f"캔들신호 {len(sigs)}종"
    else:
        verdict, reason = "⚠ CHECK", "최근 상승캔들 없음"

    return {
        "sym": sym,
        "verdict": verdict,
        "reason": reason,
        "signals": ", ".join(sigs) if sigs else "-",
        "last_candle": last_candle,
        "from_low_%": wc["from_low_%"],
        "near_base": "✔" if wc["near_base"] else "",
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
    print(f"[1/2] yfinance 1년 일봉 수집 ({len(syms)} 종목)...")
    raw = yf.download(syms, period="1y", interval="1d", auto_adjust=False,
                      progress=False, group_by="ticker", threads=True)

    print(f"[2/2] 캔들 신호 + 파동(과상승) 제외 필터 적용...")
    rows = []
    for sm in syms:
        try:
            sub = raw[sm] if len(syms) > 1 else raw
        except Exception:
            sub = None
        r = evaluate(sm, sub if sub is not None else pd.DataFrame())
        r["name"] = name_of.get(sm, "")
        rows.append(r)

    res = pd.DataFrame(rows)
    order = {"✅ PASS": 0, "⚠ CHECK": 1, "⛔ EXCLUDE": 2}
    res["_o"] = res["verdict"].map(order).fillna(3)
    res = res.sort_values("_o").drop(columns="_o").reset_index(drop=True)

    if stamp != "adhoc":
        out_path = os.path.join(OUTPUT_DIR, f"kr_candle_verified_{stamp}.csv")
        res.to_csv(out_path, index=False, encoding="utf-8-sig")

    npass = (res["verdict"] == "✅ PASS").sum()
    nexcl = (res["verdict"] == "⛔ EXCLUDE").sum()
    print("\n" + "=" * 80)
    print(f"  캔들/파동 교차검증  (PASS {npass} / EXCLUDE {nexcl} / 전체 {len(res)})")
    print("=" * 80)
    cols = [c for c in ["sym", "name", "verdict", "signals", "from_low_%", "near_base", "reason"]
            if c in res.columns]
    with pd.option_context("display.width", 200, "display.unicode.east_asian_width", True):
        print(res[cols].to_string(index=False))
    print("-" * 80)
    passed = res[res["verdict"] == "✅ PASS"]
    if not passed.empty:
        names = [f"{r['name']}({r['sym']})" for _, r in passed.iterrows()]
        print("  ✅ 캔들신호 PASS: " + ", ".join(names))
    if stamp != "adhoc":
        print(f"  저장: output/kr_candle_verified_{stamp}.csv")
    print("=" * 80)
    print("  ※ PASS=최근 상승 캔들(군) 신호 출현 + 과상승 아님. EXCLUDE=저점대비 과상승(해석제외).")
    print("    near_base/from_low_%는 파동상 '위치' 참고용. 캔들이론상 위치가 핵심이나 자동화 한계로")
    print("    PASS를 강제하지 않음. 매매 신호 아님 — 변동성 극심, 본인 판단·리스크관리 필수.")


if __name__ == "__main__":
    main()
