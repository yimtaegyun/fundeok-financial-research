"""Run the research from frozen data; append stage logs; never publish or place orders."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
def main():
    for script in ["collect_data.py","execute_notebook.py"]:
        started=datetime.now(timezone.utc).isoformat()
        process=subprocess.run([sys.executable,str(ROOT/script)],cwd=ROOT,text=True,capture_output=True)
        row={"stage":script,"started_at_utc":started,"finished_at_utc":datetime.now(timezone.utc).isoformat(),"exit_code":process.returncode,"stdout":process.stdout[-5000:],"stderr":process.stderr[-5000:]}
        with (ROOT/"outputs/execution_log.jsonl").open("a") as handle:handle.write(json.dumps(row,ensure_ascii=False)+"\n")
        print(f"{script}: exit {process.returncode}")
        if process.returncode:
            print(process.stderr,file=sys.stderr);raise SystemExit(process.returncode)
    print("Research complete. No external publication, scheduling, or trading action.")

if __name__=="__main__":
    (ROOT/"outputs").mkdir(exist_ok=True)
    main()
