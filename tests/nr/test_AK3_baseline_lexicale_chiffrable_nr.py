"""Non-régression AK3 : chiffrer le lexical contre le dense — ou dire pourquoi non.

Item de veille AK3 : « des représentations statistiques TRADITIONNELLES battent
l'IA générative ». Troisième entrée de la veille à redire la même chose sous un
angle différent, et le point propre est celui-ci : **la baseline non générative
doit être chiffrée avant d'ajouter du modèle.**

TROIS SOURCES POSSIBLES POUR CE CHIFFRE, TROIS MESURES DU 2026-09-12 :

  1. `tools/bench/forge_longmemeval.py` (TF-IDF pur) et `forge_longmemeval_bge.py`
     (dense BGE-M3) existent tous les deux — l'entrée qui disait « aucun banc de
     retrieval dans le dépôt » était fausse. Mais leur jeu de données,
     `sandbox/longmemeval/`, est **ABSENT du disque**. Les deux bancs sont là,
     le terrain d'épreuve n'y est pas.

  2. Le canal dense lui-même est indisponible (sidecar injoignable, zéro
     embedding en RAM, backends d'embedding hors service).

  3. Le journal shadow du routeur, conçu exactement pour cette comparaison,
     portait **10 observations** — dont **9 écrites par les tests NR de B4**,
     quelques minutes plus tôt, dans la même session. Une seule observation
     venait d'ailleurs, et elle datait du 2026-09-03.

⚠️ D'OÙ CE QUE CE FICHIER VERROUILLE, ET QUI N'EST PAS LE CHIFFRE. Fabriquer un
jeu maison en extrayant des phrases verbatim de chunks connus aurait donné un
chiffre — massivement favorable au lexical, par construction. C'est exactement
le piège consigné dans ce dépôt : « une mesure qui ARRANGE se vérifie avant
d'être rapportée ». On livre donc l'instrument et son honnêteté :

  - `comparer_canaux` rend `NON_MESURABLE` **avec son dénominateur** tant que la
    matière manque, au lieu d'un pourcentage bâti sur 22 documents ;
  - les observations de TEST sont étiquetées à l'écriture et écartées à la
    lecture, sinon chaque passage de la CI gonfle le corpus de calibration avec
    ses propres requêtes — ce qui vient précisément d'arriver.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))


def _mod():
    import forge_retrieval_router  # type: ignore

    return forge_retrieval_router


def _obs(n: int, origine: str = "runtime") -> list:
    """Quatre documents par requête, un par cas de figure — les taux attendus se
    lisent donc directement, sans arithmétique mentale."""
    return [{
        "query": f"requete {i}", "origine": origine,
        "resultats": [
            # les deux canaux ont contribue
            {"chunk_id": f"c{i}a", "rank": 1, "lexical_score": 1.0,
             "vector_score": 0.5, "final_score": 0.04},
            # lexical SEUL — le cas qui interesse AK3
            {"chunk_id": f"c{i}b", "rank": 2, "lexical_score": 1.0,
             "vector_score": 0.0, "final_score": 0.03},
            # dense seul
            {"chunk_id": f"c{i}c", "rank": 3, "lexical_score": 0.0,
             "vector_score": 0.5, "final_score": 0.02},
            # aucun des deux : remonte par la fusion ou les metadonnees
            {"chunk_id": f"c{i}d", "rank": 4, "lexical_score": 0.0,
             "vector_score": 0.0, "final_score": 0.01},
        ],
    } for i in range(n)]


# ── 1. L'instrument existe et refuse de conclure sur rien ─────────────────────

def test_le_comparateur_existe():
    assert callable(getattr(_mod(), "comparer_canaux", None)), (
        "aucun comparateur : le journal porte lexical_score et vector_score par "
        "document depuis le 2026-09-08, et personne ne les confronte"
    )


def test_sous_le_seuil_le_verdict_est_NON_MESURABLE_avec_son_denominateur():
    """22 documents issus de 10 requêtes, dont 9 de mes propres tests, ne font
    pas une baseline. Un pourcentage calculé là-dessus serait un chiffre inventé
    portant l'autorité d'une mesure."""
    r = _mod().comparer_canaux(_obs(3))
    assert r["verdict"] == "NON_MESURABLE", r
    assert r["observations_retenues"] == 3, r
    assert "seuil" in r, "le seuil n'est pas dit : le refus n'est pas verifiable"
    assert r.get("taux_lexical_seul") is None, (
        "un taux a ete calcule sous le seuil : c'est precisement le chiffre "
        "qu'on ne doit pas produire"
    )


def test_au_dessus_du_seuil_le_chiffre_sort():
    r = _mod().comparer_canaux(_obs(60))
    assert r["verdict"] == "MESURE", r
    assert r["documents"] == 240, r
    assert r["taux_les_deux"] == 25.0, r
    assert r["taux_lexical_seul"] == 25.0, r
    assert r["taux_dense_seul"] == 25.0, r
    assert r["taux_aucun"] == 25.0, r


# ── 2. Les observations de test ne contaminent pas la calibration ─────────────

def test_les_observations_de_test_sont_ecartees():
    """Mesuré : 9 des 10 observations du journal venaient des NR de B4, écrites
    dans la même session. Sans étiquette, la CI se calibre sur elle-même."""
    r = _mod().comparer_canaux(_obs(60) + _obs(40, origine="test"))
    assert r["observations_retenues"] == 60, (
        "les observations de test comptent dans la mesure : %s" % r
    )
    assert r["observations_de_test_ecartees"] == 40, r


def test_l_ecriture_etiquette_l_origine(tmp_path, monkeypatch):
    """L'étiquette se pose à l'ÉCRITURE. La poser à la lecture supposerait qu'on
    sache après coup d'où vient une ligne — on ne le sait pas."""
    m = _mod()
    j = tmp_path / "obs.jsonl"
    monkeypatch.setattr(m, "_JOURNAL", j, raising=False)
    dec = m.decider("une requete quelconque", {})
    m.observer("id1", "une requete quelconque", dec,
               [{"chunk_id": "x", "rank": 1, "lexical_score": 1.0,
                 "vector_score": 0.0}])
    assert j.exists(), "rien n'a ete ecrit dans le journal redirige"
    ligne = json.loads(j.read_text(encoding="utf-8").splitlines()[0])
    assert ligne.get("origine") == "test", (
        "l'observation ecrite depuis pytest n'est pas etiquetee : elle ira "
        "grossir le corpus de calibration comme du trafic reel (%s)"
        % ligne.get("origine")
    )


def test_le_journal_est_redirigeable_par_l_environnement(tmp_path, monkeypatch):
    """Sans redirection possible, un test qui traverse `search` écrit dans
    l'artefact de production — ce qui s'est produit, 9 fois.

    ⚠️ Ce test a d'abord été écrit avec `importlib.reload`, et il PASSAIT seul
    puis ÉCHOUAIT derrière le NR de AH4. Cause : ce module est chargé sous deux
    noms (`forge_retrieval_router` et `nokido_agent.app.…`) unifiés par le
    finder posé le 2026-09-10 — un `reload` y rend l'objet DÉJÀ chargé et ne
    relit donc pas l'environnement. Le défaut était sous le test : une constante
    figée à l'import ne se redirige pas. On vérifie donc la résolution À
    L'APPEL, qui ne dépend d'aucun ordre d'exécution."""
    m = _mod()
    ailleurs = tmp_path / "ailleurs.jsonl"
    assert callable(getattr(m, "_chemin_journal", None)), (
        "le chemin du journal est fige a l'import : aucun test ne peut s'isoler"
    )
    monkeypatch.setenv("LAFORGE_ROUTER_JOURNAL", str(ailleurs))
    assert Path(m._chemin_journal()) == ailleurs
    monkeypatch.delenv("LAFORGE_ROUTER_JOURNAL", raising=False)
    assert Path(m._chemin_journal()) == Path(m._JOURNAL), (
        "sans variable posee, la resolution doit revenir au chemin par defaut"
    )


# ── 3. Trois états, jamais deux ───────────────────────────────────────────────

def test_un_canal_non_observable_n_est_pas_un_canal_a_zero():
    """`NOT_OBSERVABLE` veut dire « le canal n'a rien dit », pas « le canal a dit
    zéro ». Le confondre fait conclure à la non-pertinence de ce qu'on n'a pas
    pu voir."""
    obs = _obs(60)
    for o in obs[:30]:
        for d in o["resultats"]:
            d["vector_score"] = "NOT_OBSERVABLE"
    r = _mod().comparer_canaux(obs)
    assert r["documents_canal_dense_NON_OBSERVABLE"] == 120, r
    assert r["documents"] == 240
    # les 120 non observables sortent du denominateur des taux
    assert r["documents_comparables"] == 120, (
        "des documents dont le canal dense n'a rien dit ont ete comptes comme "
        "des echecs du dense : %s" % r
    )
