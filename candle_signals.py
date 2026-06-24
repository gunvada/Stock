# -*- coding: utf-8 -*-
"""
캔들 신호 필터  (Candle Signal Filter)
=====================================
'캔들혁명 — 파동연상(The Imaging of Waves)' / '캔들개론' 교재의 캔들·캔들군·
파동·하이로우 기준선 개념을 **일봉 OHLCV로 계산 가능한 범위**로 옮긴 신호기다.

교재의 제1 명제 — "단순 형태(캔들)보다 (형성) 위치가 훨씬 중요하다" — 를 그대로
따른다. 따라서 신호는 ① 캔들 형태(shape)와 ② 하이로우 기준선/구간상 위치(position)를
함께 본 뒤 종합 판정(verdict)을 낸다. 추세는 읽지 않고, '지금 캔들이 의미 있는
위치에서 정상적인(연상되는) 형태인가'만 본다.

한계(반드시 인지): 교재 본령은 1시간/완성봉 기준의 재량적 차트 해석이고 60여 종목을
눈으로 훑는 방식이다. 여기서는 일봉 한 봉의 OHLC와 직전 봉들로 근사(proxy)할 뿐이라,
수횡파·미니기연파처럼 다수 파동의 미세 유형은 단순화된다. '필터/주석'으로만 쓰고
매매 신호로 맹신하지 말 것.

입력: 종목별 일봉 DataFrame (컬럼 date, open, high, low, close, volume; 날짜 오름차순)
출력: evaluate() → dict(shape, close_pos, position, verdict, score, reason)
"""
from statistics import median


# --------------------------------------------------------------------------- #
# ① 캔들 형태 (단일 완성봉)
# --------------------------------------------------------------------------- #
def classify_candle(o, h, l, c):
    """완성봉 1개의 형태를 교재 명칭에 가깝게 분류 + 매수편향 점수(-2..+2)."""
    rng = h - l
    if rng <= 0:
        return "무참고", 0.0
    body = abs(c - o)
    upper = h - max(o, c)        # 위 꼬리
    lower = min(o, c) - l        # 아래 꼬리
    bull = c >= o
    br = body / rng              # 몸통 비중
    ur = upper / rng
    lr = lower / rng

    # 장대양봉/음봉 (몸통이 레인지를 압도)
    if br >= 0.6:
        return ("장대양봉", 2.0) if bull else ("장대음봉", -2.0)
    # 망치형/양봉 스프링 (긴 아래꼬리 + 짧은 위꼬리 → 하방 거부, 매수 반전)
    if lr >= 0.5 and lr >= 2 * br and ur <= 0.25:
        return ("양봉스프링", 1.5) if bull else ("망치형", 1.0)
    # 위 꼬리 캔들 (긴 위꼬리 → 상방 거부, 고점권이면 매도주의)
    if ur >= 0.5 and ur >= 2 * br and lr <= 0.25:
        return ("위꼬리양봉", -1.0) if bull else ("위꼬리음봉", -1.5)
    # 팽이/도지 (작은 몸통 + 양 꼬리 → 우유부단, 위치로 판단)
    if br <= 0.25:
        return "팽이도지", 0.0
    # 그 외 보통 양/음봉
    return ("양봉", 0.7) if bull else ("음봉", -0.7)


# --------------------------------------------------------------------------- #
# ② 하이로우 기준선 / 구간상 위치  (직전 봉들 기준)
# --------------------------------------------------------------------------- #
def wave_position(prior_h, prior_l, prior_c, latest):
    """
    직전 봉들의 고가/저가/종가 열과 최신봉으로 '위치'를 근사한다.
    교재의 하이로우 기준선(전 고점/저점)과 구간(완만한 상승·수횡파·하락중)을
    일봉 수준에서 프록시.  반환: (position, pos_score)
    """
    c = float(latest["close"])
    if len(prior_h) < 3:
        return "정보부족", 0.0

    prev_high = max(prior_h)          # 전 고점(현저)
    prev_low = min(prior_l)           # 전 저점(현저)
    last_prev_close = prior_c[-1]

    span = prev_high - prev_low
    near = span * 0.03 if span > 0 else 0  # 근접 허용폭(레인지 3%)

    # 전 고점 돌파 / 앞둔 위치
    if c > prev_high + near:
        return "전고점돌파", 1.0
    if prev_high - near <= c <= prev_high + near:
        return "전고점부근", -0.3   # 저항권 — 위꼬리면 매도주의로 결합
    # 전 저점 이탈 / 부근 (반전 후보 위치)
    if c < prev_low - near:
        return "전저점이탈", -0.5
    if prev_low - near <= c <= prev_low + near:
        return "전저점부근", 0.5     # 지지권 — 매수신호와 결합 시 신뢰↑

    # 완만한 상승: 직전 종가열이 대체로 우상향
    rises = sum(1 for i in range(1, len(prior_c)) if prior_c[i] >= prior_c[i - 1])
    if rises >= max(2, int((len(prior_c) - 1) * 0.6)) and c >= last_prev_close:
        return "완만한상승", 0.6

    # 수횡파 프록시: 직전 고가/저가가 좁은 띠 안에서 횡보(변동성 수축)
    if span > 0:
        hi_band = (max(prior_h) - min(prior_h)) / span
        lo_band = (max(prior_l) - min(prior_l)) / span
        if hi_band <= 0.5 and lo_band <= 0.5:
            return "수횡파", 0.4

    return "잔구간", 0.0  # 교재의 '매매 불리 잔구간'(전체의 70~80%)


# --------------------------------------------------------------------------- #
# ③ 종합 판정  (위치 > 형태, 둘을 결합)
# --------------------------------------------------------------------------- #
def evaluate(df, lookback=7):
    """
    종목별 일봉 df로 최신봉 캔들 신호를 종합 판정.
    반환 dict: shape, close_pos, position, verdict, score, reason
    """
    df = df.sort_values("date")
    if len(df) < 4:
        return {"shape": "무참고", "close_pos": None, "position": "정보부족",
                "verdict": "중립", "score": 0.0, "reason": "봉 수 부족"}

    latest = df.iloc[-1]
    prior = df.iloc[-(lookback + 1):-1] if lookback > 0 else df.iloc[:-1]
    o, h, l, c = (float(latest["open"]), float(latest["high"]),
                  float(latest["low"]), float(latest["close"]))

    shape, shape_score = classify_candle(o, h, l, c)
    rng = h - l
    close_pos = round((c - l) / rng, 2) if rng > 0 else None   # 마감강도(1=고점마감)

    position, pos_score = wave_position(
        prior["high"].tolist(), prior["low"].tolist(),
        prior["close"].tolist(), latest)

    # 위치가 형태보다 우선 → 위치 가중 ↑. 마감강도도 소폭 반영.
    strength = (close_pos - 0.5) * 1.2 if close_pos is not None else 0.0
    score = round(shape_score + pos_score * 1.5 + strength, 2)

    # 결합 보정: 교재식 '위치+형태' 시너지/상쇄
    if position == "전고점부근" and shape in ("위꼬리양봉", "위꼬리음봉", "장대음봉"):
        score -= 1.0  # 저항권 상방거부 → 매도주의 강화
    if position in ("전저점부근", "수횡파") and shape in ("양봉스프링", "망치형", "장대양봉"):
        score += 1.0  # 지지권 매수반전 → 신뢰 강화
    if position == "잔구간":
        score *= 0.5  # 불리 잔구간은 신호 신뢰 감쇠

    if score >= 2.0:
        verdict = "강한매수"
    elif score >= 0.8:
        verdict = "매수관심"
    elif score <= -2.0:
        verdict = "강한매도"
    elif score <= -0.8:
        verdict = "매도주의"
    else:
        verdict = "중립"

    reason = f"{position}·{shape}" + (f"·마감{close_pos:.0%}" if close_pos is not None else "")
    return {"shape": shape, "close_pos": close_pos, "position": position,
            "verdict": verdict, "score": score, "reason": reason}


# 자체 점검용
if __name__ == "__main__":
    import pandas as pd
    # 전저점 부근 양봉스프링(긴 아래꼬리) → 매수 반전 예시
    rows = [
        {"date": "2026-06-08", "open": 10, "high": 10.2, "low": 9.5, "close": 9.6, "volume": 1},
        {"date": "2026-06-09", "open": 9.6, "high": 9.7, "low": 9.0, "close": 9.1, "volume": 1},
        {"date": "2026-06-10", "open": 9.1, "high": 9.2, "low": 8.6, "close": 8.7, "volume": 1},
        {"date": "2026-06-11", "open": 8.7, "high": 8.8, "low": 8.3, "close": 8.4, "volume": 1},
        {"date": "2026-06-12", "open": 8.4, "high": 8.5, "low": 8.0, "close": 8.2, "volume": 1},
        # 최신: 전저점(8.0) 부근에서 긴 아래꼬리 양봉
        {"date": "2026-06-15", "open": 8.2, "high": 8.4, "low": 7.6, "close": 8.35, "volume": 5},
    ]
    print(evaluate(pd.DataFrame(rows), lookback=5))
