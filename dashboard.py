# -*- coding: utf-8 -*-
"""
관리 대시보드 — 본장/프리마켓 트랙별 '최신 추천 + 누적 성적' 한눈 요약.
읽기 전용(커밋된 output/*.csv만 읽음). API 키·네트워크 불필요.

사용법:
  python dashboard.py            # 두 트랙 모두
  python dashboard.py regular    # 본장만
  python dashboard.py premarket  # 프리마켓만
"""
import os
import re
import sys
import glob

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
DATED = re.compile(r"_(\d{4}-\d{2}-\d{2})\.csv$")


def latest_dated(prefix):
    fs = [f for f in glob.glob(os.path.join(OUT, f"{prefix}_*.csv"))
          if DATED.search(os.path.basename(f))]
    return sorted(fs)[-1] if fs else None


def show_picks(path, none_msg):
    if not path:
        print(f"   {none_msg}")
        return
    d = pd.read_csv(path)
    date = DATED.search(os.path.basename(path)).group(1)
    print(f"   최신 픽 ({date}) — {len(d)}종목")
    if not d.empty:
        cols = [c for c in ["ticker", "gap_%", "vol_ratio", "dol_M", "dol_avg10_M", "dol_x",
                            "매수참고", "손절", "익절목표"] if c in d.columns]
        print("   " + d[cols].to_string(index=False).replace("\n", "\n   "))


def show_candle_verified(path):
    if not path:
        print("   (교차검증 파일 없음 — candle_verify.py 실행 필요)")
        return
    d = pd.read_csv(path)
    date = DATED.search(os.path.basename(path)).group(1)
    if d.empty or "pass" not in d.columns:
        print(f"   ({date}) 결과 없음")
        return
    passed = d[d["pass"] == True]
    print(f"   ({date}) {len(d)}종목 중 통과 {len(passed)}종목"
          + (f": {', '.join(passed['ticker'])}" if len(passed) else " (없음)"))
    cols = [c for c in ["ticker", "pass", "trend", "n_signals", "recent_signals", "last_candle"] if c in d.columns]
    print("   " + d[cols].to_string(index=False).replace("\n", "\n   "))


def show_ledger(path):
    if not os.path.exists(path):
        print("   (장부 없음 — 아직 채점된 거래 없음)")
        return
    d = pd.read_csv(path)
    if d.empty or "net_%" not in d.columns:
        print("   (장부 비어있음)")
        return
    net, n = d["net_%"], len(d)
    print(f"   누적 {n}거래 | 순익평균 {net.mean():+.2f}% | 승률 {(net>0).mean()*100:.0f}% "
          f"| 익절 {d['tp_hit'].mean()*100:.0f}% · 손절 {d['stop_hit'].mean()*100:.0f}%")
    cols = [c for c in ["date", "trade_date", "ticker", "net_%"] if c in d.columns]
    print("   최근 5거래:")
    print("   " + d[cols].tail(5).to_string(index=False).replace("\n", "\n   "))


def regular():
    print("=" * 72)
    print("  [본장 트랙] 눌림목(흡수) 반등 · 종가청산 · 회원시간 밖")
    print("=" * 72)
    print(" ▶ 추천종목 (pullback)")
    show_picks(latest_dated("pullback"), "(본장 최신 픽 파일 없음 — daily.yml 실행 필요)")
    print(" ▶ 캔들-베이스 교차검증 통과 (후보 축소)")
    show_candle_verified(latest_dated("candle_verified"))
    print(" ▶ 누적 성적 (verification_ledger)")
    show_ledger(os.path.join(OUT, "verification_ledger.csv"))


def premarket():
    print("=" * 72)
    print("  [프리마켓 트랙] 갭상승+활동량 모멘텀 · KST 18:30–22:00")
    print("=" * 72)
    print(" ▶ 추천종목 (premarket)")
    show_picks(latest_dated("premarket"), "(프리마켓 최신 픽 파일 없음 — premarket.yml 실행 필요)")
    print(" ▶ 누적 성적 (premarket_ledger)")
    show_ledger(os.path.join(OUT, "premarket_ledger.csv"))


def main():
    which = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
    if which in ("regular", "본장", "all"):
        regular()
    if which in ("premarket", "프리마켓", "all"):
        if which == "all":
            print()
        premarket()


if __name__ == "__main__":
    main()
