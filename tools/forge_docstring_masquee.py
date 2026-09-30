# -*- coding: utf-8 -*-
"""forge_docstring_masquee.py — rend a Python les docstrings de module masquees par un `from __future__` place AVANT elles.

POURQUOI (mesure 2026-09-29). 179 modules d'app/ + tools/ commencent par
`from __future__ import annotations` PUIS leur docstring. Python ne reconnait une
docstring de module que si elle est la PREMIERE instruction : pour ces modules
`__doc__` vaut None, `help()` est vide, et le wiki (`forge_wiki_modules`) les
compte « sans docstring ». C'est faux : ils en ont une, masquee. UNKNOWN n'est pas NO.

LA CORRECTION est une PERMUTATION : les lignes `from __future__` passent juste
apres la docstring (legal : une docstring peut preceder `from __future__`).
Controle fichier par fichier : l'AST du fichier corrige doit etre EXACTEMENT
celui de l'original, deux premieres instructions permutees, et il doit compiler.
Au moindre ecart, le fichier n'est pas ecrit et le motif est DIT.

ECRITURE GOUVERNEE, jamais un contournement : `forge_separation.enforce_separation`
puis `forge_governed_edit.governed_write` -- les gardes de l'outil MCP
`governed_edit` (secrets, AST, CRITICAL_FILES, modules-juges). Un fichier modifie
ou non suivi par git (travail d'un autre agent) n'est pas touche.

Usage :
    LAFORGE_PYTHON tools/forge_docstring_masquee.py              # liste (lecture seule)
    LAFORGE_PYTHON tools/forge_docstring_masquee.py --json       # idem, JSON
    run action=trusted_script path=tools/forge_docstring_masquee.py script_args="--appliquer --limite 60"
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

__FORGE_COLOR__ = "qualite/quality : rend a Python les docstrings de module masquees par un from __future__ place avant elles"

ROOT = Path(__file__).resolve().parent.parent
DOSSIERS = ("app", "tools")
ECARTES = {"__pycache__", "_attic", "node_modules", ".venv", "venv"}


def _futures_en_tete(arbre):
    """Nombre d'instructions `from __future__` consecutives en tete du module."""
    k = 0
    for n in arbre.body:
        if isinstance(n, ast.ImportFrom) and n.module == "__future__":
            k += 1
        else:
            break
    return k


def _est_docstring(n) -> bool:
    return (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant)
            and isinstance(n.value.value, str))


def _reste_de_ligne_vide(ligne: str, col: int) -> bool:
    """Apres la colonne `col`, la ligne ne porte que du blanc ou un commentaire."""
    reste = ligne[col:].strip()
    return not reste or reste.startswith("#")


def diagnostiquer(source: str) -> dict:
    """{'masquee': bool, 'corrigeable': bool, 'motif': str}. Ne leve jamais."""
    try:
        arbre = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return {"masquee": False, "corrigeable": False, "motif": "ILLISIBLE %s" % type(exc).__name__}
    k = _futures_en_tete(arbre)
    if k == 0 or len(arbre.body) <= k or not _est_docstring(arbre.body[k]):
        return {"masquee": False, "corrigeable": False, "motif": "non masquee"}
    lignes = source.splitlines()
    corps = arbre.body
    for i in range(k + 1):
        n = corps[i]
        if i < k and n.col_offset != 0:
            return {"masquee": True, "corrigeable": False, "motif": "future indente l.%d" % n.lineno}
        if not _reste_de_ligne_vide(lignes[n.end_lineno - 1], n.end_col_offset):
            return {"masquee": True, "corrigeable": False,
                    "motif": "autre code sur la ligne %d (`;`)" % n.end_lineno}
        suivant = corps[i + 1] if i + 1 < len(corps) else None
        if suivant is not None and suivant.lineno <= n.end_lineno:
            return {"masquee": True, "corrigeable": False,
                    "motif": "deux instructions partagent la ligne %d" % n.end_lineno}
    return {"masquee": True, "corrigeable": True, "motif": ""}


def _permutee(arbre, k):
    corps = arbre.body
    return ast.Module(body=[corps[k], *corps[:k], *corps[k + 1:]], type_ignores=arbre.type_ignores)


def demasquer(source: str):
    """-> (nouveau_source, "") ou (None, motif). Le nouveau source est PROUVE equivalent."""
    d = diagnostiquer(source)
    if not d["corrigeable"]:
        return None, d["motif"] or "non corrigeable"
    arbre = ast.parse(source)
    k = _futures_en_tete(arbre)
    doc = arbre.body[k]
    lignes = source.splitlines(keepends=True)
    a_deplacer = set()
    for n in arbre.body[:k]:
        a_deplacer.update(range(n.lineno - 1, n.end_lineno))
    bloc = [lignes[i] for i in sorted(a_deplacer)]
    if bloc and not bloc[-1].endswith(("\n", "\r")):
        bloc[-1] += "\n"
    derniere = max(a_deplacer)
    # la ligne vide qui suivait l'import part avec lui : la tete du fichier ne commence pas par un blanc
    if derniere + 1 < len(lignes) and not lignes[derniere + 1].strip():
        a_deplacer.add(derniere + 1)
    sortie = []
    for i, l in enumerate(lignes):
        if i in a_deplacer:
            continue
        sortie.append(l)
        if i == doc.end_lineno - 1:
            if not l.endswith(("\n", "\r")):
                sortie[-1] = l + "\n"
            sortie.extend(bloc)
    nouveau = "".join(sortie)
    try:
        nouvel_arbre = ast.parse(nouveau)
        compile(nouveau, "<demasquer>", "exec")
    except (SyntaxError, ValueError) as exc:
        return None, "resultat invalide : %s" % exc
    if ast.dump(nouvel_arbre) != ast.dump(_permutee(arbre, k)):
        return None, "AST different de la permutation attendue -- non ecrit"
    if not ast.get_docstring(nouvel_arbre):
        return None, "docstring toujours invisible apres correction"
    return nouveau, ""


def modules(racine: Path = ROOT):
    """Chemins relatifs (posix) des .py d'app/ et tools/, hors dossiers ecartes, tries."""
    out = []
    for dossier in DOSSIERS:
        for dirpath, dirnames, filenames in os.walk(racine / dossier):
            dirnames[:] = sorted(d for d in dirnames if d not in ECARTES)
            for f in sorted(filenames):
                if f.endswith(".py"):
                    out.append((Path(dirpath) / f).relative_to(racine).as_posix())
    return out


def masquees(racine: Path = ROOT) -> dict:
    """{chemin: diagnostic} des modules a docstring masquee ; les illisibles sont DITS."""
    out = {}
    for rel in modules(racine):
        try:
            src = (racine / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            out[rel] = {"masquee": None, "corrigeable": False, "motif": "ILLISIBLE %s" % type(exc).__name__}
            continue
        d = diagnostiquer(src)
        if d["masquee"]:
            out[rel] = d
    return out


def _non_propres(racine: Path):
    """Fichiers modifies ou non suivis selon git -- le travail d'un autre ne se touche pas.
    None si git est illisible : alors on n'ecrit RIEN (on ne sait pas qui travaille ou)."""
    try:
        r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(racine), "status",
                            "--porcelain", "--", *DOSSIERS],
                           capture_output=True, text=True, errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return {l[3:].strip().strip('"').replace("\\", "/") for l in r.stdout.splitlines() if len(l) > 3}


def appliquer(racine: Path = ROOT, agent: str = "CLAUDE", limite: int = 0) -> dict:
    """Corrige les modules masques, par les ecrivains gouvernes. -> {etat: [chemins]}."""
    sys.path.insert(0, str(racine / "tools"))
    sys.path.insert(0, str(racine))
    from forge_governed_edit import governed_write
    try:
        from nokido_agent.app.forge_separation import enforce_separation
    except ImportError:
        sys.path.insert(0, str(racine / "app"))
        from forge_separation import enforce_separation
    sales = _non_propres(racine)
    if sales is None:
        return {"GIT_ILLISIBLE_RIEN_ECRIT": []}
    bilan = {}
    faits = 0
    for rel, d in sorted(masquees(racine).items()):
        if limite and faits >= limite:
            bilan.setdefault("RESTE_APRES_LIMITE", []).append(rel)
            continue
        if not d["corrigeable"]:
            bilan.setdefault("NON_CORRIGEABLE", []).append("%s (%s)" % (rel, d["motif"]))
            continue
        if rel in sales:
            bilan.setdefault("MODIFIE_PAR_UN_AUTRE", []).append(rel)
            continue
        ok, raison = enforce_separation(agent, "governed_edit", rel)
        if not ok:
            bilan.setdefault("REFUS_SEPARATION", []).append(rel)
            continue
        src = (racine / rel).read_text(encoding="utf-8")
        nouveau, motif = demasquer(src)
        if nouveau is None:
            bilan.setdefault("NON_CORRIGEABLE", []).append("%s (%s)" % (rel, motif))
            continue
        v = governed_write(str(racine / rel), nouveau, agent=agent, allow_create=False)
        # `--limite` borne les ECRITURES TENTEES, pas les reussites (mesure 2026-09-29 : comptees
        # a la reussite, 161 refus d'ecriture ont defile au-dela d'une limite de 20).
        faits += 1
        if not v.get("ok"):
            bilan.setdefault("REFUS_%s" % str(v.get("blocked", "ECRITURE")).upper(), []).append(
                "%s (%s)" % (rel, str(v.get("reason", ""))[:90]))
            continue
        relu = (racine / rel).read_text(encoding="utf-8")
        if relu != nouveau or not ast.get_docstring(ast.parse(relu)):
            bilan.setdefault("RELECTURE_DIFFERENTE", []).append(rel)
            continue
        bilan.setdefault("CORRIGE", []).append(rel)
    return bilan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--appliquer", action="store_true", help="corriger (defaut : lecture seule)")
    ap.add_argument("--limite", type=int, default=0, help="au plus N corrections par passage")
    ap.add_argument("--agent", default="CLAUDE", help="identite presentee aux gardes")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.appliquer:
        bilan = appliquer(agent=a.agent, limite=a.limite)
        if a.json:
            print(json.dumps(bilan, ensure_ascii=False, indent=1))
        else:
            for etat, chemins in sorted(bilan.items()):
                print("[docstring-masquee] %-24s %d" % (etat, len(chemins)))
                if etat != "CORRIGE":
                    for c in chemins[:40]:
                        print("     %s" % c)
        return 0 if set(bilan) <= {"CORRIGE", "RESTE_APRES_LIMITE"} else 1
    trouves = masquees()
    if a.json:
        print(json.dumps(trouves, ensure_ascii=False, indent=1))
        return 0
    corr = sum(1 for d in trouves.values() if d["corrigeable"])
    print("[docstring-masquee] %d module(s) a docstring masquee (%d corrigeable(s)) sur %d lus"
          % (len(trouves), corr, len(modules())))
    for rel, d in sorted(trouves.items()):
        if not d["corrigeable"]:
            print("     NON CORRIGEABLE %s (%s)" % (rel, d["motif"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
