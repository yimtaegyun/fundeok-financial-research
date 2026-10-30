# 중간선거 사건 연구 — 2026-10-30 보존본

기존 사건 연구의 Python·SQL·Notebook, 집계 결과와 자체 차트다. 시장 전체 수익률과 S&P 500 가격지수, 연말과 6·12개월 보유 구간을 구분한다. 모형 평가는 2010·2014·2018·2022년 네 번의 과거 순차 검증이며, 별도로 보존한 미사용 테스트나 실제 운용 성과가 아니다.

원자료는 제공처의 권리 때문에 공개 사본에 넣지 않았다. 현재 복원 실행에서 원자료 기반 품질 검사 45개나 전체 연구를 새로 통과했다고 주장하지 않는다. Notebook의 출력은 원래 연구 시점의 실행 결과이며 메타데이터에 이를 표시했다. 내부 토론·블로그 검토 원고는 포함하지 않았다.

공식 제공처의 이용 조건을 확인한 뒤 이 폴더에서 별도 환경에 의존성을 설치하고 실행한다.

```bash
python -m pip install -r requirements.txt
python run_research.py --download
python verify_reproduction.py
```

`--download`는 공식 French Data Library·FRED·Microsoft 발표에 접근한다. 수집된 새 자료는 원래 `data/source_manifest.json`의 해시와 다를 수 있다. 데이터 기준·권리·지수 차이는 `DATA_POLICY.md`를 따른다. 2026년 선거 결과 예측, 현재 매수 신호, 사용자 투자 비중을 제시한 자료가 아니다.
