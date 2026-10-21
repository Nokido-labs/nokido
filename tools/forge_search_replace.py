#!/usr/bin/env python3
"""forge_search_replace.py — applicateur de blocs SEARCH/REPLACE (édition chirurgicale, façon Aider).

LE cœur de l'économie de tokens pour l'itération UI/code : le LLM renvoie des blocs CIBLÉS au lieu de
réécrire tout le fichier (>80% d'économie). Ce module PARSE les blocs + les APPLIQUE au fichier local
(match EXACT puis remplace), gouverné : AST-valide les .py (anti fail-close), backup, dry-run, atomique.

Comble le GAP mesuré : forge_diff_analyzer ANALYSE les changements mais n'APPLIQUE rien ; aucun applier
search/replace n'existait (Aider non intégré). Brique de base de la moulinette UI (forge_ui_moulinette)
+ utilisable par tout agent pour éditer sans réécrire (Désigner Ring4 -> blocs ciblés only).

Format de bloc (Aider) :
    <<<<<<< SEARCH
    <texte exact à trouver>
    =======
    <texte de remplacement>
    >>>>>>> REPLACE
Un bloc dont le SEARCH est VIDE = création/append du REPLACE (nouveau contenu).

USAGE
  forge_search_replace.py <fichier> [--apply]   (blocs sur stdin)   # dry-run par défaut
  import : apply_blocks(path, parse_blocks(text), dry_run=False) -> dict
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : applicateur SEARCH/REPLACE de l'edition gouvernee"  # organe declare le 2026-09-06 (audit de raccordement)

import ast
import re
import sys
from pathlib import Path

_BLOCK_RE = re.compile(r"<{5,9} SEARCH\s*?\n(.*?)\n={5,9}\s*?\n(.*?)\n>{5,9} REPLACE", re.DOTALL)
_CLOSE_RE = re.compile(r"^>{5,9} REPLACE\s*$", re.MULTILINE)
_OPEN_RE = re.compile(r"^<{5,9} SEARCH\s*$", re.MULTILINE)

# Sentinelle de REFUS : un SEARCH introuvable fait echouer apply_to_text, donc le
# refus emprunte le chemin d erreur qui EXISTE deja chez l appelant au lieu de
# lever une exception que le handler hub n attrape pas.
_AMBIGU = (
    "⚠ BLOC AMBIGU REFUSE : le corps d un bloc contient une ligne de fermeture "
    "'>>>>>>> REPLACE'. Le parseur couperait le REPLACE a cet endroit et l edition "
    "serait PERDUE EN SILENCE. Remede : passer content= (fichier complet), ou scinder."
)


def parse_blocks(text: str) -> list[tuple[str, str]]:
    """Extrait les paires (search, replace) du texte (sortie LLM).

    GARDE (mesure 2026-08-23) : le motif non-greedy s arrete au PREMIER delimiteur
    fermant, donc un bloc dont le corps contient lui-meme une ligne
    '>>>>>>> REPLACE' etait tronque et rendait ok=True — l edition partait
    silencieusement amputee. On compte les fermetures : une de plus que de blocs
    signale ce cas, et on rend une sentinelle qui fait ECHOUER l application.

    Le blockquote markdown, longtemps soupconne, est HORS DE CAUSE : la fermeture
    exige 5 a 9 chevrons SUIVIS de ' REPLACE', qu une ligne '> cite' ne peut pas
    satisfaire (verifie par execution le 2026-08-23)."""
    blocks = [(m.group(1), m.group(2)) for m in _BLOCK_RE.finditer(text or "")]
    if blocks and len(_CLOSE_RE.findall(text or "")) > len(blocks):
        return [(_AMBIGU, "")]
    # Symetrique (dette governed_edit_blocs_perdus_en_silence, instruite 2026-10-16) : une OUVERTURE sans bloc
    # complet = un bloc coupe (transport tronque vers 16 Ko) que la regex ne voit pas -- il disparaissait, ok=True.
    ouvertures = len(_OPEN_RE.findall(text or ""))
    if ouvertures > len(blocks):
        return [("⚠ BLOC INCOMPLET REFUSE : %d ouverture(s) SEARCH pour %d bloc(s) complet(s) -- un bloc sans "
                 "fermeture serait PERDU EN SILENCE. Remede : scinder (REPLACE <= 6 Ko) ou passer content=."
                 % (ouvertures, len(blocks)), "")]
    return blocks


def _ast_ok(path: str, content: str) -> str | None:
    if not path.endswith(".py"):
        return None
    try:
        ast.parse(content, filename=path)
        return None
    except SyntaxError as e:
        return f"{path}:{e.lineno}: {e.msg}"


def apply_to_text(text: str, blocks: list[tuple[str, str]]) -> dict:
    """Applique les blocs EN MÉMOIRE (match exact, 1re occurrence). Aucune IO.

    Réutilisable hors fichier (handler hub governed_edit, tests). tout-ou-rien : ok=False si
    un SEARCH est introuvable/ambigu (on ne renvoie pas un texte partiel à écrire).

    GARDE (mesure 2026-08-26) : une liste VIDE rendait ok=True avec le texte INCHANGE.
    Le handler hub `governed_edit` ecrivait alors le fichier a l identique et repondait
    `ok:true, verified: relecture disque identique` — une edition qui ne s applique pas
    annoncee comme reussie, ce qui est pire qu un echec franc. Cas reel : des blocs passes
    en tableau JSON au lieu du format Aider, que `parse_blocks` rend `[]`. Le garde
    EXISTAIT (`apply_blocks` refuse `not blocks`) mais le seul appelant reel ne passait
    pas par lui. Refuser ici couvre tous les appelants, presents et futurs."""
    if not blocks:
        return {"ok": False, "text": text, "applied": [], "failed": [{
            "block": None,
            "reason": "aucun bloc SEARCH/REPLACE reconnu — verifier le format Aider "
                      "(<<<<<<< SEARCH / ======= / >>>>>>> REPLACE), le champ attendant "
                      "du TEXTE et non un tableau JSON",
        }]}
    new = text
    applied, failed = [], []
    for i, (search, replace) in enumerate(blocks):
        if search == "":  # création / append
            new = (new + ("\n" if new and not new.endswith("\n") else "") + replace) if new else replace
            applied.append({"block": i, "mode": "append/create"})
        elif search not in new:
            failed.append({"block": i, "reason": "SEARCH introuvable (exact)", "search_head": search[:80]})
        elif new.count(search) > 1:
            failed.append({"block": i, "reason": f"SEARCH ambigu ({new.count(search)} occurrences)", "search_head": search[:80]})
        else:
            new = new.replace(search, replace, 1)
            applied.append({"block": i, "mode": "replace"})
    return {"ok": not failed, "text": new, "applied": applied, "failed": failed}


def apply_blocks(file_path: str, blocks: list[tuple[str, str]], dry_run: bool = True) -> dict:
    """Applique les blocs au fichier (match exact, 1re occurrence). Retourne un verdict.

    BLOCK seulement si : aucun bloc, un SEARCH introuvable (ambiguïté = on n'écrit RIEN, fail-safe),
    ou syntaxe .py cassée après application. Sinon écrit atomiquement (backup .bak)."""
    if not blocks:
        return {"ok": False, "error": "aucun bloc SEARCH/REPLACE parsé"}
    p = Path(file_path)
    content = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    res = apply_to_text(content, blocks)
    new = res["text"]
    if not res["ok"]:  # fail-safe : tout-ou-rien (un bloc raté = on n'écrit pas)
        return {"ok": False, "applied_dryrun": res["applied"], "failed": res["failed"],
                "note": "aucun écriture (un bloc a échoué — tout-ou-rien fail-safe)"}
    ast_err = _ast_ok(str(p), new)
    if ast_err:
        return {"ok": False, "error": f"SyntaxError après application -> refusé: {ast_err}"}
    if dry_run:
        return {"ok": True, "dry_run": True, "would_apply": res["applied"], "bytes_after": len(new.encode("utf-8"))}
    if p.exists():
        p.with_suffix(p.suffix + ".bak").write_text(content, encoding="utf-8")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp_sr")
    tmp.write_text(new, encoding="utf-8")
    tmp.replace(p)
    return {"ok": True, "applied": res["applied"], "path": str(p), "bytes": len(new.encode("utf-8"))}


def blocs_depuis(ancien: str, nouveau: str) -> str:
    """Blocs SEARCH/REPLACE qui transforment `ancien` en `nouveau`, VERIFIES par aller-retour (19/10, decision owner :
    repli governed_edit quand le compte de confiance ne peut pas ecrire un fichier du hub). Chaque SEARCH est unique et
    commence ET finit par une ligne NON vide (l'affichage du hub ecrase les doubles lignes vides). CRLF normalise.
    Versions identiques -> "". Leve ValueError plutot que de rendre des blocs non verifies."""
    import difflib

    a = ancien.replace("\r\n", "\n").splitlines(keepends=True)
    b = nouveau.replace("\r\n", "\n").splitlines(keepends=True)
    texte, ops = "".join(a), difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    plages = []
    for tag, i1, i2, _j1, _j2 in ops:
        if tag == "equal":
            continue
        lo, hi = i1, i2
        while True:
            lo, hi = max(0, lo - 1), min(len(a), hi + 1)
            while lo > 0 and not a[lo].strip():
                lo -= 1
            while hi < len(a) and not a[hi - 1].strip():
                hi += 1
            if texte.count("".join(a[lo:hi])) == 1 or (lo == 0 and hi == len(a)):
                break
        if plages and lo < plages[-1][1]:
            plages[-1] = (plages[-1][0], max(hi, plages[-1][1]))
        else:
            plages.append((lo, hi))

    def _vers_nouveau(i, fin):
        # Borne d'une plage -> indice dans `b`. Une insertion partage son indice avec la zone egale voisine : le DEBUT
        # d'une plage prend l'operation la plus tot (l'insertion avant), la FIN la plus tardive (l'insertion apres).
        for tag, i1, i2, j1, j2 in (reversed(ops) if fin else ops):
            if tag == "equal" and i1 <= i <= i2:
                return j1 + (i - i1)
            if tag != "equal" and i == (i2 if fin else i1):
                return j2 if fin else j1
        return len(b) if fin else 0

    blocs = [("".join(a[lo:hi]), "".join(b[_vers_nouveau(lo, False):_vers_nouveau(hi, True)])) for lo, hi in plages]
    r = apply_to_text(texte, blocs) if blocs else {"ok": True, "text": texte}
    if not r["ok"] or r["text"] != "".join(b):
        raise ValueError("blocs NON verifiables (aller-retour en echec) : %s" % (r.get("failed") or "texte different"))
    return "".join("<<<<<<< SEARCH\n%s=======\n%s>>>>>>> REPLACE\n" % (s, rp) for s, rp in blocs)


def main(argv: list[str]) -> int:
    import json
    if argv[:1] == ["--blocs-depuis"] and len(argv) >= 3:
        print(blocs_depuis(Path(argv[1]).read_text(encoding="utf-8"), Path(argv[2]).read_text(encoding="utf-8")),
              end="")
        return 0
    if not argv:
        print("usage: forge_search_replace.py <fichier> [--apply]   (blocs SEARCH/REPLACE sur stdin)\n"
              "       forge_search_replace.py --blocs-depuis ANCIEN NOUVEAU   (blocs verifies sur stdout)")
        return 0
    path = argv[0]
    apply = "--apply" in argv
    blocks = parse_blocks(sys.stdin.read())
    print(json.dumps(apply_blocks(path, blocks, dry_run=not apply), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
