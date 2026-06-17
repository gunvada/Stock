# -*- coding: utf-8 -*-
"""5분봉 필터/선별 순수 로직 테스트 (네트워크 불필요)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import intraday5m_filters as f

SPRING = (10, 10.92, 9.95, 10.90)
NEUT = (10, 10.05, 9.95, 9.98)


def test_enrich_vwap_and_firsthour():
    raw = [(10, 10.5, 9.5, 10.0, 1000)] * 14
    dicts, ohlc = f.enrich_day(raw)
    assert len(dicts) == 14
    assert dicts[0]["fh"] is True and dicts[12]["fh"] is False   # 13번째(idx12)부터 첫1시간 밖
    assert abs(dicts[0]["vwap"] - (10.5 + 9.5 + 10.0) / 3) < 1e-6  # 첫봉 vwap=typical


def test_vol_surge_flag():
    raw = [(10, 10.1, 9.9, 10.0, 100)] * 6 + [(10, 10.1, 9.9, 10.0, 1000)]  # 마지막봉 급증
    dicts, _ = f.enrich_day(raw)
    assert dicts[-1]["vs"] is True
    assert dicts[3]["vs"] is False


def test_signal_at_consecutive():
    ohlc = [NEUT, SPRING, SPRING]
    assert f.signal_at(ohlc, 2, "consecutive") is True    # 1,2 연속 상승
    assert f.signal_at(ohlc, 1, "consecutive") is False   # 0봉(NEUT)은 신호 아님


def test_context_ok():
    bar = {"c": 10.0, "vwap": 9.5, "fh": True, "vs": False}
    assert f.context_ok(bar, {"above_vwap": True}) is True      # 10 >= 9.5
    assert f.context_ok(bar, {"vol_surge": True}) is False      # vs=False
    assert f.context_ok(bar, {"first_hour": True}) is True


def test_simulate_f_firsthour_filters_out():
    # 신호가 첫1시간 밖에만 있으면 first_hour 필터 시 거래 0
    ohlc = [NEUT] * 13 + [SPRING, (10.0, 10.0, 9.9, 9.95), (9.95, 10.6, 9.9, 10.5)]
    dicts, _ = f.enrich_day([(o, h, l, c, 100) for (o, h, l, c) in ohlc])
    no_filter = f.simulate_f(dicts, ohlc, 5, 3, "single", {})
    fh_filter = f.simulate_f(dicts, ohlc, 5, 3, "single", {"first_hour": True})
    assert len(no_filter) >= 1 and len(fh_filter) == 0


def _run():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}개 테스트 통과")


if __name__ == "__main__":
    _run()
