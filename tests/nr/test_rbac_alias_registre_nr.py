# -*- coding: utf-8 -*-
"""NR -- le garde RBAC du hub resout l'alias d'une surface vers SA cle de registre (10/11).

MESURE QUI L'A DECLENCHE. `web_search` refuse a la session Claude Code branchee en OAuth :
`GATE_DENIED rbac:cap=web_search`. Lecture de `forge_entities` (job_716a7a87ecc3) : l'entite
`agt_oauth_nkc_nb_...` est ABSENTE ; `config/agent_identities.json` la declare pourtant alias de
`CLAUDE_CLI`. `forge_hub_gate._check_rbac` interrogeait le nom brut et n'avait AUCUNE voie pour
suivre l'alias : toute surface OAuth etait refusee sur tout outil a capacite. Aucune voie gouvernee
non plus pour inscrire une capacite (`forge_rbac` ne savait que lire).

Decision owner 10/11 (choix multiple) : « web_search seul » -- entite `agt_claude_cli` portant la
SEULE capacite web_search, alias resolu vers la CLE du registre (jamais vers l'acteur CLAUDE, qui
porte vault_read, task_approve, write_db, run_python).

Contrat :
  1. `octroyer` est en DRY-RUN par defaut : rien n'est ecrit ;
  2. la NAISSANCE reste a `forge_rbac_mapping.create_mapping` (pas de second chemin) : `octroyer`
     refuse une entite inconnue, puis AJOUTE sans jamais retirer, et laisse une ligne d'audit ;
  3. une capacite hors `CAPABILITY_REGISTRY` est refusee (pas d'ecriture) ;
  4. `forge_videur.cle_registre` rend la cle du registre pour un alias, None pour un inconnu ;
  5. le garde : entite brute absente + alias connu -> la cle du registre decide (web_search passe) ;
  6. le garde reste fail-closed : alias inconnu -> refus ; la cle n'herite PAS des droits de l'acteur ;
  7. une entite brute presente decide seule (le repli ne s'applique pas).
"""
from __future__ import annotations

import asyncio
import importlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ALIAS = "agt_oauth_nkc_test_alias"


def _base(tmp_path: Path) -> Path:
    db = tmp_path / "rbac.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE forge_entities (entity_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, "
              "display_name TEXT, ring_level INTEGER NOT NULL, capabilities TEXT, is_active INTEGER DEFAULT 1, "
              "meta TEXT, last_seen TEXT)")
    c.execute("INSERT INTO forge_entities VALUES ('agt_claude','llm','Claude',1,?,1,'{}',NULL)",
              (json.dumps(["web_search", "vault_read", "run_python"]),))
    c.execute("INSERT INTO forge_entities VALUES ('agt_brut','llm','Brut',1,?,1,'{}',NULL)",
              (json.dumps(["read_db"]),))
    c.commit()
    c.close()
    return db


def _registre(tmp_path: Path) -> Path:
    reg = tmp_path / "agent_identities.json"
    reg.write_text(json.dumps({"agents": {
        "CLAUDE_CLI": {"ring": 1, "actor": "CLAUDE", "mailbox": "CLAUDE", "aliases": ["agt_claude_cli", ALIAS]},
        "CLAUDE": {"ring": 1, "actor": "CLAUDE", "mailbox": "CLAUDE", "aliases": ["agt_claude"]},
    }}), encoding="utf-8")
    return reg


@pytest.fixture()
def rbac_mod():
    return importlib.import_module("nokido_agent.app.forge_rbac")


def _naitre(db: Path, eid: str = "agt_claude_cli", ring: int = 1):
    fm = importlib.import_module("nokido_agent.app.forge_rbac_mapping")
    return fm.create_mapping(eid, entity_type="llm", ring_level=ring, actor="NR", reason="NR", db_path=db)


@pytest.fixture()
def videur_mod(tmp_path, monkeypatch):
    m = importlib.import_module("nokido_agent.app.forge_videur")
    monkeypatch.setattr(m, "_STORE", _registre(tmp_path))
    if hasattr(m, "_CLE_CACHE"):
        monkeypatch.setattr(m, "_CLE_CACHE", {"mtime": None, "index": {}})
    return m


def test_octroyer_dry_run_n_ecrit_rien(tmp_path, rbac_mod):
    db = _base(tmp_path)
    _naitre(db)
    r = rbac_mod.RBACMiddleware(db)
    out = r.octroyer("agt_claude_cli", ["web_search"], motif="NR")
    assert out["ecrit"] is False and out["apres"] == ["web_search"]
    assert r.get_entity("agt_claude_cli", refresh=True)["capabilities"] == []


def test_entite_inconnue_refusee_pas_de_second_chemin_de_naissance(tmp_path, rbac_mod):
    r = rbac_mod.RBACMiddleware(_base(tmp_path))
    out = r.octroyer("agt_claude_cli", ["web_search"], motif="NR", ecrire=True)
    assert out["ecrit"] is False and "create_mapping" in out["refus"]
    with pytest.raises(rbac_mod.EntityNotFound):
        r.get_entity("agt_claude_cli", refresh=True)


def test_octroi_ajoute_sans_retirer_et_laisse_une_trace(tmp_path, rbac_mod):
    db = _base(tmp_path)
    _naitre(db)
    r = rbac_mod.RBACMiddleware(db)
    assert r.octroyer("agt_claude_cli", ["web_search"], actor="NR", motif="NR", ecrire=True)["ecrit"]
    assert r.get_entity("agt_claude_cli", refresh=True)["capabilities"] == ["web_search"]
    r.octroyer("agt_claude_cli", ["read_db"], actor="NR", motif="NR", ecrire=True)
    assert r.get_entity("agt_claude_cli", refresh=True)["capabilities"] == ["read_db", "web_search"]
    c = sqlite3.connect(str(db))
    n = c.execute("SELECT count(*) FROM rbac_mapping_audit WHERE entity_id='agt_claude_cli' "
                  "AND reason LIKE 'octroi:%'").fetchone()[0]
    c.close()
    assert n == 2


def test_capacite_inconnue_refusee(tmp_path, rbac_mod):
    db = _base(tmp_path)
    _naitre(db)
    r = rbac_mod.RBACMiddleware(db)
    out = r.octroyer("agt_claude_cli", ["tout_faire"], motif="NR", ecrire=True)
    assert out["ecrit"] is False and out["inconnues"] == ["tout_faire"]
    assert r.get_entity("agt_claude_cli", refresh=True)["capabilities"] == []


def test_cle_registre(videur_mod):
    assert videur_mod.cle_registre(ALIAS) == "CLAUDE_CLI"
    assert videur_mod.cle_registre(ALIAS.upper()) == "CLAUDE_CLI"
    assert videur_mod.cle_registre("claude_cli") == "CLAUDE_CLI"
    assert videur_mod.cle_registre("agt_inconnu") is None


def _verdict(gate, agent, outil="web_search"):
    return asyncio.run(gate._check_rbac(outil, {}, agent, 1, ""))


@pytest.fixture()
def gate(tmp_path, rbac_mod, videur_mod, monkeypatch):
    db = _base(tmp_path)
    r = rbac_mod.RBACMiddleware(db)
    monkeypatch.setattr(rbac_mod, "_default_rbac", r)
    return importlib.import_module("nokido_agent.app.forge_hub_gate"), r, db


def test_garde_suit_l_alias_vers_la_cle(gate):
    g, r, db = gate
    _naitre(db)
    r.octroyer("agt_claude_cli", ["web_search"], motif="NR", ecrire=True)
    ok, detail = _verdict(g, ALIAS[len("agt_"):].upper())
    assert ok is True, detail


def test_garde_fail_closed_et_sans_heritage_de_l_acteur(gate):
    g, r, db = gate
    # cle CLAUDE_CLI absente du RBAC : l'acteur CLAUDE (qui a web_search) ne doit PAS repondre a sa place
    ok, _ = _verdict(g, ALIAS[len("agt_"):].upper())
    assert ok is False
    ok, _ = _verdict(g, "INCONNU_TOTAL")
    assert ok is False


def test_entite_brute_presente_decide_seule(gate):
    g, r, db = gate
    ok, _ = _verdict(g, "BRUT")  # agt_brut existe, sans web_search
    assert ok is False
