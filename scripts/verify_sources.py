"""Read-only check of the selected original source files."""
import hashlib
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
rows=json.loads((root/'evidence/source-before.json').read_text())
changed=[]
for name,want in rows.items():
    p=Path(name)
    if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=want:
        changed.append(name)
result={'checked_files':len(rows),'changed_files':changed,'preserved':not changed,
        'scope':'selected source and documentation files; no ROM/save audit'}
print(json.dumps(result,indent=2))
raise SystemExit(bool(changed))
