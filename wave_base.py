# -*- coding: utf-8 -*-
"""
수평적 파동(다년 베이스) 탐지기  —  docs/STRATEGY_NOTES.md §1 기반
====================================================================
캔들매매법의 핵심 '위치' 요소를 근사 정량화한다. 순수 함수, 외부 의존성 없음.

이론(요약): 신뢰성 높은 캔들 신호는 아무 데서나 유효하지 않고,
  **① 큰 하락 구간**(최고점에서 깊이/오래 하락) 이후
  **② 수평적 파동 구간**(수년 횡보·보합) 의 **③ 후반부**(베이스 저점 근처, 아직
  본격 상승 이탈 전)에서 형성될 때만 유효하다.
반대로 해석하지 않는다(해석제외): 저점대비 과상승(+50%·10배), 상장기간 짧음,
  완만하기만 한 파동, 저점에서 멀거나 여러 번 돌파한 구간.

본 모듈은 다년 '주봉' 종가/고저로 위 구조를 근사한다. 저자도 위치의 완전한
객관화는 불가(80~90% 일치 수준)라 명시 → 어디까지나 '근사 분류'다.
"""

from statistics import median

# 임계값(주봉 기준, 튜닝 가능)
MIN_BARS = 156          # 최소 주봉 수 ≈ 3년 (해석제외 #4: 상장기간 짧음)
BIG_DROP = 0.50         # 최고점 대비 -50% 이상 하락해야 '큰 하락 구간'
BASE_WINDOW = 104       # 수평성 판단 구간 ≈ 최근 2년(주봉)
FLAT_RANGE = 0.60       # 최근 구간 (고-저)/중앙값 ≤ 0.60 → '수평적 뉘앙스'
POS_LOW = 0.50          # 현재가가 최근 구간 하단 50% 이내 → 베이스 후반부(미이탈)
POS_BROKEN = 0.80       # 상단 80%↑ → 이미 상승 이탈
OVEREXT_FROM_LOW = 0.50  # 베이스 저점 대비 +50%↑ → 과상승(해석제외 #1)
OVEREXT_MULT = 10.0     # 베이스 저점 대비 10배↑ → 과상승(해석제외 #3)


def classify_base(highs, lows, closes):
    """다년 주봉 고/저/종가 리스트(오래된→최신)로 베이스 위치를 근사 분류.

    반환 dict:
      label        : 베이스근접 / 베이스(완만) / 상승이탈 / 과상승 / 하락중 / 비전형 / 데이터부족
      bars         : 주봉 수
      drop_peak_%  : 최고점 대비 현재 낙폭(양수=하락)
      base_range_% : 최근 구간 (고-저)/중앙값
      pos_in_base_%: 최근 구간 내 현재가 위치(0=바닥, 100=천장)
      from_low_%   : 베이스 저점 대비 상승률
      is_base      : 정석 '수평 베이스 후반부' 여부(bool)
    """
    n = len(closes)
    base = {"label": "데이터부족", "bars": n, "drop_peak_%": None,
            "base_range_%": None, "pos_in_base_%": None, "from_low_%": None,
            "is_base": False}
    if n < MIN_BARS or not highs or not lows:
        return base

    last = float(closes[-1])
    peak = max(float(h) for h in highs)
    drop_peak = (peak - last) / peak if peak > 0 else 0.0

    win = closes[-BASE_WINDOW:] if n >= BASE_WINDOW else closes
    wlows = lows[-BASE_WINDOW:] if n >= BASE_WINDOW else lows
    whighs = highs[-BASE_WINDOW:] if n >= BASE_WINDOW else highs
    r_lo = min(float(x) for x in wlows)
    r_hi = max(float(x) for x in whighs)
    r_med = median(float(x) for x in win)
    base_range = (r_hi - r_lo) / r_med if r_med > 0 else 999.0
    pos = (last - r_lo) / (r_hi - r_lo) if r_hi > r_lo else 1.0
    from_low = (last / r_lo - 1) if r_lo > 0 else 0.0
    mult = last / r_lo if r_lo > 0 else 0.0

    base.update({
        "drop_peak_%": round(drop_peak * 100, 0),
        "base_range_%": round(base_range * 100, 0),
        "pos_in_base_%": round(pos * 100, 0),
        "from_low_%": round(from_low * 100, 0),
    })

    # 분류 (우선순위 순)
    if from_low >= OVEREXT_FROM_LOW or mult >= OVEREXT_MULT:
        base["label"] = "과상승"               # 해석제외 #1·#3
    elif drop_peak >= BIG_DROP and base_range <= FLAT_RANGE and pos <= POS_LOW:
        base["label"] = "베이스근접"           # 정석: 큰 하락 + 수평 + 후반부 저점권
        base["is_base"] = True
    elif drop_peak >= BIG_DROP and pos <= POS_LOW:
        base["label"] = "베이스(완만)"         # 큰 하락 + 저점권이나 수평성 느슨
        base["is_base"] = True
    elif pos >= POS_BROKEN:
        base["label"] = "상승이탈"             # 이미 구간 상단/돌파
    elif drop_peak < 0.20:
        base["label"] = "하락중"               # 최고점 근처(깊은 하락 아님)
    else:
        base["label"] = "비전형"
    return base
