"""NR -- analyse F de l'audit (19/10) : la stabilite des boucles se MESURE, elle ne se suppose pas.

Constat sur piece (19/10) : `endocrine_signals` a l'hormone pour cle primaire (INSERT OR
REPLACE) et `signal_emissions.db` ne tient qu'un compteur cumule. Sur 989 bases lues,
AUCUNE serie temporelle d'hormone : oscillation, hysteresis et temps de retour etaient
inmesurables -- donc ni prouves stables, ni prouves instables.

Contrat :
  * une secretion (porteuse d'un niveau) laisse une trace DATEE ; un pouls n'en laisse pas
    (1,46 M de battements du seul harness : les journaliser noierait le signal) ;
  * `stabilite()` rend INCONNU sur un journal vide -- jamais STABLE par defaut (liste
    blanche de la constitution) ;
  * une hormone qui s'allume et s'eteint en rafale ressort OSCILLE ; une hormone allumee
    sans extinction au-dela du seuil ressort PERSISTANT ; un episode unique et borne, STABLE.
Observation seulement : aucun verdict ne bloque ni ne corrige.
"""
from __future__ import annotations

import sqlite3

import pytest

import forge_endocrine as fe  # noqa: E402
import forge_signal_coupling as sc  # noqa: E402


@pytest.fixture
def bases(tmp_path, monkeypatch):
    monkeypatch.setattr(fe, "DB", tmp_path / "endocrine.db", raising=False)
    # Deux noms d'import = deux instances : l'endocrine passe par le nom PAQUET.
    # Rediriger les deux, sinon le test ecrirait dans la base VIVANTE.
    for nom in ("forge_signal_coupling", "nokido_agent.app.forge_signal_coupling"):
        try:
            mod = __import__("importlib").import_module(nom)
        except ImportError:
            continue
        monkeypatch.setattr(mod, "DB", tmp_path / "signal_emissions.db", raising=False)


def _journal(signal):
    cx = sqlite3.connect(str(sc.DB))
    try:
        return [r[0] for r in cx.execute(
            "SELECT level FROM emissions_journal WHERE signal = ? ORDER BY ts, rowid", (signal,))]
    finally:
        cx.close()


def test_une_secretion_laisse_une_trace_datee(bases):
    fe.release("TEST_JOURNAL", 0.6, source="glande_a")
    fe.release("TEST_JOURNAL", 0.0, source="glande_a")
    assert [round(x, 3) for x in _journal("TEST_JOURNAL")] == [0.6, 0.0]


def test_un_pouls_ne_remplit_pas_le_journal(bases):
    fe.release("TEST_JOURNAL", 0.4, source="glande_a")  # cree la table : temoin positif
    sc.emit_signal("harness_worker.heartbeat", emitter="test")
    assert _journal("harness_worker.heartbeat") == []
    assert len(_journal("TEST_JOURNAL")) == 1


def test_journal_vide_est_inconnu_jamais_stable(bases):
    r = sc.stabilite(fenetre_s=3600, maintenant=10_000.0)
    assert r["verdict"] == "INCONNU"
    assert r["hormones"] == {}


def test_rafale_marche_arret_ressort_oscille(bases):
    t0 = 1_000.0
    for i in range(8):  # 8 episodes en 40 min
        sc.emit_signal("H_OSC", emitter="t", level=0.8, ttl_s=600, ts=t0 + i * 300)
        sc.emit_signal("H_OSC", emitter="t", level=0.0, ttl_s=600, ts=t0 + i * 300 + 60)
    r = sc.stabilite(fenetre_s=3600, maintenant=t0 + 3000)
    assert r["hormones"]["H_OSC"]["verdict"] == "OSCILLE"
    assert r["hormones"]["H_OSC"]["episodes"] == 8
    assert r["verdict"] != "STABLE"


def test_allumee_sans_extinction_ressort_persistant(bases):
    t0 = 1_000.0
    for i in range(30):  # re-emise toutes les 10 min pendant 5 h, jamais eteinte
        sc.emit_signal("H_PERS", emitter="t", level=0.7, ttl_s=1800, ts=t0 + i * 600)
    r = sc.stabilite(fenetre_s=6 * 3600, maintenant=t0 + 29 * 600 + 10, seuil_persistant_s=4 * 3600)
    assert r["hormones"]["H_PERS"]["verdict"] == "PERSISTANT"


def test_episode_unique_borne_est_stable(bases):
    t0 = 1_000.0
    sc.emit_signal("H_OK", emitter="t", level=0.5, ttl_s=1800, ts=t0)
    sc.emit_signal("H_OK", emitter="t", level=0.0, ttl_s=1800, ts=t0 + 900)
    r = sc.stabilite(fenetre_s=3600, maintenant=t0 + 1200)
    h = r["hormones"]["H_OK"]
    assert h["verdict"] == "STABLE"
    assert h["episodes"] == 1
    assert h["duree_mediane_s"] == pytest.approx(900, abs=1)
    assert r["verdict"] == "STABLE"


def test_extinction_par_ttl_sans_emission_nulle(bases):
    # la decroissance n'emet rien : la fin d'episode se deduit du dernier ttl
    t0 = 1_000.0
    sc.emit_signal("H_TTL", emitter="t", level=0.5, ttl_s=600, ts=t0)
    r = sc.stabilite(fenetre_s=3600, maintenant=t0 + 2000)
    h = r["hormones"]["H_TTL"]
    assert h["episodes"] == 1
    assert h["duree_mediane_s"] == pytest.approx(600, abs=1)
