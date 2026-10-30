"""Append a new macro-data run without changing the original readiness run."""
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
import argparse
import hashlib
import json
import shutil
import sys

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from pipeline import verify_inputs, normalized, decode_csv, json_write, sha256

SERIES = {
    'CUUR0000SA0': 'cpi_headline_nsa',
    'CUUR0000SA0L1E': 'cpi_core_nsa',
    'CUSR0000SA0': 'cpi_headline_sa',
    'CUSR0000SA0L1E': 'cpi_core_sa',
    'LNS14000000': 'unemployment_rate',
    'CES0000000001': 'nonfarm_payroll_thousands',
}


def plot_macro(monthly, output):
    """Use one datetime axis convention for lines and bars; retain real gaps."""
    recent = monthly.loc['2023-01-01':]
    with plt.rc_context({'font.family': 'DejaVu Sans', 'axes.spines.top': False, 'axes.spines.right': False}):
        fig, ax = plt.subplots(3, 1, figsize=(10.5, 9), sharex=True)
        ax[0].plot(recent.index, recent.cpi_headline_yoy_pct, label='Headline CPI (NSA YoY)', linewidth=1.7)
        ax[0].plot(recent.index, recent.cpi_core_yoy_pct, label='Core CPI (NSA YoY)', linewidth=1.7)
        ax[0].legend(loc='upper right')
        ax[1].plot(recent.index, recent.unemployment_rate, label='Unemployment rate', color='#3c846f', linewidth=1.7)
        ax[1].legend(loc='upper right')
        ax[2].bar(recent.index, recent.payroll_change_thousands, width=20, color='#4e7aa2')
        ax[2].axhline(0, color='black', linewidth=.5)
        for a in ax:
            a.grid(alpha=.18)
        ax[0].set_ylabel('Percent YoY')
        ax[1].set_ylabel('Percent')
        ax[2].set_ylabel('Payroll change, thousands')
        ax[2].set_xlabel('Observation month (not release date)')
        ax[2].xaxis.set_major_locator(mdates.MonthLocator(interval=6))
        ax[2].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        fig.suptitle('US inflation and employment | latest downloaded vintage', x=.09, ha='left', fontsize=14)
        fig.text(.09,.02,'Source: U.S. Bureau of Labor Statistics, public API. Latest vintages; not a real-time historical backtest.\nMonthly data are not merged into daily trading signals without release-time validation.',fontsize=8,color='#555555')
        fig.tight_layout(rect=(.01,.075,.99,.95))
        fig.savefig(output, dpi=160)
        plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reuse', type=Path, help='Reuse already downloaded BLS snapshots; keep their original access times')
    args = parser.parse_args()
    old = ROOT / 'artifacts' / 'runs' / (ROOT / 'artifacts' / 'LATEST_RUN.txt').read_text().strip()
    verify_inputs(old)
    run = ROOT / 'artifacts' / 'research_updates' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for d in ['raw', 'processed', 'outputs']:
        (run / d).mkdir(parents=True, exist_ok=True)
    (ROOT / 'artifacts' / 'LATEST_RESEARCH_UPDATE.txt').write_text(run.name + '\n')
    manifest, parts = [], []
    for start, end in [(2015, 2024), (2025, 2026)]:
        url = 'https://api.bls.gov/publicAPI/v1/timeseries/data/'
        payload = {'seriesid': list(SERIES), 'startyear': str(start), 'endyear': str(end)}
        entry = {'source': 'BLS v1', 'url': url, 'request': payload, 'retrieved_at_utc': datetime.now(timezone.utc).isoformat()}
        try:
            if args.reuse:
                data = (args.reuse / 'raw' / f'bls_{start}_{end}.json').read_bytes()
                prior = json.loads((args.reuse / 'source_manifest.json').read_text())
                original = next(x for x in prior if x['request']['startyear'] == str(start))
                entry.update(retrieved_at_utc=original['retrieved_at_utc'], processed_at_utc=datetime.now(timezone.utc).isoformat(), reused_from=str(args.reuse.relative_to(ROOT)), http_status=original['http_status'])
            else:
                request = Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'User-Agent': 'FinancialResearchReadiness/0.2'})
                with urlopen(request, timeout=25) as response:
                    data = response.read(5_000_001)
                    entry['http_status'] = response.status
            body = json.loads(data)
            path = run / 'raw' / f'bls_{start}_{end}.json'
            path.write_bytes(data)
            if body.get('status') != 'REQUEST_SUCCEEDED':
                raise ValueError(str(body.get('message', body.get('status'))))
            returned = body.get('Results', {}).get('series', [])
            if set(s['seriesID'] for s in returned) != set(SERIES):
                raise ValueError('Missing requested BLS series')
            rows = []
            for series in returned:
                for obs in series['data']:
                    if not obs['period'].startswith('M') or not 1 <= int(obs['period'][1:]) <= 12:
                        continue
                    # BLS uses '-' for an unavailable observation. Preserve it as missing;
                    # unknown nonnumeric strings still stop processing.
                    value = None if obs['value'] == '-' else float(obs['value'])
                    rows.append({'month': f"{obs['year']}-{obs['period'][1:]}", 'series': SERIES[series['seriesID']], 'value': value, 'source_missing_marker': obs['value'] if value is None else '', 'footnotes': json.dumps(obs.get('footnotes', []))})
            parts.append(pd.DataFrame(rows))
            entry.update(status='downloaded_validated', file=str(path.relative_to(run)), sha256=sha256(path), observations=len(rows), message=body.get('message'))
        except Exception as exc:
            entry.update(status='failed', error_type=type(exc).__name__, error=str(exc))
        manifest.append(entry)
        json_write(run / 'source_manifest.json', manifest)
        print(json.dumps(entry, ensure_ascii=False), flush=True)
    if len(parts) != 2:
        json_write(run / 'status.json', {'status': 'failed_bls_extension', 'base_run_preserved': old.name})
        raise SystemExit(1)
    long = pd.concat(parts, ignore_index=True)
    if long.duplicated(['month', 'series']).any():
        raise ValueError('Duplicate monthly observation')
    long.to_csv(run / 'processed' / 'monthly_long.csv', index=False)
    monthly = long.pivot(index='month', columns='series', values='value').sort_index()
    monthly = monthly.dropna(how='all')
    monthly.index = pd.to_datetime(monthly.index + '-01')
    monthly = monthly.loc[:'2026-10-22']
    for kind in ['headline', 'core']:
        monthly[f'cpi_{kind}_yoy_pct'] = monthly[f'cpi_{kind}_nsa'].pct_change(12, fill_method=None).mul(100)
        monthly[f'cpi_{kind}_mom_sa_pct'] = monthly[f'cpi_{kind}_sa'].pct_change(fill_method=None).mul(100)
    monthly['payroll_change_thousands'] = monthly['nonfarm_payroll_thousands'].diff()
    monthly.to_csv(run / 'processed' / 'monthly_macro.csv', index_label='month')
    nominal = pd.concat([normalized(decode_csv(p.read_bytes()), {'2 yr': 'ust_2y', '5 yr': 'ust_5y', '10 yr': 'ust_10y', '30 yr': 'ust_30y'}, '%m/%d/%Y') for p in sorted((old / 'raw').glob('treasury_nominal_*.csv'))]).sort_index()
    nominal = nominal.loc['2015-01-01':'2026-10-22']
    nominal['slope_30y_2y'] = nominal.ust_30y - nominal.ust_2y
    nominal.to_csv(run / 'processed' / 'expanded_yield_curve.csv', index_label='date')
    latest = []
    for col in monthly:
        s = monthly[col].dropna()
        if not s.empty:
            latest.append({'series': col, 'observation_month': s.index[-1].strftime('%Y-%m'), 'value': float(s.iloc[-1])})
    pd.DataFrame(latest).to_csv(run / 'outputs' / 'latest_macro.csv', index=False)
    plot_macro(monthly, run/'outputs'/'inflation_and_employment.png')
    json_write(run/'status.json', {'status':'passed_macro_extension', 'base_run_preserved':old.name, 'monthly_rows':len(monthly), 'series_last_month':{c:monthly[c].last_valid_index().strftime('%Y-%m') if monthly[c].notna().any() else None for c in monthly}, 'yield_curve_rows':len(nominal), 'daily_signal_merge':False,'vintage':'latest revised snapshot, release timing not reconstructed','publication':False})
    print((run/'outputs'/'latest_macro.csv').read_text(),flush=True)


if __name__ == '__main__':
    main()
