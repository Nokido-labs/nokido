"""NR : les etats de whoami respectent la constitution (UNKNOWN != NO, STALE != DEAD, liste blanche).

Mesure 6/11 : `providers_available: []` sur mesures de 193 j se lisait « aucun provider », et quatre versions
deleguees rangeaient un agent muet en FAUX, un seul vivant en VRAI global, et inventaient un age de 60 s.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nokido_agent.app.forge_whoami_etats import etats_whoami  # noqa: E402


def _etats(**kw):
    base = {"providers": [], "ecartes": {}, "online": [], "services": {}}
    base.update(kw)
    return etats_whoami(base["providers"], base["ecartes"], base["online"], base["services"])


def test_provider_perime_est_illisible_jamais_faux():
    d = _etats(ecartes={"groq/llama": "mesure perimee (193 j > 7 j)"})["providers"]
    assert d["etat"] == "ILLISIBLE"
    assert d["items"][0]["etat"] == "ILLISIBLE"


def test_provider_prouve_mort_est_faux_et_un_vivant_ne_couvre_pas_un_perime():
    d = _etats(providers=[{"model": "m1"}], ecartes={"m2": "prouve mort", "m3": "mesure perimee"})["providers"]
    assert {i["nom"]: i["etat"] for i in d["items"]} == {"m1": "VRAI", "m2": "FAUX", "m3": "ILLISIBLE"}
    assert d["etat"] == "ILLISIBLE"


def test_aucun_agent_en_ligne_nest_pas_faux():
    d = _etats()["agents_pairs"]
    assert d["etat"] == "ILLISIBLE"
    assert all(i["etat"] == "ILLISIBLE" for i in d["items"])


def test_un_agent_actif_ne_couvre_pas_un_muet_et_aucun_age_invente():
    d = _etats(online=[{"agent": "ANTIGRAVITY", "last": "11:00:00", "msgs": 3}])["agents_pairs"]
    par_nom = {i["agent"]: i for i in d["items"]}
    assert par_nom["ANTIGRAVITY"]["etat"] == "VRAI"
    assert par_nom["ANTIGRAVITY"]["preuve"] == "DECLARE"
    assert "age_s" not in par_nom["ANTIGRAVITY"]
    assert par_nom["CODEX"]["etat"] == "ILLISIBLE"
    assert d["etat"] == "ILLISIBLE"


def test_lignes_sqlite_row_sont_lues_comme_le_vrai_handler():
    import sqlite3

    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    ligne = c.execute("SELECT 'OPENCODE_GLM' AS from_agent, '12:39:08' AS last, 8 AS n").fetchone()
    d = _etats(online=[ligne])["agents_pairs"]
    glm = next(i for i in d["items"] if i["agent"] == "OPENCODE_GLM")
    assert glm["etat"] == "VRAI" and glm["last"] == "12:39:08"


def test_executeurs_decouverts_et_natures_distinctes():
    d = _etats(services={
        "NokidoTaskExecutorCodex": {"status": "running", "uptime_s": 12, "pid": 1},
        "NokidoTaskExecutorMistral": {"status": "sleeping"},
        "NokidoTaskExecutorCline": {"status": "disabled"},
        "NokidoTaskExecutorX": {"status": "crashed"},
        "NokidoTaskExecutorY": {"status": "bizarre"},
        "NokidoAutre": {"status": "running"},
    })["executeurs"]
    par = {i["service"]: i for i in d["items"]}
    assert "NokidoAutre" not in par
    assert par["NokidoTaskExecutorCodex"]["etat"] == "VRAI"
    assert par["NokidoTaskExecutorCodex"]["preuve"] == "DECLARE"
    assert "age_s" not in par["NokidoTaskExecutorCodex"]
    assert par["NokidoTaskExecutorMistral"]["nature"] == "A_LA_DEMANDE"
    assert par["NokidoTaskExecutorCline"]["nature"] == "POLITIQUE"
    assert par["NokidoTaskExecutorX"]["nature"] == "PANNE"
    assert par["NokidoTaskExecutorY"]["etat"] == "ILLISIBLE"
    assert d["etat"] == "ILLISIBLE"


def test_superviseur_injoignable_et_bornes_comptees():
    assert _etats(services=None)["executeurs"]["etat"] == "ILLISIBLE"
    d = _etats(services={f"NokidoTaskExecutor{i}": {"status": "running"} for i in range(20)})["executeurs"]
    assert len(d["items"]) == 12
    assert d["coupes"] == 8


def test_whoami_reel_porte_le_bloc_par_le_handler(tmp_path, monkeypatch):
    import asyncio
    import json

    from nokido_agent.app.forge_mcp_registry import ToolRegistry

    # Hermetique (lot 6, tache/opencode_gptoss/654f8898eb47) : whoami reel ecrit dans une base jetable, pas la vivante.
    monkeypatch.setenv("LAFORGE_DB", str(tmp_path / "db.sqlite3"))
    racine = Path(__file__).resolve().parents[2]
    res = asyncio.run(ToolRegistry(root_dir=racine).handle_hub({"action": "whoami"}, agent="agt_test", ring=1))
    d = json.loads(res)
    assert set(d["status_etats"]) == {"providers", "agents_pairs", "executeurs", "refus_recents"}
    assert "providers_available" in json.dumps(d)  # les champs existants restent


def test_whoami_base_rag_absente_porte_status_etats_et_trace_illisible(tmp_path, monkeypatch):
    import asyncio
    import json
    import sqlite3
    from nokido_agent.app.forge_mcp_registry import ToolRegistry

    real_connect = sqlite3.connect

    def fake_connect(database, *args, **kwargs):
        if str(database).replace("\\", "/").endswith("embeddings.db"):
            raise sqlite3.OperationalError(f"unable to open database file: {database}")
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", fake_connect)

    reg = ToolRegistry(root_dir=tmp_path)
    res = asyncio.run(reg.handle_hub({"action": "whoami"}, agent="agt_test", ring=1))
    d = json.loads(res)
    assert "status_etats" in d
    assert set(d["status_etats"]) == {"providers", "agents_pairs", "executeurs", "refus_recents"}
    assert "providers_available" in json.dumps(d)
    # La partie RAG porte une trace explicite ILLISIBLE
    rag_domains = str(d.get("resources", {}).get("rag_domains", ""))
    assert "ILLISIBLE" in rag_domains


def test_whoami_m2m_connect_leve_m2m_etat_illisible_et_raison_agents_pairs(tmp_path, monkeypatch):
    import asyncio
    import json
    import sqlite3
    from nokido_agent.app.forge_mcp_registry import ToolRegistry

    monkeypatch.setattr("nokido_agent.app.forge_db_path.m2m_path", lambda: str(tmp_path / "m2m_absente.db"))

    real_connect = sqlite3.connect

    def fake_connect(database, *args, **kwargs):
        db_s = str(database).replace("\\", "/")
        if "m2m_absente" in db_s or db_s.endswith("embeddings.db"):
            raise sqlite3.OperationalError(f"unreachable: {database}")
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", fake_connect)

    reg = ToolRegistry()
    res = asyncio.run(reg.handle_hub({"action": "whoami"}, agent="agt_test", ring=1))
    d = json.loads(res)

    assert "ILLISIBLE" in d.get("m2m_etat", "")
    agents_pairs = d.get("status_etats", {}).get("agents_pairs", {})
    assert agents_pairs.get("etat") == "ILLISIBLE"
    assert len(agents_pairs.get("items", [])) > 0
    for it in agents_pairs["items"]:
        assert it["etat"] == "ILLISIBLE"
        assert "base M2M non lue" in it.get("raison", "")


def test_whoami_rag_connect_leve_bascule_eteinte_tools_etat_illisible(monkeypatch):
    import asyncio
    import json
    import sqlite3
    from nokido_agent.app.forge_mcp_registry import ToolRegistry
    import nokido_agent.app.forge_db_path as db_path

    real_connect = sqlite3.connect

    def fake_connect(database, *args, **kwargs):
        if str(database).replace("\\", "/").endswith("embeddings.db"):
            raise sqlite3.OperationalError(f"rag unreachable: {database}")
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", fake_connect)
    monkeypatch.setattr(db_path, "authority_switch_actif", lambda: False)

    reg = ToolRegistry()
    res = asyncio.run(reg.handle_hub({"action": "whoami"}, agent="agt_test", ring=1))
    d = json.loads(res)

    tools_etat = d.get("resources", {}).get("tools_etat", "")
    assert "ILLISIBLE" in tools_etat


def test_refus_recents_se_dit_illisible_et_tient_en_peu_de_place():
    import json

    d = _etats(services={"NokidoTaskExecutorCodex": {"status": "running"}})
    assert d["refus_recents"]["etat"] == "ILLISIBLE"
    assert len(json.dumps(d, ensure_ascii=False)) < 1500
