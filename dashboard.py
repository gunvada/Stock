# -*- coding: utf-8 -*-
"""
대시보드 생성기  (Static HTML Dashboard)
=========================================
모든 산출물(오늘 추천 픽·프리마켓 픽·누적 장부 성과·분석 인사이트·
파이프라인 상태)을 단일 self-contained HTML 한 장으로 묶는다. 외부 의존성·
서버 불필요 — output/dashboard.html 을 브라우저로 열면 끝.

데이터 소스(있는 것만 표시):
  output/recommend_<신호일>.csv     최신 = 오늘의 추천 픽
  output/premarket_<날짜>.csv       최신 = 프리마켓 갭상승 픽
  output/recommend_ledger.csv       추천 픽 누적 모니터링(시초→종가)
  output/premarket_ledger.csv       프리마켓 06:30→09:30 개장가 청산 누적
  output/feature_analysis.csv       특성별 다음날 수익률 변별력
  output/prior_runup_analysis.csv   직전상승률 코호트 성과
  output/cache/grouped_*.json       백테스트 표본 규모

사용법: python dashboard.py   → output/dashboard.html
"""
import os
import re
import sys
import glob
import html
import datetime as dt

import pandas as pd

import scanner

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = scanner.OUTPUT_DIR


# --------------------------------------------------------------------------- #
# 헬퍼
# --------------------------------------------------------------------------- #
def _latest(prefix):
    files = sorted(glob.glob(os.path.join(OUT, f"{prefix}_*.csv")))
    files = [f for f in files
             if re.search(rf"{prefix}_(\d{{4}}-\d{{2}}-\d{{2}})\.csv$", os.path.basename(f))]
    return files[-1] if files else None


def _read(path):
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _fmt(v):
    if pd.isna(v):
        return ""
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:,.0f}"
    return html.escape(str(v))


def signed_cell(v):
    """+면 초록, -면 빨강 색칠한 td."""
    if pd.isna(v):
        return "<td></td>"
    cls = "pos" if v > 0 else ("neg" if v < 0 else "zero")
    return f'<td class="{cls}">{v:+.1f}%</td>'


def verdict_badge(v):
    m = {"강한매수": "buy2", "매수관심": "buy1", "중립": "neu",
         "매도주의": "sell1", "강한매도": "sell2"}
    cls = m.get(str(v), "neu")
    return f'<span class="badge {cls}">{html.escape(str(v))}</span>'


def table(df, cols, headers, fmts=None):
    """DataFrame → HTML table. fmts: {col: callable(value)->td문자열}."""
    if df.empty:
        return '<p class="empty">데이터 없음</p>'
    fmts = fmts or {}
    th = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    trs = []
    for _, r in df.iterrows():
        tds = []
        for c in cols:
            if c in fmts:
                tds.append(fmts[c](r.get(c)))
            else:
                tds.append(f"<td>{_fmt(r.get(c))}</td>")
        trs.append("<tr>" + "".join(tds) + "</tr>")
    return f'<table><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def stat_card(label, value, sub="", tone="neutral"):
    return (f'<div class="card {tone}"><div class="card-val">{value}</div>'
            f'<div class="card-lbl">{html.escape(label)}</div>'
            f'<div class="card-sub">{html.escape(sub)}</div></div>')


# --------------------------------------------------------------------------- #
# 섹션 빌더
# --------------------------------------------------------------------------- #
def sec_picks():
    p = _latest("recommend")
    if not p:
        return "<h2>📌 오늘의 추천 픽</h2><p class='empty'>recommend_*.csv 없음</p>", None
    sig = re.search(r"recommend_(\d{4}-\d{2}-\d{2})", os.path.basename(p)).group(1)
    df = _read(p)
    cols = ["ticker", "rank_score", "ratio", "dollar_surge_x", "avg_dollar_vol_10d_M",
            "candle_signal", "candle_pos", "close_pos", "매수참고"]
    cols = [c for c in cols if c in df.columns]
    head = ["종목", "종합점수", "거래량배율", "거래대금배율", "평균거래대금($M)",
            "신호", "추세위치", "마감강도", "매수참고($)"]
    head = head[:len(cols)]
    fmts = {"candle_signal": lambda v: f"<td>{verdict_badge(v)}</td>",
            "ticker": lambda v: f'<td class="tk">{html.escape(str(v))}</td>'}
    t = table(df, cols, head, fmts)
    h = (f"<h2>📌 오늘의 추천 픽 <span class='sub'>(신호일 {sig} → 다음 거래일 매매)</span></h2>"
         f"<p class='note'>순번 = candle_score(형태+위치×1.5+마감강도) + log₁₀(거래량배율)</p>{t}")
    return h, sig


def sec_premarket():
    p = _latest("premarket")
    if not p:
        return "<h2>🌅 프리마켓 픽</h2><p class='empty'>premarket_*.csv 없음</p>"
    d = re.search(r"premarket_(\d{4}-\d{2}-\d{2})", os.path.basename(p)).group(1)
    df = _read(p)
    cols = [c for c in ["ticker", "candle_signal", "prior_close", "pm_price", "gap_%",
                        "pm_bars", "매수참고"] if c in df.columns]
    head = {"ticker": "종목", "candle_signal": "신호", "prior_close": "전일종가",
            "pm_price": "프리마켓가", "gap_%": "갭%", "pm_bars": "활동분봉", "매수참고": "매수참고"}
    fmts = {"candle_signal": lambda v: f"<td>{verdict_badge(v)}</td>",
            "gap_%": lambda v: signed_cell(v),
            "ticker": lambda v: f'<td class="tk">{html.escape(str(v))}</td>'}
    t = table(df, cols, [head[c] for c in cols], fmts)
    return (f"<h2>🌅 프리마켓 픽 <span class='sub'>({d} · ET 05:30–09:00)</span></h2>"
            f"<p class='note'>★ 권장 진입 06:30 ET (KST 19:30) · 09:30 개장가 청산</p>{t}")


def ledger_block(path, title, date_col, entry_desc):
    df = _read(path)
    if df.empty:
        return f"<h3>{title}</h3><p class='empty'>장부 없음</p>"
    n = len(df)
    avg = df["net_%"].mean()
    win = (df["net_%"] > 0).mean() * 100
    hi = df["hi_%"].mean() if "hi_%" in df.columns else float("nan")
    tone = "good" if avg > 0 else "bad"
    cards = (stat_card("순익 평균/거래", f"{avg:+.1f}%", entry_desc, tone)
             + stat_card("상승 비율", f"{win:.0f}%", f"{(df['net_%']>0).sum()}/{n}",
                         "good" if win >= 50 else "neutral")
             + stat_card("장중 최고 평균", f"{hi:+.1f}%" if pd.notna(hi) else "—", "도달 기준")
             + stat_card("누적 거래수", f"{n}", "표본"))
    # 최근 거래 표
    show = df.tail(12).iloc[::-1]
    cols = [date_col, "ticker", "candle_signal"]
    cols += [c for c in ["entry_px", "exit_px", "open", "close"] if c in df.columns]
    cols += [c for c in ["oc_%", "hi_%", "lo_%", "net_%"] if c in df.columns]
    hmap = {date_col: "날짜", "ticker": "종목", "candle_signal": "신호",
            "entry_px": "진입", "exit_px": "청산", "open": "시초", "close": "종가",
            "oc_%": "수익%", "hi_%": "최고%", "lo_%": "최저%", "net_%": "순익%"}
    fmts = {c: signed_cell for c in ["oc_%", "hi_%", "lo_%", "net_%"] if c in df.columns}
    fmts["candle_signal"] = lambda v: f"<td>{verdict_badge(v)}</td>"
    fmts["ticker"] = lambda v: f'<td class="tk">{html.escape(str(v))}</td>'
    t = table(show, cols, [hmap[c] for c in cols], fmts)
    return f"<h3>{title}</h3><div class='cards'>{cards}</div>{t}"


def sec_ledgers():
    rec = ledger_block(os.path.join(OUT, "recommend_ledger.csv"),
                       "추천 픽 (시초→종가 모니터링)", "trade_date", "당일 시초→종가")
    pm = ledger_block(os.path.join(OUT, "premarket_ledger.csv"),
                      "프리마켓 (06:30→09:30 개장가)", "date", "06:30 진입→09:30 청산")
    return f"<h2>📊 누적 성과</h2>{rec}{pm}"


def sec_insights():
    out = ["<h2>🔬 분석 인사이트</h2>"]
    # 특성 변별력
    fa = os.path.join(OUT, "feature_analysis.csv")
    if os.path.exists(fa):
        out.append("<h3>직전상승률 가설 검정 & 특성 변별력</h3>")
        out.append("<ul class='ins'>"
                   "<li><b>평균회귀 가설 기각</b>: 직전 7일 100%+ 오른 폭증주가 다음날 더 유리(+2.0%) — 모멘텀 지속.</li>"
                   "<li><b>갭하락 후보가 최악</b>(−4.7%) → 갭 하한 필터(min_signal_gap_pct) 도입.</li>"
                   "<li><b>저가 분위 우세</b>($0.5대 +3.9%/45%) — 단 슬리피지 위험으로 가중만.</li>"
                   "<li>단일 특성 상관은 모두 |0.08| 이하 — 표본 확대 후 재검증 필요.</li>"
                   "</ul>")
    pr = _read(os.path.join(OUT, "prior_runup_analysis.csv"))
    if not pr.empty and "prior7_%" in pr.columns:
        hi = pr[pr["prior7_%"] >= 100]["fwd_oc_net_%"]
        lo = pr[pr["prior7_%"] < 100]["fwd_oc_net_%"]
        cards = (stat_card("직전100%+ 순익", f"{hi.mean():+.1f}%", f"n={len(hi)} · 상승{(hi>0).mean()*100:.0f}%",
                           "good" if hi.mean() > 0 else "bad")
                 + stat_card("직전100%미만 순익", f"{lo.mean():+.1f}%", f"n={len(lo)} · 상승{(lo>0).mean()*100:.0f}%",
                             "good" if lo.mean() > 0 else "bad"))
        out.append(f"<div class='cards'>{cards}</div>")
    return "".join(out)


def sec_status(sig_date):
    grouped = glob.glob(os.path.join(OUT, "cache", "grouped_*.json"))
    dates = sorted(re.search(r"grouped_(\d{4}-\d{2}-\d{2})", os.path.basename(p)).group(1)
                   for p in grouped if re.search(r"grouped_\d{4}-\d{2}-\d{2}", p))
    span = f"{dates[0]} ~ {dates[-1]}" if dates else "—"
    surge = _latest("surge")
    last_scan = re.search(r"surge_(\d{4}-\d{2}-\d{2})", os.path.basename(surge)).group(1) if surge else "—"
    cards = (stat_card("최근 스캔 신호일", last_scan, "surge CSV 기준")
             + stat_card("백테스트 캐시", f"{len(dates)}거래일", span)
             + stat_card("오늘 추천 신호일", sig_date or "—", "recommend CSV"))
    return f"<h2>⚙️ 파이프라인 상태</h2><div class='cards'>{cards}</div>"


CSS = """
*{box-sizing:border-box}body{margin:0;font-family:'Segoe UI',-apple-system,'Malgun Gothic',sans-serif;
background:#0f1420;color:#e6e9ef;line-height:1.5}
.wrap{max-width:1100px;margin:0 auto;padding:24px}
header{display:flex;justify-content:space-between;align-items:baseline;border-bottom:2px solid #2a3550;padding-bottom:12px;margin-bottom:8px;flex-wrap:wrap;gap:8px}
h1{font-size:22px;margin:0}h1 .em{color:#5b9dff}
.ts{color:#8a93a6;font-size:13px}
h2{font-size:18px;margin:28px 0 8px;color:#cdd6e8}
h2 .sub{font-size:13px;color:#8a93a6;font-weight:normal}
h3{font-size:15px;margin:18px 0 8px;color:#aebbd6}
.note{color:#8a93a6;font-size:12px;margin:0 0 8px}
table{width:100%;border-collapse:collapse;font-size:13px;margin:6px 0 4px;background:#161d2e;border-radius:8px;overflow:hidden}
th{background:#1f2940;color:#9fb0d0;text-align:right;padding:8px 10px;font-weight:600}
th:first-child,td:first-child{text-align:left}
td{padding:7px 10px;text-align:right;border-top:1px solid #222c44}
td.tk{font-weight:700;color:#fff}
td.pos{color:#3ddc84;font-weight:600}td.neg{color:#ff6b6b;font-weight:600}td.zero{color:#8a93a6}
.badge{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700}
.badge.buy2{background:#0f5132;color:#3ddc84}.badge.buy1{background:#1c3a2e;color:#7fe0a8}
.badge.neu{background:#33384a;color:#aab}.badge.sell1{background:#4a2a1c;color:#ffb088}
.badge.sell2{background:#5c1e1e;color:#ff8080}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:8px 0}
.card{background:#161d2e;border:1px solid #222c44;border-radius:10px;padding:14px;text-align:center}
.card.good{border-color:#1f6b43}.card.bad{border-color:#7a2e2e}
.card-val{font-size:24px;font-weight:800}
.card.good .card-val{color:#3ddc84}.card.bad .card-val{color:#ff6b6b}
.card-lbl{font-size:12px;color:#aebbd6;margin-top:4px}.card-sub{font-size:11px;color:#8a93a6}
.empty{color:#8a93a6;font-style:italic;padding:8px 0}
ul.ins{font-size:13px;color:#cdd6e8;padding-left:18px}ul.ins li{margin:4px 0}
footer{margin-top:32px;color:#6b7488;font-size:11px;border-top:1px solid #222c44;padding-top:12px}
"""


def main():
    os.makedirs(OUT, exist_ok=True)
    now = dt.datetime.now()
    picks_html, sig = sec_picks()
    body = "".join([
        picks_html,
        sec_premarket(),
        sec_ledgers(),
        sec_insights(),
        sec_status(sig),
    ])
    doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>볼륨서지 스캐너 대시보드</title><style>{CSS}</style></head>
<body><div class="wrap">
<header><h1>📈 <span class="em">볼륨서지</span> 스캐너 대시보드</h1>
<span class="ts">생성 {now:%Y-%m-%d %H:%M}</span></header>
{body}
<footer>※ 본 대시보드의 모든 수치는 후보·모니터링 자료이며 매매 신호가 아닙니다.
변동성 극심 — 소액·리스크 관리 필수. 표본이 작아 통계는 누적될수록 신뢰도가 올라갑니다.</footer>
</div></body></html>"""

    path = os.path.join(OUT, "dashboard.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"[완료] 대시보드 생성: {path}")
    print(f"  → 브라우저로 열기: file://{path}")


if __name__ == "__main__":
    main()
