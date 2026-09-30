# -*- coding: utf-8 -*-
"""Declarer l'organe d'un lot de modules (`__FORGE_COLOR__`), en masse et sans casser.

Audit du 2026-09-06 : 301 modules `forge_*` sans organe dans la carte du corps —
« un module non classe est un module dont personne ne surveille la regulation ».
Trois d'entre eux DECLARAIENT deja un `__FORGE_COLOR__` que le census ne lisait pas :
il vote sur son LEXIQUE d'organes (`forge_module_census.ORGANS`) et « ssot »,
« sympathique », « gate » n'y sont pas. D'ou les deux regles de ce script :

  1. une declaration n'est ecrite que si `forge_module_census._organ_by_text(decl,
     source_is_declaration=True)` la reconnait — sinon REFUSEE, et dite ;
  2. l'insertion est AST-safe : apres `from __future__ import annotations` si present
     (elle doit rester la premiere instruction), sinon apres le docstring de module,
     sinon apres les commentaires de tete ; le resultat est re-parse avant ecriture.

    LAFORGE_PYTHON tools/forge_organ_declare.py --from lot.json          # dry-run
    LAFORGE_PYTHON tools/forge_organ_declare.py --from lot.json --apply  # ecrit

Regle du vote, MESUREE sur `_organ_by_text` le 2026-09-06 (elle decide de tout) :
seuls les mots-cles de CINQ lettres ou plus votent (`hub`, `mcp`, `snn`, `snp`
ne comptent jamais), les mots vides de `_STOP_TEXT` sont exclus (`intent` en est),
et un mot du NOM de l'organe (« cerveau », « moelle », « immunitaire », « memoire »,
« vegetatif », « cognition », « locomoteur », « digestif », « observabilite »,
« qualite », « graph », « reseau », « infra », « metabolisme ») vaut TROIS voix.
Forme sure : `<mot du nom de l'organe>/<role en clair>`.

`lot.json` : {"app/forge_x.py": "cognition/agent ...", ...}. Les declarations sont
ECRITES PAR QUELQU'UN QUI A LU LE MODULE : ce script ne devine rien (le filet
« deviner depuis la docstring » a ete retire par l'owner le 2026-07-25).
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/anatomy : declarer l'organe d'un lot de modules, AST-safe"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import ast
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MARQUE = "__FORGE_COLOR__"


def organe_reconnu(decl: str) -> str | None:
    """L'organe que le census lirait dans cette declaration, ou None."""
    from nokido_agent.tools import forge_module_census as C
    o = C._organ_by_text(decl, source_is_declaration=True)
    return o if o and not str(o).startswith("?") else None


def point_insertion(src: str) -> int | None:
    """Index de LIGNE (0-based) apres laquelle inserer, ou None si le fichier ne se parse pas."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    lignes = src.splitlines()
    corps = tree.body
    # 1. apres `from __future__ import ...` (doit rester la premiere instruction)
    for node in corps:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            return node.end_lineno - 1
    # 2. apres le docstring de module
    if corps and isinstance(corps[0], ast.Expr) and isinstance(getattr(corps[0], "value", None), ast.Constant) \
            and isinstance(corps[0].value.value, str):
        return corps[0].end_lineno - 1
    # 3. apres les commentaires / lignes vides de tete
    i = 0
    while i < len(lignes) and (not lignes[i].strip() or lignes[i].lstrip().startswith("#")):
        i += 1
    return i - 1


def _lu_par_le_census(nouveau: str, org: str) -> bool:
    """Le census lira-t-il CETTE declaration ? Sa regex, sa fenetre, son vote, rien
    d'autre. Mesure 2026-09-06 : trois modules « declares avec succes » restaient non
    classes — la declaration etait posee au-dela des 3 ko qu'il lisait (docstring
    longue), ou c'etait une mention en commentaire qui avait ete reformulee."""
    from nokido_agent.tools import forge_module_census as C
    m = C.DECL_RE.search(nouveau[:C.HEAD_CHARS])
    return bool(m) and C._organ_by_text(m.group(1), source_is_declaration=True) == org


def declarer(rel: str, decl: str, appliquer: bool, jour: str | None = None,
             reformuler: bool = False) -> dict:
    p = ROOT / rel
    out = {"module": rel, "declaration": decl}
    if not p.exists():
        out["etat"] = "ABSENT"
        return out
    try:
        src = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        out["etat"] = f"ILLISIBLE ({type(e).__name__})"
        return out
    org = organe_reconnu(decl)
    # MENTION != DECLARATION. Un lecteur de declarations (forge_wiki_modules,
    # generate_autopoiese) porte la marque dans une regex `__FORGE_COLOR__\s*=` :
    # `MARQUE in src` est vrai, mais rien n'est declare. Mesure 2026-09-06 sur le
    # lot 2b : AttributeError sur m_exist None, le lot entier tombe. Seule une
    # forme `MARQUE = ...` / `MARQUE: ...` est une declaration ; sinon on insere.
    from nokido_agent.tools import forge_module_census as C   # MEME regex ancree, MEME fenetre que le lecteur
    m_exist = C.DECL_RE.search(src) if MARQUE in src else None
    if m_exist is not None:
        existante = m_exist.group(1).strip()
        if organe_reconnu(existante):
            out["etat"] = "DEJA_DECLARE"
            return out
        # Declaration presente mais ILLISIBLE pour le census (hors lexique, ou mots
        # trop courts) : mesure 2026-09-06, 12 modules — 'routing/contract',
        # 'proprioception / SSoT', 'neuro/snn-substrate'... Sans --reformuler on la
        # laisse et on le dit ; avec, on remplace le texte declare, pas la ligne.
        if not reformuler:
            out["etat"] = "DEJA_DECLARE_ILLISIBLE"
            out["existante"] = existante
            return out
        if not org:
            out["etat"] = "REFUSE_HORS_LEXIQUE"
            return out
        # Forme conservee : une declaration citee dans du CODE (la valeur GREEN de
        # l'en-tete FORGE INTELLIGENCE de mars 2026) reste citee, sinon SyntaxError.
        # Ce commentaire a ete CLOBBERE le 2026-09-06 par l'outil lui-meme : la regex
        # non ancree y voyait la premiere « declaration » du fichier.
        citee = existante[:1] in ('"', "'") and existante[-1:] == existante[:1]
        remplacement = f'"{decl}"' if citee else decl
        nouveau = src[:m_exist.start(1)] + remplacement + src[m_exist.end(1):]
        try:
            ast.parse(nouveau)
        except SyntaxError as e:
            out["etat"] = f"CASSERAIT ({e.lineno})"
            return out
        if not _lu_par_le_census(nouveau, org):
            out.update({"etat": "HORS_TETE", "existante": existante})
            return out
        out.update({"organe": org, "existante": existante})
        if appliquer:
            p.write_text(nouveau, encoding="utf-8")
            out["etat"] = "REFORMULE"
        else:
            out["etat"] = "DRY_RUN_REFORMULE"
        return out
    if not org:
        out["etat"] = "REFUSE_HORS_LEXIQUE"
        return out
    out["organe"] = org
    idx = point_insertion(src)
    if idx is None:
        out["etat"] = "NON_PARSABLE"
        return out
    jour = jour or date.today().isoformat()
    ligne = f'{MARQUE} = "{decl}"  # organe declare le {jour} (audit de raccordement)'
    lignes = src.splitlines(keepends=True)
    nl = "\r\n" if lignes and lignes[0].endswith("\r\n") else "\n"
    ins = idx + 1
    nouveau = "".join(lignes[:ins]) + nl + ligne + nl + "".join(lignes[ins:])
    try:
        ast.parse(nouveau)
    except SyntaxError as e:
        out["etat"] = f"CASSERAIT ({e.lineno})"
        return out
    if not _lu_par_le_census(nouveau, org):
        # La declaration serait posee au-dela de la fenetre que le census lit
        # (docstring tres longue) : l'ecrire la rendrait invisible, on le DIT.
        out["etat"] = "HORS_TETE"
        return out
    out["ligne"] = ins + 2
    if appliquer:
        p.write_text(nouveau, encoding="utf-8")
        out["etat"] = "ECRIT"
    else:
        out["etat"] = "DRY_RUN"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from", dest="lot", required=True, help="JSON {module: declaration}")
    ap.add_argument("--apply", action="store_true", help="ecrire (defaut : dry-run)")
    ap.add_argument("--reformuler", action="store_true",
                    help="remplacer une declaration existante que le census ne lit pas")
    a = ap.parse_args()
    lot = json.loads(Path(a.lot).read_text(encoding="utf-8"))
    res = [declarer(rel, decl, a.apply, reformuler=a.reformuler) for rel, decl in lot.items()]
    bilan: dict[str, int] = {}
    for r in res:
        bilan[r["etat"]] = bilan.get(r["etat"], 0) + 1
    print(json.dumps({"bilan": bilan, "detail": res}, ensure_ascii=False, indent=1))
    return 0 if not any(r["etat"].startswith(("REFUSE", "CASSERAIT", "NON_PARSABLE")) for r in res) else 1


if __name__ == "__main__":
    raise SystemExit(main())
