"""NR — le producteur d'auto-amelioration annonce l'issue de chaque cycle (debat RSI 15/10).

Mesure : `self_improvement_watch` a tourne 1 024 fois « ok » pendant que le registre d'evolution
se taisait depuis le 04/10. « ok » ne distinguait pas absence de signal, doublon, ecriture et
erreur (Codex) ; AGY a mesure qu'il n'y avait AUCUN croisement : le producteur ne propose que
sur panne. L'issue est desormais en TETE du resultat, que le planificateur trace dans
`autonomous_loop_audit` (`str(resultat)[:300]`), et jamais dans le registre des experiences.
Aucune base reelle n'est touchee : ecriture, registre et sources sont simules.
"""
import sys
import types

import pytest

from nokido_agent.app import forge_autonomous_loops as L
from nokido_agent.app import forge_db_path


@pytest.fixture
def registre(monkeypatch):
    ecrits = []
    monkeypatch.setattr(L, "record_evolution_experience", lambda rec: ecrits.append(rec) or "exp")
    return ecrits


def _proposer(monkeypatch, retour):
    def write_retry(op, **_):
        if isinstance(retour, Exception):
            raise retour
        return retour

    monkeypatch.setattr(forge_db_path, "write_retry", write_retry)
    issues = []
    ok = L._proposer("p", "a", "b", "r", 0.8, issues=issues)
    return ok, issues


def test_ecrite(monkeypatch, registre):
    assert _proposer(monkeypatch, True) == (True, ["WRITTEN"]) and registre


def test_doublon(monkeypatch, registre):
    assert _proposer(monkeypatch, False) == (False, ["DEDUPLICATED"]) and not registre


def test_erreur_d_ecriture(monkeypatch, registre):
    assert _proposer(monkeypatch, RuntimeError("base verrouillee")) == (False, ["WRITE_ERROR"])


def test_ecrite_mais_registre_perdu(monkeypatch):
    def leve(rec):
        raise OSError("disque plein")

    monkeypatch.setattr(L, "record_evolution_experience", leve)
    assert _proposer(monkeypatch, True) == (True, ["WRITTEN_SANS_REGISTRE"])


def test_sans_issues_le_comportement_d_avant(monkeypatch, registre):
    monkeypatch.setattr(forge_db_path, "write_retry", lambda op, **_: True)
    assert L._proposer("p", "a", "b", "r", 0.8) is True


def _module(monkeypatch, nom, **attrs):
    m = types.ModuleType(nom)
    for k, v in attrs.items():
        setattr(m, k, v)
    monkeypatch.setitem(sys.modules, nom, m)


def test_un_cycle_sans_signal_se_lit_no_signal_en_tete(monkeypatch):
    _module(monkeypatch, "nokido_agent.app.forge_swarm_blackboard", read_zone=lambda *a, **k: [])
    _module(monkeypatch, "nokido_agent.tools.forge_regulation_efficacy", journal=lambda: [],
            verdicts=lambda ev: [], cadence=lambda *a, **k: {}, croisement_flux=lambda *a, **k: {"lie": False})
    _module(monkeypatch, "nokido_agent.tools.forge_gap_direction", point=lambda: {})
    monkeypatch.setattr(L, "_log_run", lambda *a, **k: None)
    out = L.pat_self_improvement()
    assert list(out)[0] == "issue" and out["issue"] == "NO_SIGNAL"
    assert str(out)[:300].startswith("{'issue': 'NO_SIGNAL'")
