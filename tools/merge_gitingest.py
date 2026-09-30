#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARTS = ["docs/gitingest_nokido_app.txt", "docs/gitingest_tools.txt", "docs/gitingest_ctf.txt"]
OUT = ROOT / "docs" / "gitingest_nokido.txt"

sections = []
for p in PARTS:
    f = ROOT / p
    if f.exists():
        sections.append(f.read_text(encoding="utf-8", errors="replace"))
        print(f"  + {p} ({f.stat().st_size:,} bytes)")
    else:
        print(f"  ! missing: {p}")

merged = ("\n\n" + "=" * 80 + "\n\n").join(sections)
OUT.write_text(merged, encoding="utf-8")
print(f"=> {OUT} : {OUT.stat().st_size:,} bytes")
