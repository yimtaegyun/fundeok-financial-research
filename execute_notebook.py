"""Create and execute a portable notebook using sequential CPython, without claiming a Jupyter kernel test."""
import ast
import contextlib
import io
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
def md(text):return {"cell_type":"markdown","metadata":{},"source":text.splitlines(True)}
def code(text):return {"cell_type":"code","metadata":{},"source":text.splitlines(True),"execution_count":None,"outputs":[]}
cells=[
 md("# 2026년 9월 PCE release research\n\n발표값·수정값·최근 물가 속도를 구분하고 실질 소비와 연결한다. 기준일 2026-10-29. 미래 수익률 예측 모형이나 백테스트는 포함하지 않는다.\n\n저장 출력은 각 코드 셀을 순서대로 CPython으로 실제 실행해 생성했다. 이 환경에는 Jupyter 커널이 없어 커널에서의 재실행은 검증하지 않았다. 코드는 매직 명령 없이 일반 Python으로 작성했다."),
 code('''from pathlib import Path
import base64, json, sqlite3, subprocess, sys
import pandas as pd
ROOT = Path.cwd()
assert (ROOT / "run_analysis.py").is_file(), "프로젝트 루트에서 실행하세요."
def show_png(path):
    payload = Path(path).read_bytes()
    try:
        from IPython.display import display, Image
    except ModuleNotFoundError:
        return {"image/png": base64.b64encode(payload).decode()}
    display(Image(data=payload))
print("Research root verified. No account credentials required.")
'''),
 md("## 1. 원자료 해시와 전체 분석 재실행\n\n고정된 자료를 사용한다. 수집 실패나 값 불일치를 가짜 값·이전 자료의 최신 표시로 대체하지 않는다."),
 code('''result = subprocess.run([sys.executable, str(ROOT / "run_analysis.py")], cwd=ROOT, capture_output=True, text=True, check=True)
print(result.stdout)
if result.stderr:
    print(result.stderr)
'''),
 md("## 2. SQL로 최신 결과 추출\n\n물가·실질 지출의 수준 계열에는 변화율을, 저축률에는 퍼센트포인트 차이를 사용한다."),
 code('''with sqlite3.connect(ROOT / "outputs/research.sqlite") as con:
    con.create_function("POWER", 2, lambda x,y: None if x is None or y is None else x**y)
    latest = pd.read_sql_query("SELECT * FROM monthly_changes WHERE date='2026-09-01' ORDER BY series_id", con)
    revisions = pd.read_sql_query("SELECT * FROM revision_comparison", con)
print(latest.to_string(index=False))
print("\\nPublication-vintage comparison:")
print(revisions.to_string(index=False))
'''),
 md("## 3. 최근 3개월 연율 독립 계산\n\n3개월 변화가 1년간 반복된다는 환산이다. 미래 물가 예측과 구분한다."),
 code('''levels = pd.read_csv(ROOT / "outputs/monthly_levels.csv").set_index("date")
jun = levels.loc["2026-06-01", "PCEPILFE"]
sep = levels.loc["2026-09-01", "PCEPILFE"]
annualized = ((sep/jun)**4 - 1) * 100
recorded = json.loads((ROOT/"outputs/findings.json").read_text())["core_3m_annualized_pct"]
assert abs(annualized-recorded) < 1e-10
print(f"June index={jun:.3f}, September index={sep:.3f}, 3-month annualized={annualized:.4f}%")
show_png(ROOT / "figures/02_core_momentum.png")
'''),
 md("## 4. 할인율 민감도와 해석\n\n같은 미래 현금흐름을 가정한 설명용 계산이다. 실제 기업 주가 하락률 추정이 아니다."),
 code('''sensitivity = pd.read_csv(ROOT/"outputs/illustrative_discounting.csv")
print(sensitivity.to_string(index=False))
show_png(ROOT/"figures/05_discount_sensitivity.png")
'''),
 md("## 5. 검증 결과와 분석 한계\n\n최신 수정계열은 당시 이용 가능 자료와 다를 수 있다. 실시간 예측 성과를 주장하지 않는다. 표본·시점이 다른 선거 조사와 PCE 사이의 인과효과도 계산하지 않았다."),
 code('''qa = json.loads((ROOT/"outputs/qa_results.json").read_text())
assert qa["passed"]
print(f"Passed {len(qa['checks'])} data checks.")
print("Actual/paper trades: none. Price forecast/backtest: none. Blog and social publication are tracked separately.")
''')
]

def main():
    namespace={"__name__":"__notebook__"}
    count=0
    for cell in cells:
        if cell["cell_type"]!="code":continue
        count+=1;cell["execution_count"]=count
        source="".join(cell["source"]);tree=ast.parse(source)
        final_expression=None
        if tree.body and isinstance(tree.body[-1],ast.Expr):
            final_expression=ast.Expression(tree.body.pop().value)
        stdout=io.StringIO();stderr=io.StringIO()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            exec(compile(tree,"analysis_notebook.ipynb","exec"),namespace)
            result=eval(compile(final_expression,"analysis_notebook.ipynb","eval"),namespace) if final_expression else None
        for name,stream in [("stdout",stdout),("stderr",stderr)]:
            if stream.getvalue():cell["outputs"].append({"output_type":"stream","name":name,"text":stream.getvalue().splitlines(True)})
        if isinstance(result,dict) and "image/png" in result:
            cell["outputs"].append({"output_type":"display_data","data":result,"metadata":{}})
        elif result is not None:
            cell["outputs"].append({"output_type":"execute_result","execution_count":count,"data":{"text/plain":[repr(result)]},"metadata":{}})
    notebook={"nbformat":4,"nbformat_minor":5,"metadata":{"kernelspec":{"display_name":"Python 3","language":"python","name":"python3"},"language_info":{"name":"python","version":"3.12.14"},"execution_method":"sequential CPython AST; not a Jupyter kernel execution"},"cells":cells}
    for i,cell in enumerate(cells):cell["id"]=f"pce-{i:02d}"
    (ROOT/"analysis_notebook.ipynb").write_text(json.dumps(notebook,ensure_ascii=False,indent=1)+"\n")
    print(f"Executed {count} code cells; saved analysis_notebook.ipynb")

if __name__=="__main__":main()
