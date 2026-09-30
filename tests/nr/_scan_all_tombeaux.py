"""
_scan_all_tombeaux.py — Scan exhaustif tombeaux vs imports vs appels
"""
import ast, re, sys
from pathlib import Path

ROOT_P = Path(__import__("os").path.expanduser(r"~\Script python IA\LaForge"))
APP    = ROOT_P / "app"
sys.path.insert(0, str(APP))
from nokido_core import apply_smart_patch

lf_txt   = (ROOT_P / "app" / "Nokido.py").read_text(encoding="utf-8", errors="replace")
lf_lines = lf_txt.split("\n")

# 1. Tous les tombeaux : # [EXTRAIT → module.py] fn_name
tombeaux = {}
for i, l in enumerate(lf_lines):
    m = re.match(r'^# \[(?:EXTRAIT\s*→?|→)\s*(?:→\s*)?(\w+\.py)\]\s+(\w+)\s*$', l)
    if m:
        mod_name, fn_name = m.group(1), m.group(2)
        tombeaux[fn_name] = (mod_name, i+1)

print(f"Tombeaux trouvés: {len(tombeaux)}")
for fn, (mod, line) in sorted(tombeaux.items(), key=lambda x: x[1][1]):
    print(f"  L{line:5}: {fn:<35} → {mod}")

# 2. Imports actuels dans Nokido.py
imports = set(re.findall(r'(?:from \w+ import|import )\s+(\w+)', lf_txt))
# Plus précis
import_targets = set()
for m in re.finditer(r'from \S+ import ([^#\n]+)', lf_txt):
    for name in re.split(r'[,\s]+', m.group(1)):
        name = name.strip().split(' as ')[-1].strip()
        if name:
            import_targets.add(name)

# 3. Appels directs au niveau module ou méthode (pas def, pas import, pas #)
called = {}
for i, l in enumerate(lf_lines):
    s = l.strip()
    for fn_name in tombeaux:
        if (re.search(r'\b' + re.escape(fn_name) + r'\s*\(', s)
                and not s.startswith("def ")
                and not s.startswith("from ")
                and not s.startswith("import ")
                and not s.startswith("#")):
            called.setdefault(fn_name, []).append(i+1)

# 4. Identifier les problèmes
print("\n=== ANALYSE ===")
problems = []
for fn_name, (mod, tomb_line) in tombeaux.items():
    is_imported  = fn_name in import_targets
    is_called    = fn_name in called
    in_target    = fn_name in (ROOT_P/"app"/mod).read_text(encoding="utf-8",errors="replace") if (ROOT_P/"app"/mod).exists() else False

    if is_called and not is_imported:
        status = "❌ APPELÉ SANS IMPORT"
        problems.append((fn_name, mod, called[fn_name], status))
        print(f"  {status}: {fn_name} (L{tomb_line}→{mod}) appelé aux L{called[fn_name]}")
    elif not in_target:
        status = "⚠️  ABSENT DU MODULE CIBLE"
        print(f"  {status}: {fn_name} → {mod}")
    elif is_called and is_imported:
        pass  # OK
    # else: ni appelé ni importé — tombeau passif OK

# 5. Corriger automatiquement les problèmes
print("\n=== CORRECTIONS ===")
for fn_name, mod, call_lines, status in problems:
    mod_stem = mod.replace(".py", "")
    # Ajouter import en tête de fichier après les autres imports forge_
    anchor = "from forge_startup import main  # noqa"
    new_import = f"from {mod_stem} import {fn_name}  # noqa (tombeau)"
    if new_import not in lf_txt:
        r = apply_smart_patch("app/LaForge.py", anchor, anchor + "\n" + new_import)
        lf_txt = (ROOT_P / "app" / "Nokido.py").read_text(encoding="utf-8", errors="replace")
        print(f"  {'✅' if r['ok'] else '❌'} import {fn_name} from {mod_stem}: {r}")
    else:
        print(f"  ✅ {fn_name} déjà importé")

# 6. Vérification finale
lf_final = (ROOT_P / "app" / "Nokido.py").read_text(encoding="utf-8", errors="replace")
lf_path  = ROOT_P / "app" / "Nokido.py"
try:
    compile(lf_final, str(lf_path), "exec")
    print(f"\n✅ compile() OK — {len(lf_final.split(chr(10)))}L")
except SyntaxError as e:
    print(f"\n❌ compile() ERR L{e.lineno}: {e.msg}")

print("\nDONE")
