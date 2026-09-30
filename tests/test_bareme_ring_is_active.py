"""TDD — un outil DESACTIVE doit etre refuse, pas rendu universellement permis.

MESURE DU 2026-09-12. `ToolRegistry._get_ring_needed` lit le bareme dans la
table `forge_tools` et, pour une ligne `is_active=0`, fait :

    return 99  # bloque

Le site appelant compare ainsi :

    ring_needed = self._get_ring_needed(name, args)
    if ring > ring_needed:
        return "SECURITY: Acces refuse ..."

Un ring vaut 0..4. `ring > 99` est donc TOUJOURS faux : desactiver un outil le
rend permis a TOUS les rings, UNTRUSTED compris. Le commentaire affirme
l'inverse de ce que le code fait — c'est une inversion de sens, pas un reglage.

Aucune ligne n'est desactivee aujourd'hui (mesure : 25 lignes, 0 inactive), le
defaut est donc LATENT. Il se declencherait au premier usage de la seule
commande prevue pour couper un outil.

MODEL_TEST : fixture SQLite temporaire au schema reel. Ne touche JAMAIS
`RAG/embeddings.db` (26,5 Go, base de production partagee).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
for _p in (str(RACINE.parent), str(RACINE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REG = pytest.importorskip("nokido_agent.app.forge_mcp_registry")

#: MASTER=-1, SYSTEM=0, DEV=1, TRUSTED=2, COLLAB=3, UNTRUSTED=4.
#: La premiere version de ce test omettait -1 : le correctif `return -1` l'a
#: donc passe au vert alors que MASTER franchissait encore un outil COUPE
#: (`-1 > -1` est faux). C'est le NR, qui balayait tout l'espace, qui l'a
#: rattrape. Un test dont le domaine est plus etroit que celui du code valide
#: un correctif incomplet.
RINGS = (-1, 0, 1, 2, 3, 4)


@pytest.fixture
def bareme(tmp_path):
    """Base temporaire au schema reel de `forge_tools`."""
    db = tmp_path / "bareme.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE forge_tools ("
                "tool_name TEXT PRIMARY KEY, min_ring INTEGER, is_active INTEGER)")
    con.executemany("INSERT INTO forge_tools VALUES (?,?,?)", [
        ("outil_coupe", 2, 0),      # DESACTIVE
        ("outil_actif", 2, 1),      # actif, plafond ring 2
        ("outil_strict", 0, 1),     # actif, reserve au ring 0
    ])
    con.commit()
    con.close()
    return db


def _ring_needed(monkeypatch, bareme, nom, args=None):
    reg = REG.get_registry()
    monkeypatch.setattr(reg, "db_path", bareme, raising=False)
    return reg._get_ring_needed(nom, args or {})


@pytest.mark.parametrize("ring", RINGS)
def test_un_outil_desactive_est_refuse_a_tous_les_rings(monkeypatch, bareme, ring):
    """LE DEFAUT. `is_active=0` doit DENIER, pour tout ring."""
    besoin = _ring_needed(monkeypatch, bareme, "outil_coupe")
    refuse = ring > besoin          # la comparaison EXACTE du site appelant
    assert refuse, (
        "outil DESACTIVE autorise au ring %d : _get_ring_needed rend %r, et le "
        "site appelant refuse seulement si `ring > ring_needed`. Desactiver un "
        "outil le rend donc PLUS permissif, pas moins." % (ring, besoin))


def test_controle_positif_un_outil_actif_garde_son_plafond(monkeypatch, bareme):
    """Sans lui, un correctif qui refuserait TOUT passerait le test precedent."""
    besoin = _ring_needed(monkeypatch, bareme, "outil_actif")
    assert besoin == 2, "plafond de l'outil actif altere : %r" % (besoin,)
    assert not (-1 > besoin), "MASTER refuse sur un outil ACTIF"
    assert not (2 > besoin), "ring 2 refuse alors que le plafond vaut 2"
    assert (3 > besoin), "ring 3 admis alors que le plafond vaut 2"


def test_controle_positif_un_plafond_strict_reste_strict(monkeypatch, bareme):
    besoin = _ring_needed(monkeypatch, bareme, "outil_strict")
    assert besoin == 0, "plafond strict altere : %r" % (besoin,)
    assert not (0 > besoin), "ring 0 refuse sur un outil qui lui est reserve"
    assert (1 > besoin), "ring 1 admis sur un outil reserve au ring 0"


def test_controle_positif_le_repli_code_en_dur_survit(monkeypatch, bareme):
    """Un nom ABSENT de la base doit retomber sur l'intention codee, pas sur 99.

    NEGATIVE_CONTROL du correctif : fermer l'inversion ne doit pas transformer
    « absent de la base » en « desactive ».
    """
    besoin = _ring_needed(monkeypatch, bareme, "__absent_de_la_base__")
    assert besoin == 2, (
        "un outil absent de la base ne retombe plus sur le repli code en dur "
        "(defaut 2) : %r" % (besoin,))
