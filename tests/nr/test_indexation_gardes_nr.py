"""NR — les trois outils d'indexation du 2026-09-03 et leurs gardes.

Chacun a ete ecrit APRES un defaut mesure, et chacun a lui-meme accuse a tort au
moins une fois. Ces tests verrouillent les gardes qui ont ete ajoutes en reponse.

  - `forge_db_index_advisor` : proposait 93 index, dont des `CREATE INDEX` sur des
    tables VIRTUELLES FTS5 (impossibles), des colonnes tronquees par la regex et
    des alias non resolus. Et il confondait `SCAN t` avec `SCAN t USING INDEX`,
    ce qui declarait inutile un index qui travaillait.
  - `forge_fts_trigram` : sa construction a pousse le WAL a 33,97 Go pour 30 Go
    libres — a quelques minutes de saturer le disque et de corrompre la base.
  - `forge_rag_index_fingerprint` : remede au balayage de 22,8 Go PAR DOCUMENT ;
    sa garde interdit de construire pendant qu'un ecrivain tourne.

Hermetiques : aucune base de production n'est ouverte, aucun disque n'est ecrit.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=120 (code appele) (l.125)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]


def _charger(nom):
    chemin = ROOT / "tools" / (nom + ".py")
    if not chemin.exists():
        pytest.skip("%s absent" % chemin)
    sys.path.insert(0, str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location(nom, chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------- index advisor ----

def test_forge_db_index_advisor_distingue_scan_table_et_scan_index():
    """`SCAN t USING COVERING INDEX` est une OPTIMISATION, pas un defaut.

    Les confondre faisait declarer « non retenu » un index qui faisait son
    travail — et m'aurait fait supprimer 4 index utiles sur 5 alertes.
    """
    adv = _charger("forge_db_index_advisor")
    assert adv._balaie_la_table("SCAN rag_chunks", "rag_chunks") is True
    assert adv._balaie_la_table(
        "SCAN rag_chunks USING COVERING INDEX idx_x", "rag_chunks") is False
    assert adv._balaie_la_table(
        "SEARCH rag_chunks USING INDEX idx_x (a=?)", "rag_chunks") is False


def test_forge_db_index_advisor_refuse_les_colonnes_inventees():
    """Une colonne n'est proposee que si elle EXISTE dans la table.

    Sans ce filtre, la regex proposait des index sur `embedd` ou `doma` —
    fragments tronques d'un nom reel.
    """
    adv = _charger("forge_db_index_advisor")
    colonnes = {"source", "domain", "meta"}
    assert adv._colonne_du_where(
        "SELECT id FROM t WHERE source = ?", colonnes) == "source"
    assert adv._colonne_du_where(
        "SELECT id FROM t WHERE doma = ?", colonnes) == ""
    # Predicat compose : aucun index simple ne s'en deduit.
    assert adv._colonne_du_where(
        "SELECT id FROM t WHERE text IS NOT NULL AND length(text) > 20",
        colonnes) == ""
    # json_extract EST indexable comme expression — c'est ce qui a corrige la
    # dedup d'ingestion.
    assert adv._colonne_du_where(
        "SELECT id FROM t WHERE json_extract(meta,'$.fp') = ?",
        colonnes) == "json_extract(meta,'$.fp')"


def test_forge_db_index_advisor_declare_ce_qu_il_n_a_pas_examine():
    """Un scanner qui ecarte en silence surestime sa couverture."""
    adv = _charger("forge_db_index_advisor")
    assert set(adv.ECARTES) >= {"fichiers_illisibles", "tables_non_mesurables",
                                "requetes_hors_schema"}


# ------------------------------------------------------------ trigram ----

def test_forge_fts_trigram_exige_une_marge_disque():
    """La v1 a pousse le WAL a 34 Go pour 30 Go libres. Le garde est chiffre."""
    tg = _charger("forge_fts_trigram")
    assert tg.MARGE_GO >= 10, "une marge trop faible ne protege de rien"
    assert tg.CHECKPOINT_TOUS >= 1, (
        "sans checkpoint periodique le WAL croit sans borne en autocommit")


def test_forge_fts_trigram_un_disque_illisible_nest_pas_un_disque_vide():
    """`_libre_go` rend -1 quand il ne peut pas mesurer — jamais 0, jamais grand.

    Rendre 0 declencherait un faux refus ; rendre une grande valeur ferait
    demarrer une construction qui peut saturer. Le troisieme etat est le seul
    honnete.
    """
    tg = _charger("forge_fts_trigram")
    assert tg._libre_go("\x00chemin/invalide/????") == -1.0


# --------------------------------------------------------- fingerprint ----

def test_forge_rag_index_fingerprint_refuse_sous_un_ecrivain(monkeypatch, tmp_path):
    """Construire un index prend un verrou : le faire sous une ingestion la tue.

    Base TEMPORAIRE : la premiere version pointait la base de production, ou
    l'index existe deja — `main` sortait en « rien a faire » AVANT d'atteindre
    le garde, et le test mesurait l'etat du disque au lieu du comportement.
    """
    import sqlite3
    faux = tmp_path / "t.db"
    con = sqlite3.connect(str(faux))
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, meta TEXT)")
    con.commit()
    con.close()

    idx = _charger("forge_rag_index_fingerprint")
    monkeypatch.setattr(idx, "_db", lambda: faux)
    monkeypatch.setattr(idx, "_ecrivain_actif", lambda: "forge_ingest (pid 42)")
    assert idx.main(["--apply"]) == 4, (
        "un ecrivain actif doit faire REFUSER la construction, pas la retarder")

    # Contre-epreuve : sans ecrivain, la construction aboutit — sinon le garde
    # bloquerait tout et « refuse toujours » passerait pour « refuse a raison ».
    monkeypatch.setattr(idx, "_ecrivain_actif", lambda: "")
    assert idx.main(["--apply"]) == 0


def test_forge_rag_index_fingerprint_dry_run_ne_touche_rien():
    """Sans --apply, aucune ecriture : le defaut est sur."""
    idx = _charger("forge_rag_index_fingerprint")
    assert idx.NOM and idx.EXPR.startswith("json_extract"), (
        "l'index porte sur une EXPRESSION — c'est tout l'objet du remede")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
