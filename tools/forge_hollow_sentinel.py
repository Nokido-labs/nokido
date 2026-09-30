#!/usr/bin/env python3
"""forge_hollow_sentinel.py — les fonctions CREUSES : le nom reste, le corps est parti.

`forge_fix_sentinel` ne voit qu'une chose : une ancre qui DISPARAIT. Elle est
donc structurellement aveugle au pire cas — la fonction dont le nom subsiste et
dont le corps a ete vide. Le symbole est toujours la, donc « present », donc
saine a ses yeux ; les appelants continuent de l'appeler et elle ne fait plus
rien. Aucun import ne casse, aucun test de fumee ne rougit.

Signature retenue : un corps sans instruction EFFECTIVE (`pass`, `...`, `return`
nu ou constant, `raise NotImplementedError`) surmonte d'une DOCSTRING qui, elle,
promet un comportement. L'ecart entre ce que la docstring annonce et ce que le
corps execute est le signal ; une fonction creuse SANS docstring est le plus
souvent un stub assume, pas une regression.

Exclusions volontaires — ce ne sont pas des creux, ce sont des contrats :
  * `@abstractmethod`, `Protocol`, `.pyi` : le vide EST la definition ;
  * `@overload` / `TYPE_CHECKING` : declarations de typage ;
  * les gestionnaires d'exception (`except: pass`) : autre defaut, autre garde
    (`hook` de recidive), et les melanger noierait les deux.

Sortie : rapport trie par gravite (longueur de la promesse non tenue).
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZONES = ("app", "tools", "forge_desktop")
DECOS_CONTRAT = {"abstractmethod", "overload", "abstractproperty"}
# Repertoires qui ne sont pas du code vivant : les compter reviendrait a
# signaler dix fois la meme fonction figee dans dix instantanes.
DOSSIERS_MORTS = {"_attic", "node_modules", "backups", "archive"}
# Une docstring POSEE PAR MACHINE n'est pas une promesse d'auteur. Ces tournures
# viennent de l'ancien enrichisseur AST : elles decrivent la signature, jamais
# le comportement, et les compter gonflerait le signal de bruit pur.
DOC_MACHINE = ("variable arguments", "keyword arguments", ": description.")


def _decorateurs(n: ast.AST) -> set[str]:
    noms = set()
    for d in getattr(n, "decorator_list", []) or []:
        cible = d.func if isinstance(d, ast.Call) else d
        if isinstance(cible, ast.Name):
            noms.add(cible.id)
        elif isinstance(cible, ast.Attribute):
            noms.add(cible.attr)
    return noms


def _corps_effectif(fn: ast.AST) -> list[ast.stmt]:
    """Instructions qui FONT quelque chose (docstring et `pass` exclus)."""
    corps = list(getattr(fn, "body", []))
    if corps and isinstance(corps[0], ast.Expr) and isinstance(corps[0].value, ast.Constant) \
            and isinstance(corps[0].value.value, str):
        corps = corps[1:]                       # docstring
    effectif = []
    for s in corps:
        if isinstance(s, ast.Pass):
            continue
        if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant):
            continue                            # `...` ou constante isolee
        if isinstance(s, ast.Return) and (
            s.value is None or isinstance(s.value, ast.Constant)
        ):
            continue                            # `return` nu ou `return None/0/""`
        if isinstance(s, ast.Raise):
            cible = s.exc.func if isinstance(s.exc, ast.Call) else s.exc
            if isinstance(cible, ast.Name) and cible.id == "NotImplementedError":
                continue
        effectif.append(s)
    return effectif


def scanner(min_doc_lignes: int = 2) -> list[dict]:
    creuses: list[dict] = []
    for zone in ZONES:
        for p in sorted((ROOT / zone).glob("**/*.py")):
            if DOSSIERS_MORTS & set(p.parts):
                continue
            try:
                arbre = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError):
                continue
            classes_contrat = {
                c.name for c in ast.walk(arbre)
                if isinstance(c, ast.ClassDef)
                and any(isinstance(b, ast.Name) and b.id in ("Protocol", "ABC")
                        for b in c.bases)
            }
            for parent in ast.walk(arbre):
                if isinstance(parent, ast.ClassDef) and parent.name in classes_contrat:
                    continue
                for n in getattr(parent, "body", []) if isinstance(
                        parent, (ast.Module, ast.ClassDef)) else []:
                    if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if _decorateurs(n) & DECOS_CONTRAT:
                        continue
                    doc = ast.get_docstring(n) or ""
                    if len(doc.splitlines()) < min_doc_lignes:
                        continue              # sans promesse ecrite, pas de signal
                    plat = " ".join(doc.split()).lower()
                    if any(t in plat for t in DOC_MACHINE):
                        continue              # docstring generee, pas une promesse
                    if _corps_effectif(n):
                        continue
                    creuses.append({
                        "fichier": str(p.relative_to(ROOT)).replace("\\", "/"),
                        "fonction": n.name,
                        "ligne": n.lineno,
                        "promesse_lignes": len(doc.splitlines()),
                        "promesse": " ".join(doc.split())[:150],
                    })
    # Gravite = ampleur de la promesse non tenue.
    return sorted(creuses, key=lambda c: -c["promesse_lignes"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-doc", type=int, default=2,
                    help="lignes de docstring minimales pour parler de promesse")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    creuses = scanner(a.min_doc)
    if a.json:
        print(json.dumps(creuses, ensure_ascii=False, indent=2))
        return 0
    print(f"[creuses] {len(creuses)} fonction(s) documentee(s) au corps vide "
          f"(seuil: docstring >= {a.min_doc} lignes)\n")
    for c in creuses[:40]:
        print(f"  {c['fichier']}:{c['ligne']}  {c['fonction']}()  "
              f"[promesse {c['promesse_lignes']} lignes]")
        print(f"      « {c['promesse'][:110]} »")
    if len(creuses) > 40:
        # Ne jamais tronquer en silence : un plafond tu se lit comme une absence.
        print(f"\n  ... {len(creuses) - 40} autres non affichees (--json pour tout)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
