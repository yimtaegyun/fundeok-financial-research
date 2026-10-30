"""Executed, descriptive PCE event research; no fitted price forecast or trading backtest."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from PIL import Image

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)
(ROOT / "figures").mkdir(exist_ok=True)
(ROOT / "assets").mkdir(exist_ok=True)
FONT = ROOT / "assets" / "NanumGothic-Regular.ttf"
BOLD = ROOT / "assets" / "NanumGothic-Bold.ttf"
if not FONT.exists():
    raise FileNotFoundError("Bundled Korean fonts are required; see assets/FONT_LICENSE.txt")
font_manager.fontManager.addfont(str(FONT))
font_manager.fontManager.addfont(str(BOLD))
plt.rcParams.update({"font.family": "NanumGothic", "axes.unicode_minus": False,
                     "figure.facecolor": "#f5f2ec", "axes.facecolor": "#f5f2ec",
                     "text.color":"#122b3b", "axes.labelcolor":"#122b3b",
                     "axes.spines.top":False,"axes.spines.right":False,
                     "axes.grid":True,"grid.alpha":0.18,"font.size":12})
BLUE, RED, TEAL, GREY = "#175a83", "#9f3a2c", "#287d78", "#687982"
checks = []
def check(name, condition, detail=""):
    checks.append({"check":name,"passed":bool(condition),"detail":detail})
    if not condition:
        raise AssertionError(name + ": " + str(detail))

def main():
    manifest = json.loads((ROOT/"data/source_manifest.json").read_text())
    for row in manifest:
        payload=(ROOT/row["file"]).read_bytes()
        check("source_sha256:"+row["file"],hashlib.sha256(payload).hexdigest()==row["sha256"])
    monthly=pd.read_csv(ROOT/"data/raw/pce_monthly.csv",parse_dates=["observation_date"])
    daily=pd.read_csv(ROOT/"data/raw/treasury_daily.csv",parse_dates=["observation_date"])
    monthly=monthly.rename(columns={"observation_date":"date"})
    daily=daily.rename(columns={"observation_date":"date"})
    # FRED graph parameters may not restrict combined downloads: always enforce the research window locally.
    monthly=monthly.loc[monthly.date.between("2014-01-01","2026-09-01")].copy()
    daily=daily.loc[daily.date.between("2015-01-01","2026-10-28")].copy()
    expected=pd.date_range("2014-01-01","2026-09-01",freq="MS")
    check("monthly_unique_dates",not monthly.date.duplicated().any())
    check("monthly_complete_calendar",monthly.date.tolist()==expected.tolist(),f"{len(monthly)} months")
    check("monthly_positive_complete_levels",monthly.drop(columns="date").notna().all().all() and (monthly.drop(columns="date")>0).all().all())
    check("daily_unique_dates",not daily.date.duplicated().any())
    check("daily_no_future_dates",daily.date.max()<=pd.Timestamp("2026-10-28"))
    monthly.to_csv(OUT/"monthly_levels.csv",index=False,date_format="%Y-%m-%d")
    daily.to_csv(OUT/"daily_yields.csv",index=False,date_format="%Y-%m-%d")
    ml=monthly.melt(id_vars="date",var_name="series_id",value_name="value")
    dl=daily.melt(id_vars="date",var_name="series_id",value_name="value")
    for frame in (ml,dl): frame["date"]=frame["date"].dt.strftime("%Y-%m-%d")
    facts=pd.DataFrame([
        ["core_pce_mom","2026-08","percent",0.2,"2026-09-30","bea_pce_202608_first.html"],
        ["core_pce_mom","2026-08","percent",0.3,"2026-10-29","bea_pce_202609.html"],
        ["real_pce_mom","2026-08","percent",0.6,"2026-09-30","bea_pce_202608_first.html"],
        ["real_pce_mom","2026-08","percent",0.5,"2026-10-29","bea_pce_202609.html"],
        ["saving_rate","2026-08","percent",4.1,"2026-09-30","bea_pce_202608_first.html"],
        ["saving_rate","2026-08","percent",4.0,"2026-10-29","pce_monthly.csv"],
    ],columns=["metric","period","unit","value","published_at","source_file"])
    facts.to_csv(OUT/"release_vintages.csv",index=False)
    with sqlite3.connect(OUT/"research.sqlite") as con:
        con.create_function("POWER",2,lambda x,y: None if x is None or y is None else x**y)
        ml.to_sql("monthly_observations",con,if_exists="replace",index=False)
        dl.to_sql("daily_observations",con,if_exists="replace",index=False)
        facts.to_sql("release_facts",con,if_exists="replace",index=False)
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_monthly ON monthly_observations(date,series_id)")
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_daily ON daily_observations(date,series_id)")
        con.executescript((ROOT/"analysis.sql").read_text())
        changes=pd.read_sql_query("SELECT * FROM monthly_changes WHERE date >= '2015-01-01' ORDER BY date,series_id",con)
        revisions=pd.read_sql_query("SELECT * FROM revision_comparison",con)
        common=pd.read_sql_query("SELECT * FROM common_yields ORDER BY date",con)
    level_features=changes[changes.series_id.ne("PSAVERT")].drop(columns="mom_change_pp")
    check("sql_level_features_complete_2015_onward",level_features.notna().all().all(),f"{len(level_features)} rows")
    saving_features=changes[changes.series_id.eq("PSAVERT")]
    check("saving_rate_uses_percentage_points",saving_features.mom_change_pp.notna().all() and saving_features.annualized_3m_pct.isna().all())
    for series in ["PCEPI","PCEPILFE","PCEC96","DSPIC96"]:
        src=monthly.set_index("date")[series]
        sql=changes[changes.series_id.eq(series)].sort_values("date")
        for field,lag,power in [("mom_pct",1,1),("yoy_pct",12,1),("annualized_3m_pct",3,4),("annualized_6m_pct",6,2)]:
            calc=((src/src.shift(lag))**power-1).mul(100).loc["2015-01-01":]
            check(f"sql_python_agreement:{series}:{field}",np.allclose(calc,sql[field],atol=1e-10,rtol=0))
    changes.to_csv(OUT/"monthly_features.csv",index=False)
    revisions.to_csv(OUT/"revision_comparison.csv",index=False)
    common.to_csv(OUT/"common_yields.csv",index=False)
    latest=changes[changes.date.eq("2026-09-01")].set_index("series_id")
    for series,field,expected_value in [("PCEPI","mom_pct",0.5),("PCEPI","yoy_pct",3.6),("PCEPILFE","mom_pct",0.3),("PCEPILFE","yoy_pct",3.1),("DSPIC96","mom_pct",-0.3)]:
        value=float(latest.loc[series,field])
        check(f"official_release_rounding:{series}:{field}",round(value,1)==expected_value,f"{value:.8f} -> {expected_value}")
    check("real_pce_positive_below_point_one",0<float(latest.loc["PCEC96","mom_pct"])<0.1)
    check("saving_rate_september_change_pp",abs(float(latest.loc["PSAVERT","mom_change_pp"])+0.2)<1e-10)
    last_common=common.iloc[-1].to_dict()
    # BEI includes inflation risk and liquidity premia; it is not a pure expectations measure.
    check("yield_official_snapshot_controls",last_common["date"]=="2026-10-27" and last_common["nominal_10y"]==4.99 and last_common["real_10y"]==2.64,"FRED DGS10/DFII10 source pages, manually verified 2026-10-29")
    sensitivity=[]
    for year in [5,10,20]:
        pv8=100/(1.08**year);pv9=100/(1.09**year)
        sensitivity.append({"years":year,"future_cash_flow":100,"discount_base":0.08,"discount_stress":0.09,"pv_at_8pct":pv8,"pv_at_9pct":pv9,"change_pct":100*(pv9/pv8-1)})
    sensitivity=pd.DataFrame(sensitivity)
    sensitivity.to_csv(OUT/"illustrative_discounting.csv",index=False)
    findings={
        "reference_period":"2026-09","release_at_kst":"2026-10-29T21:30:00+09:00",
        "data_vintage":"retrieved 2026-10-29, revised historical series; not real-time historical vintage",
        "headline_mom_pct":float(latest.loc["PCEPI","mom_pct"]),"headline_yoy_pct":float(latest.loc["PCEPI","yoy_pct"]),
        "core_mom_pct":float(latest.loc["PCEPILFE","mom_pct"]),"core_yoy_pct":float(latest.loc["PCEPILFE","yoy_pct"]),
        "core_3m_annualized_pct":float(latest.loc["PCEPILFE","annualized_3m_pct"]),
        "core_6m_annualized_pct":float(latest.loc["PCEPILFE","annualized_6m_pct"]),
        "real_pce_mom_pct":float(latest.loc["PCEC96","mom_pct"]),"real_dpi_mom_pct":float(latest.loc["DSPIC96","mom_pct"]),
        "saving_rate_pct":float(latest.loc["PSAVERT","value"]),
        "latest_common_yields":last_common,"discounting_20y_change_pct":float(sensitivity.iloc[-1].change_pct),
        "scope":"Descriptive release analysis, momentum transforms and illustrative discounting. No return prediction model, causal estimate, OOS investment result or backtest.",
        "n_monthly_dates":len(monthly),"n_feature_rows":len(changes),"n_daily_dates":len(daily)
    }
    (OUT/"findings.json").write_text(json.dumps(findings,ensure_ascii=False,indent=2)+"\n")
    plot_figures(changes,monthly,common,sensitivity,findings)
    env={"executed_at_utc":datetime.now(timezone.utc).isoformat(),"python":sys.version,"platform":platform.platform(),"pandas":pd.__version__,"numpy":np.__version__,"matplotlib":matplotlib.__version__,"sqlite":sqlite3.sqlite_version}
    (OUT/"environment.json").write_text(json.dumps(env,indent=2)+"\n")
    (OUT/"qa_results.json").write_text(json.dumps({"passed":all(x['passed'] for x in checks),"checks":checks},ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(findings,ensure_ascii=False,indent=2))
    print(f"QA passed: {len(checks)} checks")

def footer(fig,text):
    fig.text(.07,.025,text,fontsize=9,color=GREY)

def save(fig,name):
    buffer=io.BytesIO()
    fig.savefig(buffer,format="png",dpi=180,bbox_inches="tight",facecolor=fig.get_facecolor())
    payload=buffer.getvalue()
    if len(payload)<1000 or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"Invalid rendered figure: {name}")
    target=ROOT/"figures"/name
    temporary=target.with_suffix(".png.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary,target)
    with Image.open(target) as image:
        image.verify()
    plt.close(fig)

def plot_figures(changes,monthly,common,sensitivity,f):
    frame=changes.copy();frame["date"]=pd.to_datetime(frame.date)
    fig,ax=plt.subplots(figsize=(11,6))
    for series,label,color in [("PCEPI","전체 PCE 전년 대비",RED),("PCEPILFE","근원 PCE 전년 대비",BLUE)]:
        sub=frame[frame.series_id.eq(series)]
        ax.plot(sub.date,sub.yoy_pct,label=label,color=color,lw=2)
    ax.axhline(2,color=GREY,ls="--",lw=1,label="연준의 전체 PCE 장기 목표 2%")
    ax.set(title="PCE 물가, 2%까지 남은 거리",ylabel="전년 동월 대비 (%)",xlabel="관측월")
    ax.legend(loc="upper left",frameon=False)
    footer(fig,"출처: BEA/FRED PCEPI·PCEPILFE. 2015.01–2026.09. 2026.10.29 수집 수정계열. 과거 실시간 수치와 다를 수 있음.")
    fig.subplots_adjust(bottom=.17)
    save(fig,"01_pce_history.png")
    core=frame[frame.series_id.eq("PCEPILFE") & frame.date.ge("2023-01-01")]
    fig,ax=plt.subplots(figsize=(11,6))
    ax.plot(core.date,core.yoy_pct,color=BLUE,lw=2.5,label="전년 동월 대비")
    ax.plot(core.date,core.annualized_3m_pct,color=TEAL,lw=2,label="최근 3개월 변화의 연율 환산")
    ax.plot(core.date,core.annualized_6m_pct,color=GREY,lw=1.5,ls="--",label="최근 6개월 변화의 연율 환산")
    ax.scatter([core.date.iloc[-1]]*2,[f["core_yoy_pct"],f["core_3m_annualized_pct"]],color=[BLUE,TEAL],s=55,zorder=5)
    ax.set(title=f"근원 PCE 3.1% — 최근 3개월을 연율로 바꾸면 {f['core_3m_annualized_pct']:.2f}%",ylabel="상승률 (%)",xlabel="관측월")
    ax.legend(loc="upper left",frameon=False)
    footer(fig,"출처: BEA/FRED PCEPILFE. 3개월 연율 = [(당월 지수 / 3개월 전 지수)^4 - 1] × 100. 미래 1년의 예측값이 아님.")
    fig.subplots_adjust(bottom=.17)
    save(fig,"02_core_momentum.png")
    fig,axs=plt.subplots(1,2,figsize=(11,5.8))
    axs[0].bar(["명목 소비","실질 소비"],[.5,f["real_pce_mom_pct"]],color=[BLUE,TEAL],width=.55)
    axs[0].text(0,.53,"+0.5%",ha="center",fontsize=19,fontweight="bold")
    axs[0].text(1,.08,"0.1% 미만 증가",ha="center",fontsize=13)
    axs[0].set_ylim(0,.7);axs[0].set_ylabel("2026년 9월 전월 대비 (%)");axs[0].set_title("지갑에서 나간 돈과 실제 소비")
    axs[1].plot(monthly.date.tail(12),monthly.PSAVERT.tail(12),color=RED,lw=2,marker="o")
    axs[1].set(title="개인저축률",ylabel="가처분소득 대비 (%)")
    axs[1].tick_params(axis="x",rotation=35)
    axs[1].annotate("9월 3.8%",(monthly.date.iloc[-1],3.8),xytext=(-70,15),textcoords="offset points",color=RED,fontsize=14)
    footer(fig,"출처: BEA 2026.10.29 발표, BEA/FRED PCEC96·PSAVERT. 명목·실질은 별도 계열이며 그래프 차이를 정확한 물가 기여도로 해석하지 않음.")
    fig.subplots_adjust(bottom=.23,wspace=.32)
    save(fig,"03_spending_saving.png")
    recent=common[common.date.ge("2025-01-01")].copy();recent["date"]=pd.to_datetime(recent.date)
    fig,ax=plt.subplots(figsize=(11,6))
    for col,label,color in [("nominal_10y","미국 10년 명목금리",BLUE),("real_10y","미국 10년 실질금리",TEAL),("breakeven_10y","10년 손익분기 인플레이션",RED)]:
        ax.plot(recent.date,recent[col],label=label,color=color,lw=2)
    ax.set(title=f"장기금리는 정책금리만으로 설명되지 않는다 — 공통 관측일 {f['latest_common_yields']['date']}",ylabel="연 수익률 (%)",xlabel="관측일")
    ax.legend(loc="upper left",frameon=False)
    footer(fig,"출처: Board of Governors/FRED DGS10·DFII10. 손익분기율은 두 금리의 차이로 계산. 위험·유동성 요인 포함. 발표 후 반응이 아님.")
    fig.subplots_adjust(bottom=.17)
    save(fig,"04_yield_components.png")
    fig,ax=plt.subplots(figsize=(11,5.8))
    ax.bar(sensitivity.years.astype(str)+"년 뒤",sensitivity.change_pct,color=[TEAL,BLUE,RED],width=.5)
    for x,y in enumerate(sensitivity.change_pct): ax.text(x,y-.7,f"{y:.1f}%",ha="center",va="top",fontweight="bold",fontsize=20)
    ax.set(title="같은 현금 100을 받아도, 할인율 8% → 9%의 영향은 다르다",ylabel="현재가치 변화 (%)",ylim=(-20,1))
    footer(fig,"설명용 단일 미래 현금흐름 계산. 금리 1%p 변동이 모든 기업의 할인율을 1%p 바꾼다는 뜻이 아니며, 실제 주가 하락률 예측이 아님.")
    fig.subplots_adjust(bottom=.17)
    save(fig,"05_discount_sensitivity.png")

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        (OUT/"qa_results.json").write_text(json.dumps({"passed":False,"checks":checks,"error":str(exc)},ensure_ascii=False,indent=2))
        raise
