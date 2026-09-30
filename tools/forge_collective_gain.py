#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_collective_gain.py — ce que le collectif APPORTE, et ce qu'il RETIRE.

L'APPELANT qui manquait. Mesure du 2026-08-26 : Nokido portait deja tout l'appareil
d'une intelligence collective — `forge_swarm_router.route_swarm` (politiques, fanout
1/2/3/5, angles, voix INDEPENDANTES, porte deterministe), `forge_swarm_evidence.arbitrer`,
`forge_debate_roles` — et ces trois organes n'avaient AUCUN appelant hors de leur propre
fichier. Un allocateur qui ne tourne pas n'alloue rien.

CE QUI EST MESURE, ET POURQUOI PAS AUTRE CHOSE
==============================================
La question utile n'est pas « plusieurs LLM sont-ils meilleurs qu'un » mais « ce que ce
fanout apporte vaut-il ce qu'il coute, sur CETTE tache ». Trois choix la rendent
mesurable sans banc a construire :

1. LA PREUVE, PAS UN JUGE. Le score vient de l'execution des tests unitaires de la tache
   (`forge_humaneval_runner._run_tests`), jamais d'un LLM notant un LLM. Un panel
   GENERE, il ne VALIDE pas — et la sycophancy du juge est l'un des deux modes de
   defaillance mesures du debat multi-agents (cf. `forge_debate_roles`).
2. LES BASELINES SONT DANS LE FANOUT. Chaque tentative est un agent seul, deja paye :
   relancer la tache en `single` pour obtenir un `best_single` doublerait la facture
   pour une information qu'on tient deja. `gain_collectif` lit donc l'oracle (la
   meilleure tentative) ET le moyen (l'esperance d'un agent tire au hasard).
3. LE CAS NEGATIF EST UN RESULTAT. `degrade=True` — la bonne reponse etait la, le
   collectif ne l'a pas prise — se compte, se journalise et se rapporte comme le reste.
   C'est ce que la litterature dit central et que personne ne mesure chez soi.

CE QUE CET OUTIL NE FAIT PAS : il ne note pas la qualite d'une prose, il ne classe pas
des modeles, il ne remplace aucun banc. Il repond a une question de rendement sur une
tache dont la reussite est VERIFIABLE par execution.

Usage (leger par defaut : 3 taches) :
    LAFORGE_PYTHON tools/forge_collective_gain.py --n 3 --politique incertain
    run action=run_job script=tools/forge_collective_gain.py online=true
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

__FORGE_COLOR__ = "cognition/rendement-collectif"  # ce que coute une intelligence de plus

SORTIE = ROOT / "RAG" / "benchmark_results"


def verificateur_humaneval(entry: dict):
    """(texte du LLM) -> (reussi, preuves). La porte DETERMINISTE.

    Trois etapes, chacune deja ecrite dans le harnais HumanEval : extraire le corps,
    verifier qu'il COMPILE, puis executer les tests unitaires de la tache dans un
    processus borne. Une exception du harnais lui-meme rend `None` — non mesure — et
    non `False` : un outil casse n'est pas une mauvaise reponse.
    """
    from nokido_agent.tools import forge_humaneval_runner as HE

    def _verifier(texte: str):
        try:
            code = HE._extract_code(texte or "", entry)
            if not code.strip():
                return False, ["aucun code extrait de la reponse"]
            if not HE._compiles(entry, code):
                return False, ["le code ne compile pas"]
            ok, msg = HE._run_tests(entry, code)
            return bool(ok), [("tests unitaires OK" if ok else "tests unitaires KO: %s"
                               % str(msg)[:160])]
        except Exception as exc:  # noqa: BLE001 — le harnais a echoue, pas la reponse
            raise RuntimeError("verificateur indisponible: %s" % type(exc).__name__) from exc

    return _verifier


def mesurer(n: int = 3, politique: str = "incertain", agent: str = "CLAUDE",
            token: str = "", use_case: str = "code") -> dict:
    """Lance n taches reelles et rend l'agregat. Aucune moyenne sans denominateur."""
    from nokido_agent.tools import forge_humaneval_runner as HE
    from nokido_agent.app.forge_swarm_router import route_swarm

    entries = HE.ensure_dataset()
    if not entries:
        return {"erreur": "dataset HumanEval indisponible (reseau requis au premier appel)"}
    sujets = entries[:max(1, n)]
    SORTIE.mkdir(parents=True, exist_ok=True)
    horodate = datetime.now().strftime("%Y%m%d_%H%M%S")
    journal = SORTIE / ("collective_gain_%s.jsonl" % horodate)

    lignes, refus_videur = [], 0
    for entry in sujets:
        prompt = HE._build_prompt(entry)
        t0 = time.time()
        try:
            res = route_swarm(agent_cible=agent, task_prompt=prompt, politique=politique,
                              token=token, use_case=use_case,
                              verificateur=verificateur_humaneval(entry), max_tokens=1024)
        except Exception as exc:  # noqa: BLE001
            res = {"status": "error", "reason": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
        if res.get("status") == "error" and "Videur" in str(res.get("reason", "")):
            refus_videur += 1
        ligne = {
            "tache": entry.get("task_id"),
            "politique": politique, "mode": res.get("mode"),
            "etat": res.get("etat"), "action": res.get("action"),
            "motif": res.get("motif") or res.get("reason"),
            "cout": res.get("cout"), "gain": res.get("gain"),
            "voix_independantes": res.get("voix_independantes"),
            "preuves_deterministes": res.get("preuves_deterministes"),
            "tentatives": res.get("tentatives"),
            "duree_s": round(time.time() - t0, 1),
        }
        lignes.append(ligne)
        with journal.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        print("[%s] etat=%s gain_vs_moyen=%s degrade=%s cout=%s" % (
            ligne["tache"], ligne["etat"],
            (ligne["gain"] or {}).get("gain_vs_moyen"),
            (ligne["gain"] or {}).get("degrade"),
            (ligne["cout"] or {}).get("tokens")), flush=True)
    return {"agregat": agreger(lignes, refus_videur), "journal": str(journal)}


def agreger(lignes: list, refus_videur: int = 0) -> dict:
    """L'agregat DIT sur quoi il porte. Une moyenne sur les seules taches mesurees,
    presentee sans son denominateur, ferait passer 2 succes sur 20 essais pour 100 %."""
    gains = [ligne.get("gain") or {} for ligne in lignes]
    mesures = [g for g in gains if g.get("gain_vs_moyen") is not None]
    degrades = [g for g in mesures if g.get("degrade")]
    # CONTESTEE : le verificateur a tranche (souvent DEUX fois), mais l'arbitrage
    # n'a rien livre. C'est un cout de POLITIQUE, pas une absence de mesure.
    contestees = [g for g in gains
                  if g.get("livre") is False and g.get("mesurees")]
    voix_max = max((ligne.get("voix_independantes") or 0) for ligne in lignes) if lignes else 0
    ajustes = [g["gain_ajuste_par_ktokens"] for g in mesures
               if g.get("gain_ajuste_par_ktokens") is not None]
    tokens = sum((ligne.get("cout") or {}).get("tokens", 0) or 0 for ligne in lignes)
    appels = sum((ligne.get("cout") or {}).get("appels", 0) or 0 for ligne in lignes)
    out = {
        "taches": len(lignes),
        "mesurees": len(mesures),
        "non_mesurees": len(lignes) - len(mesures),
        "refus_videur": refus_videur,
        "appels_llm": appels,
        "tokens": tokens,
        "degradees": len(degrades),
        "contestees": len(contestees),
        "voix_independantes_max": voix_max,
        "taux_degradation": round(len(degrades) / len(mesures), 3) if mesures else None,
        "gain_vs_moyen_moyen": None,
        "gain_vs_oracle_moyen": None,
        "gain_ajuste_par_ktokens_moyen": None,
    }
    if mesures:
        out["gain_vs_moyen_moyen"] = round(
            sum(g["gain_vs_moyen"] for g in mesures) / len(mesures), 4)
        out["gain_vs_oracle_moyen"] = round(
            sum(g["gain_vs_oracle"] for g in mesures) / len(mesures), 4)
    if ajustes:
        out["gain_ajuste_par_ktokens_moyen"] = round(sum(ajustes) / len(ajustes), 4)
    if not mesures:
        out["lecture"] = ("AUCUNE tache mesuree : le verificateur n'a jamais tranche "
                          "(providers muets, videur, ou dataset absent). Rien n'est "
                          "affirme sur le collectif.")
    elif refus_videur:
        out["lecture"] = ("%d tache(s) refusee(s) par le videur : l'echantillon est "
                          "AMPUTE, pas nul." % refus_videur)
    if voix_max <= 1 and appels > len(lignes):
        # DEFAUT DE CABLAGE, mesure le 2026-08-26 : `router_call` n'expose aucun
        # moyen de cibler ou d'exclure un provider, donc les N tentatives d'un
        # fanout partent toutes au MEME modele. `groupe_independance` comptant par
        # famille de modele, les voix plafonnent a 1 -- et toute politique exigeant
        # min_voix >= 2 (incertain, important, critique) devient inatteignable par
        # construction. Premiere mesure : 6 appels, 5 reponses JUSTES, 0 acceptee.
        out["plafond_de_voix"] = (
            "voix_independantes_max=%d : toutes les tentatives ont ete servies par le "
            "MEME modele (la cascade rend toujours le premier slot disponible). Une "
            "politique exigeant 2 voix ne peut pas conclure, quelle que soit la "
            "qualite des reponses. La diversite d'ANGLE est acquise, la diversite de "
            "MODELE ne l'est pas." % voix_max)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Rendement de l'intelligence collective")
    ap.add_argument("--n", type=int, default=int(os.environ.get("LAFORGE_GAIN_N", "3")))
    ap.add_argument("--politique", default="incertain",
                    choices=("simple", "incertain", "important", "critique"))
    ap.add_argument("--agent", default="CLAUDE")
    ap.add_argument("--use-case", default="code")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    token = ""
    try:
        from nokido_agent.app.forge_secrets import get_secret

        token = get_secret("LAFORGE_HUB_TOKEN") or get_secret("FORGE_TOKEN_CLAUDE") or ""
    except Exception:  # noqa: BLE001 — sans jeton le videur tranchera, et le dira
        pass
    res = mesurer(n=a.n, politique=a.politique, agent=a.agent, token=token,
                  use_case=a.use_case)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
