"""NR : les effecteurs ARMES du tri (owner 2026-09-30 : « on arme 1 et 2 »).

Relance : n'agit que sur un organe DECLARE actif, FERME A L'INSTANT (re-examen du jour) et
ARRETE au superviseur -- jamais `sleeping` (la regulation l'a endormi), jamais un pilier du
keeper (relancer l'un ou l'autre referait l'anti-phase de la soif du 30/09) ; une demande par
service et par 24 h, puis OWNER_REQUIS une fois.
Routeur : LECTURE SEULE -- dit si le fournisseur toujours en echec est ecarte (dead_end) ;
ne marque rien.
"""
from __future__ import annotations

import importlib
import inspect
import json
import sqlite3
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def AL(tmp_path, monkeypatch):
    m = importlib.import_module("forge_autonomous_loops")
    monkeypatch.setattr(m, "_EVOLUTION_LEDGER", tmp_path / "evolution_experiences.jsonl")  # JAMAIS le vrai
    monkeypatch.setattr(m, "_ensure_ledger_migrated", lambda: None)
    monkeypatch.delenv("LAFORGE_EFFECTEUR_RELANCE", raising=False)
    monkeypatch.delenv("LAFORGE_EFFECTEUR_ROUTEUR", raising=False)
    return m


@pytest.fixture
def ensure_espion(monkeypatch):
    appels = []
    faux = types.ModuleType("nokido_agent.tools.forge_ensure_service")
    faux.ensure = lambda nom, etat: appels.append((nom, etat)) or {"success": True}
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_ensure_service", faux)
    return appels


def _dossier(AL, kind, treatment, **exp):
    eid = AL.record_evolution_experience({"status": "PENDING_CANDIDATE", "parent_commit": "t0",
                                          "kind": kind, **exp})
    AL.record_evolution_experience({"kind": "triage", "status": "TRIAGED_DRY_RUN", "parent_commit": "t0",
                                    "version": AL._TRI_VERSION, "dossier": "d-" + kind,
                                    "treatment": treatment, "experiences": [eid], "n": 1})


def _organe(AL, monkeypatch, statut, piliers=frozenset()):
    _dossier(AL, "organ_down", "RELANCE_OU_OWNER", targets=["essai:9999"])
    monkeypatch.setattr(AL, "_reexaminer", lambda kind, lot: {"par_cible": {"essai:9999": "FERME_A_L_INSTANT"}})
    monkeypatch.setattr(AL, "_politique_des_ports", lambda *a, **k: {
        "etat": "ok", "par_port": {9999: {"noms": ["NokidoEssai"], "actifs": ["NokidoEssai"], "eteints": []}}})
    monkeypatch.setattr(AL, "_statuts_superviseur", lambda: {"NokidoEssai": statut} if statut else {})
    monkeypatch.setattr(AL, "_piliers_du_keeper", lambda: set(piliers))


def _actes(AL, effecteur):
    return [e for e in (json.loads(l) for l in Path(AL._EVOLUTION_LEDGER).read_text(encoding="utf-8").splitlines() if l)
            if e.get("kind") == "effecteur" and e.get("effecteur") == effecteur]


def test_un_organe_arrete_est_relance_une_fois_puis_remonte_a_l_owner(AL, monkeypatch, ensure_espion):
    _organe(AL, monkeypatch, "stopped")
    r1 = AL.pat_evolution_effecteurs()
    assert [f["acte"] for f in r1["relance"]] == ["RELANCE_DEMANDEE"]
    assert ensure_espion == [("NokidoEssai", "running")]
    r2 = AL.pat_evolution_effecteurs()          # toujours ferme au passage suivant
    assert [f["acte"] for f in r2["relance"]] == ["OWNER_REQUIS"]
    assert len(ensure_espion) == 1, "relance repetee dans les 24 h"
    r3 = AL.pat_evolution_effecteurs()
    assert r3["relance"] == [], "OWNER_REQUIS redit a chaque passage"
    assert [a["status"] for a in _actes(AL, "relance")] == ["RELANCE_DEMANDEE", "OWNER_REQUIS"]


@pytest.mark.parametrize("statut, piliers", [
    ("sleeping", ()),                      # endormi par la regulation : un CHOIX du corps
    ("stopped", ("NokidoEssai",)),         # pilier du keeper : il l'eteint quand il ne sert plus
    (None, ()),                            # superviseur illisible : on n'agit pas a l'aveugle
])
def test_jamais_contre_la_regulation_ni_a_l_aveugle(AL, monkeypatch, ensure_espion, statut, piliers):
    _organe(AL, monkeypatch, statut, piliers)
    r = AL.pat_evolution_effecteurs()
    assert [f["acte"] for f in r["relance"]] == ["ABSTENTION"]
    assert ensure_espion == []
    assert _actes(AL, "relance") == []


def test_le_drapeau_desarme_la_relance(AL, monkeypatch, ensure_espion):
    monkeypatch.setenv("LAFORGE_EFFECTEUR_RELANCE", "0")
    _organe(AL, monkeypatch, "stopped")
    r = AL.pat_evolution_effecteurs()
    assert r["armes"]["relance"] is False and r["relance"] == []
    assert ensure_espion == []


def _motivation(tmp_path, monkeypatch, lignes):
    from nokido_agent.app import forge_motivation as mot
    db = tmp_path / "motivation.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE motivation_failures (method TEXT, target TEXT, failure_count INT, "
                "last_failure_at REAL, last_error TEXT, dead_end INT)")
    con.executemany("INSERT INTO motivation_failures VALUES (?,?,?,?,?,?)", lignes)
    con.commit()
    con.close()
    monkeypatch.setattr(mot, "DEFAULT_DB", db)
    return db


@pytest.mark.parametrize("lignes, attendu", [
    ([], "NON_ECARTE"),
    ([("llm_call:mistral", "chat", 9, 0.0, "401", 1)], "ECARTE_PAR_LE_ROUTEUR"),
])
def test_le_routeur_est_verifie_en_lecture_seule(AL, monkeypatch, tmp_path, lignes, attendu):
    _dossier(AL, "usage_findings", "ROUTEUR_A_VERIFIER", findings={"low_success": [{"tool": "mistral"}]})
    monkeypatch.setattr(AL, "_reexaminer", lambda kind, lot: {
        "par_cible": {"mistral": "TOUJOURS_EN_ECHEC"}, "mesures": {"mistral": {"n": 10, "succes_pct": 0.0}}})
    db = _motivation(tmp_path, monkeypatch, lignes)
    avant = db.read_bytes()
    r = AL.pat_evolution_effecteurs()
    assert r["routeur"] == [{"outil": "mistral", "verdict": attendu}]
    assert db.read_bytes() == avant, "la verification a ecrit dans la table du routeur"
    assert AL.pat_evolution_effecteurs()["routeur"] == [], "verifie deux fois dans les 24 h"


def test_la_verification_du_routeur_ne_marque_jamais_rien(AL):
    src = inspect.getsource(AL._effecteur_routeur)
    for geste in ("punish(", "revive_dead_end(", "INSERT", "UPDATE", "DELETE"):
        assert geste not in src, "la verification du routeur marque : %s" % geste
