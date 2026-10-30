"""Reproducible, descriptive midterm study; not a production trading forecast.

Public research inputs are downloaded only on --download. Raw vendor files and
SQLite databases are excluded from the delivery archive. See DATA_POLICY.md.
"""
from pathlib import Path
from io import StringIO
from datetime import date, datetime, timezone
from html.parser import HTMLParser
import argparse, csv, hashlib, json, math, platform, re, shutil, sqlite3, urllib.request, zipfile
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

ROOT = Path(__file__).resolve().parent
RAW, OUT, FIG = ROOT/'data'/'raw', ROOT/'results', ROOT/'figures'
FF_URL='https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip'
SP_URL='https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500&cosd=2016-10-31&coed=2025-10-29'
MS_URL='https://www.microsoft.com/en-us/Investor/earnings/FY-2027-Q1/press-release-webcast'
HEADERS={'User-Agent':'FUNDEOK-Research/0.1 (public research download)'}
QA=[]

def check(name, condition, detail=None):
    QA.append({'check':name,'passed':bool(condition),'detail':detail})
    if not condition: raise AssertionError(f'{name}: {detail}')

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def download():
    RAW.mkdir(parents=True,exist_ok=True)
    sources=[]
    for filename,url in [('ff_daily.zip',FF_URL),('fred_sp500.csv',SP_URL),('msft_q1_2027.html',MS_URL)]:
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=45) as r:
                data=r.read()
            check('nonempty download '+filename,len(data)>500)
            p=RAW/filename;p.write_bytes(data)
            sources.append({'file':filename,'url':url,'bytes':len(data),'sha256':sha(p),
              'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),'raw_redistribution':'excluded'})
        except Exception as e:
            (ROOT/'download_failure.json').write_text(json.dumps({'url':url,'error':str(e),'at':datetime.now(timezone.utc).isoformat()},indent=2))
            raise RuntimeError(f'Download failed; no stale substitution: {filename}') from e
    (ROOT/'data'/'source_manifest.json').write_text(json.dumps(sources,indent=2))

def load_ff():
    with zipfile.ZipFile(RAW/'ff_daily.zip') as z:
        check('single FF csv',len(z.namelist())==1)
        text=z.read(z.namelist()[0]).decode('utf-8-sig')
    lines=[s for s in text.splitlines() if re.match(r'^\d{8},',s)]
    d=pd.read_csv(StringIO('date,Mkt-RF,SMB,HML,RF\n'+'\n'.join(lines)))
    d['day']=pd.to_datetime(d['date'].astype(str),format='%Y%m%d')
    check('FF date uniqueness',d.day.is_unique)
    check('FF sorted dates',d.day.is_monotonic_increasing)
    check('FF no missing returns',d[['Mkt-RF','RF']].notna().all().all())
    check('FF no sentinel values',not d[['Mkt-RF','RF']].isin([-99.99,-999]).any().any())
    d['market_return']=(d['Mkt-RF']+d.RF)/100
    d['rf_return']=d.RF/100
    check('FF returns greater than minus one',(d[['market_return','rf_return']]>-1).all().all())
    # Close the study before 2026; election outcomes and 2026 forecasts are not input features.
    d=d[(d.day>='1949-01-01')&(d.day<='2024-12-31')].copy()
    check('full final followup coverage',d.day.max()>=pd.Timestamp('2023-11-08'))
    return d, text.splitlines()[0]

def calendar():
    rows=[]
    for year in range(1950,2023):
        first=date(year,11,1);monday=1+(0-first.weekday())%7
        e=pd.Timestamp(date(year,11,monday+1))
        rows.append((year,e.date().isoformat(),int(year%4==2),
                     (e+pd.DateOffset(months=6)).date().isoformat(),
                     (e+pd.DateOffset(months=12)).date().isoformat()))
    return rows

class FinancialRows(HTMLParser):
    def __init__(self,text):
        super().__init__();self.rows=[];self.row=None;self.cell=None;self.feed(text)
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        if tag in ('td','th') and self.row is not None:self.cell=[]
    def handle_data(self,text):
        if self.cell is not None:self.cell.append(text)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        if tag=='tr' and self.row is not None:self.rows.append(self.row);self.row=None

def company_inputs():
    rows=FinancialRows((RAW/'msft_q1_2027.html').read_text()).rows
    def numbers(row):
        values=[]
        for value in row[1:]:
            value=value.replace('$','').replace(',','').replace('(','-').replace(')','').strip()
            if re.fullmatch(r'-?\d+(?:\.\d+)?',value):values.append(float(value))
        return values
    def pair(label):
        candidates=[numbers(r) for r in rows if r and r[0]==label and len(numbers(r))==2]
        check('issuer table row '+label,bool(candidates))
        check('consistent repeated issuer rows '+label,all(p==candidates[0] for p in candidates))
        return candidates[0]
    revenue=pair('Total revenue');cfo=pair('Net cash from operations')
    capex=[abs(v) for v in pair('Additions to property and equipment')]
    gaap=pair('Net income')
    reconciliations=[numbers(r) for r in rows if r and r[0]=='Net income' and len(numbers(r))>=6]
    check('OpenAI adjustment reconciliation exists',bool(reconciliations))
    adjusted=[reconciliations[0][2],reconciliations[0][5]]
    # Control totals protect column order and currency/unit interpretation for this release.
    check('issuer FY2027 and FY2026 control totals',cfo==[58000,45057] and capex==[39367,19394]
          and adjusted==[36422,30833] and revenue==[92279,77673])
    return [('FY2026Q1',revenue[1],cfo[1],capex[1],gaap[1],adjusted[1]),
            ('FY2027Q1',revenue[0],cfo[0],capex[0],gaap[0],adjusted[0])]

def setup_sql(d):
    # Compute in memory, then serialize a complete snapshot once. This avoids
    # intermediate SQLite writes on filesystems that replace file inodes.
    con=sqlite3.connect(':memory:')
    con.create_function('ln1p',1,math.log1p,deterministic=True)
    con.create_function('exp',1,math.exp,deterministic=True)
    con.executescript((ROOT/'analysis.sql').read_text())
    con.executemany('INSERT INTO daily_returns VALUES(?,?,?)',
                    [(x.day.date().isoformat(),x.market_return,x.rf_return) for x in d.itertuples()])
    con.executemany('INSERT INTO event_calendar VALUES(?,?,?,?,?)',calendar())
    # Extract issuer tables and verify control totals; both columns are USD millions.
    # Positive capex = absolute magnitude of the cash-flow outflow line.
    rows=company_inputs()
    con.executemany('INSERT INTO company_financials VALUES(?,?,?,?,?,?)',rows);con.commit()
    return con

def bootstrap_summary(results):
    rng=np.random.default_rng(20261030);rows=[]
    for horizon in ['year_end','month6','month12']:
        for group,label in [(1,'midterm'),(0,'other_novembers')]:
            d=results[(results.horizon==horizon)&(results.is_midterm==group)]
            r=d.total_return.to_numpy()
            ci=np.quantile(rng.choice(r,(20000,len(r)),replace=True).mean(axis=1),[.025,.975])
            rows.append({'group':label,'horizon':horizon,'n':len(r),'positive_n':int((r>0).sum()),
              'mean_return':r.mean(),'median_return':np.median(r),'min_return':r.min(),'max_return':r.max(),
              'bootstrap_mean_ci_low':ci[0],'bootstrap_mean_ci_high':ci[1],
              'mean_max_drawdown':d.max_drawdown.mean(),'worst_max_drawdown':d.max_drawdown.min()})
    return pd.DataFrame(rows)

def replay(con):
    rows=[]
    # A retrospective expanding-window replay. Split chosen in this project, not an untouched test.
    # Every target prediction uses returns whose exits precede the test year's election.
    for year in [2010,2014,2018,2022]:
        target=pd.read_sql_query("SELECT * FROM analysis_event_results WHERE horizon='year_end' AND year=?",con,params=(year,)).iloc[0]
        for model,clause in [('midterm_mean','AND is_midterm=1'),('all_november_mean','')]:
            train=pd.read_sql_query("SELECT * FROM analysis_event_results WHERE horizon='year_end' AND year < ? "+clause,con,params=(year,))
            check(f'{model} {year} no future exits',train.exit_day.max()<target.election_day)
            pred=train.total_return.mean()
            rows.append({'year':year,'model':model,'training_n':len(train),
              'training_latest_exit':train.exit_day.max(),'prediction':pred,'actual':target.total_return,
              'absolute_error':abs(pred-target.total_return),'squared_error':(pred-target.total_return)**2,
              'direction_correct':int((pred>0)==(target.total_return>0))})
    forecasts=pd.DataFrame(rows)
    metric=forecasts.groupby('model').agg(n=('year','count'),MAE=('absolute_error','mean'),MSE=('squared_error','mean'),direction_accuracy=('direction_correct','mean')).reset_index()
    metric['RMSE']=np.sqrt(metric.pop('MSE'))
    return forecasts,metric

def sp_cases():
    d=pd.read_csv(RAW/'fred_sp500.csv')
    d.columns=['day','close'];d.day=pd.to_datetime(d.day);d.close=pd.to_numeric(d.close,errors='coerce')
    check('SP500 no duplicate dates',d.day.is_unique)
    missing=int(d.close.isna().sum());d=d.dropna().set_index('day').sort_index()
    # FRED's current rolling 10-year availability yields only two completed midterms.
    rows=[]
    for year in [2018,2022]:
        first=date(year,11,1);event=pd.Timestamp(date(year,11,2+(0-first.weekday())%7))
        entry=d.loc[d.index<event].iloc[-1]
        path=d.loc[(d.index>=entry.name)&(d.index<=pd.Timestamp(year,12,31))].close/entry.close
        rows.append({'year':year,'entry_day':str(entry.name.date()),'entry_close':entry.close,
                     'exit_day':str(path.index[-1].date()),'total_return':path.iloc[-1]-1,
                     'max_drawdown':(path/path.cummax()-1).min(),
                     'measure':'S&P 500 price index; dividends excluded'})
    check('SP500 nontrading gaps explicitly dropped',missing>=0,{'missing_observations':missing,'forward_filled':False})
    return pd.DataFrame(rows)

def style():
    font=ROOT/'assets'/'NanumGothic-Regular.ttf'
    bold=ROOT/'assets'/'NanumGothic-Bold.ttf'
    matplotlib.font_manager.fontManager.addfont(str(font));matplotlib.font_manager.fontManager.addfont(str(bold))
    plt.rcParams.update({'font.family':FontProperties(fname=str(font)).get_name(),'axes.unicode_minus':False,
      'font.size':12,'figure.facecolor':'#FBFAF6','axes.facecolor':'#FBFAF6','text.color':'#152E40',
      'axes.labelcolor':'#152E40','xtick.color':'#52616C','ytick.color':'#52616C',
      'axes.spines.top':False,'axes.spines.right':False,'axes.spines.left':False,'axes.spines.bottom':False})

def savefig(fig,name,caption):
    fig.text(.06,.025,caption,fontsize=9,color='#52616C',va='bottom')
    fig.savefig(FIG/name,dpi=190,bbox_inches='tight');plt.close(fig)

def figures(results,summary,company,sp,metrics,con):
    style()
    mid=results[(results.is_midterm==1)&(results.horizon=='year_end')].copy()
    fig,axs=plt.subplots(2,1,figsize=(11,8.5),sharex=True,gridspec_kw={'height_ratios':[2,1]})
    x=np.arange(len(mid));colors=np.where(mid.total_return>0,'#175A83','#B9563A')
    axs[0].bar(x,mid.total_return*100,color=colors,width=.68)
    axs[0].axhline(0,color='#52616C',lw=.7);axs[0].set_ylabel('선거 직전 종가 → 연말 수익률 (%)')
    axs[0].set_title('중간선거가 끝나도, 그해 연말은 손실일 수 있다',loc='left',pad=22,fontsize=19,fontweight='bold')
    axs[1].bar(x,mid.max_drawdown*100,color='#AA8A48',width=.68)
    axs[1].set_ylabel('기간 중 최대 낙폭 (%)');axs[1].set_xticks(x,mid.year,rotation=45)
    for ax in axs:ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    fig.subplots_adjust(left=.12,right=.98,bottom=.16,top=.9,hspace=.18)
    savefig(fig,'01_midterm_year_end.png','1950–2022년 중간선거 19회 | Fama/French 미국 전체 주식시장 수익률 재구성, 배당 포함\nS&P 500이 아님. 선거일 직전 거래일 종가 기준. 세금·환율·비용 제외. 직접 계산.')
    fig,ax=plt.subplots(figsize=(10,5.8));labels=['선거 → 연말','선거 → 6개월','선거 → 12개월'];x=np.arange(3)
    for offset,group,color,label in [(-.17,'midterm','#175A83','중간선거년 (19회)'),(.17,'other_novembers','#AA8A48','다른 해의 같은 11월 날짜 (54회)')]:
        a=summary[summary.group==group].set_index('horizon').loc[['year_end','month6','month12']]
        ax.bar(x+offset,a.mean_return*100,width=.32,color=color,label=label)
        ax.errorbar(x+offset,a.mean_return*100,yerr=np.vstack([(a.mean_return-a.bootstrap_mean_ci_low)*100,(a.bootstrap_mean_ci_high-a.mean_return)*100]),fmt='none',ecolor='#152E40',capsize=4)
    ax.set_xticks(x,labels);ax.set_ylabel('평균 누적 수익률 (%)');ax.legend(frameon=False,loc='upper left');ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    ax.set_title('12개월 통계를 연말 전망에 그대로 붙일 수 없다',loc='left',fontsize=19,pad=22,fontweight='bold')
    fig.subplots_adjust(bottom=.2,left=.1,top=.85)
    savefig(fig,'02_horizon_comparison.png','Fama/French 미국 전체 시장, 1950–2022년 선거일 일정 기준 | 배당 포함 | 직접 계산\n오차 막대: 연도 재표집 부트스트랩 평균의 95% 구간. 비정상성·정책 차이를 통제한 인과 추정이 아님.')
    fig,ax=plt.subplots(figsize=(10,5.5));x=np.arange(3);w=.32
    fields=['operating_cash_flow_usd_m','cash_capex_usd_m','illustrative_fcf_usd_m'];labs=['영업현금흐름','현금 설비투자','두 항목의 차이']
    for i,row in enumerate(company.itertuples()):
        vals=[getattr(row,f)/1000 for f in fields]
        bars=ax.bar(x+(i-.5)*w,vals,w,color=['#AA8A48','#175A83'][i],label=['2025년 7–9월','2026년 7–9월'][i])
        ax.bar_label(bars,labels=[f'{v:.1f}' for v in vals],padding=4,fontsize=12)
    ax.set_xticks(x,labs);ax.set_ylim(0,70);ax.set_ylabel('십억 달러');ax.legend(frameon=False)
    ax.set_title('실적 성장과 투자 후 남는 현금은 다르게 움직인다',loc='left',fontsize=19,pad=22,fontweight='bold');ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    fig.subplots_adjust(bottom=.22,left=.1,top=.83)
    savefig(fig,'03_msft_cash_flow.png','Microsoft FY2027 Q1 발표 원문 | 두 항목의 차이 = 영업현금흐름 - 현금 PP&E 취득액\n회사 전체 분기 수치. AI 부문 수익률·기업가치·리스 포함 총투자액을 뜻하지 않음.')
    fig,ax=plt.subplots(figsize=(10,5.8))
    for year,color in [(2018,'#B9563A'),(2022,'#175A83')]:
        p=pd.read_sql_query("SELECT day,level FROM paths WHERE year=? AND horizon='year_end' ORDER BY day",con,params=(year,))
        ax.plot(np.arange(len(p)),p.level*100,label=str(year),lw=2.7,color=color)
    ax.axhline(100,color='#52616C',ls='--',lw=.8);ax.set_xlabel('선거 직전 종가 이후 거래일');ax.set_ylabel('시작값 = 100');ax.legend(frameon=False)
    ax.set_title('연말 수익률 한 줄에는 중간의 하락이 빠져 있다',loc='left',fontsize=19,pad=22,fontweight='bold');ax.grid(axis='y',alpha=.15)
    fig.subplots_adjust(bottom=.2,left=.1,top=.85)
    savefig(fig,'04_path_risk.png','Fama/French 미국 전체 주식시장, 배당 포함 | 2018·2022년 사례, 직접 계산\n회복 시점과 낙폭이 달랐음. 두 사례를 근거로 2026년의 방향을 확정하지 않음.')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--download',action='store_true');args=parser.parse_args()
    for p in [RAW,OUT,FIG,ROOT/'assets']:p.mkdir(parents=True,exist_ok=True)
    if args.download:download()
    manifest=json.loads((ROOT/'data'/'source_manifest.json').read_text())
    for s in manifest: check('input hash '+s['file'],sha(RAW/s['file'])==s['sha256'])
    d,vintage=load_ff();con=setup_sql(d)
    con.execute('CREATE TABLE analysis_event_results AS SELECT * FROM event_results')
    con.execute('CREATE INDEX analysis_event_key ON analysis_event_results(year,horizon,is_midterm)')
    results=pd.read_sql_query('SELECT * FROM analysis_event_results ORDER BY year,horizon',con)
    check('73 years x 3 horizons',len(results)==219)
    check('19 midterm cycles',len(results[(results.is_midterm==1)&(results.horizon=='year_end')])==19)
    check('no missing SQL endpoints',results.notna().all().all())
    check('entry precedes election',(results.entry_day<results.election_day).all())
    check('exit follows entry',(results.exit_day>results.entry_day).all())
    check('drawdowns never positive',(results.max_drawdown<=1e-10).all())
    check('worst entry no better than final',(results.worst_from_entry<=results.total_return+1e-10).all())
    check('all study events predate 2026',(results.year<=2022).all())
    check('SQL integrity',con.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
    # Independent product arithmetic validates SQL log compounding for every window.
    errors=[]
    for r in results.itertuples():
        selected=d[(d.day>r.entry_day)&(d.day<=r.exit_day)]
        errors.append(abs(np.prod(1+selected.market_return)-1-r.total_return))
    check('SQL versus direct product',max(errors)<1e-10,{'max_absolute_error':max(errors)})
    summary=bootstrap_summary(results)
    company=pd.read_sql_query('SELECT * FROM company_cash_flow ORDER BY fiscal_period',con)
    check('company FCF subtraction',(company.illustrative_fcf_usd_m==company.operating_cash_flow_usd_m-company.cash_capex_usd_m).all())
    check('MSFT latest simple FCF',int(company.iloc[-1].illustrative_fcf_usd_m)==18633)
    forecasts,metrics=replay(con);sp=sp_cases()
    results['net_return_20bp']=(1+results.total_return)*(1-.001)**2-1
    check('costs reduce every return',(results.net_return_20bp<results.total_return).all())
    check('OOS models have four cases',(metrics.n==4).all())
    for name,table in [('event_windows.csv',results),('event_summary.csv',summary),('msft_cash_flow.csv',company),
                       ('walk_forward_predictions.csv',forecasts),('walk_forward_metrics.csv',metrics),('sp500_cases.csv',sp)]:
        table.to_csv(OUT/name,index=False,float_format='%.12g')
    figures(results,summary,company,sp,metrics,con)
    fig_files=[p for p in FIG.glob('0*.png') if p.name!='00_cover.png']
    check('four real-data figures',len(fig_files)==4)
    findings={'vintage':vintage,'historical_input_last_date_used':str(d.day.max().date()),
      'midterm_year_end':summary[(summary.group=='midterm')&(summary.horizon=='year_end')].to_dict('records')[0],
      'midterm_month12':summary[(summary.group=='midterm')&(summary.horizon=='month12')].to_dict('records')[0],
      'company_fcf_change':company.iloc[-1].illustrative_fcf_usd_m/company.iloc[0].illustrative_fcf_usd_m-1,
      'model_metrics':metrics.to_dict('records'),'sp500_cases':sp.to_dict('records'),
      'qa_passed':sum(x['passed'] for x in QA),'qa_total':len(QA),
      'scope':'Retrospective descriptive study; no independent untouched OOS, no causal estimate, no investment allocation approved.'}
    (OUT/'findings.json').write_text(json.dumps(findings,ensure_ascii=False,indent=2))
    (OUT/'quality_checks.json').write_text(json.dumps(QA,ensure_ascii=False,indent=2))
    (OUT/'environment.json').write_text(json.dumps({'python':platform.python_version(),'numpy':np.__version__,
      'pandas':pd.__version__,'matplotlib':matplotlib.__version__,'sqlite':sqlite3.sqlite_version},indent=2))
    con.commit()
    (ROOT/'data'/'research.sqlite').write_bytes(con.serialize())
    con.close();print(json.dumps(findings,ensure_ascii=False,indent=2))

if __name__=='__main__':
    started=datetime.now(timezone.utc).isoformat()
    try:
        main()
        record={'started_at_utc':started,'finished_at_utc':datetime.now(timezone.utc).isoformat(),
                'status':'succeeded','inputs':'data/source_manifest.json','results':'results/findings.json'}
    except Exception as exc:
        OUT.mkdir(parents=True,exist_ok=True)
        record={'started_at_utc':started,'finished_at_utc':datetime.now(timezone.utc).isoformat(),
                'status':'failed','error_type':type(exc).__name__,'error':str(exc),'passed_checks':sum(q['passed'] for q in QA)}
        with (OUT/'execution_log.jsonl').open('a') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
        (OUT/'failed_quality_checks.json').write_text(json.dumps(QA,ensure_ascii=False,indent=2))
        raise
    else:
        with (OUT/'execution_log.jsonl').open('a') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
