"""NR — une SOURCE ABSENTE n'est pas un DEFAUT SERVEUR, et n'est pas zero.

Defaut paye le 2026-08-26 (CI run 33015131760) : quatre pages du portail rendaient
`500 sqlite3.OperationalError: no such table: chunk_claims`. Le poste de travail ne
pouvait pas le voir — sa base porte les 131 tables. Le runner, lui, a `rag_chunks`
sans `chunk_claims` : le schema epistemique n'y a jamais ete cree.

Deux exigences, et la seconde compte autant que la premiere :

1. Une table absente ne doit pas remonter en 500. Un 500 dit « ce serveur a un bug » ;
   ici le serveur va bien, c'est SA SOURCE qui manque -> 503, en NOMMANT les tables.
2. Elle ne doit pas non plus se lire comme un resultat vide. « Aucun conflit detecte »
   sur une base sans table des claims est un mensonge tranquille — c'est la forme
   d'erreur que le corps paie le plus cher, parce qu'elle rassure.

Le troisieme etat (base illisible / absente) est teste aussi : `sqlite3.connect` en
mode ecriture CREE une base vide au lieu d'echouer, et la route accuse alors ses
tables au lieu de dire que le fichier n'existe pas.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (code appele) (l.49)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ep = pytest.importorskip("app.web_hub.epistemic")


@pytest.fixture
def base_vide(tmp_path, monkeypatch):
    """Une base qui EXISTE et ne porte aucune table — la condition du runner."""
    db = tmp_path / "embeddings.db"
    sqlite3.connect(str(db)).close()
    monkeypatch.setattr(ep, "DB", db)
    return db


@pytest.mark.parametrize(
    "nom,appel",
    [
        ("conflicts", lambda: ep._conflicts_top(5)),
        ("heatmap", lambda: ep._heatmap_predicates("memoire")),
        ("trajectory", lambda: ep._topic_chunks("memoire", 5)),
    ],
)
def test_table_absente_leve_schema_absent_et_non_une_liste_vide(base_vide, nom, appel):
    with pytest.raises(ep.SchemaAbsent) as exc:
        appel()
    # NOMMER ce qui manque : un 503 sans le nom de la table renvoie l'enquete a zero.
    assert exc.value.tables, "%s leve SchemaAbsent sans nommer la table" % nom


def test_la_page_reste_lisible_et_dit_qu_elle_est_indisponible(base_vide):
    html = ep._render_html("memoire")
    bas = html.lower()
    assert "indisponible" in bas
    # Contre-epreuve du vrai piege : ne PAS afficher le zero rassurant. On vise la
    # formule EXACTE du rendu normal — chercher « aucun conflit » tout court echouait
    # sur la phrase qui explique justement qu'on ne l'affiche pas (mesure : ma propre
    # assertion criait au loup sur son propre commentaire).
    assert "aucun conflit detecte pour ce topic" not in bas
    assert "n_conflicts" not in bas and ">0<" not in bas


def test_base_absente_ne_fabrique_pas_une_base_fantome(tmp_path, monkeypatch):
    manquante = tmp_path / "nexistepas.db"
    monkeypatch.setattr(ep, "DB", manquante)
    with pytest.raises(ep.BaseIllisible):
        ep._topic_chunks("memoire", 5)
    assert not manquante.exists(), (
        "la route a CREE la base au lieu d'echouer : elle accusera ensuite ses tables"
    )


def test_les_deux_etats_sont_distincts():
    """Un appelant doit pouvoir les separer — sinon on retombe a deux etats."""
    assert not issubclass(ep.SchemaAbsent, ep.BaseIllisible)
    assert not issubclass(ep.BaseIllisible, ep.SchemaAbsent)


def test_les_routes_traduisent_en_503_pas_en_500(base_vide):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    app = fastapi.FastAPI()
    app.include_router(ep.router, prefix="/epistemic")
    cli = TestClient(app, raise_server_exceptions=False)

    for chemin in ("/epistemic/api/conflicts",
                   "/epistemic/api/heatmap/memoire",
                   "/epistemic/api/trajectory?topic=memoire"):
        r = cli.get(chemin)
        assert r.status_code == 503, "%s -> %s (attendu 503)" % (chemin, r.status_code)
        corps = r.text.lower()
        assert "chunk_claims" in corps or "rag_chunks" in corps, (
            "%s rend 503 sans nommer la table manquante" % chemin
        )
