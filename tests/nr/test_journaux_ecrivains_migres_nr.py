"""NR — les deux ecrivains autonomes passent par l'accesseur, et PAS leurs voisins.

Chantier owner 2026-09-19 : « on ne deplace pas des tables, on retire des
ECRIVAINS du verrou RAG ». Les trois journaux pesaient ~7 900 prises du verrou en
33 h ; token_usage (4 644) et inspector_log (1 954) en font 83 % et sont les deux
seuls a etre AUTONOMES.

`conversation_log` n'est PAS ici, et c'est deliberе : son ecrivain
(`forge_conversation_logger.add_turn`) ecrit dans `conversation_log` ET dans
`rag_chunks` sur la MEME connexion, et ses lecteurs devraient basculer avec lui.
Le migrer a l'aveugle ferait lire les statistiques dans une base ou les tours ne
sont plus ecrits -- un site qui bascule seul.

Contre-epreuve indispensable : `forge_inspector._update_heartbeats` ouvre AUSSI
embeddings.db, deux lignes plus haut, pour `fleet_heartbeats`/`compute_nodes`.
Le rediriger deplacerait les pouls de la flotte dans une base de journal.
"""
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
fdp = importlib.import_module("forge_db_path")


def _sans_env(monkeypatch):
    for variable, _f in fdp._JOURNAUX.values():
        monkeypatch.delenv(variable, raising=False)


def test_token_monitor_resout_l_HISTORIQUE_sans_interrupteur(monkeypatch, tmp_path):
    """La condition qui rend la migration sure : rien ne change tant qu'on n'a
    pas bascule. Verifie par IMPORT REEL, pas par lecture de source.
    """
    _sans_env(monkeypatch)
    monkeypatch.setattr(fdp, "_JOURNAUX_SWITCH", tmp_path / "absent.switch")
    ftm = importlib.import_module("forge_token_monitor")

    assert str(ftm.DB) == fdp.db_path()
    assert os.fspath(ftm.DB) == fdp.db_path(), "les sites font str(DB) ET os.fspath"


def test_token_monitor_suit_la_bascule_a_CHAQUE_acces(monkeypatch, tmp_path):
    """Une constante figee a l'import interdirait la bascule a chaud : le hub
    ecrirait d'un cote et lirait de l'autre.
    """
    _sans_env(monkeypatch)
    ftm = importlib.import_module("forge_token_monitor")
    avant = str(ftm.DB)

    monkeypatch.setenv("LAFORGE_JOURNAL_TOKEN_USAGE_DB", str(tmp_path / "ailleurs.db"))
    pendant = str(ftm.DB)
    monkeypatch.delenv("LAFORGE_JOURNAL_TOKEN_USAGE_DB")
    apres = str(ftm.DB)

    assert pendant.endswith("ailleurs.db") and apres == avant, \
        "le chemin doit etre relu a chaque acces, sans reimport ni reload"


def _sans_interrupteur(monkeypatch, tmp_path):
    """Isoler de l'interrupteur REEL `sandbox/journaux.switch` (pose le 2026-09-23 a
    01h06) : sans cela le test lit l'etat de la machine au lieu de sa propre
    fixture, et rougit des qu'un operateur bascule. Toutes les formes d'import
    du module (deux noms = deux instances), jamais le mecanisme reel."""
    import sys
    absent = tmp_path / "absent.switch"
    for nom in ("forge_db_path", "nokido_agent.app.forge_db_path", "app.forge_db_path"):
        m = sys.modules.get(nom)
        if m is not None and hasattr(m, "_JOURNAUX_SWITCH"):
            monkeypatch.setattr(m, "_JOURNAUX_SWITCH", absent)


def test_le_chemin_de_journal_reste_utilisable_comme_un_chemin(monkeypatch, tmp_path):
    """`DB` etait un Path : ce qui le remplace doit rester PathLike, sinon un
    appelant qui fait Path(DB) casse au premier appel reel, pas au test.
    """
    _sans_env(monkeypatch)
    _sans_interrupteur(monkeypatch, tmp_path)
    ftm = importlib.import_module("forge_token_monitor")
    assert isinstance(ftm.DB, os.PathLike)
    assert Path(ftm.DB) == Path(fdp.db_path())
    assert "token_usage" in repr(ftm.DB), "un repr muet rend le diagnostic impossible"


def test_inspector_redirige_SON_journal_et_PAS_les_pouls_de_la_flotte():
    """Contre-epreuve structurelle : deux `sqlite3.connect` voisins, un seul bouge.

    Lue sur la SOURCE parce que la cible est un bloc `try` au fond d'une boucle
    de supervision : l'executer demanderait de lancer l'inspecteur. Ce que ce
    test garde, c'est le CHOIX du site, qui est precisement ce qu'on peut rater.
    """
    src = (ROOT / "app" / "forge_inspector.py").read_text(encoding="utf-8")
    lignes = src.splitlines()

    i_journal = next(n for n, l in enumerate(lignes)
                     if "CREATE TABLE IF NOT EXISTS inspector_log" in l)
    fenetre = "\n".join(lignes[max(0, i_journal - 12):i_journal])
    assert 'journal_path("inspector_log")' in fenetre, \
        "le connect du journal doit passer par l'accesseur"

    i_pouls = next(n for n, l in enumerate(lignes) if "_update_heartbeats" in l and "def " in l)
    fenetre_pouls = "\n".join(lignes[i_pouls:i_pouls + 8])
    assert "embeddings.db" in fenetre_pouls, \
        "fleet_heartbeats/compute_nodes ne sont PAS un journal : ne pas les deplacer"
    assert "journal_path" not in fenetre_pouls


def test_conversation_log_est_EXPLICITEMENT_hors_perimetre(monkeypatch, tmp_path):
    """Un reste non dit se lit comme un oubli. Il est declare, donc instruit.

    Son ecrivain alimente aussi rag_chunks sur la MEME connexion : le basculer
    enverrait `INSERT INTO rag_chunks` dans une base de journal sans cette table
    -- `OperationalError` a chaque tour, memoire episodique perdue.

    Ce test lisait autrefois la SOURCE (« `journal_path` absent »). Le 2026-09-22
    le site a ete cable quand meme (8752efca9) et ce test l'a arrete en CI ;
    mais une absence de mot ne garde pas la propriete. Decision owner du meme
    soir : conversation_log SORT du perimetre. La garde vit donc dans
    l'ACCESSEUR -- point de decision UNIQUE, que l'ecrivain et ses lecteurs
    cables consultent tous -- et se verifie au RUNTIME, interrupteur pose.
    """
    src = (ROOT / "app" / "forge_conversation_logger.py").read_text(encoding="utf-8")
    assert "INSERT OR REPLACE INTO rag_chunks" in src, \
        "si cette ecriture disparait, le perimetre a change et ce NR doit etre revu"
    assert "conversation_log" in fdp.journaux_connus(), \
        "l'accesseur doit le connaitre : un nom inconnu LEVE"
    assert "conversation_log" in fdp.journaux_retenus(), \
        "conversation_log doit etre declare RETENU, avec sa raison"
    _sans_env(monkeypatch)
    interrupteur = tmp_path / "journaux.switch"
    interrupteur.write_text("test", encoding="utf-8")
    monkeypatch.setattr(fdp, "_JOURNAUX_SWITCH", interrupteur)
    assert fdp.journaux_bascules() is True
    assert fdp.journal_path("conversation_log") == fdp.db_path(), (
        "interrupteur pose : conversation_log a QUITTE la base historique, et son "
        "insert rag_chunks partirait avec lui dans une base qui n'a pas cette table"
    )
