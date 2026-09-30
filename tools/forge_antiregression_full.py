#!/usr/bin/env python3
"""forge_antiregression_full.py — LA passe. Tous les axes, tout le depot.

Quatre outils existent, chacun aveugle a ce que les autres voient :

  1. `forge_fix_sentinel`      ancre disparue d'un .py existant
  2. `forge_hollow_sentinel`   fonction creuse : le nom reste, le corps est parti
  3. `forge_regression_sweep`  valeur abaissee / config desactivee / import orphelin

Les lancer separement produit quatre rapports qu'il faut recouper a la main, et
un lecteur retient le dernier incident cite plutot que l'etat du systeme. Ce
module ne REFAIT aucun detecteur : il les appelle et consolide PAR
FONCTIONNALITE, parce que la question posee n'est pas « quel commit a fauté »
mais « qu'est-ce qui, dans ce que nous avons construit, ne marche plus ».

Regle de lecture, valable pour chaque axe : un candidat n'est pas une
regression. Les mesures du 2026-08-14 sont sans appel — 118 pertes sur 154
etaient des modules deplaces, 35 orphelins sur 35 des packages, 5 fonctions
creuses sur 5 des vides assumes. Un rapport qui ne separe pas le CANDIDAT du
CONFIRME ment par construction. Chaque axe rend donc ses deux chiffres.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))
OUT = ROOT / "sandbox" / "antiregression_full.json"
DEPUIS = "2026-03-01"

DOMAINES = {
    "docker_keeper": "docker", "ensure_service": "docker", "docker_monitor": "docker",
    "llama_proxy": "llm local", "llamacpp": "llm local", "demand_proxy": "llm local",
    "llm_router": "routage llm", "agent_proxy": "routage llm",
    "ghost_router": "routage llm", "collab_modes": "routage llm",
    "rag_engine": "rag", "rag_store": "rag", "rebuild_local": "rag",
    "auto_compact": "rag", "embed_router": "rag", "embed_auto_trigger": "rag",
    "renal_clearance": "rag",
    "ssh": "acces distant", "pty": "acces distant",
    "orchestrator": "orchestration", "swarm": "orchestration", "handoff": "orchestration",
    "autonomous_loops": "autonomie", "regulation_loops": "autonomie",
    "resource_manager": "autonomie", "auto_pilot": "autonomie",
    "semantic_firewall": "securite", "integrity": "securite", "videur": "securite",
    "swebench_runner": "benchmarks", "dpo_extractor": "benchmarks",
    "mcp_stdio_bridge": "hub/mcp", "nokido_hub": "hub/mcp", "mcp_registry": "hub/mcp",
}


def _domaine(chemin: str) -> str:
    tige = Path(chemin).stem.replace("forge_", "")
    if tige in DOMAINES:
        return DOMAINES[tige]
    for cle, dom in DOMAINES.items():
        if cle in tige:
            return dom
    tete = chemin.split("/")[0]
    return {"app": "app (divers)", "tools": "outils (divers)",
            "forge_desktop": "ui desktop"}.get(tete, tete)


def _assume(sujet: str) -> bool:
    """Le commit ANNONCE-t-il la suppression ? Alors ce n'est pas une perte.

    On ne se fie au message que pour DISCULPER, jamais pour accuser : un sujet
    qui dit « retire xAI » prouve l'intention, un sujet anodin ne prouve rien.
    """
    s = (sujet or "").lower()
    # Vocabulaire ETABLI PAR MESURE (14/08) : les termes ci-dessous sont ceux
    # que ce depot emploie reellement quand il assume une suppression. Sans eux,
    # 12 refactors declares — CSP centralisee dans csp.py, ErrorManager dedup
    # par re-export, brain worker parke — ressortaient comme des regressions,
    # alors que la fonctionnalite a ete VERIFIEE presente sous une autre forme.
    return any(m in s for m in ("revert", "supprime", "retire", "drop", "remove",
                                "cleanup", "shim", "deprecat", "abandon",
                                "strip", "rename", "cutover",
                                "dedup", "re-export", "reexport", "centralis",
                                "desarmer", "park ", "parke", "fusion",
                                "unifi", "migration", "refonte"))


def main() -> int:
    t0 = time.time()
    from nokido_agent.tools import forge_fix_sentinel as A
    from nokido_agent.tools import forge_hollow_sentinel as B
    from nokido_agent.tools import forge_regression_sweep as C

    bilan: dict[str, dict] = {}

    # Les PIECES, pas seulement le compte : un bilan qui dit « rag : 4 » sans
    # nommer lesquelles se lit, s'inquiete, et ne permet aucune action. C'est le
    # defaut qu'on reproche aux catalogues.
    pieces: list[dict] = []

    def poser(domaine: str, axe: str, confirme: bool, quoi: str = "",
              ou: str = "", par: str = "") -> None:
        d = bilan.setdefault(domaine, {})
        e = d.setdefault(axe, {"candidats": 0, "confirmes": 0})
        e["candidats"] += 1
        e["confirmes"] += 1 if confirme else 0
        if confirme:
            pieces.append({"domaine": domaine, "axe": axe, "quoi": quoi,
                           "ou": ou, "supprime_par": par})

    print(f"[full] axe 1/5 — ancres perdues (depuis {DEPUIS})", flush=True)
    anc = A.scanner(limit=5000, depuis=DEPUIS)
    # Le sujet porte par `perdus` est celui du commit qui a INTRODUIT l'ancre :
    # le juger revient a demander a un `feat` d'annoncer une suppression qu'il
    # n'a pas faite. Seul le commit SUPPRESSEUR, retrouve au pickaxe, porte
    # l'intention — c'est lui qui disculpe (`refactor: llama_proxy becomes
    # shim` assume ses 6 pertes ; sans ce pickaxe elles ressortaient toutes).
    print(f"[full]   ... pickaxe sur {len(anc['perdus'])} pertes pour "
          f"retrouver QUI a supprime", flush=True)
    for p in anc["perdus"]:
        brut = C._git("log", "--format=%s", "-S", p["ancre"], "--",
                      p["fichier"]).strip().splitlines()
        sujet_supprimeur = brut[0] if brut else ""
        poser(_domaine(p["fichier"]), "ancre_perdue", not _assume(sujet_supprimeur),
              quoi=p["ancre"], ou=p["fichier"], par=sujet_supprimeur[:70])

    print("[full] axe 2/5 — fonctions creuses", flush=True)
    for c in B.scanner():
        # Une fonction qui DECLARE son vide dans sa docstring est un stub assume.
        aveu = any(m in c["promesse"].lower()
                   for m in ("non implement", "not implemented", "scaffold",
                             "n'est pas possible", "stub"))
        poser(_domaine(c["fichier"]), "fonction_creuse", not aveu,
              quoi=c["fonction"] + "()", ou=f"{c['fichier']}:{c['ligne']}",
              par=c["promesse"][:70])

    print("[full] axe 3/5 — imports orphelins", flush=True)
    for o in C.axe_imports_orphelins():
        poser(_domaine(o["fichier"]), "import_orphelin", True,
              quoi=o["importe"], ou=f"{o['fichier']}:{o['ligne']}")

    print("[full] axes 4-5/5 — valeurs abaissees et config desactivee", flush=True)
    valeurs, configs = C.axe_valeur_et_config(C._commits())
    for v in valeurs:
        actuel = C._valeur_actuelle(v["fichier"], v["nom"])
        n = C._nombre(actuel or "")
        if actuel is None or (v["type"] == "SEUIL_ABAISSE" and n is not None
                              and n >= v["avant"]):
            continue                      # corrige depuis, ou symbole parti
        poser(_domaine(v["fichier"]), "valeur_affaiblie", not _assume(v["sujet"]),
              quoi=f"{v['nom']} {v['avant']} -> {v['apres']}", ou=v["fichier"],
              par=f"{v['sha']} {v['sujet'][:60]}")
    for cf in configs:
        poser(_domaine(cf["fichier"]), "config_desactivee", not _assume(cf["sujet"]),
              quoi=f"{cf['cle']} {cf['avant']} -> {cf['apres']}", ou=cf["fichier"],
              par=f"{cf['sha']} {cf['sujet'][:60]}")

    total_c = sum(e["candidats"] for d in bilan.values() for e in d.values())
    total_v = sum(e["confirmes"] for d in bilan.values() for e in d.values())
    res = {"depuis": DEPUIS, "commits": anc["commits_examines"],
           "ancres_suivies": anc["ancres_suivies"], "duree_s": round(time.time() - t0, 1),
           "total_candidats": total_c, "total_confirmes": total_v,
           "par_domaine": bilan, "pieces": pieces}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[full] {anc['commits_examines']} commits, {anc['ancres_suivies']} ancres, "
          f"{res['duree_s']} s", flush=True)
    print(f"[full] {total_c} candidats -> {total_v} NON assumes\n", flush=True)
    print(f"{'domaine':22s} {'axe':20s} {'cand.':>6s} {'non assumes':>12s}", flush=True)
    for dom in sorted(bilan, key=lambda d: -sum(e["confirmes"] for e in bilan[d].values())):
        for axe, e in sorted(bilan[dom].items(), key=lambda kv: -kv[1]["confirmes"]):
            marque = "  <<<" if e["confirmes"] else ""
            print(f"{dom:22s} {axe:20s} {e['candidats']:6d} {e['confirmes']:12d}{marque}",
                  flush=True)
    print("\n[full] PIECES AU DOSSIER (non assumees) :", flush=True)
    for pc in pieces:
        print(f"   {pc['domaine']:16s} {pc['axe']:18s} {pc['quoi'][:44]:44s} "
              f"{pc['ou'][:44]}", flush=True)
        if pc["supprime_par"]:
            print(f"       supprime par : {pc['supprime_par']}", flush=True)
    print(f"\n[full] -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
