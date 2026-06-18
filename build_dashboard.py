# -*- coding: utf-8 -*-
"""
한눈 대시보드 생성 — DASHBOARD.md (GitHub 모바일 렌더링용)
==========================================================
모든 산출물(추천 픽·판정·캔들검증·윈도우시뮬·검증장부·실매매 주문)을 하나의
마크다운으로 모은다. daily.yml에서 매일 자동 갱신. 읽기 전용·키 불필요.

사용법: python build_dashboard.py  → DASHBOARD.md
"""
import os
import re
import sys
import glob
import datetime as dt

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output")
DATED = re.compile(r"_(\d{4}-\d{2}-\d{2})\.csv$")


def latest(prefix):
    fs = [f for f in glob.glob(os.path.join(OUT, f"{prefix}_*.csv")) if DATED.search(os.path.basename(f))]
    return sorted(fs)[-1] if fs else None


def md_table(df, cols):
    cols = [c for c in cols if c in df.columns]
    if df.empty or not cols:
        return "_(데이터 없음)_\n"
    head = "| " + " | ".join(cols) + " |\n"
    sep = "|" + "|".join(["---"] * len(cols)) + "|\n"
    rows = ""
    for _, r in df[cols].iterrows():
        rows += "| " + " | ".join(str(r[c]) for c in cols) + " |\n"
    return head + sep + rows


def verdict(dol_x, dol_M, candle_pass):
    try:
        x = float(dol_x); dm = float(dol_M)
    except (TypeError, ValueError):
        return "—"
    if x < 1:
        return "🔴회피(돈식음)"
    sc = int(bool(candle_pass)) + (x >= 3) + (dm >= 10)
    return ["🟠관망", "🟠주의", "🟡양호", "🟢우수"][min(sc, 3)]


def picks_section():
    p = latest("pullback")
    if not p:
        return "## 🎯 오늘의 추천 픽\n_(픽 없음 — daily.yml 실행 필요)_\n"
    date = DATED.search(os.path.basename(p)).group(1)
    df = pd.read_csv(p)
    cv = latest("candle_verified")
    cvd = pd.read_csv(cv).set_index("ticker") if cv else pd.DataFrame()
    rows = []
    for _, r in df.iterrows():
        t = r["ticker"]
        cp = bool(cvd.loc[t, "pass"]) if (not cvd.empty and t in cvd.index and "pass" in cvd.columns) else False
        tr = cvd.loc[t, "trend"] if (not cvd.empty and t in cvd.index and "trend" in cvd.columns) else "—"
        rows.append({
            "종목": t, "종가": r.get("c"), "거래대금M": r.get("dol_M"),
            "10일평균M": r.get("dol_avg10_M", "—"), "증가배": r.get("dol_x", "—"),
            "매수참고": r.get("매수참고"), "손절": r.get("손절"), "익절": r.get("익절목표"),
            "캔들": "✅" if cp else "❌", "추세": tr,
            "판정": verdict(r.get("dol_x"), r.get("dol_M"), cp),
        })
    out = pd.DataFrame(rows)
    order = {"🟢우수": 0, "🟡양호": 1, "🟠주의": 2, "🟠관망": 3, "🔴회피(돈식음)": 4, "—": 9}
    out["_o"] = out["판정"].map(lambda v: order.get(v, 9))
    out = out.sort_values(["_o", "거래대금M"], ascending=[True, False]).drop(columns="_o")
    s = f"## 🎯 오늘의 추천 픽 (본장) — 신호일 {date}\n\n"
    s += md_table(out, ["종목", "종가", "거래대금M", "10일평균M", "증가배",
                        "매수참고", "손절", "익절", "캔들", "추세", "판정"])
    s += "\n_판정: 🟢우수 / 🟡양호 / 🟠주의 / 🔴회피(거래대금 식음). 캔들=교차검증 통과._\n"
    return s


def ledger_section(title, path, cols, retcol="ret_%"):
    s = f"## {title}\n\n"
    if not os.path.exists(path):
        return s + "_(장부 없음)_\n"
    d = pd.read_csv(path)
    if d.empty:
        return s + "_(비어있음)_\n"
    if retcol in d.columns:
        rr = pd.to_numeric(d[retcol], errors="coerce").dropna()
        if len(rr):
            s += f"**누적 {len(rr)}거래 · 평균 {rr.mean():+.2f}% · 승률 {(rr>0).mean()*100:.0f}%**\n\n"
    s += md_table(d.tail(8), cols)
    return s


def main():
    now = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    parts = [f"# 📊 트레이딩 대시보드\n\n_갱신 {now} · `python build_dashboard.py`로 재생성_\n"]
    parts.append("> ⚠️ 검증상 강건한 수익 엣지 미입증 — **후보·기록용**. 소액·손절 −8% 준수.\n")
    parts.append(picks_section())
    parts.append(ledger_section(
        "📈 윈도우 시뮬 (KST 18:30매수→22:30개장매도, 창1)",
        os.path.join(OUT, "window_sim_ledger.csv"),
        ["trade_date", "ticker", "entry_0530", "exit_0930", "ret_%", "net_%"]))
    parts.append(ledger_section(
        "📒 종가청산 검증 장부 (룰 +10%/−8%)",
        os.path.join(OUT, "verification_ledger.csv"),
        ["trade_date", "ticker", "oc_%", "net_%"], retcol="net_%"))
    parts.append(ledger_section(
        "📝 실매매 주문/저널 (raw, 룰없음)",
        os.path.join(OUT, "manual_trades.csv"),
        ["trade_date", "ticker", "entry", "exit", "ret_%", "note"]))
    md = "\n".join(parts)
    with open(os.path.join(BASE, "DASHBOARD.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print("DASHBOARD.md 생성 완료")


if __name__ == "__main__":
    main()
