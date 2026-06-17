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

## 결과 컬럼
| 컬럼 | 의미 |
|---|---|
| `ratio` | 폭증 배율 (최신일 ÷ 평소 중앙값) |
| `latest_close` | 최신일 종가 |
| `latest_volume` / `baseline_volume` | 최신일 / 평소 거래량 |
| `dollar_volume_M` | 거래대금(백만 $) |
| `intraday_chg_%` | 최신일 시가→종가 변동 |
| `live_price` / `live_chg_%` | (Finnhub) 실시간 시세 |

## 프리마켓 전용 파이프라인 (본장과 분리)
프리마켓(장 시작 전) 갭상승+거래량 모멘텀만 따로 보는 별도 파이프라인이다.
출력·장부·워크플로가 본장과 완전히 분리돼 있다.
```powershell
python premarket_scanner.py            # 프리마켓 추천 픽 → output/premarket_<날짜>.csv
python premarket_verify.py             # 장 시작 전 창(ET 05:30–09:00) 매매 채점 → output/premarket_ledger.csv
python premarket_performance.py        # ↑ 장부로 최근 60일 추천 성과 집계 (성과 관리 항목)
```

### 프리마켓 추천 종목 성과 관리 (premarket_performance.py)
`premarket_verify.py` 가 누적해 둔 장부(`output/premarket_ledger.csv`)를 토대로,
**최근 60일(기본) 동안 프리마켓 추천 종목이 실제로 어땠는지**를 한곳에서 관리·집계한다.
과거 추천 회고용 성과 항목이며 매매 신호가 아니다.
```powershell
python premarket_performance.py        # 최근 60일 성과
python premarket_performance.py 90     # 창을 90일로 조정
```
집계 항목:
- **전체** — 거래수·승률·순익평균(기대값)·누적복리·MDD·손익비(Profit Factor)·익절/손절 도달률
- **추천 종목별** — 종목별 추천(거래)횟수·승률·순익합/평균·최고/최저 → 어떤 추천이 통했나
- **일자별** — 날짜별 종목수·순익평균·승률 (최근 우선)

종목별 성과표는 `output/premarket_performance_<날짜>.csv` 로 저장된다.
창 길이는 `config.json["premarket"]["performance_lookback_days"]`(기본 60) 또는 실행 인자로 조정.
