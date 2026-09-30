"""NR -- le TRI des experiences d'evolution : chaque manque recoit un traitement, a blanc d'abord.

MESURE 2026-09-25 (P1, plan owner P0-P7 du 22/08) : registre sandbox/evolution/evolution_experiences.jsonl,
658 entrees dont 652 PENDING_CANDIDATE. Six producteurs dans forge_autonomous_loops (organ_down,
capability_lost, regression_hypothesis, unmet_intention, usage_findings, parameter_proposal), ZERO
consommateur : les 6 requalifications presentes ont ete ecrites a la main. La variation existait, la
selection (forge_mutation_judge) aussi -- le maillon entre les deux, choisir le traitement selon le
diagnostic, n'existait pas. Decision owner : un tri A BLANC d'abord (il ecrit sa decision, n'execute
rien), armement traitement par traitement ensuite ; la promotion d'un code reste le commit owner.
"""
from __future__ import annotations

import importlib
import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def AL(tmp_path, monkeypatch):
    m = importlib.import_module("forge_autonomous_loops")
    led = tmp_path / "evolution_experiences.jsonl"
    monkeypatch.setattr(m, "_EVOLUTION_LEDGER", led)                 # JAMAIS le vrai registre
    monkeypatch.setattr(m, "_ensure_ledger_migrated", lambda: None)
    return m


def _exp(AL, **k):
    rec = {"status": "PENDING_CANDIDATE", "parent_commit": "test0000", **k}
    return AL.record_evolution_experience(rec)


def _lire(AL):
    return [json.loads(l) for l in Path(AL._EVOLUTION_LEDGER).read_text(encoding="utf-8").splitlines() if l]


def test_chaque_kind_recoit_son_traitement_et_l_inconnu_n_est_jamais_ecarte(AL):
    t = {k: AL._trier({"kind": k, "organ": "x", "hypothesis": "h"})[0] for k in (
        "organ_down", "usage_findings", "unmet_intention", "capability_lost",
        "regression_hypothesis", "parameter_proposal", "kind_venu_d_ailleurs")}
    assert t["organ_down"] == "RELANCE_OU_OWNER"
    assert t["usage_findings"] == "ROUTEUR_A_VERIFIER"
    # CORRECTION du meme jour : `unmet_intention` est un ECART DOC/CODE (« module forge_X.py decrit
    # dans docs/... mais absent du code »), pas une affaire de soif -- classe d'apres le NOM du kind,
    # sans lire son producteur (pat_unmet_intention_docs). La faute que la journee traquait.
    assert t["unmet_intention"] == "ECART_DOC_CODE"
    assert t["capability_lost"] == t["regression_hypothesis"] == "MUTATION_CODE_JUGEE"
    assert t["parameter_proposal"] == "APPLICATEUR_SI_ACTION_DECLAREE"
    assert t["kind_venu_d_ailleurs"] == "INDETERMINE"


def test_un_dossier_une_decision_a_blanc_et_idempotent(AL):
    a = _exp(AL, kind="usage_findings", organ="tools", hypothesis="tools a faible succes",
             findings={"low_success": [{"tool": "groq", "n": 262, "success_pct": 0}]})
    b = _exp(AL, kind="usage_findings", organ="tools", hypothesis="tools a faible succes", ts="2026-09-25T10:00:00")
    c = _exp(AL, kind="organ_down", organ="NokidoX", hypothesis="organe down soutenu")
    r = AL.pat_evolution_triage()
    assert r["a_blanc"] is True and r["dossiers_decides"] == 2 and r["experiences_couvertes"] == 3
    tri = [e for e in _lire(AL) if e.get("kind") == "triage"]
    assert {t["status"] for t in tri} == {"TRIAGED_DRY_RUN"}
    usage = next(t for t in tri if t["source_kind"] == "usage_findings")
    assert sorted(usage["experiences"]) == sorted([a, b]) and usage["treatment"] == "ROUTEUR_A_VERIFIER"
    assert "groq" in json.dumps(usage["evidence"])
    # idempotent : rien de nouveau -> aucune decision nouvelle
    assert AL.pat_evolution_triage()["dossiers_decides"] == 0
    # une nouvelle experience du MEME dossier -> une decision qui ne couvre QUE la nouvelle
    d = _exp(AL, kind="organ_down", organ="NokidoX", hypothesis="organe down soutenu", ts="2026-09-25T11:00:00")
    r3 = AL.pat_evolution_triage()
    assert r3["dossiers_decides"] == 1 and r3["experiences_couvertes"] == 1
    assert [t for t in _lire(AL) if t.get("kind") == "triage"][-1]["experiences"] == [d]
    assert c not in [t for t in _lire(AL) if t.get("kind") == "triage"][-1]["experiences"]


# ── RE-EXAMEN (decision owner 2026-09-25) : une experience ancienne est STALE, pas DEAD. Avant tout
# traitement, le tri RELIT le manque avec l'instrument MEME qui l'a ouvert, maintenant.

def test_reexamen_organe_down_par_la_sonde_et_la_politique_du_producteur(AL, monkeypatch):
    monkeypatch.setattr(AL, "_port_ouvert", lambda port: port == 7400)
    monkeypatch.setattr(AL, "_politique_des_ports", lambda *a, **k: {"etat": "lue", "ports": {}})
    monkeypatch.setattr(AL, "_classer_ports_fermes", lambda fermes, pol: (
        [f for f in fermes if f.endswith(":8766")], [f for f in fermes if f.endswith(":5557")],
        [f for f in fermes if f.endswith(":9999")]))
    r = AL._reexaminer("organ_down", [{"targets": ["webhub:7400", "brain_worker:5557"]},
                                      {"targets": ["hub_mcp:8766", "x:9999"]}])
    assert r["par_cible"] == {"webhub:7400": "RESOLU", "brain_worker:5557": "CHOIX_DE_CONFIGURATION",
                              "hub_mcp:8766": "FERME_A_L_INSTANT", "x:9999": "INDETERMINE"}
    assert r["verdict"] == "A_TRAITER"          # au moins une cible encore fermee et declaree active


def test_reexamen_ecart_doc_code_par_l_instrument_du_producteur(AL, monkeypatch):
    # Docs d'INTENTION (liste blanche du 2026-09-25) : un doc quelconque n'ouvre plus d'intention.
    monkeypatch.setattr(AL, "_modules_absents_des_docs", lambda: [{"module": "forge_b.py", "source_doc": "docs/x_plan.md"}])
    assert AL._reexaminer("unmet_intention", [{"target_module": "forge_a.py", "source_doc": "docs/y_plan.md"}])["verdict"] == "RESOLU"
    assert AL._reexaminer("unmet_intention", [{"target_module": "forge_b.py", "source_doc": "docs/x_plan.md"}])["verdict"] == "A_TRAITER"
    assert AL._reexaminer("unmet_intention", [{"target_module": "forge_X.py",
                                              "source_doc": "docs/adr/000-template.md"}])["verdict"] == "FAUX_POSITIF_GABARIT"


def test_reexamen_usage_par_les_traces_recentes(AL, monkeypatch):
    monkeypatch.setattr(AL, "_succes_recent_des_outils", lambda outils: {"groq": (262, 0), "mistral": (40, 80)})
    r = AL._reexaminer("usage_findings", [
        {"findings": {"low_success": [{"tool": "cohere", "n": 80, "success_pct": 0}]}},
        {"findings": {"low_success": [{"tool": "groq", "n": 253, "success_pct": 0},
                                      {"tool": "mistral", "n": 56, "success_pct": 0}]}}])
    assert r["par_cible"] == {"groq": "TOUJOURS_EN_ECHEC", "mistral": "RESOLU", "cohere": "INDETERMINE"}
    assert r["verdict"] == "A_TRAITER"


def test_une_decision_sans_reexamen_est_redecidee(AL, monkeypatch):
    """Les 142 decisions du premier cycle (sans re-examen, et avec le mauvais traitement pour
    unmet_intention) ne couvrent plus : le dossier est redecide, en ajout, jamais en ecrasement."""
    monkeypatch.setattr(AL, "_modules_absents_des_docs", lambda: [])
    a = _exp(AL, kind="unmet_intention", organ="intention_doc", target_module="forge_z.py",
             source_doc="docs/z_plan.md", hypothesis="module forge_z.py decrit mais absent")
    AL.record_evolution_experience({"kind": "triage", "status": "TRIAGED_DRY_RUN", "dossier": "v1",
                                    "treatment": "SOIF", "experiences": [a], "parent_commit": "t"})
    r = AL.pat_evolution_triage()
    assert r["dossiers_decides"] == 1
    der = [t for t in _lire(AL) if t.get("kind") == "triage"][-1]
    assert der["treatment"] == "ECART_DOC_CODE" and der["reexamen"]["verdict"] == "RESOLU"


def test_une_decision_d_un_instrument_perime_est_rejugee(AL, monkeypatch):
    """26/09 : les 142 decisions du 25/09 19h59 portaient les verdicts de capteurs reconnus FAUX
    depuis (unmet_intention en liste noire, CALL lu comme echec). Re-examinees, elles couvraient
    leurs experiences POUR TOUJOURS : le tri reel rendait 0 dossier decide. Une decision d'une
    version d'instrument anterieure ne couvre plus -- rejugee en ajout, jamais en ecrasement."""
    monkeypatch.setattr(AL, "_modules_absents_des_docs", lambda: [])
    a = _exp(AL, kind="unmet_intention", organ="intention_doc", target_module="forge_z.py",
             source_doc=".aider.chat.history.md", hypothesis="module forge_z.py decrit mais absent")
    AL.record_evolution_experience({"kind": "triage", "status": "TRIAGED_DRY_RUN", "version": 2,
                                    "dossier": "v2", "treatment": "ECART_DOC_CODE",
                                    "reexamen": {"verdict": "A_TRAITER"}, "experiences": [a],
                                    "parent_commit": "t"})
    r = AL.pat_evolution_triage()
    assert r["dossiers_decides"] == 1
    der = [t for t in _lire(AL) if t.get("kind") == "triage"][-1]
    assert der["version"] == AL._TRI_VERSION and der["reexamen"]["verdict"] == "MENTION_HORS_INTENTION"
    assert AL.pat_evolution_triage()["dossiers_decides"] == 0     # la nouvelle decision couvre


def test_a_blanc_le_tri_n_appelle_aucun_effecteur():
    """Tant que l'owner n'a arme aucun traitement, le tri ECRIT sa decision et n'agit sur rien."""
    m = importlib.import_module("forge_autonomous_loops")
    src = inspect.getsource(m.pat_evolution_triage) + inspect.getsource(m._trier) + inspect.getsource(m._reexaminer)
    for effecteur in ("appliquer(", "ensure(", "submit_candidate_to_judge", "juger_module", "veille_on_gap",
                      "subprocess", "declare_wanted"):
        assert effecteur not in src, "le tri a blanc appelle un effecteur : %s" % effecteur
