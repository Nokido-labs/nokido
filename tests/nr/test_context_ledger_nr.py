# -*- coding: utf-8 -*-
"""NR -- contexte servi par Nokido : index de POINTEURS, sans copie (decision owner 2026-11-08).

Exigence owner : « Nokido doit capter et agreger les contextes distants des LLM et agents pour ne
servir precisement que ce qui sert a chaque reponse, en ne servant localement de facon deterministe
que la matiere utile, avec des payloads pointant vers la matiere utile en local. »

Ces NR sont ecrits ROUGES avant le module (`app/forge_context_ledger.py`, code par AGY). Ils fixent
le contrat, pas l'implementation :

  ContextLedger(db_path, racine, messages_db=None, depot_git=None)
    - db_path sous <racine>/sandbox/, jamais `embeddings.db` (sinon ValueError) ;
  .indexer(uri, essence="", meta=None) -> dict    (cles au moins : uri, sha256)
  .resoudre(uri) -> str                           (contenu exact pointe)
      agent_messages://<id>      -> champ "content" du payload JSON de la ligne (messages_db)
      ccr://<id>                 -> <racine>/sandbox/ccr/<id>.txt   (forge_mcp_registry._archive_blob)
      run_sortie://<nom>         -> <racine>/sandbox/run_sorties/<nom> (forge_run_sortie.borner)
      git://<commit>:<chemin>    -> blob git (contenu adresse : rejeu bit a bit)
  .invalider(uri, superseded_by)                  (meme vocabulaire que rag_chunks : jamais supprime)
  .servir(requete, budget_car) -> {"payload": str, "manifeste": {"entrees": [{"uri", "sha256", ...}]}}
  .rejouer(manifeste) -> str                      (== payload au caractere pres ; ValueError si une
                                                    source a change depuis : le sha256 le prouve)

Amendements de Claude retenus par l'owner, chacun tenu ici :
  - aucune copie de texte dans l'index (essence <= 150 caracteres seulement) ;
  - aucun masquage a la CAPTURE : la source n'est jamais reecrite, le masquage vit au service ;
  - un fait invalide n'est pas servi ;
  - la base vit sous sandbox/, jamais dans embeddings.db.

Interdit : aucun test ne touche la base RAG vivante ; tout tourne en tmp_path.
"""
import hashlib
import importlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEXTE_LONG = "".join("ligne %04d du journal de l'outil, matiere utile alpha-%d\n" % (i, i * 7) for i in range(120))


def _module():
    # Import DANS le test : sans le module, chaque NR tombe ROUGE (jamais un skip silencieux).
    return importlib.import_module("nokido_agent.app.forge_context_ledger")


def _sha(octets):
    return hashlib.sha256(octets).hexdigest()


@pytest.fixture()
def corps(tmp_path):
    racine = tmp_path / "racine"
    (racine / "sandbox" / "ccr").mkdir(parents=True)
    (racine / "sandbox" / "run_sorties").mkdir(parents=True)
    (racine / "sandbox" / "ccr" / "ccr_aaaa000000000001.txt").write_text(TEXTE_LONG, encoding="utf-8")
    (racine / "sandbox" / "ccr" / "ccr_aaaa000000000002.txt").write_text(
        "pointeur stable, rejeu deterministe, alpha-21 obsolete\n" * 10, encoding="utf-8")
    (racine / "sandbox" / "run_sorties" / "run_20261108_120000_deadbeef.txt").write_text(
        "sortie bornee complete alpha-14\n" * 30, encoding="utf-8")
    msgs = tmp_path / "messages.db"
    conn = sqlite3.connect(str(msgs))
    conn.execute("CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, "
                 "correlation_id TEXT, method TEXT, payload TEXT, status TEXT, created_at TEXT)")
    conn.execute("INSERT INTO agent_messages VALUES (?,?,?,?,?,?,?,?)",
                 ("msg_1", "cli_claude", "cli_capture", "sess", "conversation.turn",
                  json.dumps({"role": "user", "content": "tour capture alpha-7 " * 20, "session": "sess"}),
                  "unread", "2026-11-08T12:00:00Z"))
    conn.commit()
    conn.close()
    led = _module().ContextLedger(db_path=racine / "sandbox" / "context_ledger.db", racine=racine,
                                  messages_db=msgs)
    return {"racine": racine, "msgs": msgs, "led": led}


def test_base_dans_sandbox_jamais_embeddings(tmp_path):
    mod = _module()
    racine = tmp_path / "r"
    (racine / "sandbox").mkdir(parents=True)
    with pytest.raises(ValueError):
        mod.ContextLedger(db_path=racine / "sandbox" / "embeddings.db", racine=racine)
    with pytest.raises(ValueError):
        mod.ContextLedger(db_path=tmp_path / "ailleurs.db", racine=racine)


def test_index_sans_copie_de_texte(corps):
    led, racine = corps["led"], corps["racine"]
    ent = led.indexer("ccr://ccr_aaaa000000000001", essence="journal de l'outil")
    assert ent["sha256"] == _sha((racine / "sandbox" / "ccr" / "ccr_aaaa000000000001.txt").read_bytes())
    conn = sqlite3.connect(str(racine / "sandbox" / "context_ledger.db"))
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for t in tables:
        for ligne in conn.execute("SELECT * FROM \"%s\"" % t):
            for v in ligne:
                if isinstance(v, (str, bytes)):
                    s = v.decode("utf-8", "replace") if isinstance(v, bytes) else v
                    assert len(s) <= 2000 or TEXTE_LONG[:200] not in s, "copie du texte dans l'index"
                    for k in range(0, len(TEXTE_LONG) - 200, 400):
                        assert TEXTE_LONG[k:k + 200] not in s, "copie du texte dans %s" % t
    conn.close()


def test_uri_resolus_vers_la_matiere_locale(corps, tmp_path):
    led, racine = corps["led"], corps["racine"]
    assert led.resoudre("ccr://ccr_aaaa000000000001") == TEXTE_LONG
    assert led.resoudre("run_sortie://run_20261108_120000_deadbeef.txt") == "sortie bornee complete alpha-14\n" * 30
    assert led.resoudre("agent_messages://msg_1") == "tour capture alpha-7 " * 20
    if not shutil.which("git"):
        pytest.fail("git absent : la resolution git:// ne peut pas etre prouvee")
    depot = tmp_path / "depot"
    depot.mkdir()
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "nr@local"],
                ["git", "config", "user.name", "nr"]):
        subprocess.run(cmd, cwd=depot, check=True)
    (depot / "f.py").write_text("V = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.py"], cwd=depot, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "v1"], cwd=depot, check=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=depot, check=True,
                            capture_output=True, text=True, errors="replace").stdout.strip()
    (depot / "f.py").write_text("V = 2\n", encoding="utf-8")  # l'arbre change, le blob non
    led_git = _module().ContextLedger(db_path=racine / "sandbox" / "ledger_git.db", racine=racine,
                                      depot_git=depot)
    assert led_git.resoudre("git://%s:f.py" % commit) == "V = 1\n"


def test_fait_invalide_non_servi(corps):
    led = corps["led"]
    led.indexer("ccr://ccr_aaaa000000000001", essence="journal alpha")
    led.indexer("ccr://ccr_aaaa000000000002", essence="rejeu alpha obsolete")
    led.invalider("ccr://ccr_aaaa000000000002", superseded_by="ccr://ccr_aaaa000000000001")
    servi = led.servir("alpha", budget_car=4000)
    uris = [e["uri"] for e in servi["manifeste"]["entrees"]]
    assert "ccr://ccr_aaaa000000000002" not in uris
    assert "alpha-21 obsolete" not in servi["payload"]


def test_manifeste_rejoue_au_caractere_et_deterministe(corps):
    led, racine = corps["led"], corps["racine"]
    led.indexer("ccr://ccr_aaaa000000000001", essence="journal alpha")
    led.indexer("run_sortie://run_20261108_120000_deadbeef.txt", essence="sortie alpha")
    led.indexer("agent_messages://msg_1", essence="tour alpha")
    a = led.servir("alpha", budget_car=4000)
    b = led.servir("alpha", budget_car=4000)
    assert a["payload"] == b["payload"], "meme requete, meme corps : meme payload"
    assert a["payload"] and len(a["payload"]) <= 4000
    assert all(e.get("sha256") for e in a["manifeste"]["entrees"])
    assert led.rejouer(json.loads(json.dumps(a["manifeste"]))) == a["payload"]
    (racine / "sandbox" / "ccr" / "ccr_aaaa000000000001.txt").write_text("autre chose\n", encoding="utf-8")
    with pytest.raises(ValueError):
        led.rejouer(a["manifeste"])


def test_uri_confinees_a_leur_magasin(corps, tmp_path):
    """Relecture 8/11 du rendu AGY : `ccr://../../x` et un chemin ABSOLU (la jointure Path jette
    la racine) lisaient hors de sandbox/ ; `git://--output=...` passait une OPTION a git show."""
    led, racine = corps["led"], corps["racine"]
    dehors = tmp_path / "secret_hors_magasin.txt"
    dehors.write_text("hors magasin\n", encoding="utf-8")
    for uri in ("ccr://../../../secret_hors_magasin.txt",
                "ccr://" + str(dehors),
                "run_sortie://../../../secret_hors_magasin.txt",
                "run_sortie://" + str(dehors)):
        with pytest.raises(ValueError):
            led.resoudre(uri)
    temoin = tmp_path / "ecrit_par_git.txt"
    for uri in ("git://--output=%s:f.py" % temoin, "git://HEAD~1:f.py", "git://-p:f.py"):
        with pytest.raises(ValueError):
            led.resoudre(uri)
    assert not temoin.exists(), "git a recu une option depuis l'URI"


def test_pointeurs_morts_purges_et_cables_a_la_retention(corps):
    """Gate firehose 8/11 : table context_ledger sans purge. Un pointeur ccr/run_sortie dont la
    cible a disparu ne se sert ni ne se rejoue : il part. agent_messages et git restent."""
    led, racine = corps["led"], corps["racine"]
    led.indexer("ccr://ccr_aaaa000000000002", essence="alpha")
    led.indexer("agent_messages://msg_1", essence="alpha")
    (racine / "sandbox" / "ccr" / "ccr_aaaa000000000002.txt").unlink()
    assert led.purger_pointeurs_morts(dry=True)["morts"] == 1
    assert led.purger_pointeurs_morts()["purges"] == 1
    conn = sqlite3.connect(str(racine / "sandbox" / "context_ledger.db"))
    restants = sorted(r[0] for r in conn.execute("SELECT uri FROM context_ledger"))
    conn.close()
    assert restants == ["agent_messages://msg_1"]
    src = (ROOT / "tools" / "forge_log_retention.py").read_text(encoding="utf-8")
    assert "purger_pointeurs_morts" in src, "purge non cablee dans run_retention"


def test_payload_hybride_nomme_chaque_source(corps):
    """Decision 8/11 : « payload hybride, jamais un pointeur nu » -- ni un contenu anonyme.
    Chaque morceau servi est precede de son en-tete `[source: <uri> ...]` ; le rejeu le refait."""
    led = corps["led"]
    led.indexer("ccr://ccr_aaaa000000000001", essence="journal alpha")
    led.indexer("agent_messages://msg_1", essence="tour alpha")
    servi = led.servir("alpha", budget_car=4000)
    assert len(servi["manifeste"]["entrees"]) == 2
    for e in servi["manifeste"]["entrees"]:
        assert "[source: %s" % e["uri"] in servi["payload"], "morceau servi sans sa source"
    assert len(servi["payload"]) <= 4000
    assert led.rejouer(servi["manifeste"]) == servi["payload"]


def test_pointeur_perime_signale_jamais_servi_en_silence(corps):
    """Le sha256 de l'index n'etait pas compare au service : une source changee depuis
    l'indexation etait servie comme si de rien n'etait. Elle va dans `perimes`, pas au payload."""
    led, racine = corps["led"], corps["racine"]
    led.indexer("ccr://ccr_aaaa000000000001", essence="journal alpha")
    led.indexer("run_sortie://run_20261108_120000_deadbeef.txt", essence="sortie alpha")
    (racine / "sandbox" / "ccr" / "ccr_aaaa000000000001.txt").write_text("change alpha\n", encoding="utf-8")
    servi = led.servir("alpha", budget_car=4000)
    assert [e["uri"] for e in servi["manifeste"]["entrees"]] == ["run_sortie://run_20261108_120000_deadbeef.txt"]
    assert servi["manifeste"].get("perimes") == ["ccr://ccr_aaaa000000000001"]
    assert "change alpha" not in servi["payload"]


def test_jeton_court_ne_ramene_pas_tout(corps):
    """Selection par sous-chaine : « a » matchait toutes les essences. Jetons de 3 caracteres
    au moins, compares aux MOTS de l'essence."""
    led = corps["led"]
    led.indexer("ccr://ccr_aaaa000000000001", essence="journal outil")
    led.indexer("ccr://ccr_aaaa000000000002", essence="rejeu deterministe")
    servi = led.servir("a rejeu", budget_car=4000)
    assert [e["uri"] for e in servi["manifeste"]["entrees"]] == ["ccr://ccr_aaaa000000000002"]


def test_aucun_masquage_a_la_capture(corps):
    led, racine, msgs = corps["led"], corps["racine"], corps["msgs"]
    sources = [racine / "sandbox" / "ccr" / "ccr_aaaa000000000001.txt",
               racine / "sandbox" / "run_sorties" / "run_20261108_120000_deadbeef.txt"]
    avant = [_sha(p.read_bytes()) for p in sources]
    conn = sqlite3.connect(str(msgs))
    payload_avant = conn.execute("SELECT payload FROM agent_messages WHERE id='msg_1'").fetchone()[0]
    conn.close()
    for u in ("ccr://ccr_aaaa000000000001", "run_sortie://run_20261108_120000_deadbeef.txt",
              "agent_messages://msg_1"):
        led.indexer(u, essence="alpha")
    led.servir("alpha", budget_car=500)
    assert [_sha(p.read_bytes()) for p in sources] == avant, "une source capturee a ete reecrite"
    conn = sqlite3.connect(str(msgs))
    assert conn.execute("SELECT payload FROM agent_messages WHERE id='msg_1'").fetchone()[0] == payload_avant
    conn.close()
