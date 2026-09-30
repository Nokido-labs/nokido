# -*- coding: utf-8 -*-
"""NR — la file de taches ne dispute plus le verrou d'ecriture de la base RAG.

Mesure du 2026-09-18. `forge_task_queue` ouvrait NEUF `sqlite3.connect(str(DB))`
bruts avec `DB = ROOT/RAG/embeddings.db`. Ce chemin et celui rendu par
`forge_db_path.db_path()` designent LE MEME FICHIER PHYSIQUE : `V:` est un
lecteur SUBSTITUE vers `Nokido/RAG/` -- meme `dev`, meme `ino`,
`os.path.samefile()` rend True, meme `-wal`, meme verrou.

    %NOKIDO_DATA%\\embeddings.db        dev=8967830048855926842 ino=281474976710724
    RAG/embeddings.db       dev=8967830048855926842 ino=281474976710724

SQLite n'admet qu'UN writer par FICHIER, WAL ou non. La file se battait donc avec
le RAG sans aucun rapport metier.

⚠️ Le defaut etait invisible a la relecture : comparer les deux chemins en TEXTE
rend False. Le faux negatif va dans le sens RASSURANT -- il fait conclure a une
absence de contention qui existe. Ce NR compare par `samefile`, jamais par texte.

Quatre defauts fermes ici, chacun avec sa morsure :
  1. la file vit hors de la base du RAG (interrupteur, patron M2M) ;
  2. `enqueue_many` tient en UNE transaction, pas une par tache ;
  3. la reclamation est ATOMIQUE (plus de fenetre entre SELECT et UPDATE) ;
  4. les deux portes d'ecriture declarent la MEME politique de checkpoint.
"""

from __future__ import annotations

__FORGE_COLOR__ = "infra/db : la file de taches hors de la base du RAG"

import ast
import os
import sqlite3
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from app import forge_db_path as dbp  # noqa: E402

SRC_QUEUE = RACINE / "app" / "forge_task_queue.py"


def test_aucun_connect_nu_dans_le_module():
    """Lecture par AST : ni commentaire ni docstring ne peut faire crier ce test.

    Une version textuelle se serait accusee elle-meme -- le fichier DECRIT le
    defaut qu'il corrige. C'est le piege paye cinq fois dans ce depot.
    """
    arbre = ast.parse(SRC_QUEUE.read_text(encoding="utf-8"))
    fautifs = [
        n.lineno
        for n in ast.walk(arbre)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "connect"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "sqlite3"
    ]
    assert not fautifs, f"connexions nues restantes aux lignes {fautifs}"


def test_morsure_le_scanner_ast_voit_un_vrai_connect(tmp_path):
    """CONTROLE NEGATIF — sans lui, un scanner casse rendrait toujours zero."""
    f = tmp_path / "faux.py"
    f.write_text(
        '"""docstring citant sqlite3.connect(x) sans en etre un."""\n'
        "import sqlite3\n"
        "def g():\n"
        "    return sqlite3.connect('x')\n",
        encoding="utf-8",
    )
    arbre = ast.parse(f.read_text(encoding="utf-8"))
    vus = [
        n.lineno
        for n in ast.walk(arbre)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "connect"
    ]
    assert vus == [4], f"le scanner doit voir la ligne 4 et ignorer la docstring, il rend {vus}"


def test_le_chemin_n_est_pas_fige_a_l_import(monkeypatch, tmp_path):
    """L'interrupteur est relu a CHAQUE appel : un site fige bascule seul."""
    import app.forge_task_queue as TQ

    cible = tmp_path / "ailleurs.db"
    monkeypatch.setenv("LAFORGE_TASKS_DB_PATH", str(cible))
    assert str(TQ.DB) == str(cible), "DB ne suit pas l'interrupteur — il a ete fige"
    monkeypatch.delenv("LAFORGE_TASKS_DB_PATH")
    assert str(TQ.DB) != str(cible), "DB reste colle a l'ancienne valeur"


def test_la_file_ne_pointe_pas_le_meme_fichier_que_le_rag(monkeypatch, tmp_path):
    """LA comparaison qui compte : par inode, jamais par texte."""
    monkeypatch.setenv("LAFORGE_TASKS_DB_PATH", str(tmp_path / "file.db"))
    conn = dbp.open_tasks()
    conn.close()
    a, b = dbp.tasks_path(), dbp.db_path()
    assert os.path.exists(a)
    assert not (os.path.exists(b) and os.path.samefile(a, b)), (
        "la file et le RAG sont le MEME fichier : le verrou d'ecriture reste partage"
    )


def test_morsure_deux_chemins_du_meme_fichier_sont_reconnus(tmp_path):
    """CONTROLE NEGATIF du precedent — `samefile` doit VOIR un alias.

    Sans ce controle, un `samefile` casse rendrait False partout et le test
    ci-dessus passerait au vert en ne prouvant rien.
    """
    f = tmp_path / "base.db"
    f.write_bytes(b"x")
    autre = tmp_path / "." / "base.db"
    assert os.path.samefile(str(f), str(autre)), "samefile ne reconnait pas un alias evident"


def test_enqueue_many_tient_en_une_transaction():
    """Une transaction par tache = N prises du verrou. Le code doit porter le lot."""
    src = SRC_QUEUE.read_text(encoding="utf-8")
    bloc = src[src.index("def enqueue_many") :]
    bloc = bloc[: bloc.index("\ndef ", 1)]
    assert "executemany" in bloc, "enqueue_many n'insere pas en lot"
    assert "BEGIN IMMEDIATE" in bloc, "le lot n'est pas dans une transaction explicite"
    arbre = ast.parse(src)
    fn = next(n for n in ast.walk(arbre)
              if isinstance(n, ast.FunctionDef) and n.name == "enqueue_many")
    appels = [n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert "enqueue" not in appels, (
        "enqueue_many boucle encore sur enqueue : une transaction PAR TACHE"
    )


def test_la_reclamation_est_atomique():
    """SELECT PENDING puis UPDATE RUNNING doivent tenir dans UNE transaction.

    Sinon un second consommateur selectionne les memes lignes entre les deux, et
    la tache part deux fois -- le second resultat ecrasant le premier.
    """
    src = SRC_QUEUE.read_text(encoding="utf-8")
    assert "def _reclamer" in src, "pas de reclamation dediee"
    bloc = src[src.index("def _reclamer") :]
    bloc = bloc[: bloc.index("\nasync def ")]
    assert "BEGIN IMMEDIATE" in bloc, "la reclamation ne prend pas le verrou avant de lire"
    i_sel = bloc.index("SELECT id,title")
    i_upd = bloc.index("UPDATE task_queue SET status='RUNNING'")
    i_com = bloc.index("COMMIT")
    assert i_sel < i_upd < i_com, "selection, marquage et commit ne sont pas dans cet ordre"


def test_le_passage_a_running_a_quitte_process_one():
    """Le laisser aussi dans `_process_one` rouvrirait la fenetre refermee."""
    src = SRC_QUEUE.read_text(encoding="utf-8")
    bloc = src[src.index("async def _process_one") :]
    bloc = bloc[: bloc.index("\ndef _reclamer")]
    lignes = [l for l in bloc.splitlines()
              if "status='RUNNING'" in l and not l.strip().startswith("#")]
    assert not lignes, "_process_one remarque RUNNING : la course est rouverte\n" + "\n".join(lignes)


def test_une_seule_politique_de_checkpoint(tmp_path):
    """Les deux portes d'ecriture doivent declarer la MEME valeur.

    Avant : 500 dans `forge_db.py`, rien dans `open_writer` (donc le defaut
    SQLite, 1000 pages) — pour le MEME fichier. On ne savait pas laquelle
    s'appliquait.
    """
    conn = dbp.open_writer(path=str(tmp_path / "t.db"))
    try:
        valeur = conn.execute("PRAGMA wal_autocheckpoint").fetchone()[0]
    finally:
        conn.close()
    autre = (RACINE / "app" / "forge_db.py").read_text(encoding="utf-8")
    assert "wal_autocheckpoint=%d" % valeur in autre, (
        f"open_writer declare {valeur}, forge_db.py declare autre chose : "
        "deux politiques silencieuses pour un meme fichier"
    )


def test_le_schema_dedie_porte_les_index_manquants(tmp_path):
    """La source n'avait AUCUN index : le worker balayait a chaque reveil."""
    conn = dbp.open_writer(path=str(tmp_path / "q.db"))
    try:
        dbp.ensure_tasks_schema(conn)
        idx = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='task_queue'")]
    finally:
        conn.close()
    assert any("status" in n for n in idx), f"pas d'index sur status : {idx}"


# ── NIVEAU 4 : INTEGRATION SUR LE CHEMIN REEL ────────────────────────────────
#
# Les deux controles ci-dessus (`test_enqueue_many_tient_en_une_transaction`,
# `test_la_reclamation_est_atomique`) lisent la SOURCE. C'est un cliquet de
# niveau 1 : il verrouille la forme du code, pas son comportement. « Le code
# contient BEGIN IMMEDIATE » n'est pas « la reclamation est atomique » -- c'est
# une mention, pas une structure.
#
# Les tests qui suivent EXECUTENT les fonctions contre une vraie base.


@pytest.fixture()
def file_isolee(monkeypatch, tmp_path):
    """Une vraie base de file, vide, hors de tout ce qui tourne."""
    monkeypatch.setenv("LAFORGE_TASKS_DB_PATH", str(tmp_path / "file.db"))
    import app.forge_task_queue as TQ

    TQ._init_table()
    return TQ


def test_execution_enqueue_many_insere_le_lot_et_rend_les_ids(file_isolee):
    TQ = file_isolee
    ids = TQ.enqueue_many([{"title": "t%d" % i, "priority": "NORMAL"} for i in range(25)])
    assert len(ids) == 25, f"25 taches deposees, {len(ids)} ids rendus"
    assert ids == sorted(ids) and ids[-1] - ids[0] == 24, (
        f"les ids ne sont pas contigus : {ids[:3]}..{ids[-3:]} — un autre ecrivain "
        "s'est intercale, ou l'insertion n'est pas dans UNE transaction"
    )
    assert TQ.queue_status().get("PENDING") == 25


def test_execution_enqueue_many_vide_ne_touche_rien(file_isolee):
    assert file_isolee.enqueue_many([]) == []
    assert file_isolee.queue_status() == {}


def test_execution_la_reclamation_ne_sert_pas_deux_fois_la_meme_tache(file_isolee):
    """LE test qui compte : deux reclamations successives ne se recouvrent pas.

    Avant le correctif, `_process_one` posait RUNNING dans une transaction
    SEPAREE du SELECT : un second consommateur pouvait reclamer les memes lignes
    entre les deux. Ici, la premiere reclamation a DEJA marque avant de rendre.
    """
    TQ = file_isolee
    TQ.enqueue_many([{"title": "t%d" % i} for i in range(10)])
    lot1 = TQ._reclamer(4)
    lot2 = TQ._reclamer(4)
    lot3 = TQ._reclamer(4)
    ids1, ids2, ids3 = {r[0] for r in lot1}, {r[0] for r in lot2}, {r[0] for r in lot3}
    assert len(ids1) == 4 and len(ids2) == 4 and len(ids3) == 2
    assert not (ids1 & ids2), f"tache servie deux fois : {sorted(ids1 & ids2)}"
    assert not (ids1 & ids3) and not (ids2 & ids3)
    assert TQ._reclamer(4) == [], "la file devrait etre vide"
    etat = TQ.queue_status()
    assert etat.get("RUNNING") == 10 and "PENDING" not in etat


def test_execution_la_reclamation_respecte_la_priorite(file_isolee):
    TQ = file_isolee
    TQ.enqueue_many([
        {"title": "basse", "priority": "LOW"},
        {"title": "haute", "priority": "HIGH"},
        {"title": "normale", "priority": "NORMAL"},
    ])
    lot = TQ._reclamer(3)
    assert [r[1] for r in lot] == ["haute", "normale", "basse"], (
        "l'ordre de priorite n'est pas respecte par la reclamation"
    )


def test_execution_le_point_d_entree_du_migrateur(tmp_path, monkeypatch):
    """Le migrateur est traverse par son CLI, pas seulement par ses fonctions.

    Mesure du depot (2026-09-06) : `check()` passait ses tests pendant que
    `--check` mourait en NameError. Un drapeau CLI se traverse.
    """
    import runpy

    outil = RACINE / "tools" / "forge_task_queue_db_split.py"
    monkeypatch.setattr(
        sys, "argv", [str(outil), "--copier", "--cible", str(tmp_path / "c.db")]
    )
    try:
        runpy.run_path(str(outil), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"le dry-run du migrateur sort en {e.code}"
    assert not (tmp_path / "c.db").exists(), "le dry-run a ECRIT — il ne doit rien ecrire"


@pytest.mark.parametrize("env,attendu_dedie", [(None, False), ("pose", True)])
def test_l_interrupteur_gouverne_le_chemin(monkeypatch, tmp_path, env, attendu_dedie):
    """Sans interrupteur ni env, le chemin reste celui d'AVANT : la bascule ne
    change rien tant qu'on ne l'a pas demandee."""
    monkeypatch.delenv("LAFORGE_TASKS_DB_PATH", raising=False)
    monkeypatch.setattr(dbp, "_TASKS_SWITCH", tmp_path / "absent.switch")
    assert dbp.tasks_switch_actif() is False
    assert dbp.tasks_path() == dbp.db_path()
    if attendu_dedie:
        monkeypatch.setenv("LAFORGE_TASKS_DB_PATH", str(tmp_path / "d.db"))
        assert dbp.tasks_switch_actif() is True
        assert dbp.tasks_path() != dbp.db_path()


# ---------------------------------------------------------------------------
# Les TROIS etats de la SOURCE du migrateur (mesure 2026-09-19)
# ---------------------------------------------------------------------------

def _migrateur():
    """Importe le migrateur par le chemin reel, `tools/` sur le path.

    Toujours la MEME instance : patcher une seconde instance ne mordrait pas sur
    la premiere (piege des deux noms d'import, 2026-09-10).
    """
    t = str(RACINE / "tools")
    if t not in sys.path:
        sys.path.insert(0, t)
    import forge_task_queue_db_split as M  # noqa: PLC0415

    return M


def _base_avec_file(chemin, lignes=1):
    conn = sqlite3.connect(str(chemin))
    try:
        conn.execute(
            "CREATE TABLE task_queue (id INTEGER PRIMARY KEY, ts TEXT, title TEXT,"
            " role TEXT, priority TEXT, status TEXT, context TEXT, result TEXT,"
            " started_at TEXT, done_at TEXT)"
        )
        for i in range(lignes):
            conn.execute("INSERT INTO task_queue (id, title) VALUES (?, ?)", (i + 1, "t%d" % i))
        conn.commit()
    finally:
        conn.close()
    return chemin


def test_une_base_source_absente_n_est_pas_une_panne(tmp_path):
    """`mode=ro` ne CREE pas le fichier : une base absente levait
    `OperationalError: unable to open database file`.

    Mesure du 2026-09-19 : c'est ce qui a fait echouer
    `test_execution_le_point_d_entree_du_migrateur` en suite complete alors qu'il
    passait 24/24 en isolation. La cause n'etait NI l'ordre des tests NI un etat
    global pollue : la CI tourne dans un worktree detache dont `RAG/embeddings.db`
    a ete cree a 03:14:23, PENDANT la suite. Au moment du test, la base n'existait
    pas encore.

    Une base absente, pour un migrateur, c'est zero ligne a copier -- pas une
    panne. Et ce n'est pas non plus un vide PROUVE : l'etat le DIT.
    """
    M = _migrateur()
    lignes, etat = M._lire(str(tmp_path / "jamais_creee.db"))
    assert lignes == []
    assert etat == "ABSENTE", etat


def test_une_source_presente_est_lue(tmp_path):
    """Contre-epreuve indispensable : sans elle, un `_lire` qui rendrait ABSENTE
    pour TOUT ferait passer le test precedent sans rien prouver."""
    M = _migrateur()
    lignes, etat = M._lire(str(_base_avec_file(tmp_path / "s.db", lignes=3)))
    assert etat == "PRESENTE", etat
    assert len(lignes) == 3


def test_une_source_muette_ne_rend_jamais_identique(tmp_path, monkeypatch):
    """LE faux vert ferme ici : `verifier` comparait deux listes vides et rendait
    IDENTIQUE -- or `main()` imprime « A POSER SEULEMENT si --verifier rend
    IDENTIQUE ». Une source illisible autorisait donc la pose de l'interrupteur
    de bascule sur une base vide.

    Liste BLANCHE : n'est IDENTIQUE que ce qui a ete PROUVE identique sur une
    source effectivement LUE.
    """
    M = _migrateur()
    absente = str(tmp_path / "source_absente.db")
    monkeypatch.setattr(M, "_source", lambda: absente)
    assert M._source() == absente, "la substitution de _source n'a pas mordu"

    r = M.verifier(tmp_path / "cible_absente.db")
    assert r["verdict"] == "INDETERMINE", r
    assert r["source_etat"] == "ABSENTE", r


def test_apply_refuse_d_ecrire_depuis_une_source_muette(tmp_path, monkeypatch):
    """Copier depuis une source muette fabriquerait une cible vide DECLAREE
    migree -- un faux vert au bout de la chaine de bascule."""
    M = _migrateur()
    monkeypatch.setattr(M, "_source", lambda: str(tmp_path / "rien.db"))
    assert not Path(M._source()).exists(), "la substitution de _source n'a pas mordu"

    cible = tmp_path / "c.db"
    r = M.copier(cible, True)
    assert r["applique"] is False, r
    assert "refus" in r, r
    assert not cible.exists(), "une cible a ete ecrite depuis une source muette"
