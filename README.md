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
| `candle_signal` | 캔들 신호 종합 판정 (강한매수/매수관심/중립/매도주의/강한매도) |
| `candle_pos` | 하이로우 기준선상 위치 (전고점돌파/전저점부근/완만한상승/수횡파/잔구간 등) |
| `close_pos` | 마감강도 (1.0=고점마감) |
| `live_price` / `live_chg_%` | (Finnhub) 실시간 시세 |

## 캔들 신호 필터 (candle_signals.py)
'캔들혁명 — **파동연상**(The Imaging of Waves)' / '캔들개론' 교재의 캔들·캔들군·
파동·**하이로우 기준선** 개념을 **일봉 OHLCV로 계산 가능한 범위**로 옮긴 신호기다.
교재의 제1 명제 — *"단순 형태보다 (형성) 위치가 훨씬 중요하다"* — 를 그대로 따라,
① 최신봉 캔들 **형태**(장대양봉·양봉스프링·망치형·위꼬리·팽이도지 등)와
② 직전 봉들 대비 **위치**(전 고점 돌파·전 저점 부근·완만한 상승·수횡파·잔구간)를
함께 본 뒤 종합 판정한다.

스캐너가 거래량 폭증 후보를 고를 때 **그 폭증봉이 의미 있는 위치의 정상적(매수편향)
캔들인지**를 가려준다(예: 고점권 위꼬리 블로우오프 음봉 vs 전고점 돌파 장대양봉).

- 기본은 **주석만** 한다(컬럼 `candle_signal`/`candle_pos`/`close_pos` 추가, 후보 제외 없음).
- `config.json["scan"]["candle_filter"]["require_verdicts"]` 에 판정 목록을 넣으면
  그 판정만 후보로 남긴다. 예: `["강한매수","매수관심"]`.
- `lookback` 으로 위치 판단에 쓸 직전 봉 수를 조정(기본 7).

> ⚠️ 교재 본령은 1시간/완성봉 기준의 재량적 차트 해석이라, 일봉 한 봉으로의 근사는
> 수횡파·미니기연파 등 다수 파동의 미세 유형을 단순화한다. **필터/참고용**일 뿐
> 매매 신호가 아니다.

## 프리마켓 전용 파이프라인 (본장과 분리)
프리마켓(장 시작 전) 갭상승+거래량 모멘텀만 따로 보는 별도 파이프라인이다.
출력·장부·워크플로가 본장과 완전히 분리돼 있다.
```powershell
python premarket_scanner.py            # 프리마켓 추천 픽 → output/premarket_<날짜>.csv
python premarket_verify.py             # 장 시작 전 창(ET 05:30–09:00) 매매 채점 → output/premarket_ledger.csv
python premarket_performance.py        # ↑ 장부로 최근 60일 추천 성과 집계 (성과 관리 항목)
```

**캔들 신호 부합 종목만 추천**: `premarket_scanner.py` 는 본장 산출물(`surge_*.csv`)의
`candle_signal` 컬럼을 읽어, `config.json["premarket"]["require_verdicts"]`(기본
`["강한매수","매수관심"]`)에 부합하는 종목만 프리마켓 추천 픽으로 발굴한다. (컬럼이 없는
구버전 CSV면 필터를 자동 생략.) 즉 **매일 = 본장 폭증 + 캔들/파동 신호 부합 → 추천,
다음날 = `premarket_verify.py` 로 검증**의 흐름이다.

### 프리마켓 최적 타점 타이밍 통계 검증 (premarket_timing_study.py)
미장 프리마켓 **최근 120거래일**을 대상으로, **어느 시간대(타점)에 진입했을 때 가장
실질적 이익이 났는지**를 통계로 검증한다. 캔들 신호와 결합해 ET 30분 버킷별 기대수익을
집계한다.
```powershell
python premarket_timing_study.py            # 최근 120거래일 (Polygon 키 필요)
python premarket_timing_study.py 60         # 창을 60거래일로
python premarket_timing_study.py selftest   # 합성 분봉으로 로직 자체검증(키 불필요)
```
- **청산**: **순수 09:30 개장가(ET) 청산**. 버킷 시각 진입 → 개장가 청산의 순수
  수익률만 측정해 타점 비교를 깨끗하게 한다(경로의존 TP/SL 미적용).
  `timing_study.exit_mode="tp_sl"` 로 바꾸면 TP/SL 우선 모드도 가능.
- **타점**: ET 30분 버킷(05:30/…/09:00) × **진입 직전 마감된 30분봉 캔들 신호** 결합.
  분봉 기준은 `signal_bar_minutes`(기본 30; 10/20도 가능 — 1분봉을 리샘플).
- **유니버스**: ① 폭증 후보 전체 vs ② 캔들신호+갭 부합 추천 픽 — **둘 다 비교**.

> **✅ 확정 타점 (20거래일 실데이터, 2026-05-19~06-16)**: 폭증 후보 전체(n=113/버킷)
> 기준 **ET 06:30(KST 19:30) 진입 → 09:30 개장가 청산**이 +3.0%/거래로 최적.
> 이른 프리마켓(06:00~06:30) 진입이 우위, 개장 직전(09:00)이 최약. 이 값은
> `config.json["premarket"]["entry_time_et"]`(기본 "06:30")로 반영돼 있다.
- **데이터**: Polygon 분봉 애그리거트(확장시간 포함, 2년 history, 무료 5req/분).
  `output/cache/` 에 grouped daily·분봉을 캐싱해 재실행 시 무호출. 산출은
  `output/timing_study_detail.csv`(후보×버킷)·`output/timing_study_buckets.csv`(집계).

> ⚠️ **데이터 제약**: yfinance 1분봉은 ~7일만 제공하므로 120일 분봉은 불가 → Polygon
> 분봉을 쓴다. 무료 5req/분 제한으로 첫 실행은 오래 걸린다(캐싱 후 빨라짐). 과거 통계는
> 미래를 보장하지 않으며, 프리마켓은 유동성이 얇아 실제 체결가가 시뮬과 다를 수 있다.

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
