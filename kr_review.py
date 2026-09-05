# -*- coding: utf-8 -*-
"""
추천 종목 성과 리뷰 (KR Recommendation Review)
===============================================
output/recommendation_ledger.csv 에 기록된 과거 추천(모의)을 현재가로 리뷰한다.
데이터는 FinanceDataReader(프록시 환경에서도 동작 — yfinance 불필요).

리뷰 항목(추천일 종가=진입 기준):
  · 현재종가 / 수익률%(진입대비)
  · 보유중 최고가(MFE%) / 최저가(MAE%)
  · 손절터치 여부(보유 중 저가가 손절선 이하로 내려간 적 있나)
  · 경과 거래일수

사용: python kr_review.py            # 모든 미마감 추천 리뷰
      python kr_review.py 2026-08-14 # 특정 추천일자만
"""

import os
import sys
import datetime as dt

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

os.environ.setdefault("REQUESTS_CA_BUNDLE", "/root/.ccr/ca-bundle.crt")
os.environ.setdefault("SSL_CERT_FILE", "/root/.ccr/ca-bundle.crt")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(BASE_DIR, "output", "recommendation_ledger.csv")


def review_one(code, rec_date, entry, stop):
    import FinanceDataReader as fdr
    try:
        df = fdr.DataReader(str(code).zfill(6), rec_date)
    except Exception as e:
        return {"error": f"{type(e).__name__}"}
    if df is None or df.empty:
        return {"error": "no data"}
    df = df.dropna(subset=["Close"])
    # 추천일 '다음날'부터의 경로(추천일 종가 이후 실제 성과)
    after = df[df.index > pd.to_datetime(rec_date)]
    if after.empty:
        # 추천 후 새 거래일이 아직 없음(주말/휴장 직후). 진입일 봉의 장중 고저를
        # 보유 성과로 오보하지 않도록 '성과 없음(0일)'으로 정직하게 반환한다.
        return {"cur": round(float(df["Close"].iloc[-1]), 0), "ret_%": 0.0,
                "MFE_%": None, "MAE_%": None, "stop_hit": "", "days": 0}
    cur = float(after["Close"].iloc[-1])
    hi = float(after["High"].max())
    lo = float(after["Low"].min())
    stop_hit = bool(lo <= stop) if stop else False
    return {
        "cur": round(cur, 0),
        "ret_%": round((cur / entry - 1) * 100, 1),
        "MFE_%": round((hi / entry - 1) * 100, 1),
        "MAE_%": round((lo / entry - 1) * 100, 1),
        "stop_hit": "손절" if stop_hit else "",
        "days": int(len(after)),
    }


def main():
    if not os.path.exists(LEDGER):
        sys.exit(f"[오류] 장부 없음: {LEDGER}. 추천 시 kr_ledger 로 먼저 기록하세요.")
    led = pd.read_csv(LEDGER, dtype={"code": str})
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if only:
        led = led[led["rec_date"] == only]
    if led.empty:
        sys.exit("리뷰할 추천이 없습니다.")

    print(f"[리뷰] {len(led)}건 추천 성과 조회 (FinanceDataReader)...")
    rows = []
    for _, r in led.iterrows():
        res = review_one(r["code"], r["rec_date"], float(r["entry"]), float(r.get("stop", 0) or 0))
        row = {"추천일": r["rec_date"], "종목": r["name"], "등급": r.get("grade", ""),
               "진입": int(r["entry"]), "손절": int(r.get("stop", 0) or 0)}
        row.update(res if "error" not in res else {"cur": "-", "ret_%": None, "MFE_%": None,
                                                   "MAE_%": None, "stop_hit": res["error"], "days": 0})
        rows.append(row)
    rev = pd.DataFrame(rows)

    stamp = dt.date.today().isoformat()
    out = os.path.join(BASE_DIR, "output", f"review_{stamp}.csv")
    rev.to_csv(out, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 92)
    print(f"  추천 종목 성과 리뷰  (리뷰일 {stamp})   ※ 모의 — 실투자 아님")
    print("=" * 92)
    cols = ["추천일", "종목", "등급", "진입", "손절", "cur", "ret_%", "MFE_%", "MAE_%", "stop_hit", "days"]
    with pd.option_context("display.width", 240, "display.unicode.east_asian_width", True):
        print(rev[cols].to_string(index=False))
    print("-" * 92)
    good = rev[pd.to_numeric(rev["ret_%"], errors="coerce") > 0]
    valid = rev[pd.to_numeric(rev["ret_%"], errors="coerce").notna()]
    if len(valid):
        avg = pd.to_numeric(valid["ret_%"], errors="coerce").mean()
        med = pd.to_numeric(valid["ret_%"], errors="coerce").median()
        print(f"  종합: {len(valid)}건 | 평균 {avg:+.1f}% / 중앙 {med:+.1f}% | "
              f"상승 {len(good)}건 / 손절터치 {(rev['stop_hit']=='손절').sum()}건")
    print(f"  저장: {out}")
    print("=" * 92)
    print("  · ret=추천일 종가 진입 대비 현재. MFE/MAE=보유 중 최고/최저. 손절터치=저가가 손절선 이탈.")
    print("  · 모의 성과일 뿐 — 표본 적고 생존편향/체결가정 한계. 매매 신호 아님.")


if __name__ == "__main__":
    main()
