"""NR 29/10 : en satiete RAM, une veille dont la dependance Docker est DEJA payee ne doit plus etre refusee
pour un cout qu'elle n'engage pas.

Constat mesure : logs/supervisor/NokidoWatchAgent.log repete « RAM en satiete : 11 veille(s) attendent »,
alors que Docker/WSL (vmmemWSL 2,76 Go) a ete reveille POUR ces veilles ; nokido_ensure_service docker stopped
est refuse (« chaine de travail active »). La regulation tenait donc Docker eveille pour des veilles qu'elle
refusait A CAUSE de lui.

Contrat : le cout MARGINAL d'une veille (0,8 Go declare) remplace le seuil GLOBAL uniquement quand le demon
Docker est deja leve ET qu'une veille le reclame ; sans cette dependance payee, la garde reste celle d'avant.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time

import pytest

import nokido_agent.app.forge_chain_executor as CE


def _executeur(monkeypatch, *, satiete=True, docker_up=True, dispo_go=4.0, maxi="2"):
    monkeypatch.setattr(CE, "_ram_en_satiete", lambda: satiete)
    monkeypatch.setattr(CE, "_docker_deja_leve_pour_veille", lambda: docker_up)
    monkeypatch.setattr(CE, "_ram_disponible_go", lambda: dispo_go)
    monkeypatch.setenv("LAFORGE_VEILLES_MAX", maxi)
    monkeypatch.setattr(CE, "_DERNIER_MOTIF_VEILLES", {}, raising=False)
    db = sqlite3.connect(":memory:")
    db.execute("create table agent_chain_nodes (chain_id text, status text)")
    ex = object.__new__(CE.ChainExecutor)

    class _Conn:
        def execute(self, *a):
            return db.execute(*a)

        def close(self):
            pass

    ex._get_conn = lambda: _Conn()
    return ex


def _chaines():
    return {
        "wj_vieille": [{"created_at": "2026-10-29T14:00:00"}],
        "wj_moyenne": [{"created_at": "2026-10-29T14:10:00"}],
        "wj_recente": [{"created_at": "2026-10-29T14:20:00"}],
    }


def test_satiete_docker_deja_leve_et_dispo_suffisante_admet_une_seule_veille(monkeypatch, caplog):
    ex = _executeur(monkeypatch, satiete=True, docker_up=True, dispo_go=4.0, maxi="2")
    with caplog.at_level(logging.WARNING):
        sortie = ex._etaler_veilles(_chaines())
    assert list(sortie) == ["wj_vieille"]
    assert any("admission marginale" in r.getMessage().lower() and r.levelno >= logging.WARNING
               for r in caplog.records)


def test_satiete_docker_non_leve_garde_inchangee_aucune_veille(monkeypatch, caplog):
    ex = _executeur(monkeypatch, satiete=True, docker_up=False, dispo_go=4.0, maxi="2")
    with caplog.at_level(logging.WARNING):
        sortie = ex._etaler_veilles(_chaines())
    assert sortie == {}
    assert any("satiete" in r.getMessage().lower() and r.levelno >= logging.WARNING
               for r in caplog.records)


def test_satiete_docker_leve_mais_dispo_sous_le_cout_marginal_refuse(monkeypatch):
    ex = _executeur(monkeypatch, satiete=True, docker_up=True,
                    dispo_go=CE._COUT_MARGINAL_VEILLE_GO / 2.0, maxi="2")
    assert ex._etaler_veilles(_chaines()) == {}


def test_hors_satiete_comportement_actuel_deux_veilles(monkeypatch):
    ex = _executeur(monkeypatch, satiete=False, docker_up=True, dispo_go=0.1, maxi="2")
    assert set(ex._etaler_veilles(_chaines())) == {"wj_vieille", "wj_moyenne"}


def test_la_dependance_doit_etre_reclamee_par_une_veille(monkeypatch, tmp_path):
    claims = tmp_path / "docker.claims.json"
    monkeypatch.setattr(CE, "_FICHIER_CLAIMS_DOCKER", claims)
    monkeypatch.setattr(CE, "_docker_daemon_up", lambda: True)
    claims.write_text('["autre_x"]', encoding="utf-8")
    assert CE._docker_deja_leve_pour_veille() is False
    claims.write_text('["wj_a"]', encoding="utf-8")
    assert CE._docker_deja_leve_pour_veille() is True


def test_pouls_du_keeper_frais_prime_et_perime_ne_prouve_rien(monkeypatch, tmp_path):
    import nokido_agent.app.forge_docker_agent as DA

    pouls = tmp_path / "docker_keeper.heartbeat"
    monkeypatch.setattr(CE, "_FICHIER_HEARTBEAT_DOCKER", pouls)
    monkeypatch.setattr(DA, "daemon_up", lambda: False)
    pouls.write_text(json.dumps({"ts": time.time(), "stats": {"daemon_up": True}}), encoding="utf-8")
    assert CE._docker_daemon_up() is True
    pouls.write_text(json.dumps({"ts": time.time() - 1000, "stats": {"daemon_up": True}}),
                     encoding="utf-8")
    assert CE._docker_daemon_up() is False
