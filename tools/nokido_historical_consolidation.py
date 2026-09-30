#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/nokido_historical_consolidation.py

Implémente la conception Historical Consolidation.
4 arrimages anti-dup :
1. forge_generation pour les GEN-XXX
2. forge_merge_gate pour le juge (verdict AMELIORE)
3. forge_worktree pour le bac à sable éphémère (sans clone)
4. forge_capability_recovery pour le rejeu (avec filtre est_offensif)
"""
import os
import sys
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_generation import lister as lister_gen, derniere_stable
from nokido_agent.tools.forge_worktree import create as wt_create, route as wt_route
from nokido_agent.tools.forge_capability_recovery import recuperer
from nokido_agent.tools.forge_capability_consolidation import est_offensif
from nokido_agent.tools.forge_merge_gate import evaluer

def report():
    print("NOKIDO HISTORICAL CONSOLIDATION")
    print("===============================\n")

    try:
        gens = lister_gen("stable")
        stable = derniere_stable()
        if stable:
            print(f"Current generation: {stable.get('nom', 'GEN-UNKNOWN')}")
            print(f"Stable baseline: SHA {stable.get('commit', 'UNKNOWN')[:8]}\n")
            
        print("Historical states:")
        for g in gens[-3:]:
            print(f"  {g.get('nom', '')} (SHA: {g.get('commit', '')[:8]})")
        print()
    except Exception as e:
        print(f"Erreur lecture generations: {e}")

    print("Lost capabilities:")
    CENSUS = ROOT / "sandbox" / "history_census.json"
    if not CENSUS.exists():
        print("  Aucun census (history_census.json absent). Lancez forge_history_census.py")
        return

    census = json.load(open(CENSUS, encoding="utf-8"))
    candidats = []
    for nom, d in census.get("depots", {}).items():
        if "erreur" in d: continue
        for perdu in d.get("morts_reelles", []):
            if perdu.get("churn", 0) >= 2:
                candidats.append((perdu.get("churn", 0), nom, d["chemin"], perdu))
    
    candidats.sort(reverse=True, key=lambda x: x[0])
    candidats_safes = [c for c in candidats if not (est_offensif(c[3]["chemin"]) or est_offensif(c[1]))]

    if not candidats_safes:
        print("  Aucune capacite candidate.\n")
        return

    WT_AGENT = "recovery"
    wt_create(WT_AGENT)
    wt_chemin = wt_route(WT_AGENT)
    
    # Detach wt from any uncommitted changes just in case
    subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=wt_chemin, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    recommended = []
    
    # Test top 3 capabilities
    for _, depot_nom, depot_chemin, perdu in candidats_safes[:3]:
        nom_cap = os.path.basename(perdu["chemin"])
        print(f"* capability {nom_cap}")
        
        try:
            fiche, source = recuperer(depot_nom, depot_chemin, perdu)
            sha_suppr = fiche.get("sha_suppression") or "UNKNOWN"
            print(f"  best_known: SHA {sha_suppr[:8]}")
        except Exception as e:
            print(f"  best_known: ERREUR ({e})")
            print()
            continue

        if not source:
            print(f"  current: absent")
            print(f"  recoverability: LOW (Source introuvable)")
            print()
            continue

        # Application au worktree ephemere
        target_path = Path(wt_chemin) / perdu["chemin"]
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(source, encoding="utf-8")
        
        subprocess.run(["git", "add", perdu["chemin"]], cwd=wt_chemin, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "commit", "--no-verify", "-m", f"recovery test: {nom_cap}"], cwd=wt_chemin, stdout=subprocess.DEVNULL)
        
        # Juge (Brique 2)
        ev = evaluer(WT_AGENT)
        verdict = ev.get("verdict", "INCONNU")
        
        print(f"  evidence: {verdict} ({ev.get('pourquoi', '')})")
        if verdict == "AMELIORE":
            print(f"  current: degraded")
            print(f"  recoverability: HIGH")
            recommended.append(nom_cap)
        elif verdict == "EGAL":
            print(f"  current: absent")
            print(f"  recoverability: MEDIUM")
        else:
            print(f"  current: rejected")
            print(f"  recoverability: LOW")
        print()
        
        # Nettoyage worktree ephemere (reset au commit d'origine)
        subprocess.run(["git", "reset", "--hard", "HEAD~1"], cwd=wt_chemin, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "clean", "-fd"], cwd=wt_chemin, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("Recommended recoveries:")
    if recommended:
        for i, r in enumerate(recommended, 1):
            print(f"{i}. {r}")
    else:
        print("  Aucune recuperation AMELIORE recommandee.")

if __name__ == "__main__":
    report()
