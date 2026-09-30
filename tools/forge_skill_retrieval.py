"""RETRIEVAL de skills — quels skills sont pertinents pour un objectif donne.

Couche 2 sur 3, strictement separee :

    CATALOGUE  forge_skill_catalogue      quels skills EXISTENT
    RETRIEVAL  ce module                  lesquels sont PERTINENTS
    PLANNING   forge_goap_hub_bridge      dans quel ORDRE les utiliser

La separation est payee, pas theorique : `forge_skill_rag_bridge` a melange
les trois et a fini par scorer des DOMAINES (`devops`, `reseau_dns`) en
croyant scorer des skills — 639 lignes, zero importeur, et un
`rag_score(skill_id)` qui mesure la couverture documentaire d'un domaine dans
le RAG, pas la pertinence d'une tache.

CE QUE CE SCORE EST, ET CE QU'IL N'EST PAS
------------------------------------------
C'est une baseline DETERMINISTE : lexical (idf sur les descriptions du
catalogue) + un prior d'usage. Ce n'est PAS du retrieval semantique, et il ne
faut pas le presenter comme tel : au 2026-09-12 aucun backend d'embedding ne
repond (`:8099`, `:8091`, `:1234` fermes, `:11434` expire). Un score
semantique s'ajoutera comme une composante SUPPLEMENTAIRE le jour ou un
embedder repondra — la baseline restera mesurable a cote, ce qui est
exactement l'ordre voulu : deterministe d'abord, cognitif ensuite, et le
second ne s'adopte que s'il bat le premier sur mesure.

Trois refus assumes, chacun adossé a un defaut deja paye :

  * Aucun score n'est OPAQUE. Chaque candidat expose ses composantes et leur
    somme EST le score. Un score dont les composantes ne totalisent pas le
    resultat rend les composantes decoratives.
  * « Rien trouve » ne devient jamais « il n'existe rien ». Sous le seuil, le
    verdict est SEARCH_MORE : elargir, pas fermer. Meme famille que
    ILLISIBLE != ABSENT.
  * Un skill dont la frontmatter ne parse pas garde sa `fiabilite` reelle :
    sa description n'est plus celle de son auteur, donc le texte sur lequel
    on le score est faux. Le proposer en silence serait mentir sur l'entree.

NR : tests/nr/test_skill_retrieval_nr.py
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import re
import sys
from typing import TYPE_CHECKING

import forge_skill_catalogue as cat

if TYPE_CHECKING:  # pragma: no cover
    pass

__FORGE_COLOR__ = "cognition/skill-retrieval : score de pertinence tache vers skill"

# Seuil par defaut. Volontairement bas : rater un skill pertinent coute plus
# cher que d'en proposer un de trop, puisque l'appelant voit le score et la
# raison. Le seuil est TOUJOURS rendu avec le resultat — un seuil implicite
# est un jugement cache.
SEUIL_DEFAUT = 0.25

# Poids du prior d'usage. Faible par construction : l'usage dit ce qui a DEJA
# servi, ce qui favorise mecaniquement l'installe. Il departage, il ne decide
# pas — sinon un skill neuf ne pourrait jamais emerger.
#
# MULTIPLICATIF, jamais additif. Mesure du 2026-09-12 sur le catalogue reel :
# en additif, `laforge-ops` sortait PREMIER sur « composer une symphonie pour
# hautbois et theremine » avec lexical=0.0 et usage=0.15 — 21 usages
# historiques suffisaient a fabriquer de la pertinence a partir de rien.
# Proportionne au lexical, un skill hors sujet reste a zero quoi qu'il ait
# servi par le passe.
POIDS_USAGE = 0.15

_MOTS_VIDES = frozenset("""
a au aux avec ce ces dans de des du elle en et eux il je la le les leur lui ma
mais me meme mes moi mon ne nos notre nous on ou par pas pour qu que qui sa se
ses son sur ta te tes toi ton tu un une vos votre vous c d j l m n s t y
the of and to in for on with is are be as at an it this that from by or
""".split())

_JETON = re.compile(r"[a-z0-9]+")


def jetons(texte: str) -> list[str]:
    """Minuscule, decoupe alphanumerique, mots vides retires.

    Pas de stemming : il ferait correspondre des mots que l'auteur n'a pas
    ecrits, et le gain n'est pas mesurable tant qu'aucune baseline n'existe.
    """
    return [m for m in _JETON.findall((texte or "").lower())
            if m not in _MOTS_VIDES and len(m) > 1]


@dataclasses.dataclass
class Candidat:
    skill_id: str
    nom: str
    score: float
    score_components: dict[str, float]
    reason: str
    fiabilite: str


@dataclasses.dataclass
class Resultat:
    objectif: str
    candidats: list[Candidat]
    verdict: str
    seuil: float
    denominateur: int
    motif: str = ""


def _idf(releve: cat.Releve) -> dict[str, float]:
    """idf LISSE : log(1 + N/df), jamais nul.

    Un idf classique log(N/df) vaut 0 quand un terme est dans tous les
    documents : deux skills au texte identique obtiendraient alors un score
    lexical nul et seraient indiscernables d'un skill hors sujet.
    """
    n = max(1, len(releve.records))
    df: dict[str, int] = {}
    for r in releve.records.values():
        for t in set(jetons(r.name_dossier + " " + (r.description or ""))):
            df[t] = df.get(t, 0) + 1
    return {t: math.log(1.0 + n / d) for t, d in df.items()}


def chercher(releve: cat.Releve, objectif: str, k: int = 3,
             seuil: float | None = None) -> Resultat:
    """Rend les k skills les plus pertinents, avec le POURQUOI de chacun.

    Les candidats ne sont PAS filtres par le seuil : le seuil decide du
    verdict, pas de la visibilite. Filtrer rendrait une liste vide dont on ne
    saurait pas distinguer « rien de pertinent » de « rien du tout ».
    """
    s = SEUIL_DEFAUT if seuil is None else float(seuil)
    idf = _idf(releve)
    q = jetons(objectif)
    poids_q = sum(idf.get(t, math.log(1.0 + len(releve.records) or 1.0)) for t in q)

    usages = [r.usage_total for r in releve.records.values()]
    usage_max = max(usages) if usages else 0

    candidats: list[Candidat] = []
    for sid, r in releve.records.items():
        texte = set(jetons(r.name_dossier + " " + (r.name_declare or "")
                           + " " + (r.description or "")))
        touches = [t for t in q if t in texte]
        gagne = sum(idf.get(t, 0.0) for t in touches)
        lexical = (gagne / poids_q) if poids_q > 0 else 0.0

        if lexical > 0 and usage_max > 0 and r.usage_total > 0:
            usage = POIDS_USAGE * lexical * (
                math.log1p(r.usage_total) / math.log1p(usage_max))
        else:
            usage = 0.0

        comps = {"lexical": round(lexical, 6), "usage": round(usage, 6)}
        total = round(sum(comps.values()), 6)

        if touches:
            raison = "termes communs : %s" % ", ".join(sorted(touches)[:6])
        else:
            raison = "aucun terme commun avec l'objectif"
        if usage > 0:
            raison += " ; %d usages historiques" % r.usage_total
        if r.etat != "OK":
            raison += " ; ATTENTION description non fiable (%s)" % r.etat

        candidats.append(Candidat(
            skill_id=sid,
            nom=r.name_declare or r.name_dossier,
            score=total,
            score_components=comps,
            reason=raison,
            fiabilite=r.etat,
        ))

    # Tri DETERMINISTE : le score, puis le skill_id. Sans second critere,
    # deux ex aequo s'ordonnent au hasard du parcours et la baseline de
    # comparaison devient inexploitable d'un run a l'autre.
    candidats.sort(key=lambda c: (-c.score, c.skill_id))
    retenus = candidats[:max(1, int(k))]

    meilleur = retenus[0].score if retenus else 0.0
    if not releve.records:
        verdict, motif = "SEARCH_MORE", "catalogue vide"
    elif meilleur >= s:
        verdict, motif = "TROUVE", "au moins un candidat au-dessus du seuil"
    else:
        verdict = "SEARCH_MORE"
        motif = ("meilleur score %.3f sous le seuil %.3f — elargir la recherche, "
                 "ne PAS conclure a l'absence de skill" % (meilleur, s))

    return Resultat(objectif=objectif, candidats=retenus, verdict=verdict,
                    seuil=s, denominateur=len(releve.records), motif=motif)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Quels skills pour cet objectif ?")
    ap.add_argument("objectif", nargs="+", help="l'objectif en clair")
    ap.add_argument("-k", type=int, default=3)
    ap.add_argument("--seuil", type=float, default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    releve = cat.scanner(cat.surfaces_reelles())
    cat.appliquer_usages(releve, cat.usages_du_poste())
    res = chercher(releve, " ".join(a.objectif), k=a.k, seuil=a.seuil)

    if a.json:
        print(json.dumps(dataclasses.asdict(res), indent=2, ensure_ascii=False))
        return 0

    print("OBJECTIF : %s" % res.objectif)
    print("VERDICT  : %s  (seuil %.2f, sur %d skills)"
          % (res.verdict, res.seuil, res.denominateur))
    if res.motif:
        print("MOTIF    : %s" % res.motif)
    for i, c in enumerate(res.candidats, 1):
        print("  %d. %-28s score=%.3f  %s" % (i, c.nom, c.score, c.score_components))
        print("     %s" % c.reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
