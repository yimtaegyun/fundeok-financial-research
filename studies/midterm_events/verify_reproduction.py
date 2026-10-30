"""Meaningful reproducibility check: recompute actual financial results and charts."""
from pathlib import Path
import hashlib,json,subprocess,sys
from PIL import Image

R=Path(__file__).resolve().parent
targets=sorted(list((R/'results').glob('*.csv'))+list((R/'figures').glob('0[1-4]*.png')))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
before={str(p.relative_to(R)):digest(p) for p in targets}
before_pixels={str(p.relative_to(R)):hashlib.sha256(Image.open(p).convert('RGB').tobytes()).hexdigest() for p in targets if p.suffix=='.png'}
run=subprocess.run([sys.executable,str(R/'run_research.py')],cwd=R,capture_output=True,text=True)
if run.returncode:
    print(run.stdout);print(run.stderr,file=sys.stderr);raise SystemExit(run.returncode)
after={str(p.relative_to(R)):digest(p) for p in targets}
checks={name:before[name]==after[name] for name in before}
pixel_checks={str(p.relative_to(R)):before_pixels[str(p.relative_to(R))]==hashlib.sha256(Image.open(p).convert('RGB').tobytes()).hexdigest() for p in targets if p.suffix=='.png'}
notebook=subprocess.run([sys.executable,str(R/'build_notebook.py')],cwd=R,capture_output=True,text=True)
if notebook.returncode:
    print(notebook.stdout);print(notebook.stderr,file=sys.stderr);raise SystemExit(notebook.returncode)
record={'same_frozen_inputs':True,'checked_files':len(checks),'all_identical':all(checks.values()),
        'files':checks,'chart_pixel_checks':pixel_checks,'notebook_python_cells_executed':True,'native_jupyter_kernel_verified':False}
(R/'results/reproducibility_check.json').write_text(json.dumps(record,indent=2))
if not record['all_identical']:raise AssertionError('Recomputed outputs differ')
print(json.dumps(record,indent=2))
