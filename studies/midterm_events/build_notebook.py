"""Create an actual executed .ipynb without claiming a Jupyter kernel was used."""
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
import json,os,sys,ast

R=Path(__file__).resolve().parent
cells=[]
def md(text):cells.append({'cell_type':'markdown','metadata':{},'source':text.splitlines(keepends=True)})
def code(text):cells.append({'cell_type':'code','execution_count':None,'metadata':{},'source':text.splitlines(keepends=True),'outputs':[]})

md('''# 중간선거 이후 매수 가설: 분석을 직접 설명하는 노트

목표는 복잡한 모델을 만드는 것이 아니라 선거 효과를 매수 근거로 쓸 수 있는지 확인하는 것이다. 연구 범위는 저장소의 `docs/METHODOLOGY_STATUS.md`에서 확인할 수 있다.

원자료가 없는 첫 실행에는 `python run_research.py --download`가 필요하다. 이 Notebook의 코드 셀은 Python에서 순차 실행해 결과를 저장했다. 이번 환경에는 Jupyter 커널이 없어 커널 실행을 검증했다고 주장하지 않는다. 일반 Jupyter의 Python 환경에서도 같은 셀을 실행하도록 작성했다.
''')
code('''from pathlib import Path
import pandas as pd
import numpy as np
import json, sqlite3, math, hashlib
ROOT = Path.cwd()
assert (ROOT / 'analysis.sql').exists(), '프로젝트 폴더에서 실행하세요.'
manifest = json.loads((ROOT / 'data/source_manifest.json').read_text())
for row in manifest:
    digest = hashlib.sha256((ROOT/'data/raw'/row['file']).read_bytes()).hexdigest()
    assert digest == row['sha256']
print('원자료 해시 일치:', len(manifest), '개')
''')
md('''## SQL이 하는 일

매일의 시장 수익률은 `(Mkt-RF + RF) / 100`이다. 초과수익과 무위험수익을 산술적으로 합친 뒤, 날짜를 따라 복리로 연결한다. 로그 수익을 합해 지수화하면 직접 곱한 것과 같은 결과를 얻는다. `analysis.sql`은 사건 경계, 보유 구간, 구간 고점과 최대 낙폭을 계산한다. 수익률을 단순 합하지 않는다.
''')
code('''connection = sqlite3.connect(ROOT/'data/research.sqlite')
connection.create_function('ln1p', 1, math.log1p)
connection.create_function('exp', 1, math.exp)
midterms = pd.read_sql_query("SELECT year,entry_day,exit_day,total_return,max_drawdown FROM analysis_event_results WHERE is_midterm=1 AND horizon='year_end' ORDER BY year", connection)
print(midterms.to_string(index=False, float_format=lambda x:f'{x:.4f}'))
assert len(midterms)==19
''')
md('''## EDA와 기준 비교

19회 중 몇 번 올랐는지와 평균만 보면 선거 이외의 연말 상승 경향을 놓칠 수 있다. 같은 날짜의 다른 54개 연도와 비교하고 보유 기간도 분리한다. 이 단계는 연관관계 관찰이며 인과효과를 입증하지 않는다. 미국 전체 시장과 S&P 500은 같은 지수가 아니다.
''')
code('''summary = pd.read_csv(ROOT/'results/event_summary.csv')
print(summary[['group','horizon','n','positive_n','mean_return','median_return','worst_max_drawdown']].to_string(index=False, float_format=lambda x:f'{x:.4f}'))
print('직접 계산한 선거-연말 상승 횟수:', int((midterms.total_return>0).sum()))
''')
md('''## 단순 기준 모델을 이겼는가

모델을 더 복잡하게 만들기 전에 과거 모든 해의 11월 평균을 기준으로 놓았다. 중간선거 평균은 관련 정보가 예측에 도움이 되는지 평가하기 위한 최소 모형이다. MAE는 실제 수익률과 예측의 차이를 절댓값으로 평균한 값이며 작을수록 좋다. RMSE는 큰 오차를 더 강하게 반영한다.

각 시험 시점 이전에 끝난 자료만 학습한다. 다만 현재 설계를 과거에 적용한 재현 검증이고, 평가 표본도 4회다. 독립된 미사용 테스트나 향후 예측 성공으로 설명하지 않는다.
''')
code('''predictions=pd.read_csv(ROOT/'results/walk_forward_predictions.csv')
metrics=pd.read_csv(ROOT/'results/walk_forward_metrics.csv')
assert (pd.to_datetime(predictions.training_latest_exit).dt.year < predictions.year).all()
print(predictions.to_string(index=False, float_format=lambda x:f'{x:.5f}'))
print('MAE/RMSE를 %포인트로 표시:')
shown=metrics.copy()
shown[['MAE','RMSE']]*=100
print(shown.to_string(index=False, float_format=lambda x:f'{x:.3f}'))
''')
md('''## 현재 기업 실적은 무엇을 말하는가

매출 성장과 투자 후 남는 현금을 구분한다. 아래 값은 Microsoft 회사 전체의 분기 현금흐름으로, AI 부문의 독립 수익률이 아니다. 현금 PP&E 취득액을 뺀 단순 차이는 리스를 포함하는 전체 투자를 포괄하지 않는다. 한 분기로 수요나 가치평가를 확정하지 않는다.
''')
code('''cash_flow=pd.read_csv(ROOT/'results/msft_cash_flow.csv')
cash_flow['simple_difference']=cash_flow.operating_cash_flow_usd_m-cash_flow.cash_capex_usd_m
assert np.allclose(cash_flow.simple_difference,cash_flow.illustrative_fcf_usd_m)
change=cash_flow.simple_difference.iloc[1]/cash_flow.simple_difference.iloc[0]-1
print(cash_flow.to_string(index=False))
print(f'단순 현금흐름 차액의 전년 동기 변화: {change:.2%}')
''')
md('''## 가격지수의 별도 확인과 비용

FRED의 S&P 500 제공 범위에서 두 선거를 확인했다. 배당 없는 가격지수 결과이며 앞의 배당 포함 미국 전체 시장과 혼합 집계하지 않는다. 거래비용은 편도 10bp라는 제안값을 양쪽에 적용했다. 실제 종목 매매와 세금·환율은 구현하지 않았다.
''')
code('''sp=pd.read_csv(ROOT/'results/sp500_cases.csv')
print(sp.to_string(index=False))
events=pd.read_csv(ROOT/'results/event_windows.csv')
assert (events.net_return_20bp < events.total_return).all()
qa=json.loads((ROOT/'results/quality_checks.json').read_text())
assert all(x['passed'] for x in qa)
print('품질 검사 통과:',len(qa))
connection.close()
''')
md('''## 의사결정과 한계

선거 패턴만으로 연말까지 매수·보유를 정할 예측 우위는 이번 순차 검증에서 확인하지 못했다. 현재 포트폴리오 비중·손실 한도·유동성과 종목별 가치평가가 더 필요하다. 전체 역사 수익은 최신 빈티지로 재구성돼 당시 공개 자료와 같지 않을 수 있다. 기간·모델을 지금 선택한 사후 편향이 남아 있다.

면접 설명 연습: ① 왜 다른 해의 같은 11월을 비교했는가 ② 수익률과 최대 낙폭이 왜 다른가 ③ 평균 모델보다 복잡한 ML을 쓰지 않은 이유는 무엇인가 ④ AI의 매출 성장과 주주 수익의 차이는 무엇인가 ⑤ 어떤 조건에서 가설을 바꿀 것인가.
''')

namespace={'__name__':'__notebook__'};count=0;previous=Path.cwd()
try:
    os.chdir(R)
    for cell in cells:
        if cell['cell_type']!='code':continue
        count+=1;source=''.join(cell['source']);ast.parse(source)
        output=StringIO()
        with redirect_stdout(output):exec(compile(source,f'notebook_cell_{count}','exec'),namespace)
        cell['execution_count']=count
        cell['outputs']=[{'output_type':'stream','name':'stdout','text':output.getvalue().splitlines(keepends=True)}]
finally:os.chdir(previous)
notebook={'cells':cells,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},
    'language_info':{'name':'python','version':sys.version.split()[0]},
    'execution_note':'Code cells executed sequentially using Python exec; no native Jupyter kernel in this environment.'},'nbformat':4,'nbformat_minor':5}
for i,cell in enumerate(notebook['cells']):cell['id']=f'fundeok-{i:02d}'
(R/'research_walkthrough.ipynb').write_text(json.dumps(notebook,ensure_ascii=False,indent=2))
(R/'results/notebook_validation.json').write_text(json.dumps({'format':'nbformat 4.5 JSON','code_cells_executed':count,'errors':0,'native_jupyter_kernel_verified':False},indent=2))
print(json.dumps({'code_cells_executed':count,'errors':0}))
