"""NR 7/11 : une reverification de livraison ne doit NI ecrire dans le depot, NI se conclure FAIT sans preuve.

Defaut mesure (job_2751ecc3, 7/11) : la tache automatique « REVERIFICATION D'UNE LIVRAISON » a ecrit run_tests.py ;
l'executeur l'a committe sous un message trompeur, et le rendu a conclu FAIT avec pointer_ref "sha_vrai_du_livrable"
(gabarit, sans SHA reel). Une reverification ne modifie pas le depot et ne se conclut pas sans preuve.

Prouve par les VRAIES fonctions :
1. la consigne creee par la voie soin (`forge_remediation._description_reverif`) porte un contrat `aucun` lu par
   `forge_task_executor._contrat_livrable` ;
2. tout commit produit est un RIEN_PRODUIT nomme (l'executeur ne commite pas pour elle) ;
3. FAIT sans SHA reel (gabarit) = ILLISIBLE, jamais FAIT ; SHA inexistant = ILLISIBLE ; SHA reel existant = FAIT.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(120)
RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app"), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture()
def m():
    spec = importlib.util.spec_from_file_location("rev_sans_ecriture_nr", RACINE / "tools" / "forge_task_executor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_le_mot_fait_en_prose_n_exige_aucun_sha(m, tmp_path):
    """Relecture du rendu : la recherche ignorait la casse, un « fait » ordinaire devenait un FAIT sans preuve."""
    effet = "[effet observe] commits produits : 0 (a..a) ; fichiers non commites : 0"
    prose = "Voici ce qui a ete fait et ce qui reste a faire.\nNON_FAIT : le module manque."
    assert m._verdict_aucun(prose, str(tmp_path), effet) is None


def test_fait_en_majuscules_sans_sha_reste_illisible(m, tmp_path):
    effet = "[effet observe] commits produits : 0 (a..a) ; fichiers non commites : 0"
    motif = m._verdict_aucun('Conclusion : FAIT\n{"intent":"OK_DONE","pointer_ref":"sha_vrai_du_livrable"}', str(tmp_path), effet)
    assert motif and m._MARQUE_ILLISIBLE in motif


def _git(wd, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                    "-C", str(wd), *a], check=True, capture_output=True)


@pytest.fixture()
def depot(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _sha_head(wd):
    return subprocess.run(["git", "-C", str(wd), "rev-parse", "HEAD"], check=True, capture_output=True,
                          text=True, errors="replace").stdout.strip()


def _desc_aucun():
    """Consigne telle que la produit la voie soin (createur reel des taches de reverification)."""
    from nokido_agent.app import forge_remediation as R
    f = {"id": "abc123", "kind": "attestation_commit_anterieur", "target": "job_suspect:50221f9ca"}
    meta = {"tache": "job_suspect", "agent": "AGY", "sha": "50221f9ca", "consigne": "reprendre 50221f9ca"}
    return R._description_reverif(f, meta)


def test_consigne_reverification_porte_un_contrat_aucun(m):
    contrat = m._contrat_livrable(_desc_aucun())
    assert contrat is not None and contrat["type"] == "aucun", contrat


def test_commit_produit_par_la_reverification_est_un_rien_produit_nomme(m, depot):
    avant = m._etat_git(str(depot))
    (depot / "run_tests.py").write_text("print('ecrit par la reverification')\n", encoding="utf-8")
    _git(depot, "add", "-A")
    _git(depot, "commit", "-q", "-m", "chore: livraison trompeuse")
    detail = 'FAIT. {"intent":"OK_DONE","pointer_ref":"%s"}' % _sha_head(depot)
    ok, effet, _ = m._juger_livraison(True, detail, str(depot), avant, desc=_desc_aucun())
    assert ok is False and "RIEN_PRODUIT" in effet, effet
    assert "aucun artefact attendu" in effet, effet


def test_fait_avec_sha_de_gabarit_est_illisible_jamais_fait(m, depot):
    avant = m._etat_git(str(depot))
    detail = 'FAIT avec le sha reel. {"intent":"OK_DONE","pointer_ref":"sha_vrai_du_livrable"}'
    ok, effet, _ = m._juger_livraison(True, detail, str(depot), avant, desc=_desc_aucun())
    assert ok is False and "[ILLISIBLE]" in effet, effet
    assert "RIEN_PRODUIT" not in effet, effet


def test_fait_avec_sha_reel_existant_est_fait(m, depot):
    avant = m._etat_git(str(depot))
    detail = 'FAIT. {"intent":"OK_DONE","pointer_ref":"%s"}' % _sha_head(depot)
    ok, effet, _ = m._juger_livraison(True, detail, str(depot), avant, desc=_desc_aucun())
    assert ok is True, effet


def test_fait_avec_sha_inexistant_est_illisible(m, depot):
    avant = m._etat_git(str(depot))
    detail = 'FAIT. {"intent":"OK_DONE","pointer_ref":"deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"}'
    ok, effet, _ = m._juger_livraison(True, detail, str(depot), avant, desc=_desc_aucun())
    assert ok is False and "[ILLISIBLE]" in effet, effet
