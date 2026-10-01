"""NR -- la soif epistemique bloquee par une dependance le DIT, et DECLARE son besoin.

MESURE 2026-09-25 : pouls frais (vivante, serie epistemic_gaps n=1218, dernier cycle 15:26), mais
journal muet depuis le 30/08 -- un cycle qui n'examine rien n'ecrivait RIEN (run L568-570). J'en
avais conclu « morte depuis 26 jours » : lecture FAUSSE tiree d'une source qui se tait. Cause
mesuree : coverage_dense exige le reranker :8100 (REFUSED), appele en direct par urllib -- donc
SANS poser `rerank.wanted`, l'intention que lit le rallumeur (forge_llama_keeper._piliers_on_demand).
BLOQUE_PAR_DEPENDANCE n'est pas DEAD : ca se dit, et le besoin se declare.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (code appele) (l.75)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_db_path as fdb  # noqa: E402
from nokido_agent.app import forge_embed_router as er  # noqa: E402
from nokido_agent.app import forge_epistemic_veille as ev  # noqa: E402


class _Rep:
    def __init__(self, d):
        self.d = d

    def read(self):
        return json.dumps(self.d).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _faux_urlopen(refuse_rerank: bool):
    def urlopen(req, timeout=None):
        url = req.full_url
        if ":8099/" in url:
            return _Rep({"data": [{"embedding": [0.1, 0.2]}]})
        if ":6333/" in url:
            return _Rep({"result": [{"payload": {"chunk_id": "c1"}}]})
        if ":8100/" in url:
            if refuse_rerank:
                raise ConnectionRefusedError(10061, "connexion refusee")
            return _Rep({"results": [{"relevance_score": 1.0}]})
        raise AssertionError("appel inattendu : %s" % url)
    return urlopen


@pytest.fixture
def base(tmp_path, monkeypatch):
    db = tmp_path / "rag.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT)")
    c.execute("INSERT INTO rag_chunks VALUES ('c1', 'un texte de corpus')")
    c.commit()
    c.close()
    monkeypatch.setattr(fdb, "db_path", lambda *a, **k: db)
    return db


def test_reranker_muet_pose_l_intention_et_nomme_la_dependance(base, monkeypatch):
    poses = []
    monkeypatch.setattr(er, "declare_wanted", lambda flag, cooldown=300.0, motif="": poses.append(flag) or True)
    monkeypatch.setattr("urllib.request.urlopen", _faux_urlopen(refuse_rerank=True))
    cov = ev.coverage_dense("comment fonctionne le coffre DPAPI de nokido")
    assert cov["ok"] is False and cov["error"].startswith("rerank KO")
    assert cov["dependance"] == "reranker :8100" and cov["intention_posee"] is True
    assert poses == ["rerank.wanted"]


def _demon():
    spec = importlib.util.spec_from_file_location("demon_soif", RACINE / "tools" / "forge_epistemic_daemon.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_le_cycle_compte_ses_abstentions_par_dependance(monkeypatch, tmp_path):
    d = _demon()
    # Examen declenche, piliers annonces prets, sandbox/ redirige (2026-09-30) : ce test
    # garde le COMPTE des abstentions quand un pilier tombe EN COURS d'examen.
    monkeypatch.setattr(d, "_decision_examen", lambda besoin: "essai")
    monkeypatch.setattr(d, "_reveiller_piliers", lambda *a, **k: (True, "essai"))
    monkeypatch.setattr(d, "_marque_dernier_examen", lambda: tmp_path / "soif_dernier_examen")
    monkeypatch.setattr(d, "_demande_manuelle", lambda: tmp_path / "soif_examen.wanted")
    from nokido_agent.app import forge_active_inference as fai
    monkeypatch.setattr(fai, "observe_signal", lambda *a, **k: {})   # JAMAIS la vraie base
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE query_log (query_text TEXT, timestamp REAL)")
    conn.execute("INSERT INTO query_log VALUES ('une vraie question assez longue', 1)")
    monkeypatch.setattr(d, "_interoceptive_split", lambda *a, **k: {"soif": [], "soin": []})
    monkeypatch.setattr(d, "_intentional_split", lambda *a, **k: [])
    monkeypatch.setattr(d.ev, "coverage_dense", lambda q: {
        "ok": False, "error": "rerank KO: refuse", "dependance": "reranker :8100", "intention_posee": True})
    r = d.run_once(conn)
    assert r["examinees"] == 0
    assert r["abstentions"] == {"reranker :8100": 1}


def test_le_keeper_n_est_arme_qu_en_mode_piliers_seuls():
    """Decision owner 2026-09-25 : le keeper est REARME pour servir rerank.wanted, mais il avait ete
    gele (05/09) pour un deadlock de sa fonction CODER. Arme SANS le mode piliers, il relancerait le
    coder : le garde refuse cette configuration dans le SSoT des services."""
    import tomllib
    services = tomllib.loads((RACINE / "proxy_deno" / "core" / "services.toml").read_text(encoding="utf-8"))["service"]
    [k] = [s for s in services if s["name"] == "NokidoLlamaKeeper"]
    if not k.get("disabled", False):
        assert k.get("env", {}).get("LAFORGE_LLAMA_KEEPER_PILIERS_ONLY") in ("1", "true"), \
            "keeper arme SANS le mode piliers seuls : il relancerait le coder (deadlock du 19/08)"


def test_le_regulateur_des_piliers_n_est_pas_endormi_par_la_rafale_ram():
    """MESURE 2026-09-25 16:01:29 (journal du superviseur) : « Sleeping NokidoLlamaKeeper (uptime
    340s) » -- la rafale RAM (supervisor.ts, memPct > RAM_SLEEP_PCT) endort TOUS les non-essentiels
    de plus de 5 min, le keeper compris. Or le keeper EST la regulation fine des piliers : il ne
    rallume que sur intention ACCORDEE et RAM <= RELOAD_OK, et eteint l'inutile. Endormi, plus
    personne n'entend `rerank.wanted`/`embed.wanted` (soif bloquee sur :8099) ni n'eteint un pilier
    oisif. Decision owner : l'exempter SANS empecher l'autoregulation -- `neverSleep` n'exempte que
    de la rafale ; l'eviction CIBLEE (POST /supervisor/sleep/<nom>) reste possible. La soif, simple
    consommatrice, reste soumise a la rafale."""
    import tomllib
    services = tomllib.loads((RACINE / "proxy_deno" / "core" / "services.toml").read_text(encoding="utf-8"))["service"]
    par_nom = {s["name"]: s for s in services}
    keeper = par_nom["NokidoLlamaKeeper"]
    if not keeper.get("disabled", False):
        assert keeper.get("neverSleep") is True, "regulateur des piliers endormi par la rafale RAM"
    assert not par_nom["NokidoEpistemicSoif"].get("neverSleep"), \
        "la soif est une CONSOMMATRICE : elle reste soumise a la regulation RAM (decision owner)"


def test_l_issue_d_une_veille_est_dite_pas_seulement_son_lancement():
    """MESURE 2026-09-25 16:01 : « veille lancee sur gap INTENTION » au journal, et RIEN sur son
    issue -- le resultat de veille_on_gap etait ignore. REQUESTED n'est pas ACHIEVED : un medecin
    constate l'effet de son traitement."""
    d = _demon()
    reussie = {"deport": False, "ok": True, "result": {
        "ok": True, "found": 7, "ingested": 3, "synthesis_ok": True, "llm_provider": "gemini_pro",
        "search_errors": []}}
    ligne = d._issue_veille(reussie)
    assert "ingerees 3" in ligne and "synthese OK" in ligne and "gemini_pro" in ligne
    echec = d._issue_veille({"deport": False, "ok": False, "error": "HTTPError 404 model_decommissioned"})
    assert echec.startswith("ECHEC") and "404" in echec
    vide = d._issue_veille({"deport": False, "ok": True, "result": {
        "ok": True, "found": 0, "ingested": 0, "synthesis_ok": False, "llm_provider": "none",
        "search_errors": ["searxng muet"]}})
    assert vide.startswith("SANS EFFET") and "searxng muet" in vide
    src = (RACINE / "tools" / "forge_epistemic_daemon.py").read_text(encoding="utf-8")
    assert "_issue_veille(" in src.split("def run_once", 1)[1]


def test_le_journal_dit_le_blocage_une_fois_puis_le_deblocage():
    d = _demon()
    bloque = {"examinees": 0, "gaps": 0, "abstentions": {"reranker :8100": 3}}
    ok = {"examinees": 2, "gaps": 0, "abstentions": {}}
    etat, lignes = None, []
    for res in (bloque, bloque, bloque, ok, ok):
        etat, ligne = d._transition_blocage(etat, res)
        if ligne:
            lignes.append(ligne)
    assert len(lignes) == 2, lignes
    assert lignes[0].startswith("BLOQUE_PAR_DEPENDANCE") and "reranker :8100" in lignes[0]
    assert lignes[1].startswith("DEBLOQUE")
