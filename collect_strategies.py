# -*- coding: utf-8 -*-
"""
GitHub 전략 수집기 (Strategy Collector) — 1단계: 수집/벤치마킹 후보 추리기
-------------------------------------------------------------------------
GitHub Search API 로 '주식/알고리즘 트레이딩 전략' 레포를 긁어와,
각 레포 README 에서 주장하는 수익률·CAGR·Sharpe·승률 숫자를 정규식으로
뽑아 한 표로 정리한다. 결과: output/strategies_<date>.csv

⚠ 매우 중요 — 여기서 뽑는 'claimed_return_%' 는 레포 작성자가 README 에
   적어둔 '주장값'일 뿐이다. 거의 다 백테스트 수치이고, 과최적화·미래참조·
   생존편향·수수료 누락이 섞여 있을 수 있어 그대로 믿으면 안 된다.
   이 스크립트는 '어떤 전략이 있고 뭐라고 주장하는지' 목록을 만드는 1단계다.
   진짜 벤치마킹(본인 데이터로 재검증)은 2단계(backtest.py 계열)에서 한다.

토큰: 환경변수 GITHUB_TOKEN (또는 config.json 의 github_token) 이 있으면
   검색 한도가 크게 올라간다(미인증 10회/분 → 인증 30회/분). 없어도 동작은 한다.
"""

import os
import re
import sys
import json
import time
import base64
import datetime as dt

import requests
import pandas as pd

# Windows 콘솔 한글 깨짐 방지 (scanner.py / verify.py 와 동일)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

GH_SEARCH = "https://api.github.com/search/repositories"
GH_README = "https://api.github.com/repos/{full_name}/readme"


# --------------------------------------------------------------------------- #
# 설정 로드 (scanner.load_config 패턴을 따름 — 환경변수 우선)
# --------------------------------------------------------------------------- #
def load_config():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)

    # 토큰은 선택사항. 환경변수가 있으면 우선.
    cfg["github_token"] = os.environ.get("GITHUB_TOKEN", cfg.get("github_token", "")).strip()

    c = cfg.setdefault("collect", {})
    c.setdefault("queries", [
        "algorithmic trading strategy backtest",
        "quant trading python returns",
        "stock trading bot backtest",
        "trading strategy sharpe ratio",
    ])
    c.setdefault("per_query", 30)
    c.setdefault("min_stars", 20)
    c.setdefault("claim_threshold_pct", 20.0)
    c.setdefault("max_readme_bytes", 200000)
    c.setdefault("search_sleep_seconds", 7)  # 미인증 10회/분 보호
    return cfg


def make_session(token):
    s = requests.Session()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "stock-strategy-collector",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    s.headers.update(headers)
    return s


# --------------------------------------------------------------------------- #
# 1) GitHub 검색 — 쿼리별 상위 레포
# --------------------------------------------------------------------------- #
def gh_get(session, url, params=None):
    """레이트리밋(403/429, X-RateLimit-Remaining=0)을 존중하며 GET."""
    for attempt in range(5):
        try:
            r = session.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            print(f"  네트워크 오류: {e} (재시도)")
            time.sleep(2 * (attempt + 1))
            continue

        remaining = r.headers.get("X-RateLimit-Remaining")
        if r.status_code in (403, 429) and remaining == "0":
            reset = int(r.headers.get("X-RateLimit-Reset", "0"))
            wait = max(5, reset - int(time.time()) + 1) if reset else 30
            wait = min(wait, 60)  # 너무 오래 잠들지 않도록 상한
            print(f"  [레이트리밋] {wait}s 대기 후 재시도... "
                  f"(GITHUB_TOKEN 설정 시 한도 크게 증가)")
            time.sleep(wait)
            continue
        return r

    return None


def search_repos(session, query, per_query, min_stars):
    """쿼리 1개에 대해 star 내림차순 상위 per_query 레포 메타데이터."""
    params = {
        "q": f"{query} stars:>={min_stars}",
        "sort": "stars",
        "order": "desc",
        "per_page": min(per_query, 100),
    }
    r = gh_get(session, GH_SEARCH, params)
    if r is None or r.status_code != 200:
        code = r.status_code if r is not None else "N/A"
        body = r.text[:160] if r is not None else ""
        print(f"  [검색 실패] '{query}' → HTTP {code} {body}")
        return []
    items = r.json().get("items", []) or []
    return items[:per_query]


# --------------------------------------------------------------------------- #
# 2) README 가져오기 + 주장 수치 추출
# --------------------------------------------------------------------------- #
def fetch_readme(session, full_name, max_bytes):
    """레포 README 원문(텍스트). 없거나 실패하면 빈 문자열."""
    r = gh_get(session, GH_README.format(full_name=full_name))
    if r is None or r.status_code != 200:
        return ""
    data = r.json()
    content = data.get("content", "")
    encoding = data.get("encoding", "")
    if encoding == "base64" and content:
        try:
            raw = base64.b64decode(content)
            return raw[:max_bytes].decode("utf-8", errors="ignore")
        except Exception:
            return ""
    return ""


# 백분율 주장: '키워드 ... 35%' 또는 '35% ... 키워드' 양방향
_PCT = r"(\d{1,4}(?:\.\d+)?)\s*%"
_RETURN_KW = (r"return|returns|profit|gain|cagr|annual|yearly|roi|"
              r"수익률|수익|연수익|누적")
# 역방향(NUM% ... 키워드) 연결부는 숫자를 허용하지 않는다 — 안 그러면
# 앞쪽의 무관한 수치(예: 'returns 120% over 3 years. win rate')가 끌려온다.
_RETURN_NEAR = re.compile(
    rf"(?:(?:{_RETURN_KW})[^%\n]{{0,40}}?{_PCT})"
    rf"|(?:{_PCT}[^%\n\d]{{0,25}}?(?:{_RETURN_KW}))",
    re.IGNORECASE,
)
_SHARPE = re.compile(r"sharpe[^0-9\-\n]{0,20}(-?\d{1,2}(?:\.\d+)?)", re.IGNORECASE)
# 승률은 보조 컬럼이라 흔한 정방향('win rate: X%', '승률 X%')만 본다.
# 역방향까지 넣으면 앞 키워드를 먼저 삼켜 정작 뒤의 값을 놓치는 부작용이 큼.
_WINRATE = re.compile(rf"(?:win\s*rate|승률)[^%\n]{{0,20}}?{_PCT}", re.IGNORECASE)


def _first_num(match):
    """그룹 중 처음으로 잡힌 숫자를 float 로."""
    for g in match.groups():
        if g is not None:
            try:
                return float(g)
            except ValueError:
                continue
    return None


def extract_claims(text):
    """README 에서 주장 수익률/Sharpe/승률을 뽑는다.
    반환: dict(max_return_pct, sharpe, win_rate_pct, snippet)."""
    if not text:
        return {"max_return_pct": None, "sharpe": None,
                "win_rate_pct": None, "snippet": ""}

    returns, best_match = [], None
    best_val = -1.0
    for m in _RETURN_NEAR.finditer(text):
        val = _first_num(m)
        if val is None:
            continue
        # 비현실적 노이즈(예: '100% test coverage', 버전 99999%) 컷
        if val <= 0 or val > 10000:
            continue
        returns.append(val)
        if val > best_val:
            best_val, best_match = val, m

    sharpes = [float(x) for x in _SHARPE.findall(text)]
    sharpes = [s for s in sharpes if -5 <= s <= 20]

    winrates = []
    for m in _WINRATE.finditer(text):
        val = _first_num(m)
        if val is not None and 0 < val <= 100:
            winrates.append(val)

    snippet = ""
    if best_match is not None:
        s = max(0, best_match.start() - 30)
        e = min(len(text), best_match.end() + 30)
        snippet = re.sub(r"\s+", " ", text[s:e]).strip()

    return {
        "max_return_pct": max(returns) if returns else None,
        "sharpe": max(sharpes) if sharpes else None,
        "win_rate_pct": max(winrates) if winrates else None,
        "snippet": snippet,
    }


def has_backtest_signal(repo, readme):
    """백테스트 코드/언급 흔적이 있으면 True (재검증 가능성 가늠용)."""
    hay = " ".join([
        repo.get("name", ""), repo.get("description") or "",
        " ".join(repo.get("topics", []) or []), readme[:5000],
    ]).lower()
    return any(k in hay for k in ("backtest", "back-test", "backtrader",
                                  "vectorbt", "백테스트"))


# --------------------------------------------------------------------------- #
# 메인
# --------------------------------------------------------------------------- #
def main():
    cfg = load_config()
    c = cfg["collect"]
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    session = make_session(cfg["github_token"])

    if not cfg["github_token"]:
        print("[안내] GITHUB_TOKEN 미설정 → 검색 한도 10회/분으로 느립니다. "
              "토큰 설정 시 빨라집니다.\n")

    sleep_s = c["search_sleep_seconds"]
    seen = {}  # full_name -> repo meta (쿼리 중복 제거)

    print(f"[1/2] GitHub 검색 ({len(c['queries'])} 쿼리, star≥{c['min_stars']})...")
    for q in c["queries"]:
        items = search_repos(session, q, c["per_query"], c["min_stars"])
        print(f"  '{q}' → {len(items)} 레포")
        for it in items:
            fn = it.get("full_name")
            if fn and fn not in seen:
                seen[fn] = it
        time.sleep(sleep_s)  # 검색 레이트리밋 보호

    print(f"\n[2/2] README 수집 + 주장 수치 추출 ({len(seen)} 레포)...")
    rows = []
    for i, (fn, repo) in enumerate(seen.items(), 1):
        readme = fetch_readme(session, fn, c["max_readme_bytes"])
        claims = extract_claims(readme)
        rows.append({
            "full_name": fn,
            "stars": repo.get("stargazers_count", 0),
            "language": repo.get("language"),
            "claimed_return_%": claims["max_return_pct"],
            "sharpe": claims["sharpe"],
            "win_rate_%": claims["win_rate_pct"],
            "has_backtest": has_backtest_signal(repo, readme),
            "pushed_at": (repo.get("pushed_at") or "")[:10],
            "url": repo.get("html_url"),
            "description": (repo.get("description") or "")[:120],
            "claim_snippet": claims["snippet"][:120],
        })
        if i % 10 == 0:
            print(f"  ...{i}/{len(seen)}")
        time.sleep(0.3)  # README 호출 간 가벼운 간격

    if not rows:
        print("  수집된 레포가 없습니다. config 의 collect.queries/min_stars 를 조정하세요.")
        return

    res = pd.DataFrame(rows)
    # 주장 수익률(없으면 -1) → star 순으로 정렬: 주장 높은 것 우선, 동률은 인기순
    res["_sort_ret"] = res["claimed_return_%"].fillna(-1)
    res = res.sort_values(["_sort_ret", "stars"], ascending=False).drop(columns="_sort_ret")
    res = res.reset_index(drop=True)
    res.insert(0, "rank", res.index + 1)

    stamp = dt.date.today().isoformat()
    out_path = os.path.join(OUTPUT_DIR, f"strategies_{stamp}.csv")
    res.to_csv(out_path, index=False, encoding="utf-8-sig")

    thr = c["claim_threshold_pct"]
    over = res[res["claimed_return_%"].fillna(-1) >= thr]
    with_bt = over[over["has_backtest"]]

    print("\n" + "=" * 80)
    print(f"  GitHub 전략 수집 결과  ({len(res)} 레포)")
    print("=" * 80)
    print(f"  주장 수익률 ≥ {thr:.0f}% 인 레포 : {len(over)}  "
          f"(그중 backtest 흔적 있음: {len(with_bt)})")
    print("-" * 80)

    show = ["rank", "full_name", "stars", "language",
            "claimed_return_%", "sharpe", "win_rate_%", "has_backtest", "pushed_at"]
    head = over if not over.empty else res
    with pd.option_context("display.max_rows", 40, "display.width", 200):
        print(head[show].head(40).to_string(index=False))

    print("-" * 80)
    print(f"  전체 CSV 저장: {out_path}")
    print("=" * 80)
    print("  ⚠ claimed_return_% / sharpe / win_rate_% 는 README 의 '주장값'이다.")
    print("    거의 다 비검증 백테스트 수치 — 과최적화·미래참조·비용누락 가능.")
    print("    2단계: has_backtest=True 인 것 위주로 전략 로직을 가져와")
    print("    본인 데이터(Polygon/yfinance)로 직접 재검증해야 진짜 벤치마킹이다.")


if __name__ == "__main__":
    main()
