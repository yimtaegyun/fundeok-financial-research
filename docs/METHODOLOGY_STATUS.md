# 7개 연구 영역과 10단계 적용 현황

7개 영역은 연구 대상이고 10단계는 수행 방법이다. 현재 공개한 기술 산출물과 아직 수행하지 않은 운용 업무를 아래처럼 연결한다. 이 체계는 모든 기관에 동일하게 적용되는 공식 표준을 뜻하지 않는다.

| 연구 영역 | 공개한 근거 | 남은 범위 |
| --- | --- | --- |
| Investment Framework | 기준일·문제 정의·검증 원칙 | 실제 운용 목표·한도 확정 |
| Global Macro Research | 루트 PCE 연구, `studies/macro_foundations/` | 당시 공개 빈티지 확장 |
| Sector & Factor Research | 금리·할인율 설명, 사건 연구의 시장·무위험수익 구분 | 산업 비교·팩터 노출 회귀 |
| Fundamental Equity Research | 사건 연구의 Microsoft 현금흐름 발췌 계산 | 기업별 전체 재무·가치평가 |
| Event-Driven Research | PCE 발표·수정치 비교, `studies/midterm_events/` | 발표 후 가격 반응과 식별 |
| Portfolio Construction | 데이터·연구 한계 문서화 | 실제·가상 비중과 위험 한도 |
| Performance Attribution | 기준 모델 오차·검증 기록 | 운용 성과 기여도 분석 |

| 단계 | 현재 산출물과 상태 |
| --- | --- |
| 1. Investment Mandate | 연구 질문·기준일 명시. 실제 운용 한도 미확정 |
| 2. Idea Generation | 물가·실질 소비·금리·사건 기간 비교 질문 |
| 3. Data Engineering | 원자료 해시·달력·중복·결측 검사, SQLite |
| 4. Research & Analysis | 변화율·빈티지·공통 관측일·사건 구간 분석 |
| 5. Modeling & Forecasting | 할인율 설명 계산, 기존 AR(1)·기준 평균 비교. 투자 예측력 미입증 |
| 6. Investment Thesis | 관측 결과와 해석 한계. 내부 사용자 가설·미합의 투자 의견은 공개 범위에서 제외 |
| 7. Research Validation | PCE 39개 검사 현재 재실행, 보호 검사 4개 현재 재실행; 사건 연구 전체 검증은 보존 기록 |
| 8. Portfolio & Risk | 실제 편입·비중·손실 한도 미실행 |
| 9. Execution | 증권 주문·가상 체결·거래비용 분석 미실행 |
| 10. Monitoring & Attribution | 재실행 도구·기준일 보존. 운용 성과와 완전 자동 모니터링 없음 |

구체적인 사적 투자 조건을 새로 정하지 않아도 기술 자료는 검토할 수 있다. 7개 연구 또는 10단계 전체를 완료한 포트폴리오라고 표시하지 않는다.
