# -*- coding: utf-8 -*-
"""
캔들 패턴 탐지기 (단일 캔들 OHLC 룰)  —  docs/STRATEGY_NOTES.md 기반
====================================================================
순수 함수·외부 의존성 없음. 본장/프리마켓 스캐너 공용 부품(향후 캔들-베이스 스캐너의 핵심).

판별 대상(상승/하락 성질 대표 캔들):
  · 양봉 스프링(민머리 양봉)      : 위꼬리 거의 없는 큰 양봉 → 강한 상승 성질
  · 위꼬리 양봉                   : 몸통 ≈ 위꼬리(1:1), 아래꼬리 짧은 양봉 → 상승 성질
  · 작은몸통 양꼬리 양봉           : 양봉팽이 / 긴 위아래꼬리 작은 양봉 계열(둘 구분은 실무상 무의미)
  · 음봉 스프링(민바닥 음봉)      : 아래꼬리 거의 없는 큰 음봉 → 하락 성질
  · 도지                          : 몸통 ≈ 0

주의: 캔들의 '성질'은 출현 위치(수평적 파동 후반부·캔들군 선상)에서만 매수신호로 유효.
      본 모듈은 형태만 판별한다(위치 판정은 스캐너 몫). 임계값은 튜닝 가능.
"""

# 범위(고-저) 정규화 비율 임계값
DOJI_BODY_MAX = 0.10      # 몸통/범위 < 0.10 → 도지
SPRING_BODY_MIN = 0.60    # 스프링 최소 몸통 비율
SPRING_FLAT_WICK = 0.08   # 스프링의 '없는' 쪽 꼬리 최대
SHORT_WICK = 0.15         # '짧은 꼬리' 최대
UWICK_YANG_MIN = 0.25     # 위꼬리 양봉의 위꼬리 최소
BODY_UWICK_EQ = 0.15      # 몸통≈위꼬리 허용 오차(범위 정규화)
SMALL_BODY_MAX = 0.35     # 작은 몸통 최대
SIDE_WICK_MIN = 0.20      # 양쪽 꼬리 최소(양꼬리 캔들)


def geometry(o, h, l, c):
    """범위 정규화한 (몸통, 위꼬리, 아래꼬리) 비율과 보조값. 범위 0이면 None."""
    rng = h - l
    if rng <= 0:
        return None
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    return {
        "rng": rng,
        "body_r": body / rng,
        "upper_r": upper / rng,
        "lower_r": lower / rng,
        "bull": c > o,
        "bear": c < o,
    }


def is_doji(o, h, l, c):
    g = geometry(o, h, l, c)
    return bool(g and g["body_r"] < DOJI_BODY_MAX)


def is_yang_spring(o, h, l, c):
    """양봉 스프링(민머리): 위꼬리 거의 없는 큰 양봉."""
    g = geometry(o, h, l, c)
    return bool(g and g["bull"] and g["body_r"] >= SPRING_BODY_MIN
               and g["upper_r"] <= SPRING_FLAT_WICK and g["lower_r"] <= SHORT_WICK)


def is_eum_spring(o, h, l, c):
    """음봉 스프링(민바닥): 아래꼬리 거의 없는 큰 음봉."""
    g = geometry(o, h, l, c)
    return bool(g and g["bear"] and g["body_r"] >= SPRING_BODY_MIN
               and g["lower_r"] <= SPRING_FLAT_WICK and g["upper_r"] <= SHORT_WICK)


def is_upper_wick_yang(o, h, l, c):
    """위꼬리 양봉: 몸통 ≈ 위꼬리, 아래꼬리 짧은 양봉(스프링 제외)."""
    g = geometry(o, h, l, c)
    if not (g and g["bull"]):
        return False
    return (g["lower_r"] <= SHORT_WICK
            and g["upper_r"] >= UWICK_YANG_MIN
            and abs(g["body_r"] - g["upper_r"]) <= BODY_UWICK_EQ
            and g["upper_r"] > SPRING_FLAT_WICK)


def is_small_body_two_wick_yang(o, h, l, c):
    """작은몸통 양꼬리 양봉(양봉팽이 / 긴 위아래꼬리 작은양봉 계열). 도지 제외."""
    g = geometry(o, h, l, c)
    if not (g and g["bull"]):
        return False
    return (DOJI_BODY_MAX <= g["body_r"] <= SMALL_BODY_MAX
            and g["upper_r"] >= SIDE_WICK_MIN and g["lower_r"] >= SIDE_WICK_MIN)


# 라벨 → 판별함수 (양봉 매수성질 위주 + 도지/음봉스프링)
_DETECTORS = {
    "양봉스프링": is_yang_spring,
    "위꼬리양봉": is_upper_wick_yang,
    "작은몸통양꼬리양봉": is_small_body_two_wick_yang,
    "음봉스프링": is_eum_spring,
    "도지": is_doji,
}

# 매수 성질(상승) 신호로 보는 라벨
BULLISH_LABELS = {"양봉스프링", "위꼬리양봉", "작은몸통양꼬리양봉"}


def detect(o, h, l, c):
    """매칭되는 모든 패턴 라벨 리스트(정렬). 범위 0이면 빈 리스트."""
    return sorted(name for name, fn in _DETECTORS.items() if fn(o, h, l, c))


def has_bullish_signal(o, h, l, c):
    """상승 성질 캔들 신호가 하나라도 있으면 True."""
    return any(lbl in BULLISH_LABELS for lbl in detect(o, h, l, c))


# =========================================================================== #
# 다중 캔들(시퀀스) 패턴  —  STRATEGY_NOTES: 상승펀치·상승다람쥐·양봉팽이군·꼬리군
#   입력은 (o,h,l,c) 캔들들의 리스트(오래된→최신).
# =========================================================================== #
def _g(c):
    return geometry(*c)


def is_lower_wick_yang(o, h, l, c):
    """아래꼬리 양봉: 몸통 ≈ 아래꼬리, 위꼬리 짧은 양봉."""
    g = geometry(o, h, l, c)
    if not (g and g["bull"]):
        return False
    return (g["upper_r"] <= SHORT_WICK and g["lower_r"] >= UWICK_YANG_MIN
            and abs(g["body_r"] - g["lower_r"]) <= BODY_UWICK_EQ)


def _small_body(c):
    g = geometry(*c)
    return bool(g and g["body_r"] <= SMALL_BODY_MAX)


def is_rising_punch(c1, c2):
    """상승펀치: 위꼬리양봉 + 아래꼬리양봉 연속(큰 양봉군 선상에서 상승 성질)."""
    return is_upper_wick_yang(*c1) and is_lower_wick_yang(*c2)


def is_rising_squirrel(c1, c2, c3):
    """상승다람쥐: (적당~큰)양봉 + 작은 음봉/도지 + 작은 양봉/양봉팽이."""
    g1, g2, g3 = _g(c1), _g(c2), _g(c3)
    if not (g1 and g2 and g3):
        return False
    return (g1["bull"] and g1["body_r"] >= 0.4              # 1봉: 양봉(적당~큼)
            and g2["body_r"] <= SMALL_BODY_MAX and not g2["bull"]  # 2봉: 작은 음봉/도지
            and g3["bull"] and g3["body_r"] <= SMALL_BODY_MAX)     # 3봉: 작은 양봉


def is_paengi_group(candles):
    """양봉 팽이군: 2~5개 연속 작은몸통, 다수가 양봉, 마지막은 양꼬리 양봉."""
    if not (2 <= len(candles) <= 5):
        return False
    if not all(_small_body(c) for c in candles):
        return False
    bulls = sum(1 for c in candles if geometry(*c) and geometry(*c)["bull"])
    return bulls >= len(candles) - 1 and is_small_body_two_wick_yang(*candles[-1])


def is_tail_group(candles):
    """꼬리군(이중/다중): 긴 위꼬리 캔들 2개+ 가 엇비슷한 고가대. 그 자체로 매수 신호."""
    longs = [c for c in candles if (geometry(*c) and geometry(*c)["upper_r"] >= 0.40)]
    if len(longs) < 2:
        return False
    highs = [c[1] for c in longs]
    lo, hi = min(highs), max(highs)
    return lo > 0 and (hi / lo - 1) <= 0.05   # 고가대 5% 이내로 모임


# 다중 패턴 라벨(모두 상승 성질 신호)
MULTI_BULLISH_LABELS = {"상승펀치", "상승다람쥐", "양봉팽이군", "꼬리군"}


def detect_multi(ohlc, lookback=6):
    """최근 lookback봉에서 다중 캔들 상승 패턴 탐지.
    반환: [{'pattern': name, 'offset': 마지막봉의 D-오프셋}]. (offset 0 = 최신)"""
    w = ohlc[-lookback:] if lookback else ohlc
    n = len(w)
    base = len(ohlc) - n            # 전역 인덱스 보정
    found = []

    def off(end_idx_global):
        return (len(ohlc) - 1) - end_idx_global

    # 2봉: 상승펀치
    for i in range(n - 1):
        if is_rising_punch(w[i], w[i + 1]):
            found.append({"pattern": "상승펀치", "offset": off(base + i + 1)})
    # 3봉: 상승다람쥐
    for i in range(n - 2):
        if is_rising_squirrel(w[i], w[i + 1], w[i + 2]):
            found.append({"pattern": "상승다람쥐", "offset": off(base + i + 2)})
    # 2~5봉: 양봉팽이군 (가장 긴 연속을 한 번만)
    for size in range(5, 1, -1):
        hit = False
        for i in range(n - size + 1):
            if is_paengi_group(w[i:i + size]):
                found.append({"pattern": "양봉팽이군", "offset": off(base + i + size - 1)})
                hit = True
                break
        if hit:
            break
    # 2~4봉: 꼬리군
    for size in range(4, 1, -1):
        hit = False
        for i in range(n - size + 1):
            if is_tail_group(w[i:i + size]):
                found.append({"pattern": "꼬리군", "offset": off(base + i + size - 1)})
                hit = True
                break
        if hit:
            break
    return found


if __name__ == "__main__":
    demo = [
        ("양봉스프링", 10, 10.92, 9.95, 10.90),
        ("위꼬리양봉", 10, 10.81, 9.97, 10.40),
        ("작은몸통양꼬리양봉", 10, 10.50, 9.60, 10.12),
        ("음봉스프링", 10.90, 10.95, 9.98, 10.00),
        ("도지", 10, 10.30, 9.70, 10.01),
    ]
    for label, o, h, l, c in demo:
        print(f"기대 {label:18s} → 탐지 {detect(o, h, l, c)}")
