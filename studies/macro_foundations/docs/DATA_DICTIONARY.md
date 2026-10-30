# 데이터 사전

모든 금리 원수치는 연율 퍼센트다. 두 금리의 차이는 퍼센트포인트(pp), 일별 변화에 100을 곱한 값은 bp다. 수익률 수준을 채권의 투자수익률로 해석하지 않는다.

| 변수 | 정의 | 원자료 |
|---|---|---|
| date | 원자료의 관측일; 다운로드 시각과 다름 | 각 소스 Date |
| ust_2y | 미국 국채 2년 명목 par 수익률 | Treasury, 2 Yr |
| ust_10y | 미국 국채 10년 명목 par 수익률 | Treasury, 10 Yr |
| ust_3m | 미국 국채 3개월 par 수익률 | Treasury, 3 Mo |
| ust_real_10y | 미국 국채 10년 실질 par 수익률 | Treasury real curve, 10 YR |
| kw_zero_yield_10y | KW 모형 적합 10년 zero 수익률 | Fed, THREEFY1000.B |
| kw_term_premium_10y | KW 모형 추정 10년 zero 기간 프리미엄 | Fed, THREEFYTP1000.B |
| nominal_real_par_spread_10y | ust_10y − ust_real_10y; 인플레이션 보상 근사 지표 | 직접 계산 |
| slope_10y_2y | ust_10y − ust_2y | 직접 계산 |
| kw_expected_avg_short_10y | kw_zero_yield_10y − kw_term_premium_10y | 같은 KW 모형 안에서 계산 |

연간 파일의 날짜를 검증하고 합친 뒤 날짜가 중복되면 중단한다. 소스별 휴일·미발표 값은 결측으로 유지한다. forward fill·backward fill은 하지 않는다. 요청 기준일 이후 관측은 제외한다. 월별 CPI 접속 점검 결과는 별도 원본으로 저장하고 발표 시각 검증 없이 일별 패널에 합치지 않는다.

일별 데이터의 원본 SHA-256·접속 URL·실행 시각·결측 수·소스별 마지막 관측일을 source_manifest.json과 data_quality.json에 기록한다. 수집 요청이 HTTP 200이어도 HTML이나 점검 안내라면 데이터로 인정하지 않는다.
