"""
_fix_await_sync.py — Trouver et corriger tous les 'await' dans des fonctions sync
"""
import ast, sys
from pathlib import Path

ROOT_P = Path(__import__("os").path.expanduser(r"~\Script python IA\LaForge"))
APP    = ROOT_P / "app"
sys.path.insert(0, str(APP))
from nokido_core import apply_smart_patch

lf_path  = APP / "Nokido.py"
lf_txt   = lf_path.read_text(encoding="utf-8", errors="replace")
lf_lines = lf_txt.split("\n")
lf_tree  = ast.parse(lf_txt)

# Trouver toutes les méthodes sync (def, pas async def) qui contiennent 'await'
problems = []
for node in ast.walk(lf_tree):
    if not isinstance(node, ast.FunctionDef):   # sync seulement
        continue
    if isinstance(node, ast.AsyncFunctionDef):  # skip async
        continue
    # Chercher les await dans le corps
    for child in ast.walk(node):
        if isinstance(child, ast.Await):
            sl, el = node.lineno, node.end_lineno
            body   = "\n".join(lf_lines[sl-1:el])
            problems.append((node.name, sl, el, body))
            break

print(f"Fonctions sync avec await: {len(problems)}")
for name, sl, el, body in problems:
    print(f"\n  {name} L{sl}-{el}:")
    print(body[:200])

# Corriger chaque cas
results = []
for name, sl, el, body in problems:
    lf_txt   = lf_path.read_text(encoding="utf-8", errors="replace")
    lf_lines = lf_txt.split("\n")
    lf_tree  = ast.parse(lf_txt)

    # Retrouver le nœud (lignes ont pu changer)
    node = next(
        (n for n in ast.walk(lf_tree)
         if isinstance(n, ast.FunctionDef) and n.name == name
         and n.lineno == sl),
        None
    )
    if not node:
        # Chercher par nom seul si ligne a changé
        node = next(
            (n for n in ast.walk(lf_tree)
             if isinstance(n, ast.FunctionDef) and n.name == name),
            None
        )
    if not node:
        results.append(f"{name}: NON TROUVÉ"); continue

    sl2, el2  = node.lineno, node.end_lineno
    old_block = "\n".join(lf_lines[sl2-1:el2])
    old_sig   = lf_lines[sl2-1]

    # Détecter l'indentation du corps
    body_indent = 8  # défaut
    for i in range(sl2, min(sl2+5, el2)):
        if lf_lines[i].strip():
            body_indent = len(lf_lines[i]) - len(lf_lines[i].lstrip())
            break

    B  = " " * body_indent
    B4 = " " * (body_indent + 4)

    # Chercher le module importé dans le stub
    import re
    m = re.search(r'from (\w+) import (\w+) as _fh', old_block)
    if not m:
        results.append(f"{name}: pas de stub _fh trouvé"); continue

    mod_name, fn_name = m.group(1), m.group(2)

    # Détecter les paramètres extra du return await _fh(...)
    m2 = re.search(r'return await _fh\(self(.*?)\)', old_block)
    extra = m2.group(1) if m2 else ""

    # Nouveau stub — sans await car fonction sync
    # Mais la fonction dans forge_handlers est async → on ne peut pas juste appeler
    # Solution : convertir la méthode sync en async def
    # ET s'assurer que les appelants await bien
    new_sig = old_sig.replace("    def " + name, "    async def " + name)
    new_block = new_sig + "\n" + B + "from " + mod_name + " import " + fn_name + " as _fh\n" + B + "return await _fh(self" + extra + ")"

    # Valider
    test_src = lf_txt.replace(old_block, new_block, 1)
    try:
        ast.parse(test_src)
        r = apply_smart_patch("app/LaForge.py", old_block, new_block)
        results.append(f"{name}: {'✅ L'+str(r['line']) if r['ok'] else '❌ '+r.get('error','')[:50]}")
    except SyntaxError as e:
        results.append(f"{name}: SYNTAX_ERR L{e.lineno}: {e.msg}")

print("\n=== CORRECTIONS ===")
print("\n".join(results))

# Vérification finale
lf_final = lf_path.read_text(encoding="utf-8", errors="replace")
try:
    ast.parse(lf_final)
    print(f"\n✅ Nokido.py syntaxe OK — {len(lf_final.split(chr(10)))}L")
except SyntaxError as e:
    print(f"\n❌ Nokido.py ERR L{e.lineno}: {e.msg}")

# Vérifier aussi les autres modules app/
print("\n=== SCAN TOUS LES MODULES ===")
for f in sorted(APP.glob("*.py")):
    if f.name.startswith("_"): continue
    try:
        txt  = f.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(txt)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef): continue
            for child in ast.walk(node):
                if isinstance(child, ast.Await):
                    print(f"  ❌ {f.name}: {node.name}() sync avec await L{node.lineno}")
                    break
    except Exception:
        pass
print("Scan terminé.")
