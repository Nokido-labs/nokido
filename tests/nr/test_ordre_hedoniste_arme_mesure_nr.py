# -*- coding: utf-8 -*-
"""NR : l'ordre hedoniste est ARME sur la mesure de tasks.db (decision owner 22/10, rapport_hedoniste_mesure).

Valeur par executeur = (livrees + 1,25) / (touches + 5) sur une fenetre glissante de 14 jours ; score = 0,7 mesure
+ 0,3 amorce (amorce bornee [0 ; 0,25] : elle ne releve ni ne condamne au-dela du prior). PANNE FOURNISSEUR : poids 0 ;
NON LIVRE / VIDE / rejet : punit ; plafond journalier et echec d'auth : neutres ; jamais essaye = 0,25 ;
base illisible -> None (l'appelant garde l'ordre d'amorce).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from nokido_agent.app import forge_motivation as M  # noqa: E402
import forge_task_executor as T  # noqa: E402

NOW = datetime(2026, 10, 22, 20, 0, 0)
LIVRE = "[effet observe] commits produits : 1 (a..b)"
RIEN = "[effet observe] commits produits : 0 (a..a) ; [NON LIVRE] aucun commit"
PANNE = "PANNE FOURNISSEUR : erreur ACP OpenCode (SilenceACP): silence de l'agent depuis 300 s"
NON_LIVRE = "NON LIVRE apres delegation (echec sans livraison)"
PLAFOND = "plafond journalier CLAUDE_HEADLESS atteint"
AUTH = "ECHEC AUTHENTIFICATION : mode permission"


def _iso(jours):
    return (NOW - timedelta(days=jours)).strftime("%Y-%m-%dT%H:%M:%S.000000")


class Base:
    def __init__(self, chemin):
        self.c = sqlite3.connect(chemin)
        self.c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, description TEXT, agent TEXT, status TEXT, result TEXT,"
                       " created_at TEXT, updated_at TEXT, reaffectations TEXT)")
        self.n = 0

    def tache(self, agent, result, jours=1, status="done", renvois=()):
        self.n += 1
        trace = [{"de": de, "vers": agent, "motif": motif, "quand": _iso(jours)[:19]} for de, motif in renvois]
        self.c.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)",
                       (f"t{self.n}", "x", agent, status, result, _iso(jours + 0.1), _iso(jours),
                        json.dumps(trace) if trace else None))

    def renvoi(self, de, motif, jours=1):
        # la tache renvoyee par `de` finit chez MISTRAL (livree) : seul le renvoi sortant de `de` est observe
        self.tache("MISTRAL", LIVRE, jours, renvois=[(de, motif)])

    def fin(self):
        self.c.commit()
        return self.c


@pytest.fixture
def base(tmp_path):
    return Base(tmp_path / "tasks.db")


def _sc(b, cands):
    return M.scores_hedonistes_mesure(cands, b.fin(), now=NOW, resultats=[])


def test_cas_mesure_nemotron_dernier(base):
    # NEMOTRON : 1 livree / 12 recues, 16 NON LIVRE + 3 pannes ; GPTOSS : 12 livrees / 20 recues, 14 pannes
    base.tache("OPENCODE_NEMOTRON", LIVRE)
    for _ in range(11):
        base.tache("OPENCODE_NEMOTRON", RIEN)
    for _ in range(16):
        base.renvoi("OPENCODE_NEMOTRON", NON_LIVRE)
    for _ in range(3):
        base.renvoi("OPENCODE_NEMOTRON", PANNE)
    for _ in range(12):
        base.tache("OPENCODE_GPTOSS", LIVRE)
    for _ in range(8):
        base.tache("OPENCODE_GPTOSS", RIEN)
    for _ in range(14):
        base.renvoi("OPENCODE_GPTOSS", PANNE)
    for _ in range(10):
        base.tache("ANTIGRAVITY", LIVRE)
    for _ in range(3):
        base.tache("ANTIGRAVITY", RIEN)
    ordre = M.ordre_hedoniste_mesure(["OPENCODE_NEMOTRON", "OPENCODE_GPTOSS", "ANTIGRAVITY", "CODEX"], "M:ecrit",
                                     base.fin(), now=NOW, resultats=[])
    assert ordre[-1] == "OPENCODE_NEMOTRON"
    assert ordre[0] == "ANTIGRAVITY"
    s = _sc(base, ["OPENCODE_NEMOTRON"])["OPENCODE_NEMOTRON"]
    # 1 livree, touches = 12 recues + 16 NON LIVRE = 28 (les 3 pannes pesent 0) : v = 2,25/33
    assert s["valeur"] == pytest.approx(2.25 / 33)
    assert s["touches"] == 28 and s["livrees"] == 1


def test_panne_fournisseur_ne_fait_pas_reculer(base):
    for _ in range(5):
        base.tache("OPENCODE_GPTOSS", LIVRE)
    avant = _sc(base, ["OPENCODE_GPTOSS"])["OPENCODE_GPTOSS"]["score"]
    for _ in range(14):
        base.renvoi("OPENCODE_GPTOSS", PANNE)
    assert _sc(base, ["OPENCODE_GPTOSS"])["OPENCODE_GPTOSS"]["score"] == pytest.approx(avant)
    for _ in range(3):
        base.renvoi("OPENCODE_GPTOSS", NON_LIVRE)  # a l'inverse, un NON LIVRE punit pleinement
    assert _sc(base, ["OPENCODE_GPTOSS"])["OPENCODE_GPTOSS"]["score"] < avant


def test_plafond_et_auth_sont_neutres(base):
    base.tache("CLAUDE_HEADLESS", LIVRE)
    avant = _sc(base, ["CLAUDE_HEADLESS"])["CLAUDE_HEADLESS"]["score"]
    for motif in (PLAFOND, AUTH, AUTH):
        base.renvoi("CLAUDE_HEADLESS", motif)
    assert _sc(base, ["CLAUDE_HEADLESS"])["CLAUDE_HEADLESS"]["score"] == pytest.approx(avant)


def test_reponse_vide_et_rejet_punissent(base):
    base.tache("MISTRAL", LIVRE)
    base.tache("MISTRAL", "REPONSE VIDE")
    base.tache("MISTRAL", LIVRE + " ; rejet en relecture")
    s = _sc(base, ["MISTRAL"])["MISTRAL"]
    assert (s["livrees"], s["touches"]) == (1, 3)


def test_fenetre_14_jours(base):
    for _ in range(30):
        base.tache("OPENCODE_GLM", RIEN, jours=20)  # hors fenetre : ignore
    base.renvoi("OPENCODE_GLM", NON_LIVRE, jours=15)  # hors fenetre aussi
    base.tache("OPENCODE_GLM", LIVRE, jours=13)
    s = _sc(base, ["OPENCODE_GLM"])["OPENCODE_GLM"]
    assert (s["livrees"], s["touches"]) == (1, 1)


def test_jamais_essaye_vaut_un_quart(base):
    base.tache("MISTRAL", LIVRE)
    s = _sc(base, ["CODEX"])["CODEX"]
    assert s["score"] == 0.25 and s["touches"] == 0


def test_poids_07_03_et_amorce_bornee(base):
    base.tache("MISTRAL", LIVRE)
    res = [{"repondeur": "MISTRAL", "classe": "M:ecrit", "verdict": "INTEGREE", "minutes": None}]  # amorce 1,0 -> 0,25
    s = M.scores_hedonistes_mesure(["MISTRAL"], base.fin(), now=NOW, resultats=res)["MISTRAL"]
    assert s["score"] == pytest.approx(0.7 * (2.25 / 6) + 0.3 * 0.25)


def test_base_illisible_rend_none(tmp_path):
    p = tmp_path / "tasks.db"
    p.write_bytes(b"pas une base sqlite" * 50)
    assert M.ordre_hedoniste_mesure(["A", "B"], "M:ecrit", sqlite3.connect(p), now=NOW, resultats=[]) is None
    vide = sqlite3.connect(tmp_path / "v.db")  # pas de table tasks
    assert M.ordre_hedoniste_mesure(["A", "B"], "M:ecrit", vide, now=NOW, resultats=[]) is None


def test_reaffecter_suit_l_ordre_mesure(monkeypatch, tmp_path):
    b = Base(tmp_path / "tasks.db")
    for _ in range(6):
        b.tache("MISTRAL", RIEN, jours=0.5)
    b.tache("WORKER_CODE", LIVRE, jours=0.5)
    b.tache("CODEX", "x", status="pending", jours=0.1)  # t8 : la tache a reaffecter
    b.fin()
    chemin = tmp_path / "tasks.db"
    monkeypatch.setattr(T, "_db", lambda: sqlite3.connect(chemin))
    monkeypatch.setattr(T, "_lire_registre", lambda: {"agents": {}})
    monkeypatch.setattr(T, "_executeur_bat", lambda agent, **k: agent in ("MISTRAL", "WORKER_CODE"))
    monkeypatch.setattr(M, "lire_resultats", lambda *a, **k: [])
    monkeypatch.setattr(M, "_maintenant", lambda: NOW)
    assert T._reaffecter({"id": "t8", "agent": "CODEX"}, "quota", ordre=["MISTRAL", "WORKER_CODE"]) == "WORKER_CODE"
    c = sqlite3.connect(chemin)
    t = json.loads(c.execute("SELECT reaffectations FROM tasks WHERE id='t8'").fetchone()[0])[-1]
    assert t["vers"] == "WORKER_CODE" and t["arme"] is True
