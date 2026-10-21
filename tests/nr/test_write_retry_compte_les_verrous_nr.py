"""NR -- analyse 02 de l'audit (19/10) : la contention SQLite se MESURE par producteur.

Constat sur piece : `forge_db_path.write_retry` reprend une ecriture bloquee par un verrou
(recul + jitter) mais ne COMPTE rien. Les reprises, et meme les abandons, etaient
invisibles : impossible de dire quel producteur subit la contention de la base partagee,
ni si elle croit. Une mesure absente n'est pas une contention nulle.

Contrat : chaque reprise sur verrou est constatee sous `sqlite.verrou.reprise`, chaque
abandon sous `sqlite.verrou.abandon`, avec le PRODUCTEUR (module.qualname de l'operation)
comme emetteur, dans la base dediee de `forge_signal_coupling` -- jamais dans la base RAG.
Une ecriture qui passe du premier coup ne laisse rien.
"""
from __future__ import annotations

import sqlite3

import pytest

import forge_db_path as dbp  # noqa: E402


@pytest.fixture
def compteur(tmp_path, monkeypatch):
    base = tmp_path / "signal_emissions.db"
    for nom in ("forge_signal_coupling", "nokido_agent.app.forge_signal_coupling"):
        try:
            mod = __import__("importlib").import_module(nom)
        except ImportError:
            continue
        monkeypatch.setattr(mod, "DB", base, raising=False)
    # write_retry importe `time` localement : c'est le module qu'on neutralise
    monkeypatch.setattr(__import__("time"), "sleep", lambda *_a, **_k: None)
    return base


def _compte(base, signal):
    if not base.exists():
        return {}
    cx = sqlite3.connect(str(base))
    try:
        return {e: n for e, n in cx.execute(
            "SELECT emitter, n FROM emissions WHERE signal = ?", (signal,))}
    except sqlite3.OperationalError:
        return {}
    finally:
        cx.close()


class _Conn:
    def close(self):
        pass


def _producteur_bloque(n_verrous):
    etat = {"appels": 0}

    def ecrire_fiche(_conn):
        etat["appels"] += 1
        if etat["appels"] <= n_verrous:
            raise sqlite3.OperationalError("database is locked")
        return "ecrit"
    return ecrire_fiche


def test_une_reprise_est_comptee_au_nom_du_producteur(compteur, monkeypatch):
    monkeypatch.setattr(dbp, "open_writer", lambda **_k: _Conn())
    op = _producteur_bloque(2)
    assert dbp.write_retry(op, attempts=6) == "ecrit"
    reprises = _compte(compteur, "sqlite.verrou.reprise")
    assert sum(reprises.values()) == 2
    assert any("ecrire_fiche" in e for e in reprises), reprises


def test_un_abandon_est_compte(compteur, monkeypatch):
    monkeypatch.setattr(dbp, "open_writer", lambda **_k: _Conn())
    with pytest.raises(sqlite3.OperationalError):
        dbp.write_retry(_producteur_bloque(99), attempts=3)
    assert sum(_compte(compteur, "sqlite.verrou.abandon").values()) == 1


def test_une_ecriture_directe_ne_laisse_rien(compteur, monkeypatch):
    monkeypatch.setattr(dbp, "open_writer", lambda **_k: _Conn())
    assert dbp.write_retry(_producteur_bloque(0)) == "ecrit"
    assert _compte(compteur, "sqlite.verrou.reprise") == {}
    assert _compte(compteur, "sqlite.verrou.abandon") == {}
