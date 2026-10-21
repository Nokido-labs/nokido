"""NR -- la trace de consultation du hub juge le DOMAINE, pas seulement l'heure (phase 2 des gardes, owner 17/10).

Mesure 17/10 : CLAUDE a ajoute trois fonctions dans des modules existants (forge_task_executor, forge_llm_router,
forge_recon_breaker) sans consulter LEUR domaine ; `consultation_recente(agent)` ne retenait que la DERNIERE question et
les DERNIERS fichiers proposes : une consultation sur un autre sujet suffisait. Owner : « les garde fous doivent
emaner du hub ». Extension de la brique EXISTANTE (forge_introspect, lue par le handler governed_edit depuis le 31/08),
pas un second registre : chaque consultation cumule ses domaines (modules de la question et du rendu), horodates.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_introspect as I  # noqa: E402


@pytest.fixture
def trace(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "TRACE", tmp_path / "introspect_trace.json")
    monkeypatch.setattr(I, "SERIE", tmp_path / "introspect_serie.jsonl")


def _rendu(*chemins):
    return {"fichiers_procedures": list(chemins)}


def test_une_consultation_retient_les_domaines_du_rendu(trace):
    I.noter_consultation("CLAUDE", "reaffecter une tache", {
        "fichiers_procedures": ["app/forge_task_bus.py"],
        "modules_trouves": [{"module": "forge_worktree", "chemin": "tools/forge_worktree.py"}]})
    for chemin in ("app/forge_task_bus.py", "tools/forge_worktree.py"):
        assert I.consultation_du_domaine("CLAUDE", chemin)["vu"], chemin
    assert not I.consultation_du_domaine("CLAUDE", "app/forge_llm_router.py")["vu"]


def test_citer_un_module_dans_la_question_ne_prouve_pas_la_consultation(trace):
    """Revue adverse de Codex (17/10, CONFIRME) : une question contenant le nom du module suffisait, meme sans
    resultat. Seuls les domaines effectivement RENDUS par la consultation comptent."""
    I.noter_consultation("CLAUDE", "je cite forge_task_executor pour passer le gate", {"fichiers_procedures": []})
    assert not I.consultation_du_domaine("CLAUDE", "tools/forge_task_executor.py")["vu"]


def test_les_domaines_cumulent_d_une_consultation_a_l_autre(trace):
    I.noter_consultation("CLAUDE", "q1", _rendu("tools/forge_worktree.py"))
    I.noter_consultation("CLAUDE", "q2", _rendu("app/forge_llm_router.py"))
    assert I.consultation_du_domaine("CLAUDE", "tools/forge_worktree.py")["vu"], "la 2e consultation n'efface pas la 1re"


def test_le_domaine_est_propre_a_l_agent(trace):
    I.noter_consultation("CLAUDE", "q", _rendu("tools/forge_worktree.py"))
    r = I.consultation_du_domaine("ANTIGRAVITY", "tools/forge_worktree.py")
    assert r["vu"] is False and r["etat"] == "JAMAIS"


def test_deux_consultations_simultanees_ne_s_effacent_pas(trace, monkeypatch):
    """Mesure 17/10 : la trace de CLAUDE est revenue a « derniere il y a 9 h » alors qu'il venait de consulter, pendant
    qu'AGY et Codex appelaient le hub en parallele -- la trace est un JSON lu, modifie et RECRIT en entier : deux appels
    concurrents lisent le meme instantane et le second efface le premier (mise a jour perdue). Le gate cognitif repondait
    alors « JAMAIS » a tort. La barriere rend la course deterministe : sans verrou, les deux lisent avant d'ecrire."""
    import threading

    barriere = threading.Barrier(2, timeout=0.5)
    lire = I._lire_trace

    def lire_puis_attendre():
        d = lire()
        try:
            barriere.wait()
        except threading.BrokenBarrierError:
            pass  # avec verrou, l'autre attend le verrou : la barriere expire et l'on continue
        return d

    monkeypatch.setattr(I, "_lire_trace", lire_puis_attendre)
    fils = [threading.Thread(target=I.noter_consultation, args=(agent, "q", _rendu("tools/forge_%s.py" % agent.lower())))
            for agent in ("CLAUDE", "ANTIGRAVITY")]
    for f in fils:
        f.start()
    for f in fils:
        f.join(5)
    monkeypatch.setattr(I, "_lire_trace", lire)
    d = I._lire_trace()
    assert {"CLAUDE", "ANTIGRAVITY"} <= set(d), "une consultation concurrente a ete effacee : %s" % sorted(d)


def test_une_consultation_ancienne_du_domaine_est_dite_perimee(trace):
    I.noter_consultation("CLAUDE", "q", _rendu("tools/forge_worktree.py"))
    d = I._lire_trace()
    d["CLAUDE"]["domaines"]["forge_worktree"] = time.time() - 2 * I.TTL_CONSULTATION_S
    I._ecrire_trace(d)
    r = I.consultation_du_domaine("CLAUDE", "tools/forge_worktree.py")
    assert r["vu"] is False and r["etat"] == "PERIMEE", r
