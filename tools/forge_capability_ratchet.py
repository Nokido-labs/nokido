#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_capability_ratchet.py — cliquet de CAPACITES sur la matrice observee.

TROU FERME
==========
`forge_regression_matrix.py` ENREGISTRE 166 capacites (tool, signature d'arguments,
forme de sortie), mais son `--check` deduplique par NOM de tool et n'en controle que
29 : `arg_keys` et la forme de sortie sont stockes et JAMAIS compares. Mesure du
2026-08-16 : 30 capacites avaient deja change de forme de reponse (`run` passant de
{job_id,log_tail,ok,pid,rc,started,status} a {error,job_id,ok,task_id}) sans qu'aucun
consommateur ne lise le signal. Le contrat etait ecrit, jamais relu.

Ce cliquet lit ce qui etait deja ecrit, et le compare a un socle VERSIONNE en git.
Meme forme que `forge_mutation_ratchet.py` (socle gele, --check / --ecrire-socle,
INDETERMINE jamais confondu avec CONFORME).

GARANTI vs OPPORTUNISTE
=======================
Le seul champ qui doit etre DECLARE : le reel ne peut pas l'inferer. Une capacite
opportuniste qui change de contrat se signale (REVIEW) ; une capacite garantie qui
change ou disparait BLOQUE. Tout est opportuniste par defaut ; `GARANTIES` ne liste
que le noyau par lequel tout passe.

POURQUOI LA FORME DOMINANTE, PAS LA RECENTE
===========================================
`forme_recente` bascule sur UN seul appel aberrant -- ce serait un garde a faux
positifs (leçon du 2026-08-05 : un garde qui crie sur 3 lignes ne sert personne).
On gele donc la forme DOMINANTE (majoritaire), et l'apparition d'une derive
dominante->recente devient un REVIEW : un contrat en train de basculer, pas encore
bascule.

ABSENCE N'EST PAS PERTE
=======================
Une capacite absente de la matrice peut simplement etre sortie de la fenetre faute
d'appels : ce n'est pas une regression. On ne conclut a la perte qu'en croisant avec
l'inventaire du code (`_tools_structural`) et la surface offerte (`_tools_exposed`),
sondes deja durcies dans forge_regression_matrix. C'est la leçon du 2026-08-12 :
`tools/list` scope par ring avait fabrique 24 faux « PERDU » dont `poll`.

Usage :
    forge_capability_ratchet.py --check          # 0 conforme / 1 regression / 3 indetermine
    forge_capability_ratchet.py --ecrire-socle   # fige l'etat courant
    forge_capability_ratchet.py --json
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "observabilite/audit : cliquet de capacites sur la matrice observee"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOCLE = os.path.join(ROOT, "tests", "nr", "capability_socle.json")

# Une matrice perimee decrit un passe, pas l'etat courant : conclure dessus, c'est
# le faux-vert du 2026-08-15 (trois coches vertes rendues sans mesure).
FRAICHEUR_H = int(os.environ.get("LAFORGE_CAPRATCHET_FRAICHEUR_H", "72"))

# Noyau par lequel tout passe. Perdre l'un d'eux = perdre l'usage du hub.
GARANTIES = {"run", "read", "rag", "query", "hub", "governed_edit"}

# Mais le NOM ne suffit pas : `run(action,code,explanation,timeout)` a 2491 appels et
# `run(action,explanation,lane,online,script)` en a 4. Geler les deux comme garanties
# donnait 92 BLOCK potentiels sur 166 capacites (mesure du 2026-08-16) -- un garde qui
# bloque sur tout finit desarme, ce qui est pire qu'aucun garde. Une capacite n'est
# garantie que si son usage est ETABLI.
SEUIL_GARANTI = int(os.environ.get("LAFORGE_CAPRATCHET_SEUIL_GARANTI", "100"))


def _log(m: str) -> None:
    print(f"[cap-ratchet] {m}", flush=True)


def _rm():
    """Le module matrice, seule source des sondes d'inventaire (anti-duplication)."""
    sys.path.insert(0, ROOT)
    from nokido_agent.tools import forge_regression_matrix as RM  # type: ignore

    return RM


def _cle(tool: str, arg_keys: list) -> str:
    """Identite d'une capacite = son nom ET sa signature d'arguments.

    `run(action)` et `run(action,code,explanation,timeout)` sont DEUX capacites :
    perdre la seconde en gardant la premiere est invisible a un check par nom.
    """
    return f"{tool}|{','.join(arg_keys)}"


def _meme_forme(a, b) -> bool:
    """Deux formes decrivent-elles le MEME contrat ?

    Mesure du 2026-08-16 : sur 30 derives observees, 6 n'etaient que du bruit de
    seuil -- `texte:long` -> `texte:moyen` signale une reponse plus courte, pas un
    contrat different (les classes viennent de bornes a 80 / 400 caracteres). Les
    comparer strictement aurait produit 6 REVIEW permanents et rendu le cliquet
    illisible : un garde qui crie sans objet ne sert personne (2026-08-05).

    `obj:?` signifie « objet dont les cles n'ont pas pu etre lues » (payload tronque
    dans le journal). L'opposer a une liste de cles accuserait la troncature, pas le
    module : face a un `obj:?`, on ne compare donc que le TYPE.
    """
    a, b = str(a or "?"), str(b or "?")
    if a == b:
        return True
    if a.startswith("texte") and b.startswith("texte"):
        return True  # meme type, longueur differente : pas un changement de contrat
    if a.startswith("obj") and b.startswith("obj") and ("obj:?" in (a, b)):
        return True  # cles non observables d'un cote : indecidable, pas une alerte
    return False


def _est_forme_erreur(forme) -> bool:
    """La forme decrit-elle un chemin d'ERREUR plutot qu'un contrat de succes ?

    Mesure du 2026-08-16 : `job_status` figurait en tete des derives, sa forme
    dominante {job_id,log_tail,ok,pid,rc,started,status} devenant {error,job_id,ok,
    task_id} sur 407 appels. Verification par appel reel : `{"ok": false, "error":
    "unknown job_id"}` -- c'est le chemin d'erreur legitime d'un job inconnu, pas un
    contrat rompu. Le dernier appel d'une fenetre est souvent une sonde qui echoue.

    Une forme d'erreur ne vaut donc pas alerte de BASCULE. Elle reste comparee si
    elle devient DOMINANTE : la majorite des appels qui echouent, c'est une vraie
    regression, et cette branche-la n'est pas filtree.
    """
    return "error" in str(forme or "").lower()


def _charger_matrice(RM):
    if not os.path.exists(RM.MATRIX):
        return None, f"matrice absente ({RM.MATRIX}) -- lancer forge_regression_matrix.py --extract"
    try:
        with open(RM.MATRIX, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"matrice illisible : {type(exc).__name__}: {exc}"
    gen = doc.get("generated_ts")
    try:
        age_h = (datetime.now() - datetime.fromisoformat(str(gen)[:26])).total_seconds() / 3600.0
    except (TypeError, ValueError):
        return None, f"matrice sans horodatage exploitable (generated_ts={gen!r})"
    if age_h > FRAICHEUR_H:
        return None, (f"matrice perimee ({age_h:.0f} h > {FRAICHEUR_H} h) -- "
                      f"elle decrit un passe, pas l'etat courant")
    return doc, f"{gen} ({age_h:.0f} h)"


def _courant(doc: dict) -> dict:
    """{cle: fiche} des capacites observees, contrat compris."""
    out = {}
    for e in doc.get("capabilities", []):
        tool = str(e.get("tool", ""))
        keys = list(e.get("arg_keys") or [])
        c = _cle(tool, keys)
        # Une meme cle peut reapparaitre (signatures identiques agregees) : on garde
        # la plus appelee, qui porte la forme la mieux etablie.
        if c in out and out[c]["calls"] >= int(e.get("calls") or 0):
            continue
        out[c] = {
            "tool": tool,
            "arg_keys": keys,
            "forme": str(e.get("forme_dominante") or "?"),
            "forme_recente": str(e.get("forme_recente") or "?"),
            "derive": bool(e.get("derive_forme")),
            "calls": int(e.get("calls") or 0),
            "last_ts": e.get("last_ts"),
        }
    return out


def _actions_offertes() -> set:
    """Les ACTIONS d'un tool sont offertes, meme si aucun tool ne porte leur nom.

    Mesure du 2026-08-16 : `poll` cumule ~35 000 appels, possede un `handle_poll` et
    un dispatch, mais n'est PAS un tool -- c'est `hub(action="poll")`, declare dans
    l'enum. Le journal reseau enregistre l'action dans la colonne `tool`, si bien
    qu'un inventaire naif la declare MUETTE. C'est le meme piege qu'une sonde qui
    vise le mauvais port et fabrique une panne (2026-08-15).

    Corollaire mesure : le correctif du 2026-08-12 ajoutant `"poll": 3` a
    `_TOOL_MIN_RING` est INOPERANT -- `get_tool_list` filtre `_all_tools()`, ou poll
    ne figure pas. Il a ete declare efficace sans etre verifie.
    """
    sys.path.insert(0, ROOT)
    try:
        from nokido_agent.app.forge_mcp_registry import ToolRegistry  # type: ignore

        catalogue = ToolRegistry()._all_tools()
    except Exception:
        return set()  # non observable : on n'invente pas de surface
    offertes = set()
    for t in catalogue:
        if not isinstance(t, dict):
            continue
        schema = t.get("inputSchema") or t.get("input_schema") or {}
        props = schema.get("properties") or {}
        enum = (props.get("action") or {}).get("enum") or []
        offertes.update(str(v) for v in enum)
    return offertes


def _surface(RM):
    """(code, surface offerte, actions offertes) via les sondes deja durcies."""
    struct, ssrc = RM._tools_structural()
    if struct is None:
        return None, None, None, ssrc
    exposed, esrc = RM._tools_exposed()
    if exposed is None:
        return None, None, None, esrc

    def base(t):
        return t.rsplit("__", 1)[-1]

    actions = _actions_offertes()
    return ({base(t) for t in struct}, {base(t) for t in exposed}, actions,
            f"{ssrc} + {esrc} + {len(actions)} actions")


def mesurer() -> dict:
    RM = _rm()
    doc, motif = _charger_matrice(RM)
    if doc is None:
        return {"observable": False, "raison": motif}
    struct, exposed, actions, src = _surface(RM)
    if struct is None:
        return {"observable": False,
                "raison": f"inventaire NON OBSERVABLE ({src}) -- un refus n'est pas une absence"}
    return {"observable": True, "matrice": motif, "inventaire": src,
            "capacites": _courant(doc), "struct": struct, "exposed": exposed,
            "actions": actions}


def _tier(gele_fiche, tool: str, calls: int = 0) -> str:
    if gele_fiche and gele_fiche.get("tier"):
        return str(gele_fiche["tier"])
    return "garanti" if (tool in GARANTIES and calls >= SEUIL_GARANTI) else "opportuniste"


def _verdict(courant: dict):
    if not courant.get("observable"):
        return 3, {"etat": "INDETERMINE", "raison": courant.get("raison", "?")}
    try:
        with open(SOCLE, encoding="utf-8") as fh:
            gele = json.load(fh).get("capacites", {})
    except (OSError, json.JSONDecodeError) as exc:
        return 3, {"etat": "INDETERMINE",
                   "raison": f"socle illisible ({exc}) -- regenerer avec --ecrire-socle"}

    caps = courant["capacites"]
    struct, exposed = courant["struct"], courant["exposed"]
    actions = courant.get("actions") or set()
    add, review, block, muet, ok = [], [], [], [], 0

    for cle, g in gele.items():
        tool = str(g.get("tool") or cle.split("|", 1)[0])
        tier = _tier(g, tool, int(g.get("calls_au_gel") or 0))
        cur = caps.get(cle)

        if cur is None:
            # Absente de la fenetre. Trois etats distincts, pas un seul « PERDU ».
            if tool in actions:
                ok += 1  # offerte comme action d'un tool : jamais muette
            elif tool not in struct and tool not in exposed:
                cible = block if tier == "garanti" else review
                cible.append({"cle": cle, "tier": tier, "motif": "DISPARUE",
                              "detail": "absente de la matrice ET du code"})
            elif tool in struct and tool not in exposed:
                muet.append({"cle": cle, "tier": tier, "motif": "MUET",
                             "detail": "encore codee, plus offerte"})
                if tier == "garanti":
                    block.append({"cle": cle, "tier": tier, "motif": "MUET",
                                  "detail": "capacite garantie retiree de la surface"})
            else:
                # Encore offerte, simplement plus appelee dans la fenetre. Pas une perte.
                ok += 1
            continue

        if not _meme_forme(cur["forme"], g.get("forme")):
            cible = block if tier == "garanti" else review
            cible.append({"cle": cle, "tier": tier, "motif": "CONTRAT CHANGE",
                          "gele": g.get("forme"), "observe": cur["forme"],
                          "calls": cur["calls"]})
        elif cur["derive"] and not g.get("derive") and not _est_forme_erreur(cur["forme_recente"]):
            review.append({"cle": cle, "tier": tier, "motif": "CONTRAT QUI BASCULE",
                           "gele": g.get("forme"), "observe": cur["forme_recente"],
                           "calls": cur["calls"]})
        else:
            ok += 1

    for cle, c in caps.items():
        if cle not in gele:
            add.append({"cle": cle, "tier": _tier(None, c["tool"], c["calls"]),
                        "calls": c["calls"]})

    rapport = {"etat": "REGRESSION" if block else "CONFORME",
               "matrice": courant["matrice"], "inventaire": courant["inventaire"],
               "pass": ok, "add": add, "review": review, "block": block, "muet": muet,
               "socle_taille": len(gele)}
    return (1 if block else 0), rapport


def _ecrire_socle(courant: dict) -> int:
    if not courant.get("observable"):
        _log(f"REFUS de geler : {courant.get('raison')}")
        _log("  Geler un etat non observe fabriquerait un socle faux.")
        return 3
    caps = {}
    for cle, c in courant["capacites"].items():
        caps[cle] = {"tool": c["tool"], "arg_keys": c["arg_keys"], "forme": c["forme"],
                     "derive": c["derive"], "tier": _tier(None, c["tool"], c["calls"]),
                     "calls_au_gel": c["calls"], "last_ts_au_gel": c["last_ts"]}
    os.makedirs(os.path.dirname(SOCLE), exist_ok=True)
    with open(SOCLE, "w", encoding="utf-8") as fh:
        json.dump({"genere_par": "tools/forge_capability_ratchet.py --ecrire-socle",
                   "matrice": courant["matrice"], "inventaire": courant["inventaire"],
                   "capacites": caps}, fh, ensure_ascii=False, indent=1, sort_keys=True)
    gar = sum(1 for v in caps.values() if v["tier"] == "garanti")
    _log(f"socle ecrit : {os.path.relpath(SOCLE, ROOT)} "
         f"({len(caps)} capacites gelees, dont {gar} garanties)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Cliquet de capacites sur la matrice observee")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--ecrire-socle", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    courant = mesurer()
    if a.ecrire_socle:
        return _ecrire_socle(courant)

    code, r = _verdict(courant)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        return code

    _log(r["etat"])
    if r.get("raison"):
        _log(f"  {r['raison']}")
        return code
    _log(f"  matrice {r['matrice']} | {r['inventaire']}")
    _log(f"  PASS {r['pass']} / socle {r['socle_taille']} | ADD {len(r['add'])} | "
         f"REVIEW {len(r['review'])} | BLOCK {len(r['block'])}")
    for b in r["block"]:
        _log(f"  BLOCK   [{b['tier']}] {b['cle']}  {b['motif']}"
             + (f"  {b.get('gele')} -> {b.get('observe')}" if b.get("observe") else ""))
    for m in r["muet"]:
        _log(f"  MUET    [{m['tier']}] {m['cle']}  {m['detail']}")
    for v in r["review"][:20]:
        _log(f"  REVIEW  [{v['tier']}] {v['cle']}  {v['motif']}"
             + (f"  {v.get('gele')} -> {v.get('observe')}" if v.get("observe") else ""))
    if len(r["review"]) > 20:
        _log(f"  ... {len(r['review']) - 20} REVIEW de plus (--json pour tout)")
    for n in r["add"][:10]:
        _log(f"  ADD     [{n['tier']}] {n['cle']}  ({n['calls']} appels)")
    if len(r["add"]) > 10:
        _log(f"  ... {len(r['add']) - 10} ADD de plus (--json pour tout)")
    return code


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
