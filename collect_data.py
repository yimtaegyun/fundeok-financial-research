"""Freeze public government source files. No credentials or synthetic fallback."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
SOURCES = [
    ("pce_monthly.csv", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=PCEPI,PCEPILFE,PCEC96,DSPIC96,PSAVERT&cosd=2014-01-01&coed=2026-09-01", "BEA via FRED", "government statistics; cite BEA/FRED"),
    ("treasury_daily.csv", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS2,DGS10,DFII10&cosd=2015-01-01&coed=2026-10-28", "Board of Governors / US Treasury via FRED", "Public Domain: Citation Requested; cite Board of Governors and FRED. Breakeven spread is calculated locally from DGS10 minus DFII10."),
    ("bea_pce_202609.html", "https://www.bea.gov/news/2026/personal-income-and-outlays-september-2026", "BEA", "US government release"),
    ("bea_pce_202608_first.html", "https://www.bea.gov/news/2026/personal-income-and-outlays-august-2026", "BEA", "US government release; prior publication vintage"),
    ("bea_pce_202609.pdf", "https://www.bea.gov/sites/default/files/2026-10/pi0926.pdf", "BEA", "US government release"),
    ("bea_gdp_2026q3.html", "https://www.bea.gov/news/2026/gdp-advance-estimate-3rd-quarter-2026", "BEA", "US government release"),
    ("fomc_20261028.html", "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm", "Federal Reserve", "US government release"),
    ("fec_2026_dates.pdf", "https://www.fec.gov/documents/5910/2026pdates.pdf", "FEC", "US government publication"),
]

def fetch(item):
    name, url, agency, rights = item
    target = ROOT / "data" / "raw" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "QuandeokResearch/1.0 educational reproducible macro research"})
            with urllib.request.urlopen(req, timeout=45) as response:
                data = response.read()
                content_type = response.headers.get("Content-Type", "")
                status = response.status
                final_url = response.url
            if status != 200 or len(data) < 100:
                raise ValueError(f"Bad response {status}: {name}")
            if name.endswith(".csv") and (b"observation_date" not in data[:100] and b"DATE" not in data[:100]):
                raise ValueError(f"Expected CSV, received {content_type}: {name}")
            if name.endswith(".pdf") and not data.startswith(b"%PDF"):
                raise ValueError(f"Expected PDF: {name}")
            target.write_bytes(data)
            return {"file": str(target.relative_to(ROOT)), "url": url, "resolved_url": final_url,
                    "agency": agency, "license_note": rights, "http_status": status,
                    "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                    "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "content_type": content_type}
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1 + attempt)
    raise RuntimeError(f"No data substitution allowed: {name}: {last_error}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Explicitly replace frozen snapshots with current server responses")
    args = parser.parse_args()
    manifest = ROOT / "data" / "source_manifest.json"
    if manifest.exists() and not args.refresh:
        records = json.loads(manifest.read_text())
        for row in records:
            data = (ROOT / row["file"]).read_bytes()
            if hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise RuntimeError(f"Snapshot hash mismatch: {row['file']}")
        print(f"Verified {len(records)} frozen source files. No network refresh.")
        return
    records, errors = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch, item): item[0] for item in SOURCES}
        for future in as_completed(futures):
            try:
                row = future.result()
                records.append(row)
                print(f"OK {row['file']}: {row['bytes']} bytes")
            except Exception as exc:
                errors.append(str(exc))
    if errors:
        (ROOT / "data" / "collection_errors.json").write_text(json.dumps(errors, ensure_ascii=False, indent=2))
        raise RuntimeError("Collection failed; no complete manifest written: " + "; ".join(errors))
    records.sort(key=lambda row: row["file"])
    manifest.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    print("Frozen source_manifest.json written.")

if __name__ == "__main__":
    main()
