"""NR — le WAL de la base RAG ne doit plus pouvoir saturer le volume.

Mesure 2026-09-01 : trois ingestions concurrentes (408 325 chunks) ont porte
`embeddings.db-wal` a 53 Go et sature V: — 0 octet libre. Toute ecriture RAG
rendait alors `disk I/O error` : le sidecar de traces est parti en quarantine et
le hub est tombe deux fois. Le checkpoint de rattrapage a chiffre le gaspillage :
12 857 716 pages versees pour 0,21 Go de donnees reelles — le WAL n'etait presque
que des REECRITURES.

Ce que ces tests tiennent, et pourquoi :

1. Le garde s'abstient sous le seuil, et ne LEVE jamais — un checkpoint qui
   explose dans une boucle d'ingestion couterait plus cher que le WAL.
2. Un WAL absent se distingue d'un WAL illisible : rendre `False` pour les deux
   fabriquerait un faux negatif indetectable (cf. RULES_SHARED, « ne jamais
   conclure d'une source qui se tait »).
3. TRUNCATE rend REELLEMENT le fichier au disque. C'est la seule mesure qui
   compte : PASSIVE verse les pages sans rendre un octet, et c'est precisement
   ce qui a trompe le rattrapage du 01/09.
4. Le garde a un APPELANT. Un checkpoint parfait que personne n'invoque est un
   garde branche sur un signal que personne n'emet — le motif deja paye le
   2026-07-30 sur `INSULIN_VECTORIZATION` et sur l'intention `llama.wanted`.
"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_db_path as F  # noqa: E402


def _base_wal(tmp_path, lignes: int = 4000):
    """Base WAL avec une connexion LAISSEE OUVERTE : sans lecteur vivant SQLite
    checkpointe et supprime le WAL a la fermeture, et le test n'aurait plus rien
    a mesurer."""
    db = tmp_path / "rag_test.db"
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, txt TEXT)")
    conn.commit()
    for _ in range(lignes):
        conn.execute("INSERT INTO t (txt) VALUES (?)", ("x" * 1024,))
    conn.commit()
    return db, conn


def test_sous_le_seuil_sabstient_sans_lever(tmp_path, monkeypatch):
    db, conn = _base_wal(tmp_path)
    try:
        monkeypatch.setattr(F, "DB_PATH", str(db))
        r = F.checkpoint_wal(seuil_mo=10_000)
        assert r["fait"] is False
        assert r["raison"] == "sous le seuil"
        # La taille est RENDUE meme quand rien n'est fait : sans elle, impossible
        # de savoir si le garde dort ou si le WAL est vraiment petit.
        assert r["wal_mo"] >= 0
    finally:
        conn.close()


def test_wal_absent_nest_pas_un_echec(tmp_path, monkeypatch):
    db = tmp_path / "sans_wal.db"
    sqlite3.connect(str(db)).close()
    monkeypatch.setattr(F, "DB_PATH", str(db))
    r = F.checkpoint_wal(seuil_mo=0)
    assert r["fait"] is False
    # Le motif distingue « pas de WAL » de « wal illisible » : deux causes
    # opposees ne doivent pas rendre le meme mot.
    assert r["raison"] == "pas de WAL"


def test_truncate_rend_le_fichier_au_disque(tmp_path, monkeypatch):
    """La connexion reste OUVERTE mais idle — c'est la situation reelle du hub.

    Premiere version de ce test : elle fermait la connexion « pour liberer le
    TRUNCATE ». Or fermer la DERNIERE connexion fait checkpointer SQLite qui
    SUPPRIME le WAL, si bien que le garde rendait « pas de WAL » et le test
    echouait sur un montage impossible. Un lecteur idle, lui, n'empeche pas la
    troncature : c'est exactement ce qu'a mesure le rattrapage du 01/09, ou
    PASSIVE rendait busy=0 alors que le hub tournait.
    """
    db, conn = _base_wal(tmp_path)
    try:
        monkeypatch.setattr(F, "DB_PATH", str(db))
        avant = (Path(str(db) + "-wal")).stat().st_size
        assert avant > 0, "le montage du test ne produit pas de WAL"
        r = F.checkpoint_wal(seuil_mo=0, truncate=True)
        assert r["fait"] is True
        assert r["mode"] == "TRUNCATE"
        apres = (Path(str(db) + "-wal")).stat().st_size
        # LA mesure qui compte : des octets RENDUS, pas des pages « versees ».
        # PASSIVE verse tout et ne rend rien — c'est ce qui avait fait croire
        # le 01/09 que le disque allait respirer.
        assert apres < avant
    finally:
        conn.close()


def test_passive_ne_bloque_pas_un_lecteur(tmp_path, monkeypatch):
    db, conn = _base_wal(tmp_path)
    try:
        monkeypatch.setattr(F, "DB_PATH", str(db))
        r = F.checkpoint_wal(seuil_mo=0)
        assert r["fait"] is True
        assert r["mode"] == "PASSIVE"
        # busy=1 est l'abstention normale sous lecteur, jamais une erreur : le
        # code appelant ne doit pas la traiter comme un echec.
        assert r["busy"] in (0, 1)
    finally:
        conn.close()


def test_le_garde_a_un_appelant():
    """Sans emetteur, un garde ne s'est JAMAIS declenche — mesure du 2026-07-30.
    L'ingestion de veille est le chemin qui a fait exploser le WAL : c'est elle
    qui doit rendre la main au disque entre deux depots."""
    src = (ROOT / "tools" / "forge_veille_clone_ingest.py").read_text(
        encoding="utf-8", errors="replace")
    assert "checkpoint_wal" in src, (
        "forge_veille_clone_ingest n'appelle plus checkpoint_wal : le WAL peut "
        "de nouveau croitre sans borne pendant une campagne")
    # INVOQUE, pas seulement importe : un `import` n'a pas de parenthese. La forme
    # litterale `checkpoint_wal()` interdisait tout appel AVEC arguments -- dont le
    # correctif du 2026-09-23 (`truncate=True`, WAL a 23 Go en PASSIVE).
    import re
    assert re.search(r"\bcheckpoint_wal\(", src), "importe mais jamais invoque"
