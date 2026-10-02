# -*- coding: utf-8 -*-
"""NR -- un appelant SYNCHRONE publie vraiment son fait au tableau noir (2026-10-01).

`propose_fact` n'a jamais existe dans forge_swarm_blackboard : forge_comm_watch et
forge_presence l'importaient, l'ImportError tombait dans leur except (851 avertissements
de comm_watch, un `pass` muet chez presence) et AUCUN de leurs faits n'a atteint le
tableau noir. Ce NR traverse le CHEMIN REEL (`_alert`, `_emit_arrival` depuis une boucle
comme dans le hub) contre une base jetable posee sur l'instance que ces modules importent
(`nokido_agent.app...`) -- deux noms d'import feraient deux instances, et le test
ecrirait dans la vraie base.
"""
import ast
import asyncio
import importlib
import sqlite3
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

NOM_BB = "nokido_agent.app.forge_swarm_blackboard"
# Modules dont un nom importe ABSENT a deja tue une publication en silence : le cliquet
# AST les couvre tous. Le faux module ci-dessous imite la VRAIE signature (`persist`) --
# une premiere version imitait `emit`, le nom mort, et masquait le defaut.
CIBLES_CLIQUET = ("forge_swarm_blackboard", "forge_critical_events")
EVENEMENTS: list = []


@pytest.fixture
def bb(tmp_path, monkeypatch):
    paquet = importlib.import_module("nokido_agent.app")
    EVENEMENTS.clear()

    def persist(kind, severity, payload=None):
        EVENEMENTS.append((kind, severity, dict(payload or {})))
        return len(EVENEMENTS)
    for nom, attr, fonction in (("forge_critical_events", "persist", persist),
                                ("forge_intention_journal", "record", lambda **k: None)):
        faux = types.ModuleType("nokido_agent.app." + nom)
        setattr(faux, attr, fonction)
        monkeypatch.setitem(sys.modules, "nokido_agent.app." + nom, faux)
        monkeypatch.setattr(paquet, nom, faux, raising=False)
    m = importlib.import_module(NOM_BB)
    monkeypatch.setattr(m, "_DB", tmp_path / "swarm.db")
    monkeypatch.setattr(m, "_writer_conn", None)
    monkeypatch.setattr(m, "_write_lock", None)
    m.init_db()
    yield m
    if m._writer_conn is not None:
        m._writer_conn.close()


def _faits(m):
    c = sqlite3.connect(str(m._DB))
    try:
        return {k: (v, w) for k, v, w in c.execute(
            "SELECT key, value, worker_id FROM swarm_blackboard WHERE zone = 'discovered_facts'")}
    finally:
        c.close()


def _attendre_les_taches(m):
    async def _att():
        for _ in range(200):
            if not m._TACHES_FOND:
                return
            await asyncio.sleep(0.01)
    return _att()


def test_aucun_import_d_un_nom_absent_du_blackboard_ni_des_evenements():
    absents = []
    for cible in CIBLES_CLIQUET:
        m = importlib.import_module("nokido_agent.app." + cible)
        for dossier in ("app", "tools"):
            for f in sorted((ROOT / dossier).glob("*.py")):
                if f.name.startswith("tmp_"):
                    continue  # brouillons d'agents, souvent non versionnes : pas des organes
                texte = f.read_text(encoding="utf-8", errors="replace")
                if cible + " import" not in texte:
                    continue
                for n in ast.walk(ast.parse(texte)):
                    if isinstance(n, ast.ImportFrom) and (n.module or "").endswith(cible):
                        absents += ["%s/%s:%d %s.%s" % (dossier, f.name, n.lineno, cible, a.name)
                                    for a in n.names if a.name != "*" and not hasattr(m, a.name)]
    assert not absents, "noms importes qui n'existent pas : %s" % absents


def test_sans_boucle_le_fait_est_ecrit(bb):
    r = bb.apply_fact_sync("discovered_facts", "fait temoin", key="k1", source="nr", ring=2)
    assert r.get("ok") is True
    assert _faits(bb)["k1"] == ("fait temoin", "nr")


def test_le_ring_par_defaut_est_refuse_sans_exception(bb):
    r = bb.apply_fact_sync("discovered_facts", "fait temoin", key="k0", source="nr")
    assert "ACL" in (r.get("error") or "")
    assert "k0" not in _faits(bb)


def test_dans_une_boucle_la_tache_est_posee_puis_ecrite(bb):
    async def scenario():
        r = bb.apply_fact_sync("discovered_facts", "fait boucle", key="k2", source="nr", ring=2)
        assert r == {"ok": None, "planifie": True, "zone": "discovered_facts"}
        await _attendre_les_taches(bb)
    asyncio.run(scenario())
    assert _faits(bb)["k2"] == ("fait boucle", "nr")


def test_comm_watch_publie_ses_changements(bb):
    cw = importlib.import_module("forge_comm_watch")
    cw._alert([{"brick": "brique_nr", "change": "modifie", "detail": "detail nr"}])
    valeur, auteur = _faits(bb)["comm_watch_last"]
    assert auteur == "comm_watch" and "brique_nr" in valeur
    assert [(k, s) for k, s, _ in EVENEMENTS] == [("comm_brick_change", "warn")]
    assert "brique_nr" in EVENEMENTS[0][2]["detail"]


def test_un_profil_interdit_ne_casse_pas_comm_watch(monkeypatch):
    # Sous le compte du shell sandbox, Path.exists LEVAIT sur C:/Users/<autre>/.codex :
    # forge_comm_watch ne se chargeait pas, le correctif ci-dessus n'aurait jamais tourne.
    cw = importlib.import_module("forge_comm_watch")
    vrai = Path.exists

    def exists(self, *a, **k):
        if self.name == ".codex":
            raise PermissionError(5, "Acces refuse", str(self))
        return vrai(self, *a, **k)
    monkeypatch.setattr(Path, "exists", exists)
    monkeypatch.delenv("LAFORGE_OWNER_HOME", raising=False)
    assert isinstance(cw._owner_home(), Path)


def test_presence_publie_l_arrivee_depuis_la_boucle_du_hub(bb):
    pr = importlib.import_module("forge_presence")

    async def scenario():
        pr._emit_arrival("AGENT_NR")
        await _attendre_les_taches(bb)
    asyncio.run(scenario())
    assert _faits(bb)["presence_arrival_AGENT_NR"] == ("AGENT_NR present (arrived)", "forge_presence")
    for _ in range(200):  # l'evenement part dans un thread (hors boucle du hub)
        if EVENEMENTS:
            break
        time.sleep(0.01)
    assert [(k, s) for k, s, _ in EVENEMENTS] == [("cli_present", "info")]
