"""Local SHA inventory against the saved audit, without touching parent Git."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    baseline=json.loads((ROOT/'docs/architecture/2026-10-05/source-snapshot.json').read_text(encoding='utf-8'))['files']
    paths=subprocess.run(['rg','--files','src','tests','docs','scripts','replay_tool','assets','.github','README.md','INSTALL.md','pyproject.toml','constraints-python312.txt','.gitignore'],cwd=ROOT,check=True,capture_output=True,text=True).stdout.splitlines()
    current={}
    for name in paths:
        normalized=name.replace('\\','/')
        if normalized.split('/')[0] in {'out', '.runtime', '.pytest_cache', '.playwright-mcp', '__pycache__', '.git'} or '__pycache__' in normalized.split('/') or normalized in ('docs/implementation/change-inventory.json',) or normalized.endswith('.png'):
            continue
        current[normalized]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    payload={'scope':'local SHA inventory; no Git revision or ownership of pre-existing untracked files claimed',
        'generated_at':datetime.now(timezone.utc).isoformat(),'baseline_file_count':len(baseline),
        'changed_from_baseline':{k:{'before':v,'after':current[k]} for k,v in baseline.items() if k in current and current[k]!=v},
        'paths_not_in_baseline':{k:v for k,v in current.items() if k not in baseline},
        'baseline_paths_missing':sorted(set(baseline)-set(current))}
    path=ROOT/'docs/implementation/change-inventory.json'
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"changed from baseline: {len(payload['changed_from_baseline'])}; outside baseline: {len(payload['paths_not_in_baseline'])}")
