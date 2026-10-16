"""NR -- le M2M autonome hub <-> AGY : une demande de TRAVAIL atteint l'executeur agy, sans copier-coller.

Owner 2026-10-14 : « repare le M2M autonome entre le hub et AGY autonome, ce n'est pas acceptable les
copier-coller ». Mesure du soir, quatre defauts sur la meme boucle :
  1. postal : un courrier HANDOFF_NEXT (« lis ce dossier, ecris ta reponse ») est repondu par groq,
     « je te remets l'artefact des que termine » -- le repondeur n'execute RIEN ;
  2. agent_messages : le meme intent (categorie routing) recoit un OK_DONE structure SANS travail ;
  3. une notification de tache (method task.*) recoit une reponse bavarde EN PARALLELE du vrai
     travail de l'executeur ;
  4. l'executeur coupe en silence a 3000 caracteres une demande longue.
Ce NR traverse le CHEMIN REEL : tick() postal et _drain_agent_messages() sur une base temporaire,
avec un hub, un firewall et une boite postale factices -- jamais les vrais.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _charger(nom):
    spec = importlib.util.spec_from_file_location(nom + "_sous_test", ROOT / "tools" / (nom + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def agy(tmp_path, monkeypatch):
    mod = _charger("forge_gemini_autonomous_agent")
    monkeypatch.setattr(mod, "_SUIVI_TACHES", tmp_path / "suivi.json")

    def _interdit(*a, **k):
        raise AssertionError("une demande de travail ne doit JAMAIS partir en conversation")
    monkeypatch.setattr(mod, "_local_chat", _interdit)
    return mod


class FauxHub:
    def __init__(self, statuts=None, assign=None):
        self.appels, self.statuts = [], statuts or {}
        self.assign = assign if assign is not None else json.dumps({"ok": True, "task_id": "t1"})

    def tool(self, nom, args):
        self.appels.append((nom, args))
        if args.get("action") == "assign":
            return self.assign
        return json.dumps({"status": self.statuts.get(args.get("task_id"), "pending"),
                           "result_summary": "fait", "error": None})


HANDOFF = json.dumps({"intent": "HANDOFF_NEXT", "pointer_ref": "file:dossier.md",
                      "artefact_attendu": "reponse.md"})


@pytest.mark.parametrize("corps", [
    HANDOFF,
    "[GEMINI-AUTO] " + HANDOFF,
    json.dumps({"text": HANDOFF}),
    json.dumps({"intent": "FACT_PROPOSED", "pointer_ref": "x", "artefact_attendu": "f.md"}),
])
def test_une_demande_de_travail_est_reconnue(agy, corps):
    assert agy.demande_de_travail(corps) is not None


@pytest.mark.parametrize("corps", ["bonjour, tu en penses quoi ?", '{"intent":"COLLAB_PING"}',
                                   '{"intent":"OK_DONE","pointer_ref":"x"}', ""])
def test_une_conversation_n_est_pas_du_travail(agy, corps):
    assert agy.demande_de_travail(corps) is None


def test_le_depot_cree_une_tache_antigravity_et_la_suit(agy):
    hub = FauxHub()
    assert agy.deposer_tache_agy("CLAUDE", "mail_1", HANDOFF, client=hub) == {"task_id": "t1"}
    nom, args = hub.appels[0]
    assert (nom, args["action"], args["agent"], args["intent"]) == ("task", "assign", "ANTIGRAVITY", "HANDOFF_NEXT")
    assert HANDOFF in args["description"] and '"pointer_ref"' in args["description"]
    assert json.loads(agy._SUIVI_TACHES.read_text(encoding="utf-8"))["t1"]["from"] == "CLAUDE"


def test_un_depot_refuse_est_dit_et_rien_n_est_suivi(agy):
    rs, via = agy.reponse_travail("CLAUDE", "mail_1", HANDOFF, client=FauxHub(assign="[Hub] Erreur: GATE_DENIED"))
    assert via == "executeur-agy:KO" and json.loads(rs)["intent"] == "ERR_DEPENDENCY"
    assert not agy._SUIVI_TACHES.exists()


def test_le_resultat_revient_a_l_emetteur_d_origine(agy):
    maintenant = time.time()
    agy._SUIVI_TACHES.write_text(json.dumps({
        "t1": {"from": "CLAUDE", "mail": "m1", "ts": maintenant},
        "t2": {"from": "CODEX", "mail": "m2", "ts": maintenant},
        "t3": {"from": "CLAUDE", "mail": "m3", "ts": maintenant - 2 * 86400}}), encoding="utf-8")
    postes = []
    out = agy.relayer_resultats(lambda *a, **k: postes.append((a, k)), client=FauxHub({"t1": "completed"}),
                                maintenant=maintenant)
    corps = {a[1]: json.loads(a[2].split("] ", 1)[1]) for a, _k in postes}
    assert corps["CLAUDE"]["intent"] in ("OK_DONE", "ERR_TIMEOUT")
    assert {(a[1], json.loads(a[2].split("] ", 1)[1])["intent"]) for a, _k in postes} == {
        ("CLAUDE", "OK_DONE"), ("CLAUDE", "ERR_TIMEOUT")}
    assert set(json.loads(agy._SUIVI_TACHES.read_text(encoding="utf-8"))) == {"t2"}
    assert {o.get("tache") for o in out} >= {"t1", "t3"}


def test_un_suivi_illisible_se_dit(agy):
    agy._SUIVI_TACHES.write_text("{illisible", encoding="utf-8")
    out = agy.relayer_resultats(lambda *a, **k: None, client=FauxHub())
    assert "ILLISIBLE" in out[0]["suivi_taches"]


class FauxFirewall:
    def pre_flight(self, *a, **k):
        return type("PF", (), {"ok": True, "safe_task": None})()

    def post_flight(self, *a, **k):
        return type("PF", (), {"ok": True})()


@pytest.fixture
def corps_isole(agy, monkeypatch):
    import nokido_agent.app.forge_semantic_firewall as fw
    monkeypatch.setattr(fw, "get_firewall", lambda: FauxFirewall())
    hub = FauxHub()
    monkeypatch.setattr(agy, "_client_hub", lambda client=None: hub)
    monkeypatch.setattr(agy, "_reveiller_pool_local", lambda: None)
    monkeypatch.setenv("GEMINI_AUTO_FORCE", "1")
    return hub


def test_chemin_reel_tick_postal(agy, corps_isole, monkeypatch):
    import nokido_agent.app.forge_postal as fp
    import nokido_agent.tools.gemini_poll_daemon as gpd
    postes, acquittes = [], []
    monkeypatch.setattr(gpd, "load_token", lambda *a, **k: "jeton-factice")
    monkeypatch.setattr(fp, "facteur", lambda *a, **k: None)
    monkeypatch.setattr(fp, "secretaire", lambda *a, **k: [{"id": "mail_1", "from": "CLAUDE", "body": HANDOFF}])
    monkeypatch.setattr(fp, "claim", lambda *a, **k: True)
    monkeypatch.setattr(fp, "unclaim", lambda *a, **k: None)
    monkeypatch.setattr(fp, "post", lambda *a, **k: postes.append((a, k)))
    monkeypatch.setattr(fp, "ack_mail", lambda mid, ag: acquittes.append(mid))
    monkeypatch.setattr(agy, "_drain_agent_messages", lambda token: [])
    out = agy.tick()
    assert acquittes == ["mail_1"]
    reponse = postes[0][0][2]
    assert "executeur-agy" in reponse and "tasks.db:t1" in reponse and "HANDOFF_NEXT" in reponse
    assert any(o.get("travail") == "executeur-agy" for o in out)


def test_session_interactive_ouverte_le_travail_part_la_conversation_reste(agy, corps_isole, monkeypatch):
    """Mesure 2026-10-14 : avec AGY ouvert par l'owner, tout etait differe -- le travail n'atteignait
    jamais l'executeur. Desormais seule la CONVERSATION est laissee a la session interactive."""
    import nokido_agent.app.forge_postal as fp
    import nokido_agent.tools.gemini_poll_daemon as gpd
    monkeypatch.delenv("GEMINI_AUTO_FORCE", raising=False)
    monkeypatch.setattr(gpd, "_is_gemini_interactive_running", lambda: True)
    monkeypatch.setattr(gpd, "load_token", lambda *a, **k: "jeton-factice")
    reclames, postes = [], []
    monkeypatch.setattr(fp, "facteur", lambda *a, **k: None)
    monkeypatch.setattr(fp, "secretaire", lambda *a, **k: [
        {"id": "mail_conv", "from": "CLAUDE", "body": "tu en penses quoi ?"},
        {"id": "mail_travail", "from": "CLAUDE", "body": HANDOFF}])
    monkeypatch.setattr(fp, "claim", lambda ag, mid: reclames.append(mid) or True)
    monkeypatch.setattr(fp, "unclaim", lambda *a, **k: None)
    monkeypatch.setattr(fp, "post", lambda *a, **k: postes.append(a))
    monkeypatch.setattr(fp, "ack_mail", lambda *a, **k: None)
    monkeypatch.setattr(agy, "_drain_agent_messages", lambda token: pytest.fail("drain conversationnel en session ouverte"))
    out = agy.tick()
    assert reclames == ["mail_travail"]
    assert len(postes) == 1 and "tasks.db:t1" in postes[0][2]
    assert isinstance(out, list) and any(o.get("travail") == "executeur-agy" for o in out)


def _base_m2m(tmp_path):
    db = tmp_path / "m2m.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, "
                "correlation_id TEXT, method TEXT, payload TEXT, status TEXT, created_at TEXT, read_at TEXT)")
    maintenant = time.strftime("%Y-%m-%d %H:%M:%S")
    con.executemany("INSERT INTO agent_messages (id, from_agent, to_agent, method, payload, status, created_at) "
                    "VALUES (?,?,?,?,?,?,?)", [
                        ("frm_tache", "agt_claude", "agt_antigravity", "task.assign",
                         json.dumps({"text": "mission longue"}), "unread", maintenant),
                        ("frm_travail", "agt_claude", "agt_antigravity", "tool.hub.arg.message",
                         json.dumps({"text": HANDOFF}), "unread", maintenant)])
    con.commit()
    con.close()
    return db


def test_chemin_reel_drain_agent_messages(agy, corps_isole, tmp_path, monkeypatch):
    import nokido_agent.app.forge_db_path as dbp
    db = _base_m2m(tmp_path)
    monkeypatch.setattr(dbp, "m2m_path", lambda *a, **k: db)
    out = agy._drain_agent_messages(None)
    con = sqlite3.connect(db)
    statuts = dict(con.execute("SELECT id, status FROM agent_messages WHERE id LIKE 'frm_t%'").fetchall())
    reponses = [json.loads(p)["text"] for (p,) in con.execute(
        "SELECT payload FROM agent_messages WHERE correlation_id IS NOT NULL").fetchall()]
    con.close()
    assert statuts == {"frm_tache": "read", "frm_travail": "read"}
    assert len(reponses) == 1 and "tasks.db:t1" in reponses[0] and "OK_DONE" not in reponses[0]
    assert any(o.get("tache") == "laissee a l'executeur ANTIGRAVITY (tasks.db)" for o in out)


def test_l_executeur_ne_coupe_plus_une_demande_longue_a_3000():
    ex = _charger("forge_task_executor")
    longue = "consigne " * 700
    assert len(ex._extract_message(longue)) == len(longue) > 3000
    assert len(ex._extract_message("x" * 40000)) == 30000
