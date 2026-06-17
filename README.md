# 거래량 폭증주 스캐너 (US Volume Surge Scanner)

미국 증시 전 종목의 일봉을 받아와, **최근 7거래일 동안 거래량이 평소 대비 N배
폭증**한 소형주/페니주 후보를 매일 미국 장 개장 전(한국시간 22:30 직전)에
자동으로 골라낸다.

> ⚠️ **중요 — 읽고 시작하세요.**
> 이 도구는 **후보 종목 스캐너**이지 매매 신호기나 수익 보장 도구가 아닙니다.
> "매일 10% 이상 수익"은 어떤 전략으로도 지속 보장이 불가능하며, 거래량 폭증
> 페니주는 하루 -30%도 흔합니다. 결과는 반드시 본인이 검증하고, 소액·손절선
> 설정 등 리스크 관리를 직접 하세요. 매매 주문은 이 도구가 실행하지 않습니다.

## 동작 방식
- **Polygon `grouped daily`** 엔드포인트로 하루치 전 종목 일봉을 **호출 1회**로 수신
  → 최근 7거래일 = 약 7~10회 호출로 시장 전체 스캔.
- 종목별로 `최신일 거래량 / 직전일들 거래량(중앙값)` = **폭증 배율** 계산.
- 가격대(기본 $0.3~$20), 최소 거래량/거래대금 필터로 소형주·페니주만 추림.
- (선택) **Finnhub**로 상위 후보 실시간/프리마켓 시세 보강.

## 설치
```powershell
cd "C:\Users\ADMIN\Desktop\주식시장"
python -m pip install -r requirements.txt
```
(pandas, requests만 필요 — 이미 설치돼 있으면 생략 가능)

## 설정
1. https://polygon.io 가입 → 무료 API 키 발급 (Stocks Starter 무료 티어 가능)
2. `config.example.json` 을 `config.json` 으로 복사
3. `polygon_api_key` 에 키 입력. (Finnhub 키는 선택 — 비워도 됨)

키를 파일에 두기 싫으면 환경변수로도 가능:
```powershell
$env:POLYGON_API_KEY = "your_key"
```

### 주요 설정값 (config.json → scan)
| 키 | 의미 | 기본 |
|---|---|---|
| `lookback_trading_days` | 비교 기간(거래일) | 7 |
| `volume_surge_threshold` | "폭증" 기준 배율 | 50 |
| `watch_threshold` | "관찰" 기준 배율 | 10 |
| `price_min` / `price_max` | 가격대 필터 | 0.3 ~ 20 |
| `min_baseline_avg_volume` | 평소 최소 거래량(노이즈 제거) | 50,000 |
| `min_latest_volume` | 당일 최소 거래량 | 300,000 |
| `min_latest_dollar_volume` | 당일 최소 거래대금($) | 1,000,000 |
| `rate_sleep_seconds` | 호출 간 대기(무료 5/분이면 13) | 13 |

> 무료 티어는 5호출/분 제한이라 7일 스캔에 ~2분 걸립니다. 유료 키면
> `config.json` 에 `"rate_sleep_seconds": 1` 을 추가해 빠르게 돌릴 수 있습니다.
> **50배는 매우 희귀**합니다. 결과가 비면 `volume_surge_threshold` 를 낮추세요.

## 수동 실행
```powershell
python scanner.py
```
결과는 콘솔 출력 + `output\surge_<날짜>.csv` 저장.

## 매일 자동 실행 (장 개장 전)
```powershell
powershell -ExecutionPolicy Bypass -File .\register_task.ps1
```
→ 매일 **22:00 KST**에 자동 실행, 로그는 `logs\` 에 저장.
시간 변경은 `register_task.ps1` 의 `-At 22:00` 수정.

- 즉시 테스트: `Start-ScheduledTask -TaskName VolumeSurgeScanner`
- 삭제: `Unregister-ScheduledTask -TaskName VolumeSurgeScanner -Confirm:$false`

## 교차 검증 + 프리마켓 (verify.py)
단일 소스(Polygon)만 믿지 않고, **서로 독립적인 무료 채널로 같은 값을 다시
계산해 신뢰도를 점검**한다. scanner 실행 후 이어서:
```powershell
python verify.py
```
- **Polygon**(기준값) ↔ **Yahoo(yfinance)** 두 독립 소스로 폭증 배율을 각각 재계산.
- **Stooq**(키 불필요, 마이크로캡은 없을 수 있어 베스트에포트), **Finnhub**(무료 키 넣으면) 추가 대조.
- 프리마켓/실시간 시세를 함께 표시(yfinance, 키 불필요).
- 결과는 `output\verified_<날짜>.csv` 저장.

판정 기준:
- **✅ CONFIRMED** — Yahoo가 폭증을 독립 확인 + 채널 간 거래량 편차가 허용치(기본 25%) 이내
- **⚠ CHECK** — 소스 불일치/누락 → 매매 전 반드시 직접 재확인

> ⚠️ `premkt_chg_%` 는 **미국 장 마감 시간대에는 직전 정규장 종가 기준**으로 표시될
> 수 있습니다(프리마켓 거래가 시작된 시간대에 실행해야 실제 프리마켓 변동이 잡힘).
> 정확한 프리마켓을 보려면 한국시간 17:00~22:30 사이(미국 프리마켓)에 실행하세요.

### verify 설정 (config.json → "verify" 섹션, 선택)
| 키 | 의미 | 기본 |
|---|---|---|
| `top_n_verify` | 검증할 상위 종목 수 | 25 |
| `vol_tolerance_pct` | Polygon↔Yahoo 거래량 허용 편차(%) | 25 |
| `use_stooq` | Stooq 3차 대조 사용 | true |

## GitHub 전략 수집 (collect_strategies.py) — 벤치마킹 1단계
GitHub에서 '주식/알고리즘 트레이딩 전략' 레포를 긁어와, 각 README가 **주장하는**
수익률·CAGR·Sharpe·승률을 한 표로 정리한다. "수익률 20% 넘는 코드 벤치마킹"의
**1단계(후보 수집)**.
```powershell
python collect_strategies.py
```
- **GitHub Search API**로 키워드(config `collect.queries`) × star 정렬 상위 레포 수집.
- 각 README에서 `수익률/return/CAGR/Sharpe/win rate/승률` 숫자를 정규식으로 추출.
- 결과는 `output\strategies_<날짜>.csv` 저장. `claimed_return_%` 내림차순 정렬.

> ⚠️ **`claimed_return_%`·`sharpe`·`win_rate_%` 는 README의 '주장값'일 뿐**입니다.
> 거의 다 비검증 백테스트 수치라 과최적화·미래참조(look-ahead)·생존편향·수수료
> 누락이 섞여 있을 수 있어 **그대로 믿으면 안 됩니다.** 진짜 벤치마킹(2단계)은
> `has_backtest=True` 인 전략의 로직을 가져와 본인 데이터(Polygon/yfinance)로
> `backtest.py` 계열로 **직접 재검증**해야 합니다.

토큰을 넣으면 검색 한도가 크게 올라갑니다(미인증 10회/분 → 인증 30회/분, README
조회 60/시간 → 5000/시간). 없어도 동작은 하지만 느립니다:
```powershell
$env:GITHUB_TOKEN = "ghp_..."   # 또는 config.json 의 "github_token"
```

### collect 설정 (config.json → "collect" 섹션, 선택)
| 키 | 의미 | 기본 |
|---|---|---|
| `queries` | 검색 키워드 목록 | (트레이딩 전략 4종) |
| `per_query` | 쿼리당 상위 레포 수 | 30 |
| `min_stars` | 최소 star | 20 |
| `claim_threshold_pct` | "주장 수익률 N% 이상" 강조 기준 | 20 |
| `search_sleep_seconds` | 검색 호출 간 대기(미인증 보호) | 7 |

## 전략 재검증 (benchmark.py) — 벤치마킹 2단계
1단계가 모은 레포들이 "수익률 20%+"라 **주장**하는 전략 유형을, **임의 코드를
돌리는 대신 투명하게 재구현**해 과거 데이터로 정직하게 백테스트하고 **매수 후
보유(buy & hold) 기준선**과 비교한다.
```powershell
python benchmark.py
```
정직한 회계의 3원칙:
- **look-ahead 차단** — 신호는 t일 종가까지의 정보로만 결정 → t→t+1 수익에 적용
- **거래비용 반영** — 포지션 변경 1회당 `cost_bps`(기본 5bps) 차감
- **buy & hold 비교** — 이걸 못 이기면 그 전략은 (비용·세금 감안 시) 의미 없음

재구현한 전략 유형: `buy_hold`(기준선), `sma_50_200`(골든크로스),
`momentum_200`(시계열 모멘텀), `rsi_meanrev`(RSI 평균회귀), `donchian_20_10`(돌파 추세추종).
종목별로 돌린 뒤 **중앙값**으로 집계(한 종목 운 배제). 결과는
`output\benchmark_<날짜>.csv`(집계)와 `benchmark_detail_<날짜>.csv`(종목×전략)로 저장.

> 예시(SPY/QQQ/AAPL/MSFT/NVDA, 10년, 5bps): buy_hold가 CAGR·Sharpe 모두 1위로,
> 능동전략 어느 것도 buy_hold의 CAGR을 못 이김. 능동전략은 MDD(낙폭)는 줄였지만
> 수익률을 함께 깎아먹는 전형적 트레이드오프를 보였다. → README의 '주장 20%+'는
> 이런 정직한 회계에서 검증되기 전엔 믿을 수 없다는 방증.

> ⚠️ 이 수치도 '이 바스켓·이 기간'의 과거 결과일 뿐 미래를 보장하지 않는다.
> 목적은 주장 수익률을 정직한 회계로 다시 재보는 것이지 매매 신호가 아니다.

### benchmark 설정 (config.json → "benchmark" 섹션, 선택)
| 키 | 의미 | 기본 |
|---|---|---|
| `tickers` | 백테스트 종목 바스켓 | SPY/QQQ/AAPL/MSFT/NVDA |
| `period` | yfinance 기간 문자열 | 10y |
| `cost_bps` | 포지션 변경 1회당 비용(bps) | 5 |
| `rf_annual` | 무위험수익률(연, Sharpe용) | 0 |

## 결과 컬럼
| 컬럼 | 의미 |
|---|---|
| `ratio` | 폭증 배율 (최신일 ÷ 평소 중앙값) |
| `latest_close` | 최신일 종가 |
| `latest_volume` / `baseline_volume` | 최신일 / 평소 거래량 |
| `dollar_volume_M` | 거래대금(백만 $) |
| `intraday_chg_%` | 최신일 시가→종가 변동 |
| `live_price` / `live_chg_%` | (Finnhub) 실시간 시세 |
