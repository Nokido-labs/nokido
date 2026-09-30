"""
_patch_at_runner.py — Patch _handle_at via forge_at_dispatch
"""
import ast, re, sys
from pathlib import Path

ROOT_P = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_P / "app"))
from nokido_core import apply_smart_patch

lf_path  = ROOT_P / "app" / "Nokido.py"
lf_txt   = lf_path.read_text(encoding="utf-8", errors="replace")
lf_lines = lf_txt.split("\n")
lf_tree  = ast.parse(lf_txt)

node = next(
    (n for n in ast.walk(lf_tree)
     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
     and n.name == "_handle_at"), None
)
if node is None:
    print("SKIP: déjà patché"); sys.exit(0)

sl, el    = node.lineno, node.end_lineno
old_block = "\n".join(lf_lines[sl-1:el])
lines     = lf_lines[sl-1:el]
print(f"_handle_at: L{sl}-{el} ({el-sl+1}L)")

# Indentation du corps
body_indent = 12
for i in range(1, min(10, len(lines))):
    if lines[i].strip():
        body_indent = len(lines[i]) - len(lines[i].lstrip()); break
B  = " " * body_indent
B4 = " " * (body_indent + 4)
print(f"body_indent: {body_indent}sp")

# Trouver les bornes exactes de @nlu dans le bloc
nlu_start = nlu_end = None
for i, line in enumerate(lines):
    if re.search(r'elif cmd == "@nlu"', line):
        nlu_start = i
    if nlu_start is not None and i > nlu_start:
        # Fin = prochain elif/else au même niveau
        stripped = line.lstrip()
        indent   = len(line) - len(stripped)
        if indent == body_indent and (stripped.startswith("elif ") or stripped.startswith("else:")):
            nlu_end = i - 1
            break

if nlu_start is None:
    print("ERREUR: @nlu non trouvé dans _handle_at"); sys.exit(1)
if nlu_end is None:
    nlu_end = len(lines) - 1

print(f"@nlu: lines[{nlu_start}:{nlu_end}] ({nlu_end-nlu_start+1}L)")

# Extraire le corps de @nlu (sans la ligne elif)
nlu_body_lines = []
for line in lines[nlu_start+1:nlu_end+1]:
    orig_indent = len(line) - len(line.lstrip()) if line.strip() else 0
    rel_indent  = orig_indent - (body_indent + 4)  # relatif au corps elif
    new_indent  = B4 + " " * max(0, rel_indent)
    nlu_body_lines.append(new_indent + line.lstrip() if line.strip() else "")

nlu_body = "\n".join(nlu_body_lines)

# Signature
sig_end = sl - 1
for i in range(sl-1, min(sl+5, el)):
    if lf_lines[i].rstrip().endswith(":"): sig_end = i; break
orig_sig = "\n".join(lf_lines[sl-1:sig_end+1])

Q = '"'
fh_map = [
    ("@loop",     "forge_handlers",     "_handle_loop",    True),
    ("@role",     "forge_handlers",     "_handle_role",    True),
    ("@mode",     "forge_handlers",     "_handle_mode",    True),
    ("@rag",      "forge_handlers",     "_handle_rag",     True),
    ("@proxy",    "forge_handlers",     "_handle_proxy",   False),
    ("@workflow", "forge_hub_handlers", "handle_workflow", True),
    ("@ci",       "forge_hub_handlers", "handle_ci",       True),
    ("@chain",    "forge_handlers",     "_handle_chain",   True),
    ("@audit",    "forge_handlers",     "_handle_audit",   False),
    ("@switch",   "forge_handlers",     "handle_switch",   True),
]

body = [
    f'{B}"""Dispatcher @cmd."""',
    f"{B}parts = cmd_line.strip().split()",
    f"{B}cmd   = parts[0].lower() if parts else {Q}{Q}",
    f"{B}chat  = self._chat_log()",
    f"{B}from forge_at_dispatch import AT_DISPATCH as _AT",
    f"{B}if cmd in _AT:",
    f"{B4}await _AT[cmd](self, cmd_line, parts, cmd); return",
]
for cmd_k, mod, fn, with_arg in fh_map:
    body.append(f"{B}if cmd == {Q}{cmd_k}{Q}:")
    body.append(f"{B4}from {mod} import {fn}")
    body.append(f"{B4}await {fn}(self, cmd_line); return" if with_arg
                else f"{B4}await {fn}(self); return")
body += [
    f"{B}if cmd == {Q}@help{Q}:",
    f"{B4}await self._show_help(cmd_line); return",
    f"{B}if cmd == {Q}@diag{Q}:",
    f"{B4}from forge_health import run_diagnostics",
    f"{B4}await run_diagnostics(self); return",
    f"{B}if cmd == {Q}@estim{Q}:",
    f"{B4}from forge_handlers import _handle_estim",
    f"{B4}await _handle_estim(self, cmd_line[len(cmd):].strip()); return",
    f"{B}if cmd == {Q}@model{Q}:",
    f"{B4}sub = parts[1].lower() if len(parts) > 1 else {Q}list{Q}",
    f"{B4}await self._select_model(sub); return",
    f"{B}if cmd == {Q}@apply{Q}:",
    f"{B4}from forge_handlers import _handle_apply",
    f"{B4}await _handle_apply(self, cmd_line); return",
    f"{B}if cmd == {Q}@nlu{Q}:",
    nlu_body,
    f"{B4}return",
    # Pas de else: pour éviter le conflit avec le if/else interne du @nlu
    f"{B}if cmd not in _AT and cmd not in ({Q}@loop{Q},{Q}@role{Q},{Q}@mode{Q},{Q}@rag{Q},{Q}@proxy{Q},{Q}@workflow{Q},{Q}@ci{Q},{Q}@chain{Q},{Q}@audit{Q},{Q}@switch{Q},{Q}@help{Q},{Q}@diag{Q},{Q}@estim{Q},{Q}@model{Q},{Q}@apply{Q},{Q}@nlu{Q}):",
    f"{B4}chat.write({Q}[dim]@ inconnue : {Q} + cmd + {Q} — @help[/]{Q})",
]

new_block = orig_sig + "\n" + "\n".join(body)

# Validation : substituer dans le fichier entier
test_src = lf_txt.replace(old_block, new_block, 1)
try:
    ast.parse(test_src)
    print(f"Syntaxe OK — new_block {len(new_block.split(chr(10)))}L")
except SyntaxError as e:
    ctx = test_src.split("\n")
    print(f"SYNTAX_ERR L{e.lineno}: {e.msg}")
    for i in range(max(0, e.lineno-3), min(len(ctx), e.lineno+2)):
        print(f"  {i+1}: {repr(ctx[i][:80])}")
    sys.exit(1)

# Patch
r = apply_smart_patch("app/LaForge.py", old_block, new_block)
if not r["ok"]:
    print("PATCH_ERR: " + r.get("error","?")[:80]); sys.exit(1)
print(f"Patch OK: L{r['line']}")

# Vérification finale
lf_final = lf_path.read_text(encoding="utf-8", errors="replace")
try:
    ast.parse(lf_final)
    print(f"Nokido.py: OK — {len(lf_final.split(chr(10)))}L")
except SyntaxError as e:
    print(f"FINAL_ERR L{e.lineno}: {e.msg}"); sys.exit(1)

print("DONE")
