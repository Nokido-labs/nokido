"""Non-régression AH4 : mesurer l'ADAPTATION, pas la performance d'un instantané.

Item de veille AH4 (`FutureSim`, arXiv 2605.15188) : « rejouer des événements du
monde pour évaluer des agents ADAPTATIFS — mesurer l'adaptation à une
information qui arrive, pas la performance sur un instantané ».

CE QUI EXISTAIT. `forge_router_replay.rejouer` rejoue la DÉCISION à entrée
constante et compte les divergences : c'est une mesure de **dérive du code**,
utile, mais orthogonale. Il le dit lui-même — « aucune qualité n'est mesurée
ici ». Rejouer la même entrée ne dit rien de ce qui se passe quand l'entrée
CHANGE.

CE QUE LA MESURE A TROUVÉ, et qui vaut plus que la fonction ajoutée :

  `decider()` EST adaptatif. Quand `availability["vector"]` vaut PENDING,
  REFUSED_BY_POLICY ou UNKNOWN, il reporte le poids vectoriel sur le lexical —
  un REPORT et non une pénalité, précisément pour ne pas conclure à la
  non-pertinence de ce qu'on n'a pas pu voir.

  …et `RAGEngine.search` l'appelle avec `{}`. Un dictionnaire vide. La
  disponibilité par canal est calculée, journalisée, et **jamais soumise à la
  décision**. La capacité d'adaptation existe, complète et correcte, et n'est
  sollicitée sur aucun chemin réel.

⚠️ CE N'EST PAS UN BUG À CORRIGER ICI, et ce fichier ne le corrige pas. Le choix
est documenté dans `search` : la disponibilité n'est connue qu'APRÈS le
classement, la faire peser sur les poids qui PRODUISENT ce classement serait
circulaire. Le rôle de AH4 est de **chiffrer** cet écart entre capacité et
sollicitation, pas de trancher un arbitrage d'architecture qu'on n'a pas mandat
de rouvrir. Un mécanisme présent n'est pas un effet — c'est la troisième fois
dans cette session, et la mesure doit le dire au lieu de le laisser croire.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))


def _mod():
    import forge_router_replay  # type: ignore

    return forge_router_replay


def _obs(n: int, ctx=None, query="comment fonctionne la consolidation memoire") -> list:
    import forge_retrieval_router as R  # type: ignore

    from dataclasses import asdict
    return [{
        "schema": R.SCHEMA_OBSERVATION, "kind": R.OBSERVATION_REELLE,
        "query_id": f"q{i}", "query": query, "origine": "runtime",
        "decision": asdict(R.decider(query, ctx or {})),
    } for i in range(n)]


# ── 1. La mesure existe ───────────────────────────────────────────────────────

def test_la_mesure_d_adaptation_existe():
    assert callable(getattr(_mod(), "mesurer_adaptation", None)), (
        "seule la derive a entree constante est mesuree : rien ne dit si le "
        "systeme CHANGE d'avis quand l'information change"
    )


# ── 2. Adapté / inerte / non mesurable ────────────────────────────────────────

def test_une_information_qui_change_la_decision_donne_ADAPTE():
    """Le canal vectoriel devient indisponible : les poids doivent bouger."""
    r = _mod().mesurer_adaptation(_obs(12), {"vector": "UNKNOWN"})
    assert r["verdict"] == "ADAPTE", r
    assert r["adaptees"] == 12 and r["inertes"] == 0, r
    assert r["taux_adaptation_pct"] == 100.0, r


def test_une_information_sans_effet_donne_INERTE():
    """Une information que la décision n'écoute pas ne doit pas se lire comme une
    adaptation réussie — ni comme une panne."""
    r = _mod().mesurer_adaptation(_obs(12), {"canal_imaginaire": "UNKNOWN"})
    assert r["verdict"] == "INERTE", r
    assert r["adaptees"] == 0, r


def test_sans_observation_le_verdict_est_NON_MESURABLE():
    r = _mod().mesurer_adaptation([], {"vector": "UNKNOWN"})
    assert r["verdict"] == "NON_MESURABLE", r
    assert r["observations_retenues"] == 0, r
    assert r.get("taux_adaptation_pct") is None, (
        "un taux a ete calcule sur zero observation"
    )


# ── 3. Le chiffre qui compte : capacité ≠ sollicitation ───────────────────────

def test_la_mesure_distingue_la_CAPACITE_de_la_SOLLICITATION():
    """Le cœur d'AH4. `decider` sait s'adapter ; encore faut-il qu'on lui donne
    l'information. Les observations dont le contexte de disponibilité est VIDE
    prouvent qu'on ne la lui donne pas."""
    m = _mod()
    r = m.mesurer_adaptation(_obs(10, ctx={}), {"vector": "UNKNOWN"})
    assert r["observations_avec_contexte_de_disponibilite"] == 0, r
    assert r["capacite_d_adaptation"] == "PRESENTE", r
    assert r["sollicitation_reelle"] == "JAMAIS", (
        "la mesure ne distingue pas une capacite presente d'une capacite "
        "employee : un mecanisme present n'est pas un effet (%s)" % r
    )

    r2 = m.mesurer_adaptation(_obs(10, ctx={"vector": "AVAILABLE"}),
                              {"vector": "UNKNOWN"})
    assert r2["observations_avec_contexte_de_disponibilite"] == 10, r2
    assert r2["sollicitation_reelle"] == "OBSERVEE", r2


def test_une_sollicitation_marginale_ne_se_lit_pas_OBSERVEE():
    """Mesuré le 2026-09-12 : UNE observation sur dix portait un contexte de
    disponibilité. Un binaire aurait rendu « OBSERVEE » et fait croire que le
    chemin réel alimente la décision — alors que 9 sur 10 passent `{}`."""
    m = _mod()
    r = m.mesurer_adaptation(_obs(1, ctx={"vector": "AVAILABLE"}) + _obs(9, ctx={}),
                             {"vector": "UNKNOWN"})
    assert r["observations_avec_contexte_de_disponibilite"] == 1, r
    assert r["sollicitation_reelle"] == "MARGINALE", (
        "une sollicitation a 10 %% est rendue « %s »" % r["sollicitation_reelle"]
    )
    assert r["taux_sollicitation_pct"] == 10.0, r


def test_le_point_d_entree_expose_la_mesure(capsys):
    """Une mesure qu'aucun point d'entrée n'expose est une dette de câblage. Et
    c'est le drapeau CLI qui casse, pas la fonction — déjà payé deux fois ici."""
    m = _mod()
    rc = m.main(["--adaptation", "vector=UNKNOWN"])
    sortie = capsys.readouterr().out
    assert rc == 0
    assert "capacite_d_adaptation" in sortie, sortie[:300]
    assert "sollicitation_reelle" in sortie, sortie[:300]


def test_les_observations_de_test_ne_comptent_pas():
    """Même discipline qu'en AK3 : la CI ne se mesure pas elle-même."""
    obs = _obs(12) + [dict(o, origine="test") for o in _obs(8)]
    r = _mod().mesurer_adaptation(obs, {"vector": "UNKNOWN"})
    assert r["observations_retenues"] == 12, r
    assert r["observations_de_test_ecartees"] == 8, r
