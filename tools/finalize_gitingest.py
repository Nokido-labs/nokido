#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEP = "\n\n" + "=" * 80 + "\n\n"

PARTS = [
    ("app/ (559 files)", "docs/gitingest_nokido_app.txt"),
    ("tools/ (272 files)", "docs/gitingest_tools.txt"),
    ("ctf/ (447 files)", "docs/gitingest_ctf.txt"),
    ("proxy_deno/ (19 files)", "docs/gitingest_deno.txt"),
    ("docs/ (199 files)", "docs/gitingest_docs.txt"),
]

sections = []
for label, rel in PARTS:
    p = ROOT / rel
    if p.exists() and p.stat().st_size > 100:
        sections.append(f"# SECTION: {label}\n" + p.read_text(encoding="utf-8", errors="replace"))
        print(f"  + {label}: {p.stat().st_size:,} bytes")
    else:
        print(f"  ! skip {label} (missing or empty)")

out = ROOT / "docs" / "gitingest_nokido.txt"
out.write_text(SEP.join(sections), encoding="utf-8")
print(f"\n=> {out.name}: {out.stat().st_size:,} bytes ({len(sections)} sections)")
