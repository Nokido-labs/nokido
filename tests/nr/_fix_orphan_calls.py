"""
_fix_orphan_calls.py — Corriger tous les appels orphelins après tombeau dans Nokido.py
"""
import ast, re, sys
from pathlib import Path

ROOT_P = Path(__import__("os").path.expanduser(r"~\Script python IA\LaForge"))
APP    = ROOT_P / "app"
sys.path.insert(0, str(APP))
from nokido_core import apply_smart_patch

lf_path = APP / "Nokido.py"

def read_fresh():
    return lf_path.read_text(encoding="utf-8", errors="replace")

results = []

# ── 1. _purge_pycache() L21 + del L22 ────────────────────────────────────
# Remplacer par l'import + appel depuis forge_startup
txt = read_fresh()
old = "_purge_pycache()\ndel _purge_pycache, _shutil  # nettoyage namespace (_pathlib conservé)"
new = (
    "from forge_startup import _purge_pycache as _ppc\n"
    "_ppc()\n"
    "del _ppc, _shutil  # nettoyage namespace (_pathlib conservé)"
)
r = apply_smart_patch("app/LaForge.py", old, new)
results.append("_purge_pycache call: " + ("✅" if r["ok"] else "❌ "+r.get("error","")[:50]))

# ── 2. _read_env_file("Nokido.env") L267 ────────────────────────────────
txt = read_fresh()
old = '_read_env_file("Nokido.env")   # chargé avant tout le reste'
new = (
    'from forge_startup import _read_env_file as _ref\n'
    '_ref("Nokido.env")   # chargé avant tout le reste\n'
    'del _ref'
)
r = apply_smart_patch("app/LaForge.py", old, new)
results.append("_read_env_file call: " + ("✅" if r["ok"] else "❌ "+r.get("error","")[:50]))

# ── 3. debug_log() appels inline L3648, L5173 ────────────────────────────
# Ces appels sont dans des méthodes de classe — ils utilisent debug_log
# importé depuis forge_logging ou défini localement
# Vérifier si debug_log est importé dans Nokido.py
txt = read_fresh()
has_debug_import = "from forge_logging import debug_log" in txt or "from forge_logging import" in txt
debug_def_exists = "def debug_log" in txt

if not has_debug_import and not debug_def_exists:
    # Ajouter l'import en tête de fichier (après les imports standards)
    r = apply_smart_patch(
        "app/LaForge.py",
        "from forge_startup import _purge_pycache as _ppc",
        "from forge_startup import _purge_pycache as _ppc\nfrom forge_logging import debug_log  # noqa"
    )
    results.append("debug_log import: " + ("✅" if r["ok"] else "❌ "+r.get("error","")[:50]))
else:
    results.append("debug_log: déjà disponible dans Nokido.py")

# ── 4. _ssh_setup_wizard() L624 ─────────────────────────────────────────
# Dans une méthode de classe → doit être import local
txt = read_fresh()
lines = txt.split("\n")
# Trouver le contexte exact
idx = next((i for i,l in enumerate(lines) if "_ssh_setup_wizard()" in l and "from" not in l), None)
if idx is not None:
    ctx = "\n".join(lines[max(0,idx-2):idx+3])
    results.append(f"_ssh_setup_wizard context L{idx+1}:\n{ctx}")
    old_line = lines[idx]
    # Remplacer par import local
    indent = len(old_line) - len(old_line.lstrip())
    sp = " " * indent
    new_block = (sp + "from forge_ssh import handle_ssh_setup_wizard as _wiz\n" +
                 sp + "_wiz()")
    r = apply_smart_patch("app/LaForge.py", old_line, new_block)
    results.append("_ssh_setup_wizard call: " + ("✅" if r["ok"] else "❌ "+r.get("error","")[:50]))

# ── 5. ollama_call() L3769 ──────────────────────────────────────────────
# Déjà importé depuis forge_ollama en tête de Nokido.py ?
txt = read_fresh()
has_ollama_import = "from forge_ollama import ollama_call" in txt
results.append("ollama_call déjà importé: " + str(has_ollama_import))
# Si oui, l'appel inline est légitime — pas d'action nécessaire

# ── 6. Supprimer la def _purge_pycache orpheline L6262 ──────────────────
txt = read_fresh()
tree = ast.parse(txt)
lines = txt.split("\n")
dup = next(
    (n for n in ast.walk(tree)
     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
     and n.name == "_purge_pycache" and n.col_offset == 0),
    None
)
if dup:
    old_def = "\n".join(lines[dup.lineno-1:dup.end_lineno])
    r = apply_smart_patch("app/LaForge.py", old_def, "# [_purge_pycache → forge_startup.py]")
    results.append("_purge_pycache def orpheline: " + ("✅ supprimée" if r["ok"] else "❌ "+r.get("error","")[:50]))

# ── Vérification finale ───────────────────────────────────────────────────
txt = read_fresh()
try:
    ast.parse(txt)
    results.append(f"\n✅ Nokido.py syntaxe OK — {len(txt.split(chr(10)))}L")
except SyntaxError as e:
    results.append(f"\n❌ Nokido.py ERR L{e.lineno}: {e.msg}")

# Vérifier aussi qu'il n'y a plus d'appels orphelins
tombeau_names = re.findall(r'^# \[(?:EXTRAIT|→)[^\]]+\]\s+(\w+)', txt, re.MULTILINE)
remaining_orphans = []
for fn_name in tombeau_names:
    for i, l in enumerate(txt.split("\n")):
        if re.match(r'^\s*' + re.escape(fn_name) + r'\s*\(', l) and "from" not in l and "def " not in l and "#" not in l:
            remaining_orphans.append(f"L{i+1}: {l.strip()[:60]}")
if remaining_orphans:
    results.append("⚠️  Appels orphelins restants:" + chr(10) + chr(10).join(remaining_orphans))
else:
    results.append("✅ Aucun appel orphelin restant")

print("\n".join(results))
print("\nDONE")
