"""forge_swarm_reducer -- ForgeSwarm phase REDUCE : synthese DETERMINISTE des resultats d'un essaim.

Promis par docs/roadmap_forge_swarm.md (« Phase 3 REDUCE : reduce(results, goal) -> dict ») et maintenu
par decision owner le 18/10. Pourquoi un module et pas une ligne de plus dans l'orchestrateur : l'anti-dup
d'AGY (tasks.db:job_fdf084d7) a mesure que run_forge_swarm collecte puis commit/discard sans AUCUNE
synthese ; la reduction est une responsabilite propre (lisible par l'agent principal, rejouable en test),
distincte du commit physique que porte VFSOverlay.

Premier pas, volontairement sans LLM : chaque pas est range dans UNE categorie (reussie / echouee / sautee /
non executee), une chaine « ERR: » / « TIMEOUT: » du DAGRunner est un echec, un pas attendu sans resultat
n'est PAS une reussite, le resume est borne et DIT ce qu'il omet. Meme entree -> meme sortie.
"""
from __future__ import annotations

__FORGE_COLOR__ = 'Locomoteur/Orchestration'

RESUME_MAX = 600
_ERREUR_MAX = 160
_FICHIERS_MAX = 5


def _classe(resultat) -> str:
    if isinstance(resultat, str):  # DAGRunner encode exceptions et timeouts en chaine
        return "echouee"
    if not isinstance(resultat, dict):
        return "echouee"  # forme inattendue : jamais rangee du cote sain
    if resultat.get("skipped"):
        return "sautee"
    return "reussie" if resultat.get("ok") else "echouee"


def reduce(results: dict, goal: str, touched: list | None = None, attendus: list | None = None) -> dict:
    """Synthese deterministe des `results` d'un essaim (cle = task_id) pour le but `goal`.

    `attendus` : identifiants des pas du plan ; un attendu absent de `results` est NON EXECUTE.
    `touched` : fichiers ecrits par le commit de l'overlay (vide si discard)."""
    results = results or {}
    reussies, echouees, sautees = [], [], []
    for tid in sorted(results):
        r = results[tid]
        cat = _classe(r)
        if cat == "reussie":
            reussies.append(tid)
        elif cat == "sautee":
            sautees.append(tid)
        else:
            err = r if isinstance(r, str) else (r.get("error") if isinstance(r, dict) else repr(r))
            echouees.append({"task_id": tid,
                             "op": r.get("op") if isinstance(r, dict) else None,
                             "error": str(err or "echec sans message")[:_ERREUR_MAX]})
    non_executees = sorted(set(attendus or ()) - set(results))
    n = len(set(results) | set(attendus or ()))
    touches = sorted(touched or [])
    ok = bool(n) and not echouees and not sautees and not non_executees

    lignes = ["but : %s" % goal, "%d/%d pas reussis" % (len(reussies), n)]
    lignes += ["ECHEC %s : %s" % (e["task_id"], e["error"]) for e in echouees]
    if sautees:
        lignes.append("sautes (dependance echouee) : %s" % ", ".join(sautees))
    if non_executees:
        lignes.append("non executes : %s" % ", ".join(non_executees))
    resume, omis = "", 0
    for i, l in enumerate(lignes):
        if len(resume) + len(l) + 1 > RESUME_MAX - 40:
            omis = len(lignes) - i
            break
        resume += l + "\n"
    if omis:
        resume += "... %d ligne(s) omise(s) (borne %d car.)" % (omis, RESUME_MAX)

    titre = "swarm: %s" % " ".join(str(goal).split())
    suffixe = " (%d/%d)" % (len(reussies), n)
    titre = titre[:72 - len(suffixe)] + suffixe
    corps = ["%d/%d taches reussies ; %d fichier(s)" % (len(reussies), n, len(touches))]
    corps += ["- %s" % f for f in touches[:_FICHIERS_MAX]]
    if len(touches) > _FICHIERS_MAX:
        corps.append("- ... %d autre(s)" % (len(touches) - _FICHIERS_MAX))
    return {"goal": goal, "ok": ok, "n": n, "reussies": reussies, "echouees": echouees,
            "sautees": sautees, "non_executees": non_executees, "touches": touches,
            "resume": resume.rstrip("\n"), "message_commit": titre + "\n\n" + "\n".join(corps)}
