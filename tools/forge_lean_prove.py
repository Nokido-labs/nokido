#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_lean_prove -- la boucle de PREUVE de Nokido : un modele propose, Lean juge, l'erreur revient au modele.

Decision owner du 15/10 : Nokido porte Lean, et la boucle doit etre « pilotable par d'autres CLI de la surface
(claude ou autre en local gratuit) » -- jamais dependante du quota d'un seul agent. Le fournisseur passe donc par
`forge_agent_proxy.ask` (gemini_cli, claude_cli, groq, ollama, ... : le chemin reel du routeur), dans l'ordre
donne ; un fournisseur indisponible est NOTE et le suivant prend la main.

Securite -- Lean EXECUTE du code a l'elaboration (`#eval`, `IO`, elaborateurs) : une preuve proposee par un modele
est du code non fiable. Trois barrieres :
  1. le modele ne remplace QUE les `sorry` du fichier cible : l'enonce, les imports et le reste sont gardes tels quels ;
  2. liste NOIRE stricte sur la preuve proposee (#eval, IO, unsafe, macro, elab, syntax, import, axiom, sorry,
     implemented_by, extern, initialize, run_cmd ...) : un seul jeton -> refus sans lancer Lean ;
  3. Lean tourne dans le compte du job (bac du hub), jamais dans la session de l'owner.
Le juge final est forge_lean_verify (sources, build, axiomes par liste blanche) : la boucle ne s'auto-certifie pas.

Usage : LAFORGE_PYTHON tools/forge_lean_prove.py --fichier Formel/Defi.lean [--fournisseurs gemini_cli,groq]
        [--essais 3]   (rapport RAG/lean/preuve_*.json ; rc 0 si PROUVE)
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/preuve_formelle : boucle de preuve routee (tout fournisseur via ask), Lean juge, budget borne"

import asyncio
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FOURNISSEURS_PAR_DEFAUT = ("gemini_cli", "claude_cli", "groq", "ollama")
INTERDITS = ("#eval", "#exit", "#print", "IO.", "IO ", "unsafe", "macro", "elab", "syntax", "import", "axiom",
             "sorry", "admit", "implemented_by", "extern", "initialize", "run_cmd", "run_elab", "run_meta",
             "native_decide", "opaque", "set_option", "open private", "System.", "Lean.Elab", "Lean.Meta.evalExpr")
_RE_BLOC = re.compile(r"```(?:lean4?|)\s*\n(.*?)```", re.S)


def preuve_interdite(preuve: str) -> str | None:
    """Premier jeton interdit trouve dans la preuve proposee, ou None."""
    for jeton in INTERDITS:
        if jeton in preuve:
            return jeton
    return None


def extraire_preuve(reponse: str) -> str:
    """Le premier bloc de code de la reponse, sinon la reponse entiere (sans blancs de bord)."""
    m = _RE_BLOC.search(reponse or "")
    return (m.group(1) if m else (reponse or "")).strip()


def substituer(source: str, preuve: str) -> tuple:
    """(nouvelle source, nombre de `sorry` remplaces). Seul le PREMIER `sorry` hors commentaire est remplace : une
    preuve a la fois, le reste du fichier intact a l'octet."""
    m = re.search(r"\bsorry\b", source)
    if not m:
        return source, 0
    return source[:m.start()] + "(by\n  " + preuve.replace("\n", "\n  ") + ")" + source[m.end():], 1


def demander(fournisseur: str, invite: str, ask_fn=None, timeout: int = 300) -> tuple:
    """(texte, erreur) via le chemin reel du routeur. Un appel en echec est une erreur DITE, pas une preuve ratee."""
    if ask_fn is None:
        from nokido_agent.app.forge_agent_proxy import ask as _ask

        def ask_fn(p, m):
            return asyncio.run(_ask(p, m, rag_context=False, max_tokens=1500, timeout=timeout, _bascule=False))
    try:
        r = ask_fn(fournisseur, invite)
    except Exception as exc:  # noqa: BLE001 - fournisseur indisponible : note, le suivant prend la main
        return "", "%s: %s" % (type(exc).__name__, str(exc)[:160])
    if not isinstance(r, dict):
        return "", "reponse non conforme"
    if r.get("error"):
        return "", str(r["error"])[:200]
    for cle in ("response", "text", "content"):
        if isinstance(r.get(cle), str):
            return r[cle], ""
    return "", "aucun texte dans la reponse"


def _invite(source: str, erreur: str) -> str:
    base = ("Tu es un assistant de preuve Lean 4 (coeur, sans Mathlib). Dans le fichier ci-dessous, remplace le "
            "PREMIER `sorry` par une preuve. Reponds UNIQUEMENT par la preuve (tactiques ou terme), dans un bloc "
            "```lean```, sans l'enonce, sans import, sans #eval ni IO.\n\n```lean\n%s\n```" % source)
    return base + ("\n\nTentative precedente refusee par Lean :\n```\n%s\n```" % erreur[-1500:] if erreur else "")


def prouver(projet: Path, fichier: str, fournisseurs=FOURNISSEURS_PAR_DEFAUT, essais: int = 3,
            ask_fn=None, juge=None) -> dict:
    """Boucle bornee : pour chaque fournisseur, au plus `essais` tentatives sur une COPIE du projet ; le juge
    (forge_lean_verify.verifier par defaut) tranche. Rend le journal complet, preuve comprise si elle est acceptee."""
    import forge_lean_verify as lv

    juge = juge or lv.verifier
    source = (Path(projet) / fichier).read_text(encoding="utf-8")
    journal, t0 = [], time.time()
    for fournisseur in fournisseurs:
        erreur = ""
        for n in range(1, essais + 1):
            texte, panne = demander(fournisseur, _invite(source, erreur), ask_fn)
            if panne:
                journal.append({"fournisseur": fournisseur, "essai": n, "etat": "INDISPONIBLE", "raison": panne})
                break
            preuve = extraire_preuve(texte)
            interdit = preuve_interdite(preuve)
            if interdit or not preuve:
                erreur = "jeton interdit : %r" % interdit if interdit else "preuve vide"
                journal.append({"fournisseur": fournisseur, "essai": n, "etat": "REFUSE", "raison": erreur})
                continue
            nouveau, remplaces = substituer(source, preuve)
            with tempfile.TemporaryDirectory(prefix="lean_essai_") as tmp:
                copie = Path(tmp) / "projet"
                shutil.copytree(projet, copie, ignore=shutil.ignore_patterns(".lake"))
                (copie / fichier).write_text(nouveau, encoding="utf-8")
                verdict = juge(copie)
            journal.append({"fournisseur": fournisseur, "essai": n, "etat": verdict["etat"],
                            "raison": verdict.get("raison", "")})
            if verdict["etat"] == "PROUVE" and remplaces:
                return {"etat": "PROUVE", "fournisseur": fournisseur, "essais": n, "preuve": preuve,
                        "journal": journal, "duree_s": round(time.time() - t0, 1)}
            if verdict["etat"] == "INCONNU":
                return {"etat": "INCONNU", "raison": verdict.get("raison", ""), "journal": journal,
                        "duree_s": round(time.time() - t0, 1)}
            erreur = verdict.get("sortie") or verdict.get("raison", "")
    return {"etat": "NON_PROUVE", "journal": journal, "duree_s": round(time.time() - t0, 1)}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    def opt(nom, defaut=None):
        return argv[argv.index(nom) + 1] if nom in argv and argv.index(nom) + 1 < len(argv) else defaut
    fichier = opt("--fichier")
    if not fichier:
        print("usage : forge_lean_prove.py --fichier Formel/Defi.lean [--fournisseurs a,b] [--essais 3]")
        return 2
    fournisseurs = tuple(p.strip() for p in opt("--fournisseurs", ",".join(FOURNISSEURS_PAR_DEFAUT)).split(",") if p.strip())
    r = prouver(ROOT / opt("--projet", "formel"), fichier, fournisseurs, int(opt("--essais", "3")))
    sortie = ROOT / "RAG" / "lean" / ("preuve_%s.json" % time.strftime("%Y%m%d-%H%M%S"))
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[lean-prove] %s -- %s ; rapport %s" % (r["etat"], r.get("fournisseur") or r.get("raison", ""), sortie))
    return 0 if r["etat"] == "PROUVE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
