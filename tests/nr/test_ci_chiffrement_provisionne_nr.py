"""NR -- la CI publique PROVISIONNE le chiffrement at-rest, sinon consigne un refus DIT (decision owner 2026-10-20).

Depuis 230f9e15b le chiffrement est obligatoire : `nokido-composants --tout` rend 2 sans VeraCrypt/cryptsetup ni
refus consigne. Les runners GitHub n'ont ni l'un ni l'autre : le parcours paquet s'arreterait sur les trois systemes.
Decision owner (« Provisionner, sinon refus dit ») : la CI installe le chiffrement (Linux : cryptsetup et un VRAI
volume LUKS mesure ; Windows : VeraCrypt par choco ; macOS : VeraCrypt par brew) ; la ou ca echoue, la recette passe
un refus EXPLICITE motive « runner CI », et le rapport le dit.

Ce qui est garde :
  * les jobs `installation` et `paquet` provisionnent le chiffrement par OS, avant la recette, sans arreter le job ;
  * `arguments_chiffrement_recette` : rien si le chiffrement est present, sinon `--sans-chiffrement` + un motif qui
    nomme le runner CI et le systeme -- et le parcours paquet s'en sert pour `nokido-composants` ;
  * l'etape `chiffrement` sous Linux ne dit PASS que sur un volume LUKS cree, monte, ecrit et relu
    (`mesurer_volume_luks`) ; ailleurs elle dit ce qu'elle n'a pas mesure.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
WORKFLOW = RACINE / ".github" / "workflows" / "installation-complete.yml"
RECETTE = RACINE / "tools" / "forge_install_acceptance.py"


def _module():
    spec = importlib.util.spec_from_file_location("ci_chiffrement_nr", RECETTE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.R.clear()
    return m


def _job(nom):
    texte = WORKFLOW.read_text(encoding="utf-8")
    bloc = texte.split("\n  %s:" % nom, 1)[1]
    suivant = [i for i in (bloc.find("\n  paquet:"), bloc.find("\n  organisme:"), bloc.find("\n  installation:"))
               if i > 0]
    return bloc[:min(suivant)] if suivant else bloc


@pytest.mark.parametrize("job", ["installation", "paquet"])
def test_les_jobs_provisionnent_le_chiffrement_par_os_avant_la_recette(job):
    t = _job(job)
    for marque in ("apt-get install -y cryptsetup", "choco install veracrypt", "brew install --cask veracrypt"):
        assert marque in t, "%s : %s absent" % (job, marque)
        assert t.index(marque) < t.index("forge_install_acceptance.py"), "%s : provisionner AVANT la recette" % job
    assert t.count("continue-on-error: true") >= 1, "un provisionnement qui echoue n'arrete pas le job : il se dit"


def test_arguments_de_la_recette_selon_le_chiffrement():
    m = _module()
    assert m.arguments_chiffrement_recette(True, "Linux") == []
    args = m.arguments_chiffrement_recette(False, "Darwin")
    assert args[0] == "--sans-chiffrement" and args[1] == "--motif-refus"
    assert "runner CI" in args[2] and "Darwin" in args[2]
    assert "arguments_chiffrement_recette(" in RECETTE.read_text(encoding="utf-8").split("def arguments_chiffrement_recette", 1)[1], \
        "le parcours paquet doit s'en servir pour nokido-composants"


@pytest.mark.parametrize("mesure, attendu", [(("PASS", "volume LUKS cree, monte, ecrit et relu"), "PASS"),
                                             (("FAIL", "luksFormat refuse"), "FAIL"),
                                             (("NON_TESTE", "sudo indisponible"), "NON_TESTE")])
def test_sous_linux_le_pass_exige_un_vrai_volume_luks(monkeypatch, mesure, attendu):
    m = _module()
    monkeypatch.setattr(m.sys, "platform", "linux")
    monkeypatch.setattr(m.shutil, "which", lambda nom: "/usr/sbin/cryptsetup" if nom == "cryptsetup" else None)
    monkeypatch.setattr(m, "mesurer_volume_luks", lambda: mesure)
    m._chiffrement()
    assert m.R["chiffrement"]["etat"] == attendu, m.R["chiffrement"]
    assert mesure[1] in m.R["chiffrement"]["detail"]
