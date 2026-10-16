#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_banc_collectif.py -- l'intelligence COLLECTIVE se mesure : equipe contre modele seul, a budget egal.

POURQUOI (owner 15/10, choix multiple « Banc d'abord, puis mode revue » ; audit ChatGPT : « il a acces a plein
de LLM mais sa puissance n'est pas cumulative ? »). On ne decide pas qu'une equipe de modeles vaut mieux qu'un
seul : on le MESURE sur un jeu FIGE, verifie par des tests REELS, a budget d'appels EGAL.

CE QU'IL REUTILISE (aucun moteur neuf) : tools/forge_humaneval_runner.run -- generation, auto-correction
HONNETE (doctests + auto-tests ecrits sans la solution), escalade multi-modeles, verdict final UNIQUE sur les
tests d'evaluation, JSON par execution. Ce module ne fait que composer deux bras et les comparer.

LES BRAS (meme sous-ensemble, meme budget maximal d'appels par tache = 1 + B) :
  seul   : fournisseur P, self_repair = B           (le meilleur modele, qui se corrige lui-meme)
  equipe : fournisseur P, self_repair = B - k, escalate = Q1..Qk  (la correction passe par d'AUTRES modeles)
VERDICT : pass_rate des deux bras, gain en points, taches SAUVEES par l'equipe et taches PERDUES (regressions),
appels reels, latence -- denominateurs toujours declares. Un gain sous la variance d'echantillon est dit tel.

Usage :
    run_job script=tools/forge_banc_collectif.py online=true script_args="--seul groq --equipe openrouter,nvidia --taches 40 --budget 2"
Sortie : RAG/humaneval/banc_collectif_<seul>_vs_<equipe>_<N>_<date>.json
"""
from __future__ import annotations

__FORGE_COLOR__ = "cognition/fitness : banc collectif, equipe de modeles contre modele seul a budget egal"

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def comparer(seul: dict, equipe: dict) -> dict:
    """Compare deux resumes de run() sur le MEME sous-ensemble. Pur, testable sans reseau."""
    rs = {r["task_id"]: r for r in seul.get("results") or []}
    re_ = {r["task_id"]: r for r in equipe.get("results") or []}
    # Une erreur de TRANSPORT (`llm_error` : quota, debit, reseau) n'est pas un echec du modele : INCONNU. La compter
    # « ratee » fabriquait un faux gain -- mesure 15/10 au banc 164 : groq a rendu 60 llm_error d'affilee a partir
    # de la tache 98, chacune serait devenue une tache « sauvee par l'equipe ». On l'ecarte des DEUX bras, et on le dit.
    transport = sorted(t for t in set(rs) & set(re_)
                       if "llm_error" in (rs[t].get("reason"), re_[t].get("reason")))
    communs = sorted(set(rs) & set(re_) - set(transport))
    n = len(communs)
    ps = sum(1 for t in communs if rs[t]["pass"])
    pe = sum(1 for t in communs if re_[t]["pass"])
    sauvees = [t for t in communs if re_[t]["pass"] and not rs[t]["pass"]]
    perdues = [t for t in communs if rs[t]["pass"] and not re_[t]["pass"]]
    appels = {nom: sum(1 + int(r.get("repairs") or 0) for t, r in d.items() if t in communs)
              for nom, d in (("seul", rs), ("equipe", re_))}
    taux = (lambda k: round(100.0 * k / n, 1) if n else None)
    gain = (taux(pe) - taux(ps)) if n else None
    # Ecart-type d'une difference de proportions appariees, approx. sur les discordants (test de McNemar).
    discordants = len(sauvees) + len(perdues)
    bruit = round(100.0 * math.sqrt(discordants) / n, 1) if n else None
    if not n:
        verdict = "INCONNU : aucune tache commune aux deux bras hors erreurs de transport (%d)" % len(transport)
    elif discordants == 0:
        verdict = "AUCUN ECART : les deux bras reussissent et echouent sur les memes taches"
    elif abs(gain) <= bruit:
        verdict = "ECART SOUS LE BRUIT (%+.1f pts, bruit ~%.1f) : rien de prouve" % (gain, bruit)
    else:
        verdict = ("GAIN COLLECTIF MESURE (%+.1f pts)" if gain > 0 else "PERTE COLLECTIVE MESUREE (%+.1f pts)") % gain
    return {"taches_communes": n, "hors_mesure_transport": transport, "reussites": {"seul": ps, "equipe": pe},
            "pass_rate": {"seul": taux(ps), "equipe": taux(pe)}, "gain_points": gain, "bruit_points": bruit,
            "sauvees_par_equipe": sauvees, "perdues_par_equipe": perdues, "appels": appels,
            "latence_s": {"seul": seul.get("elapsed_s"), "equipe": equipe.get("elapsed_s")}, "verdict": verdict}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Banc collectif : equipe de modeles contre modele seul, budget egal")
    ap.add_argument("--seul", required=True, help="fournisseur du bras seul (et generateur du bras equipe)")
    ap.add_argument("--equipe", required=True, help="fournisseurs de correction du bras equipe (CSV)")
    ap.add_argument("--taches", type=int, default=40)
    ap.add_argument("--budget", type=int, default=2, help="corrections maximales par tache (B)")
    a = ap.parse_args(argv)
    escalade = [p.strip() for p in a.equipe.split(",") if p.strip() and p.strip() != a.seul]
    if not escalade:
        print("[banc] equipe vide (ou identique au bras seul) : rien a comparer")
        return 2
    if a.budget < len(escalade):
        print("[banc] budget %d < %d correcteurs : budget porte a %d pour rester EGAL entre les bras"
              % (a.budget, len(escalade), len(escalade)))
        a.budget = len(escalade)
    import forge_humaneval_runner as he

    stamp = time.strftime("%Y%m%d-%H%M")
    print("[banc] bras SEUL : %s, self_repair=%d, %d taches" % (a.seul, a.budget, a.taches), flush=True)
    seul = he.run(provider=a.seul, max_entries=a.taches, self_repair=a.budget, tag="banc_seul_" + stamp)
    print("[banc] bras EQUIPE : %s + %s, self_repair=%d" % (a.seul, ",".join(escalade), a.budget - len(escalade)),
          flush=True)
    equipe = he.run(provider=a.seul, max_entries=a.taches, self_repair=max(0, a.budget - len(escalade)),
                    escalate=",".join(escalade), tag="banc_equipe_" + stamp)
    comp = comparer(seul, equipe)
    rapport = {"banc": "collectif", "date": stamp, "seul": a.seul, "equipe": [a.seul] + escalade,
               "budget_par_tache": 1 + a.budget, "comparaison": comp}
    out = he.HE_DIR / ("banc_collectif_%s_vs_%s_%d_%s.json" % (a.seul, "-".join(escalade), a.taches, stamp))
    out.write_text(json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[banc] %s | seul %s %% (%s/%s) | equipe %s %% | sauvees %d, perdues %d | appels %s"
          % (comp["verdict"], comp["pass_rate"]["seul"], comp["reussites"]["seul"], comp["taches_communes"],
             comp["pass_rate"]["equipe"], len(comp["sauvees_par_equipe"]), len(comp["perdues_par_equipe"]),
             comp["appels"]), flush=True)
    print("[banc] rapport : %s" % out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
