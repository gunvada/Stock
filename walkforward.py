# -*- coding: utf-8 -*-
"""
워크포워드 / 구간 안정성 검증 (P0)
==================================
pullback_backtest_detail.csv(거래별 결과)를 **시간 구간**과 **거래량배율 버킷**으로
쪼개, 엣지가 특정 시기/구간에만 쏠려 있는지(과적합·장세 의존)를 검증한다.
읽기 전용(커밋된 백테스트 결과). API 키·네트워크 불필요.

핵심 질문: "평균 +수익이 전 구간에서 꾸준한가, 아니면 소수 구간/대박에 의존하는가?"

사용법:
  python walkforward.py [n_segments=6]
  python walkforward.py output/pullback_backtest_detail.csv 6
"""
import os
import sys

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
DEFAULT_DETAIL = os.path.join(OUT, "pullback_backtest_detail.csv")
TP = 10.0  # +10% 도달 기준


def bucket_stats(returns):
    """수익률 리스트 → 통계 dict (순수 함수)."""
    n = len(returns)
    if n == 0:
        return {"n": 0, "win_%": 0.0, "avg_%": 0.0, "median_%": 0.0,
                "tp_hit_%": 0.0, "best_%": 0.0, "worst_%": 0.0}
    wins = [r for r in returns if r > 0]
    s = sorted(returns)
    median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    return {
        "n": n,
        "win_%": round(len(wins) / n * 100, 0),
        "avg_%": round(sum(returns) / n, 1),
        "median_%": round(median, 1),
        "tp_hit_%": round(sum(1 for r in returns if r >= TP) / n * 100, 0),
        "best_%": round(max(returns), 1),
        "worst_%": round(min(returns), 1),
    }


def segment_by_time(detail, n_segments, col="close_exit_%"):
    """sig_date 정렬 후 n_segments 등분, 각 구간 통계. 반환: list[dict]."""
    d = detail.sort_values("sig_date").reset_index(drop=True)
    out = []
    n = len(d)
    if n == 0:
        return out
    size = max(1, -(-n // n_segments))  # ceil
    for i in range(0, n, size):
        chunk = d.iloc[i:i + size]
        st = bucket_stats(chunk[col].tolist())
        st["기간"] = f"{chunk['sig_date'].iloc[0]}~{chunk['sig_date'].iloc[-1]}"
        out.append(st)
    return out


def consistency(seg_stats):
    """구간 통계 → 안정성 지표(순수). 양(+)구간 비율, 평균들의 표준편차 등."""
    avgs = [s["avg_%"] for s in seg_stats if s["n"] > 0]
    k = len(avgs)
    if k == 0:
        return {}
    pos = sum(1 for a in avgs if a > 0)
    mean = sum(avgs) / k
    var = sum((a - mean) ** 2 for a in avgs) / k
    return {"segments": k, "양수구간_%": round(pos / k * 100, 0),
            "구간평균_평균": round(mean, 1), "구간평균_표준편차": round(var ** 0.5, 1)}


def vol_buckets(detail, col="close_exit_%"):
    """거래량배율 구간별 통계."""
    d = detail.copy()
    d["bk"] = pd.cut(d["vol_ratio"], [0, 20, 50, 1e9],
                     labels=["10-20배", "20-50배", "50배+"])
    rows = []
    for name, g in d.groupby("bk", observed=True):
        st = bucket_stats(g[col].tolist())
        st["구간"] = name
        rows.append(st)
    return rows


def main():
    args = [a for a in sys.argv[1:]]
    path = DEFAULT_DETAIL
    n_seg = 6
    for a in args:
        if a.endswith(".csv"):
            path = a
        elif a.isdigit():
            n_seg = int(a)
    if not os.path.exists(path):
        sys.exit(f"[오류] {path} 없음. 먼저 pullback_backtest.py 실행 필요.")

    d = pd.read_csv(path)
    print(f"[워크포워드] {len(d)}거래  {d['sig_date'].min()}~{d['sig_date'].max()}  ({n_seg}구간)")

    for scen, col in [("종가청산", "close_exit_%"), ("TP/SL플랜", "plan_exit_%")]:
        if col not in d.columns:
            continue
        segs = segment_by_time(d, n_seg, col)
        cons = consistency(segs)
        overall = bucket_stats(d[col].tolist())
        print("\n" + "=" * 88)
        print(f"  [{scen}] 시간 구간별 (전체: 승률 {overall['win_%']:.0f}% · 평균 {overall['avg_%']:+.1f}% · 중앙 {overall['median_%']:+.1f}%)")
        print("=" * 88)
        sdf = pd.DataFrame(segs)[["기간", "n", "win_%", "avg_%", "median_%", "tp_hit_%", "best_%", "worst_%"]]
        print(sdf.to_string(index=False))
        if cons:
            print(f"  안정성 → 양(+)구간 {cons['양수구간_%']:.0f}% · 구간평균 {cons['구간평균_평균']:+.1f}% "
                  f"(표준편차 {cons['구간평균_표준편차']:.1f})")

    print("\n" + "=" * 88)
    print("  [거래량배율 버킷별] (종가청산)")
    print("=" * 88)
    vdf = pd.DataFrame(vol_buckets(d))[["구간", "n", "win_%", "avg_%", "median_%", "tp_hit_%"]]
    print(vdf.to_string(index=False))

    pd.DataFrame(segment_by_time(d, n_seg)).to_csv(
        os.path.join(OUT, "walkforward_segments.csv"), index=False, encoding="utf-8-sig")
    print("\n  저장: output/walkforward_segments.csv")
    print("  ※ 평균이 +라도 '중앙값≈0 + 소수 구간/대박 의존'이면 신뢰성 낮음(과적합·장세의존).")


if __name__ == "__main__":
    main()
