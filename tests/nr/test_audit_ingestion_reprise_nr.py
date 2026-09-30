"""NR — l'ingestion de l'audit du corps doit REPRENDRE sur un verrou, pas mourir.

DEFAUT MESURE le 2026-09-08, et decouvert par la PARALLELISATION elle-meme.
Deux jobs tournaient de front — la veille U1 (100 depots) et l'audit
d'autoregulation. L'audit a produit son verdict COMPLET (1894 modules, 16
organes, 0 zone morte), puis est mort a l'ecriture :

    sqlite3.OperationalError: database is locked
    File ".../forge_body_regulation_audit.py", line 699, in ingest_rag

Le job rend rc=1. Or l'AUDIT a reussi : c'est son INGESTION qui a echoue.
Encore `TRANSPORT != APPLICATIF`, le troisieme cas de la journee.

CE QUI EST EN JEU, et ce n'est pas le rc. La regle du corps est explicite :
« une ecriture SQLite qui rend `database is locked` est PERDUE si personne ne la
reprend ». Ici le travail de l'audit — 16 cartes d'organes plus la synthese —
n'a jamais atteint le RAG. Personne ne s'en apercevrait : le log affiche le
verdict, le cache `body_regulation.json` est ecrit, et seul le RAG reste muet.

CE QUI N'ETAIT PAS LE DEFAUT. `ingest_rag` utilise DEJA `open_writer(timeout=60)`,
le patron prouve (WAL + autocommit + busy_timeout). Il n'improvise pas. Mais
`busy_timeout` attend un verrou LIBERABLE, pas un verrou tenu par une
transaction ouverte chez le voisin — c'est ecrit noir sur blanc dans la
docstring de `write_retry`. La parade est d'ENVELOPPER l'ecriture, pas de
changer de connexion.

⚠️ Ce NR n'ecrit JAMAIS dans la base reelle : il fabrique la sienne. La base RAG
pese 22,8 Go et un test qui y ecrit pendant qu'un job ingere reproduirait
exactement l'incident qu'il mesure.
"""

from __future__ import annotations

import ast
import sqlite3
import threading
import time
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (verrou reel) (l.109)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
SOURCE = RACINE / "tools" / "forge_body_regulation_audit.py"


def _db_path():
    import sys

    for chemin in (RACINE, RACINE / "app"):
        if str(chemin) not in sys.path:
            sys.path.insert(0, str(chemin))
    return pytest.importorskip("app.forge_db_path")


def test_le_module_de_base_expose_la_reprise():
    """Sans `write_retry`, le contrat suivant n'aurait pas de remede a exiger."""
    m = _db_path()
    assert hasattr(m, "write_retry"), "forge_db_path.write_retry a disparu"
    assert hasattr(m, "open_writer"), "forge_db_path.open_writer a disparu"


def test_l_ingestion_de_l_audit_passe_par_la_reprise():
    """Contrat statique : l'ecriture RAG de l'audit est enveloppee.

    On cherche l'appel dans l'AST, pas dans le texte : une MENTION en commentaire
    n'est pas un usage -- defaut de capteur paye quatre fois le 2026-09-08.
    """
    arbre = ast.parse(SOURCE.read_text(encoding="utf-8", errors="replace"))
    appels = {
        (getattr(n.func, "id", None) or getattr(n.func, "attr", None))
        for n in ast.walk(arbre) if isinstance(n, ast.Call)
    }
    assert "write_retry" in appels, (
        "l'ingestion RAG de l'audit n'est pas enveloppee dans write_retry : une "
        "ecriture refusee sur verrou est PERDUE, et le verdict de l'audit "
        "n'atteint jamais le RAG (mesure du 2026-09-08, database is locked)"
    )


def test_la_reprise_survit_a_un_voisin_qui_tient_le_verrou(tmp_path, monkeypatch):
    """Le contrat qui MORD : sans reprise, cette ecriture serait perdue.

    Base FABRIQUEE, jamais la vraie. Un thread voisin ouvre une transaction en
    ecriture et la garde ~1,2 s ; l'ecriture protegee doit finir par passer.

    ⚠️ `write_retry(op)` N'ACCEPTE PAS de chemin : il ouvre la base RAG par
    defaut. Premiere version de ce test : elle a donc vise la VRAIE base de
    22,8 Go, et seul un `no such table` l'a empechee d'ecrire — alors que la
    docstring de ce fichier l'interdisait explicitement. On detourne donc
    `open_writer` vers la base fabriquee, ce qui teste la LOGIQUE DE REPRISE
    sans jamais toucher la production.
    """
    m = _db_path()
    base = tmp_path / "essai.db"
    monkeypatch.setattr(
        m, "open_writer",
        lambda timeout=None, path=None: sqlite3.connect(
            str(base), timeout=timeout or 5, isolation_level=None),
    )

    with sqlite3.connect(str(base)) as amorce:
        amorce.execute("PRAGMA journal_mode=WAL")
        amorce.execute("CREATE TABLE t(id TEXT PRIMARY KEY, v TEXT)")

    tenu = threading.Event()
    relache = threading.Event()

    def voisin():
        cx = sqlite3.connect(str(base), timeout=30)
        cx.execute("BEGIN IMMEDIATE")
        cx.execute("INSERT INTO t(id, v) VALUES('voisin', 'x')")
        tenu.set()
        time.sleep(1.2)
        cx.commit()
        cx.close()
        relache.set()

    fil = threading.Thread(target=voisin, daemon=True)
    fil.start()
    assert tenu.wait(5), "le voisin n'a pas pris le verrou : test non concluant"

    def ecrire(conn):
        conn.execute("INSERT OR REPLACE INTO t(id, v) VALUES('audit', 'carte')")

    debut = time.time()
    m.write_retry(ecrire)
    duree = time.time() - debut
    fil.join(timeout=10)

    with sqlite3.connect(str(base)) as verif:
        lignes = {r[0] for r in verif.execute("SELECT id FROM t")}

    assert "audit" in lignes, (
        f"l'ecriture a ete PERDUE malgre la reprise (duree {duree:.2f}s) -- "
        "c'est exactement l'incident du 2026-09-08"
    )
    assert "voisin" in lignes, "le voisin a ete ecrase : la reprise ne doit rien detruire"
