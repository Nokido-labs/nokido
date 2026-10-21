"""NR -- le controle FTS5 de rag_fts se fait sur une COPIE, jamais sur la base vivante (decision owner 20/10).

Mesure du 20/10 : `PRAGMA integrity_check` (lance par le cold_backup de MemoryConsolidator) rend « malformed inverted
index for FTS5 table main.rag_fts » -- UNE observation. Decision owner « chantier dedie, mesurer d'abord » : un 2e
observateur, la commande FTS5 `integrity-check` propre a la table. Or cette commande passe par un INSERT : verrou
d'ECRITURE sur la base vivante (V:, 50 Go) pendant toute sa duree -- le hub s'arrete au-dela de 120 s bloque. Elle se
joue donc sur la copie que fait deja `forge_db_backup` (API .backup, en ligne), posee sur E: (765 Go libres).

Contrat (extension de tools/forge_db_backup.py, pas d'outil neuf) :
  * `controler_fts(copie, tables)` -> {table: "OK" | "CORROMPU: <message>" | "ABSENTE"} ; REFUSE (ValueError) le
    chemin de la base vivante ;
  * `place_suffisante(dossier, minimum_octets)` : la copie bloque le checkpoint du WAL de la base vivante, qui grossit
    sur SON volume -- on refuse de demarrer sous le minimum ;
  * CLI `--controle-fts rag_fts --rapport <json>` : copie brute (pas de zstd), controle, rapport JSON ecrit.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def _mod():
    spec = importlib.util.spec_from_file_location("db_backup_fts_nr", RACINE / "tools" / "forge_db_backup.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _base(p: Path, corrompre: bool = False) -> Path:
    con = sqlite3.connect(p)
    con.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED)")
    con.executemany("INSERT INTO rag_fts VALUES (?, ?, ?, ?)",
                    [("c%d" % i, "le texte numero %d parle de respiration et de ventilation" % i, "s", "d")
                     for i in range(300)])
    con.commit()
    if corrompre:
        con.execute("DELETE FROM rag_fts_data WHERE id > 10")   # index inverse ampute : FTS5 le dit « malformed »
        con.commit()
    con.close()
    return p


def test_une_table_fts_saine_est_ok(tmp_path):
    m = _mod()
    r = m.controler_fts(_base(tmp_path / "saine.db"), ["rag_fts", "absente_fts"])
    assert r == {"rag_fts": "OK", "absente_fts": "ABSENTE"}, r


def test_une_table_fts_corrompue_est_dite(tmp_path):
    m = _mod()
    r = m.controler_fts(_base(tmp_path / "abimee.db", corrompre=True), ["rag_fts"])
    assert r["rag_fts"].startswith("CORROMPU"), r


@pytest.mark.parametrize("nom", ["rag_fts) --", "rag fts", "rag_fts(rag_fts"])
def test_un_nom_de_table_hors_identifiant_est_refuse(tmp_path, nom):
    """Livraison GLM b62fc5bfc : `Path(table).match(regex)` est un GLOB, pas une regex -- un nom arbitraire passait,
    puis entrait dans un SQL construit par f-string (injection)."""
    m = _mod()
    with pytest.raises(ValueError):
        m.controler_fts(_base(tmp_path / "x.db"), [nom])


def test_le_controle_refuse_la_base_vivante(monkeypatch, tmp_path):
    m = _mod()
    vivante = _base(tmp_path / "vivante.db")
    monkeypatch.setattr(m, "DB", vivante)
    with pytest.raises(ValueError):
        m.controler_fts(vivante, ["rag_fts"])


def test_la_place_minimum_est_exigee(tmp_path):
    m = _mod()
    assert m.place_suffisante(tmp_path, 1) is True
    assert m.place_suffisante(tmp_path, 10 ** 18) is False


def test_le_point_d_entree_copie_controle_et_rapporte(monkeypatch, tmp_path):
    """Chemin reel : `main()` et ses drapeaux CLI."""
    m = _mod()
    monkeypatch.setattr(m, "DB", _base(tmp_path / "vivante.db"))
    rapport = tmp_path / "rapport.json"
    # La place libre du volume temporaire n'est pas l'objet de ce test (1re version : rc 2 sur un poste a moins de
    # 10 Go libres, releve par GLM le 20/10).
    volumes = []
    monkeypatch.setattr(m, "place_suffisante", lambda d, minimum: volumes.append(Path(d)) or True)
    monkeypatch.setattr(sys, "argv", ["forge_db_backup.py", "--dir", str(tmp_path / "copies"), "--no-zstd",
                                      "--controle-fts", "rag_fts", "--rapport", str(rapport)])
    assert m.main() == 0
    doc = json.loads(rapport.read_text(encoding="utf-8"))
    assert doc["fts"] == {"rag_fts": "OK"} and Path(doc["copie"]).exists(), doc
    assert Path(doc["copie"]).resolve() != (tmp_path / "vivante.db").resolve()
    assert (tmp_path / "vivante.db").parent.resolve() in [v.resolve() for v in volumes], (
        "la place se mesure sur le volume de la BASE (le WAL vivant y grossit), pas seulement sur la destination")


def test_une_table_corrompue_ecrit_quand_meme_le_rapport(monkeypatch, tmp_path):
    m = _mod()
    monkeypatch.setattr(m, "DB", _base(tmp_path / "vivante.db", corrompre=True))
    monkeypatch.setattr(m, "place_suffisante", lambda d, minimum: True)
    rapport = tmp_path / "rapport.json"
    monkeypatch.setattr(sys, "argv", ["forge_db_backup.py", "--dir", str(tmp_path / "copies"),
                                      "--controle-fts", "rag_fts", "--rapport", str(rapport)])
    assert m.main() == 3
    doc = json.loads(rapport.read_text(encoding="utf-8"))
    assert doc["fts"]["rag_fts"].startswith("CORROMPU"), doc
