# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "cognition/fitness"
FITNESS COGNITIVE — mesurer COMMENT le systeme raisonne, pas seulement s'il
finit par tomber juste.

LE PROBLEME QUE CA COUVRE
=========================
Un systeme peut garder 100 % de ses outils et devenir moins intelligent dans leur
usage. Deux executions qui rendent toutes deux SUCCESS :

    A : 8 etapes, 3 outils, 1 correction, 1 verification
    B : 31 appels, 12 inutiles, 4 mauvaises hypotheses, 2 retries

Les benchmarks de SORTIE (HumanEval, BFCL, SWE) donnent le meme verdict aux deux.
La regression cognitive est invisible pour eux — c'est precisement le trou.

PREREQUIS, REPARE LE 2026-08-14
===============================
Cette mesure ne valait rien avant ce jour : les 41 714 trajectoires portaient
toutes le trace_id litteral `[REDACTED:key]` (le DLP caviardait l'identifiant de
correlation, un hex de 32 etant lu comme une cle) et `args` etait vide sur 100 %
des lignes (les arguments vivent sur la ligne IN que le sidecar ignorait). Sans
groupement, tout score de raisonnement aurait ete INVENTE.

On ne mesure donc QUE les trajectoires reellement correlables, et le
denominateur est TOUJOURS declare — un pourcentage sans son denominateur a deja
coute assez cher ici.

LA METRIQUE
===========
    efficacite = 100 x taux_succes x (1 - taux_retry)

Elle baisse si le systeme reussit moins, ET si le systeme tourne en rond pour le
meme resultat. C'est le `goal_achievement / reasoning_cost` sous une forme bornee
et comparable dans le temps. Elle est ecrite au format des autres benchmarks
(`pass_rate`), donc `pat_eval_fitness` la compare AUTOMATIQUEMENT au dernier
releve et ecrit une proposal si elle chute de plus de 5 points. Aucun nouveau
mecanisme de detection : on se branche sur celui qui existe.

    LAFORGE_PYTHON tools/forge_cognitive_fitness.py            # affiche
    LAFORGE_PYTHON tools/forge_cognitive_fitness.py --emit     # ecrit le releve
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACES = ROOT / "RAG" / "execution_traces.db"
SORTIE = ROOT / "RAG" / "cognitive"

# Un trace_id non correlable : on ne peut RIEN en dire, on l'ecarte et on le
# compte (jamais de silence sur ce qui a ete jete).
_NON_CORRELABLES = ("system", "")


def _acteurs() -> set:
    """Identites qui DECIDENT (kind=cli_agent au registre), en majuscules.

    PREMIERE MESURE, 2026-08-14 : sans ce filtre, l'efficacite tombait a 14,78 %
    avec 85,22 % de « retry » — alors que le succes etait de 100 %. Ce n'etait
    pas un raisonnement qui tourne en rond : c'etait le POLLING des daemons
    (STATE_ENCODER rappelant `run` toutes les dix secondes). Compter une boucle
    de surveillance comme une hesitation cognitive produit un chiffre faux, et
    un chiffre faux publie vaut moins que pas de chiffre du tout.

    Le registre d'identites (schema 2+) porte deja la distinction : `kind`.
    Fail-closed : registre illisible -> aucun acteur -> INDETERMINE, jamais une
    mesure calculee sur n'importe qui.
    """
    try:
        reg = json.loads((ROOT / "config" / "agent_identities.json")
                         .read_text(encoding="utf-8"))
        return {n.upper() for n, e in (reg.get("agents") or {}).items()
                if e.get("kind") == "cli_agent"}
    except Exception as e:  # noqa: BLE001
        print(f"[cognitif] registre d'identites ILLISIBLE ({type(e).__name__}) | "
              f"consequence: impossible de distinguer un agent qui raisonne d'un "
              f"daemon qui sonde", flush=True)
        return set()


def _trajectoires(fenetre_h: float) -> tuple[dict, dict]:
    """({trace_id: [actions]}, angles_morts). Chaque action = (tool, success)."""
    depuis = time.time() - fenetre_h * 3600
    acteurs = _acteurs()
    groupes: dict = {}
    ecartes = 0
    hors_acteurs = 0
    total = 0
    con = sqlite3.connect(f"file:{TRACES.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        for r in con.execute(
            "SELECT trace_id, action_json, success FROM traces WHERE ts > ? ORDER BY ts",
            (depuis,),
        ):
            total += 1
            tid = (r["trace_id"] or "").strip()
            if tid in _NON_CORRELABLES or tid.startswith("[REDACTED"):
                ecartes += 1
                continue
            try:
                a = json.loads(r["action_json"] or "{}")
            except Exception:  # noqa: BLE001
                a = {}
            if str(a.get("agent") or "").upper() not in acteurs:
                hors_acteurs += 1        # daemon, service, hook : pas un raisonnement
                continue
            groupes.setdefault(tid, []).append(
                (str(a.get("tool") or "?"), int(r["success"] or 0))
            )
    finally:
        con.close()
    return groupes, {"lignes_vues": total, "ecartees_non_correlables": ecartes,
                     "ecartees_hors_acteurs": hors_acteurs,
                     "acteurs_connus": len(acteurs)}


def mesurer(fenetre_h: float = 24.0) -> dict:
    groupes, angles = _trajectoires(fenetre_h)
    n_traj = len(groupes)
    if not n_traj:
        # Aucune trajectoire = AUCUNE mesure. Surtout pas un score de 0, qui se
        # lirait comme un effondrement cognitif alors qu'on n'a rien observe.
        return {"etat": "INDETERMINE", "raison": "aucune trajectoire correlable",
                **angles, "fenetre_h": fenetre_h}

    etapes, succes, retries, total_actions = [], 0, 0, 0
    for _tid, actions in groupes.items():
        etapes.append(len(actions))
        precedent = None
        for tool, ok in actions:
            total_actions += 1
            succes += ok
            if precedent is not None and tool == precedent:
                retries += 1       # meme outil deux fois de suite = on repasse
            precedent = tool

    taux_succes = succes / total_actions
    taux_retry = retries / total_actions
    efficacite = 100.0 * taux_succes * (1.0 - taux_retry)
    return {
        "etat": "MESURE",
        "pass_rate": round(efficacite, 2),          # nom attendu par l'adapter
        "taux_succes_pct": round(100 * taux_succes, 2),
        "taux_retry_pct": round(100 * taux_retry, 2),
        "trajectoires": n_traj,
        "actions": total_actions,                    # LE denominateur, toujours
        "etapes_medianes": statistics.median(etapes),
        "etapes_max": max(etapes),
        "fenetre_h": fenetre_h,
        **angles,
    }


def emettre(fenetre_h: float = 24.0) -> dict:
    m = mesurer(fenetre_h)
    if m.get("etat") != "MESURE":
        return m        # on n'ecrit RIEN sans mesure : pas de faux releve
    SORTIE.mkdir(parents=True, exist_ok=True)
    f = SORTIE / f"cognitive_{time.strftime('%Y%m%d_%H%M%S')}.json"
    f.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    m["_fichier"] = str(f)
    return m


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--fenetre-h", type=float, default=24.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    m = emettre(a.fenetre_h) if a.emit else mesurer(a.fenetre_h)
    if a.json:
        print(json.dumps(m, ensure_ascii=False, indent=2))
        return 0 if m.get("etat") == "MESURE" else 2
    if m.get("etat") != "MESURE":
        print(f"[cognitif] INDETERMINE — {m.get('raison')} "
              f"({m.get('lignes_vues', 0)} lignes vues, "
              f"{m.get('ecartees_non_correlables', 0)} ecartees)")
        return 2
    print(f"[cognitif] efficacite {m['pass_rate']} % "
          f"(succes {m['taux_succes_pct']} %, retry {m['taux_retry_pct']} %)")
    print(f"   {m['trajectoires']} trajectoire(s) / {m['actions']} action(s) "
          f"sur {m['fenetre_h']} h — mediane {m['etapes_medianes']} etapes, "
          f"max {m['etapes_max']}")
    if m.get("ecartees_non_correlables"):
        print(f"   ecartees non correlables : {m['ecartees_non_correlables']} "
              f"/ {m['lignes_vues']} (trace_id absent ou caviarde)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
