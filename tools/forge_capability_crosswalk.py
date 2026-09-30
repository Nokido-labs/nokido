#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_capability_crosswalk.py — CAP-* : une capacite, ses quatre preuves.

Le manque nomme le 2026-08-16 ([[docset_deja_bati_et_cliquet_capacites]]) : chaque
brique existe et aucune ne se parle. `forge_capability_ratchet` sait QUELLES
capacites sont observees (166 gelees), `forge_mcp_registry` sait QUI les sert et
a partir de quel ring, `tests/` sait lesquelles sont couvertes, et
`forge_capability_lineage` sait DEPUIS QUAND elles existent. Personne ne joint
les quatre, donc personne ne peut repondre a « cette capacite est-elle tenue ? ».

Ce module ne mesure rien de neuf : il JOINT. Chaque capacite devient un `CAP-*`
type, portant les champs demandes au fil ouvert :

    id                 CAP-<tool>
    tier               garanti | opportuniste            (socle du cliquet)
    handler            module + fonction + ligne         (registre)
    reachable_from     ring minimal + presence catalogue  (registre)
    tests              fichiers qui la citent             (tests/)
    historical_proof   sha + date de naissance            (git, option --lignee)
    trous              ce qui manque, nomme

ANGLES MORTS — assumes et dits, jamais masques :
  1. `tests` est une MENTION, pas une couverture : un fichier qui cite « ask »
     ne prouve pas qu'il l'exerce. Lire ce champ comme « piste », jamais comme
     « teste ». L'inverse (aucune mention) est, lui, concluant.
  2. Un handler introuvable ne veut PAS dire capacite morte : les tools
     DYNAMIQUES (`forge_call_dynamic`, `dyn_*`) n'ont pas de `handle_*` statique.
     Verdict `handler_dynamique_ou_introuvable`, jamais « perdu » — la lecon de
     `poll`, pris pour muet alors qu'il etait une ACTION de `hub`.
  3. Sans `--lignee`, `historical_proof` vaut `null` : ABSENT n'est pas ZERO.

    LAFORGE_PYTHON tools/forge_capability_crosswalk.py            # jointure seule
    LAFORGE_PYTHON tools/forge_capability_crosswalk.py --lignee --top 20

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `actions_prouvees` — JOINT : croise les capacites PROUVEES (crosswalk) avec la whitelist PLANIFIABLE (ALLOWED_METHODS).
- `annotation_preference` — Suffixe de prompt ADVISOIRE : vascularisation du joint vers le planificateur GOAP.
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/audit : une capacite et ses quatre preuves"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOCLE = os.path.join(ROOT, "tests", "nr", "capability_socle.json")
REGISTRY = os.path.join(ROOT, "app", "forge_mcp_registry.py")
TESTS_DIR = os.path.join(ROOT, "tests")

_RE_HANDLER = re.compile(r"^\s*(?:async\s+)?def\s+(handle_\w+)\s*\(", re.M)
_RE_RING = re.compile(r"_TOOL_MIN_RING\s*[:=]\s*dict\s*=?\s*\{|_TOOL_MIN_RING\s*=\s*\{")


def _socle() -> dict:
    """Capacites observees, gelees par le cliquet. Source unique : on ne re-invente
    pas un inventaire, on lit celui qui fait deja autorite."""
    with open(SOCLE, encoding="utf-8") as f:
        return json.load(f)


def _handlers() -> dict:
    """`handle_<tool>` -> (fichier, ligne), lu UNE fois."""
    out = {}
    with open(REGISTRY, encoding="utf-8", errors="replace") as f:
        src = f.read()
    for m in _RE_HANDLER.finditer(src):
        out[m.group(1)] = ("app/forge_mcp_registry.py", src[: m.start()].count("\n") + 1)
    return out


def _rings() -> dict:
    """tool -> ring minimal, depuis `_TOOL_MIN_RING`. {} si la table est illisible :
    on rend alors `null` par capacite plutot qu'un 0 rassurant et faux."""
    with open(REGISTRY, encoding="utf-8", errors="replace") as f:
        src = f.read()
    m = _RE_RING.search(src)
    if not m:
        return {}
    bloc = src[m.end(): src.find("}", m.end())]
    return {k: int(v) for k, v in re.findall(r"[\"'](\w+)[\"']\s*:\s*(\d+)", bloc)}


def _mentions_tests(tools) -> dict:
    """tool -> [fichiers de test qui le citent SOUS UNE FORME D'APPEL].

    Premiere version : tout mot du fichier. Resultat `sans_test: 0` sur 29
    capacites — evidemment faux : `ask`, `run`, `event`, `crawl` sont des mots
    courants qui apparaissent partout. Un indicateur qui ne trouve jamais de trou
    ne mesure rien, il rassure (mesure 2026-08-16, meme famille que les gardes
    verts sans mesure).
    On exige donc une forme qui ressemble a un appel — chaine litterale `"ask"`,
    ou `handle_ask` — et non un mot nu. Cela reste une MENTION : le champ dit
    « piste », pas « couverture ».

    Deuxieme faux-vert, plus sournois : meme resserre, le compte restait 0. Cause
    — `tests/nr/capability_socle.json` CITE les 29 tools en clair. Le crosswalk
    lisait sa propre donnee d'entree et se donnait raison (« un outil qui indexe
    le depot qu'il alimente se donne raison »). On ne scanne donc que les `.py` :
    un fichier de DONNEES n'a jamais teste personne. Effet mesure : 0 -> 11
    capacites sans test sur 29.
    """
    motifs = {t: re.compile(r"[\"']%s[\"']|\bhandle_%s\b" % (re.escape(t), re.escape(t)))
              for t in tools}
    idx: dict = {t: [] for t in tools}
    for dp, dn, fn in os.walk(TESTS_DIR):
        dn[:] = [d for d in dn if d not in {"__pycache__", ".pytest_cache"}]
        for f in fn:
            if not f.endswith(".py"):  # les .json de tests/ sont des donnees, pas des tests
                continue
            p = os.path.join(dp, f)
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    txt = fh.read()
            except OSError:
                continue
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            for t, rx in motifs.items():
                if rx.search(txt):
                    idx[t].append(rel)
    return idx


def _naissance(fonction: str) -> dict | None:
    """Commit qui a introduit `<fonction>` (git -S). None si git muet.

    Deux pieges payes le 2026-08-16, tous deux silencieux :
      - motif : `-S "def handle_ask("` ne rend RIEN alors que `-S handle_ask`
        rend le bon commit. Un `-S` trop specifique echoue sans le dire.
      - `-1` combine a `--reverse` limite AVANT d'inverser : on obtient le
        commit le plus RECENT, pas la naissance. On prend donc la premiere
        ligne du log inverse complet.
    Couteux (~8 s par capacite sur 6192 commits) : reserve a `--lignee`, borne
    par `--top`.
    """
    cmd = ["git", "-c", "safe.directory=*", "-C", ROOT, "log", "--all", "--reverse",
           "-S", fonction, "--date=short", "--pretty=format:%h|%ad|%s"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                             errors="replace").stdout.strip()
    except Exception as exc:  # noqa: BLE001
        # « git empeche » n'est PAS « capacite sans commit ». Sous `run
        # action=python`, WORKSPACE_GUARD interdit subprocess : le crosswalk
        # rendait alors 0 preuve historique sur toute la ligne, ce qui se lit
        # comme un resultat alors que c'est une absence d'instrument. Lancer en
        # `trusted_script` (ou ps_clm) pour obtenir les preuves.
        return {"indisponible": type(exc).__name__}
    if not out:
        return None
    part = out.splitlines()[0].split("|", 2)
    if len(part) < 2:
        return None
    return {"sha": part[0], "date": part[1], "sujet": part[2][:80] if len(part) > 2 else ""}


def croiser(lignee: bool = False, top: int = 0) -> dict:
    socle = _socle()
    caps = socle.get("capacites") or {}
    handlers = _handlers()
    rings = _rings()

    par_tool: dict = {}
    for meta in caps.values():
        tool = meta.get("tool")
        if not tool:
            continue
        e = par_tool.setdefault(tool, {"tool": tool, "tiers": set(), "arg_sets": 0, "calls": 0})
        e["tiers"].add(meta.get("tier") or "?")
        e["arg_sets"] += 1
        e["calls"] += int(meta.get("calls_au_gel") or 0)

    mentions = _mentions_tests(sorted(par_tool))
    entrees = []
    for tool, e in sorted(par_tool.items()):
        fn = f"handle_{tool}"
        h = handlers.get(fn)
        tests = sorted(set(mentions.get(tool, [])))
        trous = []
        if not h:
            trous.append("handler_dynamique_ou_introuvable")
        if not tests:
            trous.append("aucune_mention_en_test")
        if tool not in rings:
            trous.append("ring_non_declare")
        entrees.append({
            "id": "CAP-" + tool,
            "tool": tool,
            "tier": "garanti" if "garanti" in e["tiers"] else sorted(e["tiers"])[0],
            "signatures_observees": e["arg_sets"],
            "calls_au_gel": e["calls"],
            "handler": ({"module": h[0], "fonction": fn, "ligne": h[1]} if h else None),
            "reachable_from": {"ring_min": rings.get(tool), "au_catalogue": tool in rings},
            "tests": tests[:6],
            "historical_proof": None,
            "trous": trous,
        })

    if lignee:
        cibles = [x for x in entrees if x["handler"]]
        cibles.sort(key=lambda x: -x["calls_au_gel"])
        for x in cibles[: (top or len(cibles))]:
            x["historical_proof"] = _naissance(x["handler"]["fonction"])

    n = len(entrees)
    return {
        "genere_par": "tools/forge_capability_crosswalk.py",
        "socle": {"fichier": "tests/nr/capability_socle.json",
                  "inventaire": socle.get("inventaire"), "signatures": len(caps)},
        "n_capacites": n,
        "sans_handler": sum(1 for x in entrees if not x["handler"]),
        "sans_test": sum(1 for x in entrees if "aucune_mention_en_test" in x["trous"]),
        "sans_ring": sum(1 for x in entrees if "ring_non_declare" in x["trous"]),
        "avec_preuve_historique": sum(
            1 for x in entrees if x["historical_proof"] and "sha" in x["historical_proof"]),
        "preuve_indisponible": sum(
            1 for x in entrees if x["historical_proof"] and "indisponible" in x["historical_proof"]),
        "angles_morts": [
            "`tests` = MENTION, pas couverture : concluant en creux (aucune), jamais en plein.",
            "handler absent != capacite morte : les tools dynamiques n'ont pas de handle_*.",
            "sans --lignee, historical_proof est ABSENT, pas ZERO.",
        ],
        "capacites": entrees,
    }


def _etat_preuve(cap: dict) -> str:
    """Etat de preuve d'une capacite (J2 : DECLARED < DECLARED_TESTED < INVOCABLE).

    calls_au_gel>0 = un appel a REUSSI au gel du socle = INVOCABLE (preuve d'usage la plus forte du
    crosswalk). Un test qui la mentionne = DECLARED_TESTED (mention, pas couverture). Sinon DECLARED.
    """
    if int(cap.get("calls_au_gel") or 0) > 0:
        return "INVOCABLE"
    if cap.get("tests"):
        return "DECLARED_TESTED"
    return "DECLARED"


def actions_prouvees(crosswalk: dict, allowed_methods, contracts: dict = None) -> dict:
    """JOINT : croise les capacites PROUVEES (crosswalk) avec la whitelist PLANIFIABLE (ALLOWED_METHODS).

    fiche_capability_graph_joint_2026-09-27, E1. Fonction PURE : n'ecrit rien, ne sonde rien. Une capacite
    ne devient une ACTION planifiable que si elle est a preuve INVOCABLE (ou mieux) ET dans allowed_methods.
    Le reste est CLASSE, jamais ecarte en silence :
      - prouvee HORS whitelist -> `non_planifiables` (dette de vascularisation : le planner ne peut pas
        encore ordonner cet outil pourtant prouve) ;
      - dans la whitelist mais NON prouvee -> `non_prouves` (J2 : DECLARED != INVOCABLE).
    preconditions/effets : renseignes depuis `contracts` quand connus, sinon ['UNKNOWN'] -- jamais fabriques.
    """
    allowed = set(allowed_methods or ())
    contracts = contracts or {}
    actions, non_planifiables, non_prouves = [], [], []
    tools_crosswalk = set()
    for cap in crosswalk.get("capacites", []):
        tool = cap.get("tool")
        if not tool:
            continue
        tools_crosswalk.add(tool)
        etat = _etat_preuve(cap)
        prouve = etat in ("INVOCABLE", "RELIABLE")
        meta = allowed_methods.get(tool) if isinstance(allowed_methods, dict) else None
        ring = meta.get("ring") if isinstance(meta, dict) else None
        pre, eff = ["UNKNOWN"], ["UNKNOWN"]
        c = contracts.get(tool)
        if isinstance(c, dict) and c.get("vivant") is not None:
            pre = ["service_vivant" if c.get("vivant") else "service_absent"]
        if tool in allowed and prouve:
            actions.append({"tool": tool, "planifiable": True, "etat_preuve": etat, "ring": ring,
                            "preconditions": pre, "effets": eff,
                            "raison": "prouvee par usage et dans ALLOWED_METHODS"})
        elif prouve:
            non_planifiables.append({"tool": tool, "etat_preuve": etat,
                                     "raison": "prouvee par usage mais hors ALLOWED_METHODS (dette de cablage)"})
        else:
            non_prouves.append({"tool": tool, "etat_preuve": etat,
                                "raison": "capacite declaree, aucune preuve d'usage (DECLARED != INVOCABLE)"})
    for m in sorted(allowed - tools_crosswalk):
        non_prouves.append({"method": m, "etat_preuve": "DECLARED",
                            "raison": "dans ALLOWED_METHODS mais absente du crosswalk (aucune preuve d'usage)"})
    return {
        "genere_par": "tools/forge_capability_crosswalk.actions_prouvees",
        "actions": actions,
        "non_planifiables": non_planifiables,
        "non_prouves": non_prouves,
        "resume": {
            "n_actions": len(actions),
            "n_non_planifiables": len(non_planifiables),
            "n_non_prouves": len(non_prouves),
            "recouvrement": "%d/%d de la whitelist prouves+planifiables" % (len(actions), len(allowed)),
        },
        "angles_morts": [
            "INVOCABLE = un appel a reussi AU GEL du socle ; pas une garantie presente (STALE possible).",
            "non_planifiables = dette de vascularisation : outils prouves que le planner ne lit pas encore.",
            "sans contracts, preconditions/effets valent UNKNOWN -- absence de mesure, pas absence d'effet.",
        ],
    }


def annotation_preference(methods_available, allowed_methods, stats) -> str:
    """Suffixe de prompt ADVISOIRE : vascularisation du joint vers le planificateur GOAP.

    Parmi les methodes DEJA planifiables (`methods_available`), marque celles PROUVEES par l'usage en
    trajectoire -- succes EFFECTIFS (count x taux), pas simples tentatives -- via `actions_prouvees`.
    `stats` = `forge_trajectory.analyze_trajectories()['method_stats']` (par methode : count + taux).
    PREFERENCE, jamais restriction : aucune methode n'est retiree ; l'inconnu reste disponible, non marque.
    Rend "" si rien n'est prouve (prompt inchange = comportement actuel preserve). Fonction pure.
    """
    dispo = set(methods_available or ())
    succes, caps = {}, []
    for m, v in (stats or {}).items():
        if m not in dispo:
            continue
        s = int(round(float(v.get("count", 0)) * float(v.get("success_rate", 0))))
        if s <= 0:  # tente sans jamais reussir != prouve (une abstention n'est pas un acte)
            continue
        succes[m] = s
        caps.append({"tool": m, "calls_au_gel": s, "tests": []})
    if not caps:
        return ""
    joint = actions_prouvees({"capacites": caps}, {m: (allowed_methods or {}).get(m, {}) for m in dispo})
    prouvees = sorted((a["tool"] for a in joint.get("actions", [])), key=lambda m: -succes.get(m, 0))
    if not prouvees:
        return ""
    liste = ", ".join("%s(%d)" % (m, succes[m]) for m in prouvees)
    return ("\n\nPREFERENCE -- methodes EPROUVEES par l'usage (succes en trajectoire entre parentheses) : "
            + liste + ".\nA qualite egale, prefere-les ; tu PEUX employer les autres methodes autorisees si "
            "la tache l'exige. Cette liste oriente, elle ne restreint pas.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Crosswalk CAP-* : capacite -> module -> ring -> test -> commit")
    ap.add_argument("--lignee", action="store_true", help="ajoute historical_proof (git -S, couteux)")
    ap.add_argument("--top", type=int, default=0, help="avec --lignee : limite aux N plus appelees")
    ap.add_argument("--trous", action="store_true", help="ne sortir que les capacites a trou")
    ap.add_argument("--out", default="", help="ecrire le JSON dans ce fichier")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args()

    rap = croiser(lignee=ns.lignee, top=ns.top)
    if ns.trous:
        rap["capacites"] = [x for x in rap["capacites"] if x["trous"]]
    if ns.out:
        with open(ns.out, "w", encoding="utf-8") as f:
            json.dump(rap, f, ensure_ascii=False, indent=1)
        print(f"[crosswalk] ecrit -> {ns.out}")
    if ns.json:
        print(json.dumps(rap, ensure_ascii=False, indent=1))
    else:
        resume = {k: v for k, v in rap.items() if k not in ("capacites", "angles_morts")}
        print(json.dumps(resume, ensure_ascii=False, indent=1))
        for x in rap["capacites"][:20]:
            print("  %-22s %-12s ring=%-4s tests=%-2d %s" % (
                x["id"], x["tier"], x["reachable_from"]["ring_min"], len(x["tests"]),
                ",".join(x["trous"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
