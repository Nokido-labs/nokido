"""forge_intent_audit.py — chaque module réalise-t-il l'INTENTION derrière lui ?

Demande owner (02/08) : « audite chaque module, capte l'intention derrière, vois si c'est
FAIT ». L'intention d'un module = ce qu'il PROMET (docstring, nom, __FORGE_COLOR__). « Fait »
= des signaux mesurables qu'il tient sa promesse : quelqu'un l'utilise, il n'est pas un
squelette, sa fonction déclarée est appelée. Un module qui existe mais que PERSONNE
n'importe, ou plein de STUB/TODO/NotImplemented, ou dont la fonction publique n'est jamais
appelée = intention DÉCLARÉE mais NON RÉALISÉE.

Ce jour même, cette classe a été trouvée à la main : forge_hybrid_retriever (0 conso ->
archivé), forge_policy_rego / forge_bounded_queue (0 conso), gardes branchés sur un signal
sans émetteur, embed_batch défini 2×. Cet outil les débusque SYSTÉMATIQUEMENT.

LÉGER par choix : pur grep/AST, ZÉRO LLM, ZÉRO embed (la RAM a saturé à 100 % le 02/08 ;
un audit ne doit pas aggraver). Il ne PROUVE pas qu'un module est mort — il RANGE par
suspicion et donne les signaux, à instruire. Trois états : réalisé · suspect · illisible.

CLI : `--globs "app/forge_*.py,tools/forge_*.py" [--json] [--limit 40]`.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

__FORGE_COLOR__ = "immunitaire/audit-intention-realisee"

ROOT = Path(__file__).resolve().parent.parent
_STUB = re.compile(r"\b(TODO|FIXME|STUB|NotImplementedError|raise NotImplemented|XXX)\b")
_IMPORT = re.compile(r"(?:^|\W)(?:import|from)\s+([a-zA-Z_][\w.]*)")


def _modules(globs: list[str]) -> dict[str, Path]:
    out = {}
    for g in globs:
        for p in ROOT.glob(g.strip()):
            if p.is_file() and "_attic" not in str(p) and "backups" not in str(p):
                out[p.stem] = p
    return out


def _corpus_texts(globs_dirs: list[str]) -> list[tuple[str, str]]:
    """(nom, texte) de tous les .py candidats importateurs — lu UNE fois."""
    seen, out = set(), []
    for g in ("app/**/*.py", "tools/**/*.py"):
        for p in ROOT.glob(g):
            if "_attic" in str(p) or "backups" in str(p) or "__pycache__" in str(p):
                continue
            if p in seen:
                continue
            seen.add(p)
            try:
                out.append((p.stem, p.read_text(encoding="utf-8", errors="replace")))
            except OSError:  # muet-ok : fichier illisible ignoré du corpus d'appelants
                continue
    return out


def _public_defs(src: str) -> list[str]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    return [n.name for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not n.name.startswith("_")]


def audit(globs: list[str]) -> dict:
    cibles = _modules(globs)
    if not cibles:
        return {"etat": "ILLISIBLE", "raison": f"aucun module pour {globs}"}
    corpus = _corpus_texts(globs)
    # UN balayage. Index INVERSE {identifiant -> set(modules ou il apparait)} : lookup
    # O(1) au lieu de re-scanner le corpus par module (O(N^2) -> timeout mesure 02/08).
    importeurs: dict[str, int] = {}
    _IDENT = re.compile(r"[A-Za-z_]\w+")
    ou_apparait: dict[str, set[str]] = {}
    for nom, txt in corpus:
        for m in _IMPORT.finditer(txt):
            base = m.group(1).split(".")[0]
            if base in cibles and base != nom:
                importeurs[base] = importeurs.get(base, 0) + 1
        for tok in set(_IDENT.findall(txt)):
            ou_apparait.setdefault(tok, set()).add(nom)

    # RÉFÉRENCE HORS-CODE : un module nommé dans la doctrine (CLAUDE.md), un config,
    # un hook ou services.toml est INVOQUÉ par un chemin que le grep de code ne voit
    # PAS — comme __main__. Le classer « mort » est un faux positif mesuré le 06/08 :
    # forge_symbiotic_bridge est cité dans CLAUDE.md (SymbioticBridge), il n'est pas mort.
    # On scanne les fichiers non-code UNE fois et on downgrade « suspect ».
    refs_hc: set[str] = set()
    try:
        _racine = Path(__file__).resolve().parent.parent
        _NONCODE = (".md", ".toml", ".json", ".yaml", ".yml", ".cfg", ".ini", ".txt")
        for _sub in ("docs", "config", "CLAUDE.md", "GEMINI.md", ".claude"):
            _base = _racine / _sub
            _paths = [_base] if _base.is_file() else (_base.rglob("*") if _base.is_dir() else [])
            for _fp in _paths:
                if _fp.is_file() and _fp.suffix in _NONCODE:
                    try:
                        _t = _fp.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    for _nom in cibles:
                        if _nom in _t:
                            refs_hc.add(_nom)
    except Exception:  # noqa: BLE001 - muet-ok : filtre bonus, jamais bloquant pour l'audit
        pass

    resultats = []
    for nom, p in sorted(cibles.items()):
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            resultats.append({"module": nom, "etat": "illisible", "raison": str(e)[:50]})
            continue
        doc = ast.get_docstring(ast.parse(src)) if src.strip() else None
        intent = (doc or "").strip().splitlines()[0][:90] if doc else "(pas de docstring)"
        n_imp = importeurs.get(nom, 0)
        stubs = len(_STUB.findall(src))
        lignes = src.count("\n") + 1
        defs = _public_defs(src)
        # fonction publique jamais appelee AILLEURS : le nom n'est present dans AUCUN
        # autre module. On teste contre l'union globale MOINS les tokens propres au
        # module (approx sure : si un nom n'est QUE dans self, il est orphelin).
        jamais_appelee = []
        if defs:
            for d in defs[:8]:
                mods = ou_apparait.get(d, set())
                if not (mods - {nom}):  # n'apparait QUE dans le module lui-meme (ou nulle part)
                    jamais_appelee.append(d)

        # POINT D'ENTREE : `__main__` = lancé en CLI/job/service/hook, PAS destiné à être
        # importé. « 0 importeur » n'y est PAS un défaut — la réalisation passe par une
        # invocation (config/schtask/services.toml/hook), non traçable par grep. On le DIT
        # au lieu de crier au mort (sinon 220 faux positifs, mesuré 02/08).
        entry = bool(re.search(r'if\s+__name__\s*==\s*[\'"]__main__[\'"]', src))
        signaux = []
        if n_imp == 0 and not entry and lignes > 30:
            signaux.append("0_importeur")
        if stubs >= 3:
            signaux.append(f"{stubs}_stub/todo")
        if defs and len(jamais_appelee) == len(defs) and n_imp == 0 and not entry:
            signaux.append("aucune_def_publique_appelee")
        if signaux and nom in refs_hc:
            signaux.append("reference_config_doc")
            etat = "invoque_hors_code"
        elif signaux:
            etat = "suspect"
        elif entry and n_imp == 0:
            etat = "point_entree"
        else:
            etat = "realise"
        resultats.append({
            "module": nom, "etat": etat, "intention": intent,
            "importeurs": n_imp, "stubs": stubs, "lignes": lignes,
            "signaux": signaux,
            "defs_orphelines": jamais_appelee[:5] if "aucune_def_publique_appelee" in signaux else [],
        })

    suspects = [r for r in resultats if r["etat"] == "suspect"]
    suspects.sort(key=lambda r: (-len(r["signaux"]), r["importeurs"]))
    return {"etat": "ok", "n_modules": len(cibles), "n_suspects": len(suspects),
            "suspects": suspects, "tous": resultats}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--globs", default="app/forge_*.py,tools/forge_*.py")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()
    r = audit([g for g in args.globs.split(",") if g.strip()])
    if r["etat"] != "ok":
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 2
    if args.json:
        r["suspects"] = r["suspects"][:args.limit]
        r.pop("tous", None)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    print(f"modules audites : {r['n_modules']} | INTENTION NON REALISEE (suspect) : {r['n_suspects']}\n")
    for s in r["suspects"][:args.limit]:
        print(f"  [{','.join(s['signaux'])}] {s['module']} (imp={s['importeurs']}, {s['lignes']}l)")
        print(f"      intention: {s['intention']}")
        if s["defs_orphelines"]:
            print(f"      defs jamais appelees: {', '.join(s['defs_orphelines'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
