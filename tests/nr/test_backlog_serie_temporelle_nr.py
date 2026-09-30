"""NR — un snapshot qui s'ECRASE ne permet pas de verifier qu'un drain DRAINE.

MESURE DU 2026-09-20. Trois lectures du backlog vectoriel, a 33 minutes d'ecart :

    19:38  vector_pending = 64
    19:55  vector_pending = 66
    20:11  vector_pending = 81

Impossible d'en conclure quoi que ce soit : `rafraichir()` ECRASE le snapshot
precedent (`os.replace`), donc aucune serie n'existe. Les trois points ci-dessus
n'ont ete obtenus que parce que je les ai releves a la main pendant une session.
Personne, dans le corps, ne peut repondre a « le backlog derive-t-il ? ».

C'est la transition EFFECT -> VERIFIED qui manque. Le drain
(`forge_reindex_deport`, pouls frais, pid vivant) fait peut-etre parfaitement son
travail -- ou pas : rien ne permet de le dire. Un organe dont on ne peut pas
verifier l'effet est indistinguable d'un organe inutile.

POURQUOI ICI, ET PAS DANS UN NOUVEAU MODULE. Le patron existe DEUX fois dans le
corps -- `forge_generation._append_oplog` (« journal JSONL rejouable, chaque
ligne une victoire figee ») et `sandbox/introspect_serie.jsonl`. On ajoute une
ligne la ou la mesure est DEJA calculee, au lieu de recalculer ailleurs sur un
etat qui aura change.

CONSOMMATEUR DEMONTRABLE, exige avant tout nouveau champ : `forge_resource_manager`
ARBITRE deja sur `vector_pending` (il en lit la valeur instantanee). Une serie lui
permet de distinguer un seuil franchi d'une DERIVE -- deux situations qui appellent
des reponses differentes et qu'une lecture unique confond.

CE QUI N'EST PAS FAIT, et c'est deliberе : aucune borne sur le fichier. Une ligne
par rafraichissement, quelques rafraichissements par jour, ~100 octets la ligne :
l'ordre de grandeur est le kilo-octet par jour. Borner coûterait l'histoire qu'on
cherche precisement a constituer, et une borne muette est le defaut que ce depot
combat.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

ma = pytest.importorskip("app.forge_memory_availability")


@pytest.fixture()
def isole(monkeypatch, tmp_path):
    """Compteurs figes : on teste l'ECRITURE de la serie, pas le calcul."""
    faux = {"total": 1000, "vector": {ma.PENDING: 7, ma.AVAILABLE: 900,
                                      ma.REFUSED_BY_POLICY: 93},
            "lexical": {ma.AVAILABLE: 990, "ecart_source": 10},
            "by_domain": [], "avg_quality": None}
    monkeypatch.setattr(ma, "compteurs", lambda conn=None: faux, raising=True)
    return tmp_path / "snap.json"


def test_une_serie_est_ecrite_a_cote_du_snapshot(isole):
    """Sans elle, aucune tendance n'est calculable -- mesure du 2026-09-20."""
    ma.rafraichir(conn=None, chemin=isole)
    serie = list(isole.parent.glob("*.jsonl"))
    assert serie, (
        "aucune serie ecrite : le snapshot ecrase son predecesseur et l'histoire "
        "du backlog est perdue a chaque rafraichissement."
    )


def test_la_serie_S_AJOUTE_au_lieu_d_ecraser(isole):
    """Le coeur du contrat. Un fichier reecrit a chaque fois ne vaut pas mieux
    que le snapshot qu'il est cense completer."""
    ma.rafraichir(conn=None, chemin=isole)
    ma.rafraichir(conn=None, chemin=isole)
    ma.rafraichir(conn=None, chemin=isole)
    serie = list(isole.parent.glob("*.jsonl"))[0]
    lignes = [l for l in serie.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lignes) == 3, (
        f"{len(lignes)} ligne(s) apres 3 rafraichissements : la serie ECRASE au "
        f"lieu d'ajouter, donc elle ne porte aucune histoire."
    )
    d = json.loads(lignes[0])
    for champ in ("ts", "vector_pending", "vector_available", "total"):
        assert champ in d, f"champ `{champ}` absent : la tendance serait incalculable"
    assert d["vector_pending"] == 7, "la serie ne porte pas la mesure reelle"


def test_la_serie_ne_CASSE_JAMAIS_le_snapshot(isole, monkeypatch):
    """Un journal qui echoue ne doit pas emporter la mesure qu'il accompagne.

    C'est la regle appliquee partout ici : « un journal qui echoue ne desarme pas
    un garde ». Le snapshot est l'acte principal ; la serie l'accompagne.
    """
    vrai_open = open

    def _refuse(f, *a, **k):
        if str(f).endswith(".jsonl"):
            raise PermissionError(13, "Permission denied", str(f))
        return vrai_open(f, *a, **k)

    monkeypatch.setattr("builtins.open", _refuse)
    snap = ma.rafraichir(conn=None, chemin=isole)
    assert snap["vector_pending"] == 7, "le snapshot a ete emporte par l'echec du journal"
    assert isole.is_file(), "le snapshot n'a pas ete ecrit alors que c'est l'acte principal"
