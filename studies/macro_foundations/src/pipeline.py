"""A real-data readiness pilot. No external publishing or trading is implemented."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import time
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 20_000_000


def json_write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode_csv(data: bytes):
    text = data.decode("utf-8-sig", errors="strict")
    start = text.lstrip().lower()
    if start.startswith("<") or "<html" in start[:1000]:
        raise ValueError("HTML_RESPONSE_NOT_DATA: HTTP 200 does not establish a successful data download")
    lines = text.splitlines()
    header = next((i for i, line in enumerate(lines) if line.startswith("Date,") or line.startswith("date,")), None)
    if header is None:
        raise ValueError("MISSING_DATE_HEADER")
    frame = pd.read_csv(io.StringIO(text), skiprows=header, na_values=["ND", "N/A", "."])
    if len(frame) == 0:
        raise ValueError("EMPTY_DATA")
    return frame


def treasury_url(year: int, real: bool):
    series = "daily_treasury_real_yield_curve" if real else "daily_treasury_yield_curve"
    return (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        f"daily-treasury-rates.csv/{year}/all?type={series}&field_tdr_date_value={year}&page&_format=csv"
    )


def fetch_one(task, raw_dir):
    name, url, kind = task
    entry = {"source": name, "url": url, "kind": kind, "retrieved_at_utc": datetime.now(timezone.utc).isoformat()}
    started = time.monotonic()
    try:
        request = Request(url, headers={"User-Agent": "FinancialResearchReadiness/0.1 (public statistical research)"})
        with urlopen(request, timeout=30) as response:
            content = response.read(MAX_BYTES + 1)
            entry.update(http_status=response.status, content_type=response.headers.get("Content-Type"), final_url=response.url)
        if len(content) > MAX_BYTES:
            raise ValueError("RESPONSE_TOO_LARGE")
        if kind == "csv":
            frame = decode_csv(content)
            entry["raw_rows"] = len(frame)
            path = raw_dir / f"{name}.csv"
        elif kind == "json":
            payload = json.loads(content)
            if payload.get("status") != "REQUEST_SUCCEEDED":
                raise ValueError("BLS_REQUEST_NOT_SUCCEEDED")
            path = raw_dir / f"{name}.json"
        elif kind == "event_html":
            text = content.decode("utf-8-sig", errors="strict")
            if "September 16, 2026" not in text or "raise the target range" not in text:
                raise ValueError("FOMC_EVENT_TEXT_NOT_CONFIRMED")
            # Store a digest and source reference, not the whole webpage.
            entry.update(status="verified_document", sha256=hashlib.sha256(content).hexdigest())
            return entry
        else:
            raise ValueError("UNKNOWN_TASK_TYPE")
        path.write_bytes(content)
        entry.update(status="downloaded_validated", file=str(path.relative_to(raw_dir.parent)), bytes=len(content), sha256=sha256(path))
    except Exception as exc:
        entry.update(status="failed", error_type=type(exc).__name__, error=str(exc)[:600])
    finally:
        entry["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return entry


def normalized(frame: pd.DataFrame, mappings: dict, date_format: str):
    available = {str(c).strip().lower(): c for c in frame.columns}
    expected = ["date", *mappings]
    absent = [c for c in expected if c not in available]
    if absent:
        raise ValueError(f"MISSING_REQUIRED_COLUMNS: {absent}")
    out = pd.DataFrame({"date": pd.to_datetime(frame[available["date"]], format=date_format, errors="raise")})
    for source_col, output_col in mappings.items():
        source = frame[available[source_col]]
        converted = pd.to_numeric(source, errors="coerce")
        if (source.notna() & converted.isna()).any():
            raise ValueError(f"INVALID_NUMERIC_VALUE: {source_col}")
        out[output_col] = converted
    if out["date"].duplicated().any():
        raise ValueError("DUPLICATE_OBSERVATION_DATES")
    return out.set_index("date").sort_index()


def bounded(frame, start, as_of):
    selected = frame.loc[(frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(as_of))].copy()
    if selected.empty:
        raise ValueError("NO_OBSERVATIONS_IN_REQUESTED_PERIOD")
    return selected


def build_dataset(run_dir: Path, config):
    raw = run_dir / "raw"
    nominal_files = sorted(raw.glob("treasury_nominal_*.csv"))
    real_files = sorted(raw.glob("treasury_real_*.csv"))
    if not nominal_files or not real_files:
        raise ValueError("TREASURY_SNAPSHOTS_MISSING")
    nominal = pd.concat([
        normalized(decode_csv(p.read_bytes()), {"2 yr": "ust_2y", "10 yr": "ust_10y", "3 mo": "ust_3m"}, "%m/%d/%Y")
        for p in nominal_files
    ]).sort_index()
    real = pd.concat([
        normalized(decode_csv(p.read_bytes()), {"10 yr": "ust_real_10y"}, "%m/%d/%Y")
        for p in real_files
    ]).sort_index()
    if nominal.index.duplicated().any() or real.index.duplicated().any():
        raise ValueError("DUPLICATE_DATES_ACROSS_ANNUAL_FILES")
    kw = normalized(decode_csv((raw / "fed_kim_wright.csv").read_bytes()), {
        "threefy1000.b": "kw_zero_yield_10y", "threefytp1000.b": "kw_term_premium_10y"
    }, "%Y-%m-%d")
    panel = nominal.join(real, how="outer").join(kw, how="outer").sort_index()
    pilot = config["pilot"]
    future_excluded = int((panel.index > pd.Timestamp(pilot["as_of_date"])).sum())
    panel = bounded(panel, pilot["start_date"], pilot["as_of_date"])
    panel["nominal_real_par_spread_10y"] = panel["ust_10y"] - panel["ust_real_10y"]
    panel["slope_10y_2y"] = panel["ust_10y"] - panel["ust_2y"]
    panel["kw_expected_avg_short_10y"] = panel["kw_zero_yield_10y"] - panel["kw_term_premium_10y"]
    # Keep weekends and source-specific holidays missing. Never forward- or backward-fill.
    numeric = panel.to_numpy(dtype=float)
    if np.isinf(numeric).any():
        raise ValueError("INFINITE_VALUES")
    years_required = set(range(int(pilot["start_date"][:4]), int(pilot["as_of_date"][:4]) + 1))
    years_found = set(nominal.index.year)
    if not years_required.issubset(years_found):
        raise ValueError(f"MISSING_HISTORY_YEARS: {sorted(years_required - years_found)}")
    panel.to_csv(run_dir / "processed" / "daily_panel.csv", index_label="date", float_format="%.10g")
    quality = {
        "status": "passed", "rows": len(panel), "columns": len(panel.columns),
        "start": panel.index.min().date().isoformat(), "end": panel.index.max().date().isoformat(),
        "future_rows_excluded": future_excluded, "duplicate_dates": int(panel.index.duplicated().sum()),
        "missing_counts": {k: int(v) for k, v in panel.isna().sum().items()},
        "series_last_observation": {c: panel[c].last_valid_index().date().isoformat() if panel[c].notna().any() else None for c in panel},
        "imputation": "none", "units": "percent per annum; differences are percentage points",
        "vintage": "latest downloaded snapshot; no historical release-time vintage assurance",
        "public_redistribution": "disabled pending source-specific review"
    }
    json_write(run_dir / "outputs" / "data_quality.json", quality)
    return panel, quality


def analyze(panel: pd.DataFrame, output: Path, config):
    import statsmodels.api as sm
    output.mkdir(parents=True, exist_ok=True)
    latest = []
    for c in panel:
        s = panel[c].dropna()
        unit = "percent_per_annum" if c in {"ust_2y", "ust_10y", "ust_3m", "ust_real_10y", "kw_zero_yield_10y", "kw_expected_avg_short_10y"} else "percentage_points"
        latest.append({"series": c, "observation_date": s.index[-1].date().isoformat(), "value": float(s.iloc[-1]), "unit": unit})
    pd.DataFrame(latest).to_csv(output / "latest_observations.csv", index=False, float_format="%.10g")
    panel.describe().T.to_csv(output / "descriptive_statistics.csv", float_format="%.10g")
    change = panel["ust_10y"].dropna().diff().mul(100)
    samples = pd.DataFrame({"target_change_bp": change, "lag1_change_bp": change.shift(1)}).dropna()
    m = config["pilot"]["model"]
    train = samples.loc[:m["train_end"]]
    validation = samples.loc[(samples.index > pd.Timestamp(m["train_end"])) & (samples.index <= pd.Timestamp(m["validation_end"]))]
    test = samples.loc[m["test_start"]:]
    if min(len(train), len(validation), len(test)) < 100:
        raise ValueError("INSUFFICIENT_CHRONOLOGICAL_SPLIT")
    model = sm.OLS(train.target_change_bp, sm.add_constant(train[["lag1_change_bp"]], has_constant="add")).fit(
        cov_type="HAC", cov_kwds={"maxlags": m["hac_maxlags"]}
    )
    coefficients = pd.DataFrame({"coefficient": model.params, "hac_standard_error": model.bse, "p_value": model.pvalues})
    coefficients.to_csv(output / "ar1_coefficients.csv", index_label="term", float_format="%.10g")
    scores, predictions = [], []
    for name, part in [("train", train), ("validation", validation), ("test", test)]:
        forecast = np.asarray(model.predict(sm.add_constant(part[["lag1_change_bp"]], has_constant="add")))
        observed = part.target_change_bp.to_numpy()
        for model_name, values in [("AR1", forecast), ("zero_change_baseline", np.zeros(len(part)))]:
            scores.append({"split": name, "model": model_name, "n": len(part), "start": part.index.min().date().isoformat(),
                           "end": part.index.max().date().isoformat(), "rmse_bp": float(np.sqrt(np.mean((observed - values) ** 2))),
                           "mae_bp": float(np.mean(np.abs(observed - values)))})
        predictions.append(pd.DataFrame({"date": part.index, "split": name, "observed_bp": observed, "ar1_forecast_bp": forecast, "baseline_bp": 0}))
    pd.concat(predictions).to_csv(output / "ar1_predictions.csv", index=False, float_format="%.10g")
    pd.DataFrame(scores).to_csv(output / "ar1_validation.csv", index=False, float_format="%.10g")
    metrics = {"purpose": "computational_readiness_only", "strategy_backtest": False, "point_in_time_validated": False,
               "model_parameters_status": "proposal", "train_only_fit": True, "tuning_on_validation_or_test": False,
               "fixed_baseline": "zero change in next observation's yield", "scores": scores,
               "limitations": ["Latest revised snapshots, not historical release vintages", "No equity, valuation, trading return, or causal claim", "No policy intent identification"]}
    json_write(output / "model_check.json", metrics)

    with plt.rc_context({"font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False}):
        fig, axes = plt.subplots(3, 1, figsize=(11, 9.5), sharex=True)
        panel[["ust_10y", "ust_real_10y"]].rename(columns={"ust_10y": "Treasury 10Y par yield", "ust_real_10y": "Treasury 10Y real par yield"}).plot(ax=axes[0], color=["#245c85", "#d28344"], linewidth=1)
        panel[["nominal_real_par_spread_10y"]].rename(columns={"nominal_real_par_spread_10y": "Nominal-real par-yield spread (approximation)"}).plot(ax=axes[1], color=["#397b69"], linewidth=1)
        panel[["kw_zero_yield_10y", "kw_term_premium_10y", "kw_expected_avg_short_10y"]].rename(columns={"kw_zero_yield_10y": "KW fitted 10Y zero yield", "kw_term_premium_10y": "KW 10Y term premium", "kw_expected_avg_short_10y": "KW expected average short rate"}).plot(ax=axes[2], linewidth=1)
        for ax in axes:
            ax.set_ylabel("Percent / pp")
            ax.grid(alpha=.2)
            ax.legend(loc="upper left", fontsize=8)
        axes[2].set_xlabel("Observation date")
        fig.suptitle("US Treasury yields and term premium | execution pilot", fontsize=15, x=.08, ha="left")
        fig.text(.08, .025, "Sources: U.S. Treasury; Federal Reserve Board (Kim-Wright). Latest downloaded vintage.\nThe nominal-real par spread is not pure expected inflation; this pilot does not identify political coordination.", fontsize=8, color="#555555")
        fig.tight_layout(rect=(.02, .075, .98, .95))
        fig.savefig(output / "yields_and_term_premium.png", dpi=160)
        plt.close(fig)
    return metrics


def verify_inputs(run_dir: Path):
    manifest = json.loads((run_dir / "source_manifest.json").read_text())
    verified = 0
    for entry in manifest:
        if entry.get("file"):
            p = run_dir / entry["file"]
            if sha256(p) != entry["sha256"]:
                raise ValueError(f"SNAPSHOT_DIGEST_MISMATCH: {p.name}")
            verified += 1
    return verified


def replay(run_dir: Path, target: Path):
    verify_inputs(run_dir)
    config = json.loads((run_dir / "config_snapshot.json").read_text())
    panel = pd.read_csv(run_dir / "processed" / "daily_panel.csv", index_col="date", parse_dates=True)
    return analyze(panel, target, config)


def main():
    import statsmodels.api as sm
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "project.json")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if config["publication"]["enabled"] or config["schedule"]["enabled"]:
        raise SystemExit("This readiness runner requires publication and schedules disabled.")
    now = datetime.now(timezone.utc)
    run_dir = ROOT / "artifacts" / "runs" / now.strftime("%Y%m%dT%H%M%SZ")
    for d in ["raw", "processed", "outputs"]:
        (run_dir / d).mkdir(parents=True, exist_ok=True)
    json_write(run_dir / "config_snapshot.json", config)
    state = {"run_id": run_dir.name, "started_at_utc": now.isoformat(), "started_at_kst": now.astimezone(ZoneInfo("Asia/Seoul")).isoformat(),
             "research_as_of_date": config["pilot"]["as_of_date"], "git_commit": None, "publication_urls": [],
             "status": "running", "publication_enabled": False, "schedule_enabled": False}
    json_write(run_dir / "run.json", state)
    try:
        years = range(int(config["pilot"]["start_date"][:4]), int(config["pilot"]["as_of_date"][:4]) + 1)
        tasks = [(f"treasury_{'real' if real else 'nominal'}_{year}", treasury_url(year, real), "csv") for year in years for real in [False, True]]
        tasks.extend([
            ("fed_kim_wright", "https://www.federalreserve.gov/data/yield-curve-tables/feds200533.csv", "csv"),
            ("fred_probe", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10", "csv"),
            ("bls_cpi_probe", "https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0?startyear=2025&endyear=2026", "json"),
            ("fomc_20260916", "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm", "event_html")
        ])
        with ThreadPoolExecutor(max_workers=3) as pool:
            manifest = []
            for entry in pool.map(lambda task: fetch_one(task, run_dir / "raw"), tasks):
                manifest.append(entry)
                print(f"{entry['source']}: {entry['status']}", flush=True)
        json_write(run_dir / "source_manifest.json", manifest)
        required_failures = [e for e in manifest if e["status"] == "failed" and (e["source"].startswith("treasury_") or e["source"] == "fed_kim_wright")]
        if required_failures:
            raise ValueError(f"REQUIRED_SOURCE_FAILED: {[e['source'] for e in required_failures]}")
        panel, quality = build_dataset(run_dir, config)
        metrics = analyze(panel, run_dir / "outputs", config)
        inputs = verify_inputs(run_dir)
        state.update(status="passed_execution_pilot", completed_at_utc=datetime.now(timezone.utc).isoformat(),
                     latest_observation=quality["end"], dataset_rows=quality["rows"], verified_snapshot_files=inputs,
                     failed_optional_sources=[e["source"] for e in manifest if e["status"] == "failed"],
                     environment={"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__, "statsmodels": sm.__version__, "matplotlib": matplotlib.__version__})
    except Exception as exc:
        state.update(status="failed", error_type=type(exc).__name__, error=str(exc), completed_at_utc=datetime.now(timezone.utc).isoformat())
        raise
    finally:
        json_write(run_dir / "run.json", state)
        (ROOT / "artifacts" / "LATEST_RUN.txt").write_text(run_dir.name + "\n")
        print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
