"""
cleanup_nokido.py — Ménage Nokido vers la Corbeille Windows
Lance : python cleanup_nokido.py
"""

import os
import sys
from collections import defaultdict
from pathlib import Path

# Racine DERIVEE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
ROOT = Path(__file__).resolve().parent.parent

# Installer send2trash si absent
try:
    import send2trash
except ImportError:
    print("Installation send2trash...")
    os.system(f'"{sys.executable}" -m pip install send2trash -q')
    import send2trash

stats = defaultdict(int)


def trash(p: Path, label: str):
    try:
        send2trash.send2trash(str(p))
        stats[label] += 1
    except Exception as e:
        print(f"  SKIP {p.name}: {e}")


print("=== Ménage Nokido → Corbeille ===\n")

# 1. task_mod_*.log dans sandbox (~15357 fichiers)
sb = ROOT / "sandbox"
task_mod = list(sb.glob("task_mod_*.log"))
print(f"[1] task_mod_*.log : {len(task_mod)} fichiers...")
for f in task_mod:
    trash(f, "task_mod_logs")
print(f"    → {stats['task_mod_logs']} déplacés en corbeille")

# 2. task_tests_*.log
task_tests = list(sb.glob("task_tests_*.log"))
print(f"[2] task_tests_*.log : {len(task_tests)} fichiers...")
for f in task_tests:
    trash(f, "task_tests_logs")
print(f"    → {stats['task_tests_logs']} déplacés")

# 3. Fichiers _a.txt _b.txt etc (temporaires debug)
tmp_files = list(sb.glob("_*.txt")) + list(sb.glob("_*.py"))
keep = {"_cline_mode.py", "_get_db_fix.py", "_guard_fix.txt"}
tmp_files = [f for f in tmp_files if f.name not in keep]
print(f"[3] Fichiers temp sandbox (_*.txt/_*.py) : {len(tmp_files)}...")
for f in tmp_files:
    trash(f, "sandbox_tmp")
print(f"    → {stats['sandbox_tmp']} déplacés")

# 4. .mypy_cache (382MB)
mypy = ROOT / ".mypy_cache"
if mypy.exists():
    size_mb = sum(f.stat().st_size for f in mypy.rglob("*") if f.is_file()) // 1024 // 1024
    print(f"[4] .mypy_cache ({size_mb}MB)...")
    trash(mypy, "mypy_cache")
    print("    → déplacé en corbeille")

# 5. app/__pycache__ et sous-dossiers
pycaches = list((ROOT / "app").rglob("__pycache__"))
print(f"[5] __pycache__ dans app/ : {len(pycaches)} dossiers...")
for d in pycaches:
    trash(d, "pycache")
print(f"    → {stats['pycache']} déplacés")

# 6. sandbox/__pycache__
sb_pyc = sb / "__pycache__"
if sb_pyc.exists():
    trash(sb_pyc, "pycache")

# 7. Anciens fichiers _*.log autres dans sandbox
other_logs = [f for f in sb.glob("*.log") if not f.name.startswith("task_")]
# Garder bridge.log et mcp_live.log
keep_logs = {"bridge.log", "mcp_live.log", "mcp_nr.log"}
old_logs = [f for f in other_logs if f.name not in keep_logs]
print(f"[6] Autres logs sandbox : {len(old_logs)} fichiers...")
for f in old_logs:
    trash(f, "other_logs")
print(f"    → {stats['other_logs']} déplacés")

print("\n=== Résumé ===")
total = sum(stats.values())
print(f"Total déplacés en corbeille : {total} éléments")
print(f"  task_mod logs  : {stats['task_mod_logs']}")
print(f"  task_tests logs: {stats['task_tests_logs']}")
print(f"  sandbox tmp    : {stats['sandbox_tmp']}")
print(f"  mypy_cache     : {stats['mypy_cache']}")
print(f"  pycache        : {stats['pycache']}")
print(f"  autres logs    : {stats['other_logs']}")
print("\nTout est récupérable depuis la Corbeille Windows.")
