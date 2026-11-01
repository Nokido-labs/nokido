"""TDD — `ps_clm` doit lier l'autorite obtenue a celle du demandeur.

MESURE DU 2026-09-12. La branche `sandbox == "ps_clm"` de `handle_run` ne
consulte AUCUN ring. Elle ne verifie que l'attestation DEV, qui est un
interrupteur GLOBAL : une fois armee par l'owner pour un motif legitime, tout
appelant capable d'atteindre le handler obtient une execution sous
`NT AUTHORITY\\Systeme`.

Qui peut l'atteindre : `run` est plafonne a 2 par la table RBAC et a 3 par
`_get_ring_needed` — la plus stricte gagne, donc **ring 2 (TRUSTED)**.
Autrement dit, attestation armee ⇒ ring 2 ⇒ SYSTEM.

L'ASYMETRIE QUI LE REND FLAGRANT, et que le commentaire du code nomme
lui-meme : `console`, qui ne donne que la session UTILISATEUR, est garde
ring-0 default-deny ; `ps_clm`, qui donne SYSTEM, ne l'est par rien. Le garde
est inverse par rapport au privilege accorde.

CHOIX DU PLANCHER, et pourquoi pas 0 : l'attestation s'appelle « DEV » et le
canal documente pour lire le profil owner est `ps_clm` depuis un client de
ring 1. Un plancher a 0 couperait ce canal meme owner-arme ; un plancher a 1
exclut ring 2 et au-dela sans rien casser de documente. La comparaison avec le
plancher de `console` (0) reste un arbitrage OWNER, pas une evidence : les
deux n'exposent pas la meme chose.

ORDRE DES DEUX GARDES — il fait partie du contrat : le plancher de ring est
verifie AVANT l'attestation. C'est le controle le moins cher, et surtout c'est
ce qui rend la propriete TESTABLE sans armer quoi que ce soit ni lancer le
moindre PowerShell. Un test qui devrait armer l'attestation pour verifier le
ring executerait du code SYSTEM pour prouver une borne.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import os
import sqlite3

@pytest.fixture(autouse=True)
def _setup_corrigibility_db(tmp_path, monkeypatch):
    db_file = tmp_path / "embeddings.db"
    db_file.touch()
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE IF NOT EXISTS corrigibility_state (key TEXT PRIMARY KEY, value TEXT, set_by TEXT, reason TEXT, ts REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS opsec_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, set_by TEXT, reason TEXT, updated_at REAL NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS opsec_audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, old_level TEXT, new_level TEXT, set_by TEXT, reason TEXT, ts REAL NOT NULL)")
    conn.commit()
    conn.close()
    monkeypatch.setenv("LAFORGE_DB", str(db_file))
    monkeypatch.setenv("LAFORGE_DB_PATH", str(db_file))
    monkeypatch.setenv("LAFORGE_AUTHORITY_DB", str(db_file))
    # forge_corrigibility fige DB A L'IMPORT : patcher l'attribut, sinon l'environnement ne change rien.
    import nokido_agent.app.forge_corrigibility as _corr
    import nokido_agent.app.forge_db_path as _dbp
    monkeypatch.setattr(_corr, "DB", db_file)
    # le kill-switch se lit chez forge_opsec via authority_path() (resolu a chaque appel) : la base temoin, la aussi
    monkeypatch.setattr(_dbp, "authority_path", lambda *a, **k: str(db_file))

RACINE = Path(__file__).resolve().parents[1]
for _p in (str(RACINE.parent), str(RACINE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REG = pytest.importorskip("nokido_agent.app.forge_mcp_registry")

ARGS = {"action": "shell", "code": "echo NOKIDO_PROBE_RING", "sandbox": "ps_clm"}
MARQUEUR = "NOKIDO_PROBE_RING"


async def _run(ring):
    reg = REG.get_registry()
    return await reg.dispatch(name="run", args=dict(ARGS), agent="NR_TEST",
                              ring=ring)


@pytest.mark.asyncio
async def test_ring_trusted_ne_franchit_pas_ps_clm():
    """LE DEFAUT : ring 2 n'etait borne que par un interrupteur global."""
    res = str(await _run(2))
    assert MARQUEUR not in res, "la charge a ete EXECUTEE au ring 2"
    assert "ring" in res.lower(), (
        "le refus de ps_clm au ring 2 ne mentionne pas le ring : l'autorite "
        "obtenue n'est bornee que par l'attestation, qui est GLOBALE. "
        "Attestation armee = ring 2 obtient SYSTEM. Reponse: %r" % res[:240])


@pytest.mark.asyncio
async def test_controle_positif_le_ring_dev_passe_le_plancher():
    """Sans lui, un plancher qui refuserait tout passerait le test precedent.

    Ring 1 doit franchir le PLANCHER et se faire arreter par l'ATTESTATION —
    deux gardes distincts, deux motifs distincts. Si le refus au ring 1 parle
    du ring, le plancher est trop haut et coupe le canal documente.
    """
    res = str(await _run(1))
    assert MARQUEUR not in res, "la charge a ete EXECUTEE au ring 1"
    assert "dev" in res.lower() or "attestation" in res.lower(), (
        "le refus au ring 1 ne vient pas de l'attestation : le plancher de "
        "ring coupe le canal documente de lecture du profil owner. "
        "Reponse: %r" % res[:240])


@pytest.mark.asyncio
async def test_la_surface_legitime_du_tool_run_est_preservee():
    """NEGATIVE_CONTROL : borner ps_clm ne borne pas `run` en general.

    Un bac non privilegie doit rester atteignable aux memes rings qu'avant.
    On n'execute rien : un `sandbox` hors contrat est refuse par le garde de
    validation, et ce refus prouve que l'appel a bien traverse le dispatch
    jusqu'au routage des bacs.
    """
    reg = REG.get_registry()
    res = str(await reg.dispatch(
        name="run", args={"action": "shell", "code": "echo x",
                          "sandbox": "__bac_hors_contrat__"},
        agent="NR_TEST", ring=2))
    assert "ps_clm" not in res or "ring" not in res.lower(), (
        "un bac quelconque herite du refus propre a ps_clm : la borne a "
        "deborde sur toute la surface de `run`. Reponse: %r" % res[:240])
