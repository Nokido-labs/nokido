"""NR -- le medecin CHOISIT le traitement selon le diagnostic : un manque INTERNE ne part pas en veille web.

MESURE 2026-09-25 (epreuve owner « comme un vrai medecin ») : le manque d'intention de rang 1 etait
l'item NEXT de la roadmap -- « autopsie RUNTIME de ACP et A2A ... etablir pour forge_acp_adapter
forge_acp_client ... les appelants les consommateurs ». Un manque sur le CODE DE NOKIDO. La soif l'a
envoye en veille WEB : SearXNG en timeout, repli academique, et 35 chunks arXiv ingeres dans la base
vivante -- desintegrations de mesons B, Navier-Stokes-Fourier-« P1 », ondes de spin (« phase »).
Journal : « veille ISSUE : REUSSIE -- ingerees 9 ». Le traitement a REUSSI et le patient va plus mal :
effet IATROGENE. Le web ne documente pas le code de Nokido ; un tel manque se traite par enquete de
code, jamais par une veille.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OBJECTIF_DU_25 = ("Nokido vise : phase P1 autopsie RUNTIME de ACP ET de A2A sans rien construire, etablir pour "
                  "forge_acp_adapter forge_acp_client forge_acp_server forge_a2a_card et forge_a2a_server")


def _demon():
    spec = importlib.util.spec_from_file_location("demon_soif_traitement",
                                                  RACINE / "tools" / "forge_epistemic_daemon.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _depot(tmp_path, *modules):
    for rel in modules:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("# module\n", encoding="utf-8")
    return tmp_path


def test_un_objectif_qui_cite_des_modules_du_depot_est_un_manque_interne(tmp_path, monkeypatch):
    d = _demon()
    monkeypatch.setattr(d, "ROOT", _depot(tmp_path, "app/forge_acp_adapter.py", "tools/forge_a2a_card.py"))
    assert d._modules_du_depot_cites(OBJECTIF_DU_25) == ["forge_acp_adapter", "forge_a2a_card"]
    assert d._manque_interne(OBJECTIF_DU_25) == ["forge_acp_adapter", "forge_a2a_card"]
    # un nom qui n'EXISTE PAS dans le depot n'est pas une preuve de module
    assert d._modules_du_depot_cites("comparer forge_imaginaire a LangGraph") == []
    assert d._manque_interne("etat de l'art du reranking cross-encoder multilingue") == []


# RECIDIVE MESUREE le meme jour, 16:58, apres relance : le rang 1 etait MON fait P0 du tableau noir
# (« Nokido P0 : CORRECTION ... la soif epistemique n est PAS morte, elle est BLOQUEE ... »). Aucun
# module cite -> classe VEILLE -> « REUSSIE, ingerees 10 » sur « epistemologie dependance ». Le critere
# « cite un module » etait trop etroit : les intentions viennent de la ROADMAP de Nokido, elles sont
# du travail interne PAR CONSTRUCTION. Interne par defaut ; externe seulement sur demande EXPLICITE.
OBJECTIF_DE_16H58 = ("Nokido P0 : CORRECTION 2026-09-25 15h35 de ce fait pose le matin meme -- la soif "
                     "epistemique n est PAS morte, elle est BLOQUEE PAR DEPENDANCE")


def test_un_item_de_roadmap_sans_demande_de_savoir_externe_est_interne():
    d = _demon()
    assert d._manque_interne(OBJECTIF_DE_16H58), "item de roadmap classe VEILLE : recidive de 16:58"


def test_seule_une_demande_explicite_de_savoir_externe_part_en_veille():
    d = _demon()
    for q in ("Nokido vise : etat de l'art du protocole A2A de Google",
              "Nokido P1 : lire la specification ACP publiee",
              "Nokido bute sur : RFC 9110 semantique des codes 4xx",
              "Nokido P2 : comprendre https://modelcontextprotocol.io/specification"):
        assert d._manque_interne(q) == [], q


def _cycle(d, monkeypatch, objectif):
    from nokido_agent.app import forge_active_inference as fai
    monkeypatch.setattr(fai, "observe_signal", lambda *a, **k: {})   # JAMAIS la vraie base
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE query_log (query_text TEXT, timestamp REAL)")
    monkeypatch.setattr(d, "_interoceptive_split", lambda *a, **k: {"soif": [], "soin": []})
    monkeypatch.setattr(d, "_intentional_split", lambda *a, **k: [objectif])
    monkeypatch.setattr(d.ev, "coverage_dense", lambda q: {"ok": True, "score": -1.5, "gap": False})
    monkeypatch.setattr(d, "_propose_gap", lambda *a, **k: None)
    monkeypatch.setattr(d, "AUTO_VEILLE", True)
    # Examen declenche SANS reveiller de pilier ni toucher le vrai sandbox/ (2026-09-30 :
    # l'examen exteroceptif a sa porte, la decision de traitement est testee derriere).
    import tempfile
    _tmp = Path(tempfile.mkdtemp(prefix="soif_nr_"))
    monkeypatch.setattr(d, "_decision_examen", lambda besoin: "essai")
    monkeypatch.setattr(d, "_reveiller_piliers", lambda *a, **k: (True, "essai"))
    monkeypatch.setattr(d, "_marque_dernier_examen", lambda: _tmp / "soif_dernier_examen")
    monkeypatch.setattr(d, "_demande_manuelle", lambda: _tmp / "soif_examen.wanted")
    journal, veilles = [], []
    monkeypatch.setattr(d, "_journal", journal.append)
    monkeypatch.setattr(d.ev, "veille_on_gap", lambda q, **k: veilles.append(q) or {"ok": True, "result": {}})
    return d.run_once(conn), journal, veilles


def test_un_manque_interne_ne_part_pas_en_veille_web_et_le_dit(tmp_path, monkeypatch):
    d = _demon()
    monkeypatch.setattr(d, "ROOT", _depot(tmp_path, "app/forge_acp_adapter.py"))
    res, journal, veilles = _cycle(d, monkeypatch, OBJECTIF_DU_25)
    assert veilles == [], "manque INTERNE envoye en veille web : effet iatrogene du 25/09"
    assert res["intention_gap"]["traitement"] == "INTERNE"
    assert res["veilles"] == 0
    assert any("manque INTERNE" in l and "forge_acp_adapter" in l for l in journal), journal


def test_la_recidive_de_16h58_ne_part_pas_en_veille(monkeypatch):
    d = _demon()
    res, journal, veilles = _cycle(d, monkeypatch, OBJECTIF_DE_16H58)
    assert veilles == [] and res["intention_gap"]["traitement"] == "INTERNE"
    assert any("manque INTERNE" in l for l in journal), journal


def test_un_manque_externe_part_toujours_en_veille(tmp_path, monkeypatch):
    d = _demon()
    monkeypatch.setattr(d, "ROOT", _depot(tmp_path, "app/forge_acp_adapter.py"))
    res, _journal, veilles = _cycle(d, monkeypatch, "Nokido vise : etat de l'art du protocole A2A de Google")
    assert len(veilles) == 1
    assert res["intention_gap"]["traitement"] == "VEILLE"
