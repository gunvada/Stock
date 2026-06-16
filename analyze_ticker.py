# -*- coding: utf-8 -*-
"""
단일 종목 반등 안내판 (Single-ticker rebound dashboard)
--------------------------------------------------------
사용법:  python analyze_ticker.py TICKER [일수=20]
예:      python analyze_ticker.py SOXL 20

객관적 수치 + 우리가 백테스트한 '검증된 버킷'에 매핑해 반등 확률을 안내한다.
확률은 임의 수치가 아니라 15거래일 백테스트 결과를 근거로 한다(표본/주의 함께 표기).
"""
import os
import sys
import json
import time
import datetime as dt
from statistics import median

import requests
import scanner

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CACHE = os.path.join(scanner.OUTPUT_DIR, "cache")
DAY = "https://api.polygon.io/v2/aggs/ticker/{t}/range/1/day/{f}/{to}"
MIN10 = "https://api.polygon.io/v2/aggs/ticker/{t}/range/10/minute/{d}/{d}"

# ── 백테스트 근거 버킷 (15거래일 표본) ─────────────────────────────────
# (조건설명, 다음날 본장 평균%, 승률%, 표본n)
REF = {
    "pullback_sweet": ("거래량10배+ & 당일 -5~-15% 음봉", +4.6, 60, 95),
    "pullback_deep":  ("거래량10배+ & 당일 -15~-30% 음봉", +3.2, 48, 60),
    "pullback_shallow": ("거래량10배+ & 당일 -5~0% 음봉", +1.4, 50, 110),
    "green_on_vol":   ("거래량10배+ & 당일 양봉(0~+10%)", -0.5, 41, 193),
    "gap_chase":      ("갭상승 20%+ 추격(시초매수)", -3.9, 33, 52),
    "gap_extreme":    ("극단 갭 80%+ 추격", -11.9, 20, 5),
    "parabolic_2d":   ("직전 2일 +100%+ 폭등", -5.2, 33, 51),
    "parabolic_huge": ("직전 2일 +200%+ 폭등", -22.8, 28, 18),
}


def get(url, key):
    for _ in range(3):
        r = requests.get(url, params={"adjusted": "true", "sort": "asc",
                                      "limit": 50000, "apiKey": key}, timeout=30)
        if r.status_code == 429:
            time.sleep(15); continue
        return r.json().get("results", []) or [] if r.status_code == 200 else []
    return []


def daily(ticker, days, key):
    today = dt.date.today()
    f = (today - dt.timedelta(days=days + 12)).isoformat()
    return get(DAY.format(t=ticker, f=f, to=today.isoformat()), key)


def intraday(ticker, date, key):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f"bars_{ticker}_{date}.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    res = get(MIN10.format(t=ticker, d=date), key)
    json.dump(res, open(p, "w", encoding="utf-8"))
    return res


def fmt(x, s="%"):
    return f"{x:+.1f}{s}" if x is not None else "N/A"


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python analyze_ticker.py TICKER [일수=20]")
    ticker = sys.argv[1].upper()
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    cfg = scanner.load_config()
    key = cfg["polygon_api_key"]

    bars = daily(ticker, days, key)
    if len(bars) < 8:
        sys.exit(f"[{ticker}] 일봉 데이터 부족({len(bars)}일). 티커 확인 필요.")
    bars = bars[-(days + 1):]
    last = bars[-1]
    prev = bars[-2]
    vols = [b["v"] for b in bars]
    base_vol = median(vols[:-1][-7:]) if len(vols) > 2 else vols[0]

    price = last["c"]
    vol_ratio = last["v"] / base_vol if base_vol else 0
    oc = (last["c"] - last["o"]) / last["o"] * 100
    gap = (last["o"] - prev["c"]) / prev["c"] * 100
    close_pos = (last["c"] - last["l"]) / (last["h"] - last["l"]) if last["h"] > last["l"] else 0.5
    dol_M = last["v"] * last["c"] / 1e6
    run2d = (last["c"] / bars[-3]["c"] - 1) * 100 if len(bars) >= 3 else 0
    run5d = (last["c"] / bars[-6]["c"] - 1) * 100 if len(bars) >= 6 else 0
    hi_n = max(b["h"] for b in bars)
    lo_n = min(b["l"] for b in bars)
    sup3 = min(b["l"] for b in bars[-3:])     # 최근 3일 지지(저가)

    # 최근 거래일 분봉(있으면) → VWAP/장중 지지
    last_date = dt.datetime.utcfromtimestamp(last["t"] / 1000).date().isoformat()
    ib = intraday(ticker, last_date, key)
    vwap = None
    if ib:
        num = sum(b["c"] * b["v"] for b in ib); den = sum(b["v"] for b in ib)
        vwap = num / den if den else None

    # ── 셋업 분류 ──
    flags = []
    setup = None
    if run2d >= 200:
        setup = "parabolic_huge"
    elif run2d >= 100:
        setup = "parabolic_2d"
    elif gap >= 80:
        setup = "gap_extreme"
    elif vol_ratio >= 10 and -15 <= oc < -5:
        setup = "pullback_sweet"
    elif vol_ratio >= 10 and -30 <= oc < -15:
        setup = "pullback_deep"
    elif vol_ratio >= 10 and -5 <= oc < 0:
        setup = "pullback_shallow"
    elif vol_ratio >= 10 and oc >= 0:
        setup = "green_on_vol"
    elif gap >= 20:
        setup = "gap_chase"

    if price < 0.3 or price > 20:
        flags.append(f"가격 ${price:.2f} — 검증 유니버스($0.3~20) 밖. 통계 적용 주의.")
    if dol_M < 2:
        flags.append(f"거래대금 ${dol_M:.1f}M — 유동성 낮음(≥$2M 권장). 슬리피지 위험.")
    if vol_ratio < 3:
        flags.append(f"거래량 배율 {vol_ratio:.1f}배 — 폭증 신호 약함(관심 부족).")

    print("\n" + "=" * 74)
    print(f"  {ticker}  반등 안내판   (최근 {len(bars)}거래일, 기준일 {last_date})")
    print("=" * 74)
    print(f"  현재가 ${price:.3f}   |  {days}일 레인지 ${lo_n:.2f} ~ ${hi_n:.2f}")
    print(f"  당일 캔들 : 시초→종가 {fmt(oc)}  갭 {fmt(gap)}  마감강도 {close_pos:.2f}(고가근접도)")
    print(f"  거래량    : 평소대비 {vol_ratio:.1f}배   거래대금 ${dol_M:.1f}M")
    print(f"  모멘텀    : 2일 {fmt(run2d)}   5일 {fmt(run5d)}")
    if vwap:
        print(f"  당일 VWAP : ${vwap:.3f}  (현재가가 VWAP {'위' if price>=vwap else '아래'})")
    print("-" * 74)

    print("  [셋업 판정]")
    if setup:
        desc, avg, win, n = REF[setup]
        print(f"    매칭 버킷 : {desc}")
        print(f"    과거 통계 : 다음날 본장 평균 {avg:+.1f}%, 반등(상승) {win}%  (표본 n={n}, 15일)")
        verdict = ("반등 우위" if win >= 55 else "중립~약세" if win >= 45 else "약세/회피")
        print(f"    확률 판정 : {verdict}")
    else:
        print("    뚜렷한 검증 셋업 아님 — 거래량 폭증/갭/눌림 신호가 약함. 관망 권장.")
    print("-" * 74)

    print("  [매수 타점 가이드]")
    if setup in ("pullback_sweet", "pullback_deep", "pullback_shallow"):
        buy_lo, buy_hi = sup3, price
        stop = round(sup3 * 0.93, 3)
        tgt = round(price * 1.12, 3)
        print(f"    성격     : 눌림목 반등 후보 (데이터상 유일한 +엣지 영역)")
        print(f"    매수구간 : ${buy_lo:.3f} ~ ${buy_hi:.3f}  (최근3일 지지~현재가)")
        print(f"    진입타이밍: 다음 거래일 시초가 부근. 시초 급락 시 VWAP 회복 확인 후.")
        print(f"    손절     : ${stop}  (최근 지지 -7% 하회 시)")
        print(f"    1차목표  : ${tgt} (+12%)  →  ⚠ 종가 전 청산(오버나잇 금지, 강세시 갭다운)")
    elif setup in ("parabolic_2d", "parabolic_huge"):
        print(f"    성격     : 파라볼릭 천장 — 데이터상 며칠 더 하락(반등 {REF[setup][2]}%).")
        print(f"    가이드   : ❌ 신규 매수 금지. 떨어진다고 받지 말 것(칼 잡기).")
        print(f"    관망조건 : 거래량 줄며 -5~15% 수준으로 '진정'된 음봉 나올 때까지 대기.")
    elif setup in ("gap_chase", "gap_extreme"):
        print(f"    성격     : 갭상승 추격 — 5종 전략 전부 손실(평균 {REF[setup][1]:+.1f}%).")
        print(f"    가이드   : ❌ 시초가 추격 금지. 굳이면 오프닝 팝만(개장 30분 내 청산).")
    elif setup == "green_on_vol":
        print(f"    성격     : 거래량 터진 양봉 — 다음날 평균 {REF[setup][1]:+.1f}%(식는 경향).")
        print(f"    가이드   : 추격 비권장. 눌림(-5~15% 음봉) 만들 때 재검토.")
    else:
        print(f"    가이드   : 검증된 진입 신호 없음. 매수 근거 부족 — 관망.")
    print("-" * 74)

    if flags:
        print("  [경고]")
        for f in flags:
            print(f"    ⚠ {f}")
        print("-" * 74)
    print("  ※ 확률은 15거래일 백테스트 기반. 실거래 전 60~90일 재검증 권장.")
    print("  ※ 매수/청산은 본인 판단·실행. 손절선 준수, 종가 전 청산(강세주 오버나잇 금지).")
    print("=" * 74)


if __name__ == "__main__":
    main()
