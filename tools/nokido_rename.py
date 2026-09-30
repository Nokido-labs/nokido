#!/usr/bin/env python3
"""Renommage Nokido -> Nokido — Phase 1 (docs prose, coupe nette). Dry par defaut.

COUPE NETTE : renomme UNIQUEMENT la marque en PROSE. Protege tout code / chemin /
identifiant / service / env / alias-MCP :
  - masque le code (fences ``` et inline `...`) AVANT toute substitution ;
  - protege compounds / services / env / modules / paths dans la prose restante ;
  - remplace 'Nokido' / 'Nokido' -> 'Nokido', 'nokido' standalone -> 'nokido'.
IO binaire + surrogateescape = zero perte d'octet, preserve les fins de ligne.
Cibles = docs texte du depot (.md / .txt). Install/pyproject/code/services = phases
separees (Phase 1b / Phase 2), traites a part.

Usage (via run action=trusted_script) : [--apply]   (defaut = dry-run, n'ecrit rien)
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/rename : renommage phase 1, docs prose, coupe nette"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import ast
import glob
import io
import os
import re
import time
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # racine du depot

CODE = re.compile(r"```.*?```|`[^`\n]+`", re.DOTALL)
PROSE = re.compile(
    r"(LaForge[A-Za-z0-9]*[-._][A-Za-z0-9]+|LaForge[A-Z][A-Za-z0-9]+|LaForge[\\/]|LAFORGE_[A-Z0-9_]+"
    r"|forge_[a-z0-9_]+|laforge[-_.][a-z0-9]+|laforge[\\/]|[A-Za-z0-9]laforge|[\\/][A-Za-z0-9_.\-]*LaForge)"
    r"|(La-Forge|LaForge)|((?<![A-Za-z])laforge(?![A-Za-z]))"
)


def _rep(m):
    if m.group(1):
        return m.group(1)          # PROTEGE (code/infra) — inchange
    return "Nokido" if m.group(2) else "nokido"


def transform(text: str) -> str:
    store = []

    def mask(m):
        store.append(m.group(0))
        return "\x01%d\x02" % (len(store) - 1)

    masked = CODE.sub(mask, text)
    out = PROSE.sub(_rep, masked)
    return re.sub(r"\x01(\d+)\x02", lambda m: store[int(m.group(1))], out)


def transform_ui(text: str) -> str:
    # Fichiers UI (html/js user-facing) : PAS de masque markdown (les backticks
    # sont des template literals JS). Le groupe protege de PROSE garde deja
    # identifiants / paths / classes CSS / refs de fichier / env.
    return PROSE.sub(_rep, text)


UI_GLOBS = (
    os.path.join("app", "web_hub", "**", "*.html"),
    os.path.join("app", "web_hub", "static", "*.js"),
    os.path.join("docs", "*.html"),
    os.path.join("data", "llamacpp_webui_fr", "*.html"),
)
UI_EXCLUDE = ("compiled", "_ds_bundle", "design_handoff", ".ref.", "node_modules", ".min.")


def _ui_targets(root):
    seen = set()
    for pat in UI_GLOBS:
        for p in glob.glob(os.path.join(root, pat), recursive=True):
            if not os.path.isfile(p):
                continue
            low = p.replace("\\", "/").lower()
            if any(x in low for x in UI_EXCLUDE):
                continue
            if p in seen:
                continue
            seen.add(p)
            yield p


PY_SKIP = ("/.git/", "/__pycache__/", "/rag/", "/backups/", "/node_modules/",
           "/.venv/", "/venv/", "/dist/", "/build/", "/.bridge_tmp/",
           "/shadow_mutation/", "/shadow_evolution/", "/sandbox/", "/.internal_logs/")


def _py_targets(root):
    for dp, dn, fn in os.walk(root):
        low = dp.replace("\\", "/").lower() + "/"
        if any(s in low for s in PY_SKIP):
            dn[:] = []
            continue
        for f in fn:
            if f.endswith(".py") and f != "nokido_rename.py":
                yield os.path.join(dp, f)


def _prose_spans(src):
    lines = src.splitlines(keepends=True)
    cum = [0]
    for ln in lines:
        cum.append(cum[-1] + len(ln))

    def off(line, col):
        return cum[line - 1] + col

    spans = []
    try:
        for tk in tokenize.generate_tokens(io.StringIO(src).readline):
            if tk.type == tokenize.COMMENT:
                spans.append((off(tk.start[0], tk.start[1]), off(tk.end[0], tk.end[1])))
    except Exception:
        pass
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = getattr(node, "body", None)
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(getattr(body[0], "value", None), ast.Constant)
                        and isinstance(body[0].value.value, str)
                        and body[0].value.end_lineno is not None):
                    d = body[0].value
                    spans.append((off(d.lineno, d.col_offset), off(d.end_lineno, d.end_col_offset)))
    except Exception:
        pass
    return spans


def transform_pycode(src):
    # PROSE de code inerte SEULEMENT : commentaires (#) + docstrings module/def/class.
    # Aucun autre string (paths/data/SQL/templates) ni identifiant touche.
    spans = sorted(set(_prose_spans(src)), reverse=True)
    out = src
    for s, e in spans:
        seg = out[s:e]
        new = PROSE.sub(_rep, seg)
        if new != seg:
            out = out[:s] + new + out[e:]
    return out


LONE_QUOTED = re.compile(r"^[rbuRBUfF]*(['\"]{1,3})(La-Forge|LaForge|laforge)\1$")


FUNC_STR = re.compile(r'''["']?[\w./-]*la-?forge[\w./-]*["']?''', re.I)
_CANON_BRAND = {"LaForge", "La-Forge"}


def _pystr_protect(text):
    # Dans un STRING token .py : masque les brand-strings FONCTIONNELS (identifiants
    # composes agt_laforge/wrk_laforge, conteneurs exegol-laforge, globs laforge_*.log,
    # slugs laforge-, paths /repos/.../La-Forge, env LAFORGE_, service NokidoMCP,
    # literal quote 'laforge') AVANT PROSE.sub ; ne laisse renommer QUE le brand
    # canonique autonome (LaForge / La-Forge = prose). Puis restaure les masques.
    store = []

    def _m(m):
        s = m.group(0)
        if s in _CANON_BRAND:
            return s
        store.append(s)
        return "\x01%d\x02" % (len(store) - 1)

    masked = FUNC_STR.sub(_m, text)
    out = PROSE.sub(_rep, masked)
    return re.sub(r"\x01(\d+)\x02", lambda mm: store[int(mm.group(1))], out)


def transform_pystr(src):
    # STRING tokens .py : PROSE (protege deja paths/env/modules) + skip lone-quoted
    # bare brand ("LaForge" seul = segment de chemin / cle, PAS de la prose).
    spans = []
    try:
        for tk in tokenize.generate_tokens(io.StringIO(src).readline):
            if tk.type == tokenize.STRING:
                spans.append((tk.start, tk.end, tk.string))
    except Exception:
        return src
    if not spans:
        return src
    lines = src.splitlines(keepends=True)
    cum = [0]
    for ln in lines:
        cum.append(cum[-1] + len(ln))

    def off(pos):
        return cum[pos[0] - 1] + pos[1]

    out = src
    for start, end, text in sorted(spans, key=lambda s: off(s[0]), reverse=True):
        if LONE_QUOTED.match(text.strip()):
            continue
        new = _pystr_protect(text)
        if new != text:
            out = out[:off(start)] + new + out[off(end):]
    return out


def _targets(root):
    seen = set()
    for pat in ("*.md", os.path.join("docs", "**", "*.md")):
        for p in glob.glob(os.path.join(root, pat), recursive=True):
            if os.path.isfile(p) and p not in seen:
                seen.add(p)
                yield p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", default=None, help="racine a scanner (defaut = depot du tool)")
    ap.add_argument("--superrepo", action="store_true", help="cibler le dossier parent (superrepo)")
    ap.add_argument("--ui", action="store_true", help="mode UI: html/js user-facing, sans masque markdown")
    ap.add_argument("--pycode", action="store_true", help="mode code: prose .py inerte (commentaires + docstrings)")
    ap.add_argument("--timebox", type=float, default=55.0, help="secondes max par run (pycode)")
    ap.add_argument("--checkpoint", default="", help="fichier de reprise (pycode) : paths deja traites")
    ap.add_argument("--pystr", action="store_true", help="mode strings .py user-facing (PROSE + skip lone-quoted brand)")
    a = ap.parse_args()
    if a.superrepo:
        root = os.path.dirname(ROOT)
    else:
        root = os.path.abspath(a.root) if a.root else ROOT
    nf = 0
    tot = 0
    if a.pycode:
        targets, xform = _py_targets, transform_pycode
    elif a.pystr:
        targets, xform = _py_targets, transform_pystr
    elif a.ui:
        targets, xform = _ui_targets, transform_ui
    else:
        targets, xform = _targets, transform
    done = set()
    ckpt = a.checkpoint or None
    if ckpt and os.path.exists(ckpt):
        done = set(open(ckpt, encoding="utf-8").read().split("\n"))
    fh = open(ckpt, "a", encoding="utf-8") if (ckpt and a.apply) else None
    t0 = time.time()
    nf = tot = remaining = 0
    hit_timebox = False
    changed = []
    for p in targets(root):
        if p in done:
            continue
        if (a.pycode or a.pystr) and time.time() - t0 > a.timebox:
            remaining += 1
            hit_timebox = True
            continue
        try:
            data = open(p, "rb").read()
        except Exception:
            continue
        if (a.pycode or a.pystr) and b"aforge" not in data and b"La-Forge" not in data:
            if fh:
                fh.write(p + "\n")
            continue
        text = data.decode("utf-8", "surrogateescape")
        new = xform(text)
        if new != text:
            nf += 1
            tot += sum(1 for o, n in zip(text.split("\n"), new.split("\n")) if o != n)
            changed.append(os.path.relpath(p, root))
            if a.apply:
                with open(p, "wb") as f:
                    f.write(new.encode("utf-8", "surrogateescape"))
        if fh:
            fh.write(p + "\n")
    if fh:
        fh.close()
    tag = "APPLIED" if a.apply else "DRY"
    print(f"{tag}: files={nf} changed_lines={tot} remaining~={remaining} timebox={'HIT' if hit_timebox else 'ok'}")
    for c in changed[:60]:
        print("  ", c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
