# -*- coding: utf-8 -*-
"""윈도우 시뮬 순수 로직 테스트 (네트워크 불필요)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import window_sim as ws


def test_window_prices_basic():
    bars = [("09:30", 10.0), ("09:35", 10.2), ("10:30", 10.5)]
    entry, exit_ = ws.window_prices(bars)
    assert entry == 10.0 and exit_ == 10.5     # 첫봉 시가 / 마지막(10:30) 시가


def test_window_prices_insufficient():
    assert ws.window_prices([("09:30", 10.0)]) is None
    assert ws.window_prices([]) is None


def test_window_prices_bad_entry():
    assert ws.window_prices([("09:30", 0.0), ("10:30", 1.0)]) is None


def test_next_trading_date_skips_weekend():
    assert ws.next_trading_date("2026-06-12") == "2026-06-15"  # 금→월
    assert ws.next_trading_date("2026-06-15") == "2026-06-16"


def _run():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"\n{len(fns)}개 테스트 통과")


if __name__ == "__main__":
    _run()
