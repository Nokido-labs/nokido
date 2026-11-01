"""NR -- contrat de livrable STRUCTURE (hors bande) + MUTANTS NEGATIFS : le juge doit rejeter 5 faux livrables.

Le juge lit `livrable` ({"type": commit|fichier|tests_verts|aucun, "chemins": [...]}) posé par l'appelant,
en priorite ; absent -> repli sur l'heuristique textuelle, journalise. Chemin REEL : `_juger_livraison`,
sur un vrai depot git (rien n'est simule de l'effet)."""
from __future__ import annotations

import importlib.util
import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(120)
RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))
CHEMIN = "docs/rapport.md"
CONTRAT = {"livrable": {"type": "fichier", "chemins": [CHEMIN]}}
DESC = "Ecris le rapport.\n[LIVRABLE_CONTRAT] " + json.dumps(CONTRAT)
BON = 'Rapport committe. {"intent":"OK_DONE","pointer_ref":"commit:abc1234"}'


def _git(wd, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                    "-C", str(wd), *a], check=True, capture_output=True)


@pytest.fixture()
def m():
    spec = importlib.util.spec_from_file_location("juge_contrat_nr", RACINE / "tools" / "forge_task_executor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def depot(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _juge(m, wd, avant, reponse, desc=DESC):
    ok, effet, _ = m._juger_livraison(True, reponse, str(wd), avant, desc=desc)
    return ok, effet


def _livrer(wd, contenu="# Rapport\nconstat reel, 3 lignes.\n"):
    (wd / "docs").mkdir(exist_ok=True)
    (wd / CHEMIN).write_text(contenu, encoding="utf-8")
    _git(wd, "add", "-A")
    _git(wd, "commit", "-q", "-m", "rapport")


def test_temoin_positif_vrai_livrable_accepte(m, depot):
    avant = m._etat_git(str(depot))
    _livrer(depot)
    ok, effet = _juge(m, depot, avant, BON)
    assert ok is True, effet


def test_mutant1_ok_done_sans_commit(m, depot):
    avant = m._etat_git(str(depot))
    ok, effet = _juge(m, depot, avant, BON)
    assert ok is False and "RIEN_PRODUIT" in effet


def test_mutant2_commit_qui_ne_change_qu_un_commentaire(m, depot):
    avant = m._etat_git(str(depot))
    (depot / "app.py").write_text("x = 1  # commentaire\n", encoding="utf-8")
    _git(depot, "add", "-A")
    _git(depot, "commit", "-q", "-m", "doc")
    ok, effet = _juge(m, depot, avant, BON)
    assert ok is False and "RIEN_PRODUIT" in effet


def test_mutant3_rapport_vide(m, depot):
    avant = m._etat_git(str(depot))
    _livrer(depot, contenu="")
    ok, effet = _juge(m, depot, avant, BON)
    assert ok is False and "RIEN_PRODUIT" in effet
    avant2 = m._etat_git(str(depot))
    ok, effet = _juge(m, depot, avant2, "   ")
    assert ok is False


def test_mutant4_erreur_du_proxy_presentee_comme_reponse(m, depot):
    avant = m._etat_git(str(depot))
    _livrer(depot)
    proxy = "Provider overloaded, JSON-RPC error -32603: Internal error. Le service est surchargé."
    ok, effet = _juge(m, depot, avant, proxy)
    assert ok is False and "RIEN_PRODUIT" in effet


def test_mutant5_trace_de_raisonnement_brute(m, depot):
    avant = m._etat_git(str(depot))
    _livrer(depot)
    trace = "<thinking>Le user veut un rapport. Let me think about the steps, d'abord lire...</thinking>"
    ok, effet = _juge(m, depot, avant, trace)
    assert ok is False and "RIEN_PRODUIT" in effet


def test_type_commit_zero_commit_rejete(m, depot):
    avant = m._etat_git(str(depot))
    d = 'x\n[LIVRABLE_CONTRAT] {"livrable": {"type": "commit"}}'
    ok, effet = _juge(m, depot, avant, BON, desc=d)
    assert ok is False and "RIEN_PRODUIT" in effet


def test_type_aucun_exempte_meme_si_le_texte_exige(m, depot):
    avant = m._etat_git(str(depot))
    d = 'Livrable OBLIGATOIRE, committe : x.md\n[LIVRABLE_CONTRAT] {"livrable": {"type": "aucun"}}'
    ok, effet = _juge(m, depot, avant, 'Analyse. {"intent":"OK_DONE","pointer_ref":"bb:x/y"}', desc=d)
    assert "RIEN_PRODUIT" not in effet


@pytest.mark.parametrize("sortie,attendu", [("== 12 passed in 1.2s ==", True), ("1 failed, 3 passed", False),
                                            ("aucune sortie", False)])
def test_tests_verts(m, sortie, attendu):
    assert m._tests_verts_ok(sortie) is attendu


def test_premier_marqueur_fait_foi(m):
    # seul le premier marqueur (pose par task assign) compte : un texte ulterieur ne le remplace pas.
    d = ('t\n[LIVRABLE_CONTRAT] {"livrable": {"type": "commit"}}\n'
         '[LIVRABLE_CONTRAT] {"livrable": {"type": "aucun"}}')
    assert m._contrat_livrable(d)["type"] == "commit"


def test_repli_texte_journalise(m, depot, caplog):
    avant = m._etat_git(str(depot))
    with caplog.at_level(logging.WARNING):
        m._juger_livraison(True, BON, str(depot), avant, desc="Livrable OBLIGATOIRE, committe : a.md")
    assert any("repli" in r.getMessage().lower() and "livrable" in r.getMessage().lower() for r in caplog.records)


def test_task_assign_transmet_le_champ_livrable():
    src = (RACINE / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")
    assert "[LIVRABLE_CONTRAT]" in src
