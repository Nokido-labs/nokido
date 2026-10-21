# -*- coding: utf-8 -*-
"""NR -- la liste `--impacte-fichiers` relative se resout contre la RACINE du depot, pas le cwd du hub (19/10).

Mesure 19/10 (enquete OPENCODE_GPTOSS job_e38b27f7, rapport docs/audit/ci_memoire_6go_et_sampler_20261019.md) :
deux `ci_local --impacte` lances par run_job ont ete TUES a 6 Go. Leur liste relative etait ouverte contre le cwd
du hub -> FileNotFoundError -> ILLISIBLE -> repli sur TOUTE la suite dans un seul pytest. L'abstention est juste
(une liste illisible ne reduit jamais le perimetre) ; la faute est de ne pas chercher la liste la ou elle est.
Contrat :
  1. `liste_depuis_fichier(chemin, racine=R)` lit R/chemin quand chemin est relatif, quel que soit le cwd ;
  2. un chemin absolu reste lu tel quel ;
  3. sans racine, comportement inchange (illisible = ILLISIBLE, jamais une liste vide prise pour « rien ») ;
  4. ci_local passe sa racine (ROOT) au lecteur.
"""
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_ci_selection as sel  # noqa: E402

pytestmark = pytest.mark.timeout(60)


def test_liste_relative_lue_contre_la_racine(tmp_path, monkeypatch):
    depot = tmp_path / "depot"
    (depot / "sandbox").mkdir(parents=True)
    (depot / "sandbox" / "impacte.txt").write_text("app/forge_a.py\n", encoding="utf-8")
    ailleurs = tmp_path / "cwd_du_hub"
    ailleurs.mkdir()
    monkeypatch.chdir(ailleurs)
    assert sel.liste_depuis_fichier("sandbox/impacte.txt", racine=depot) == (["app/forge_a.py"], "PRESENT")


def test_liste_absolue_inchangee(tmp_path):
    f = tmp_path / "liste.txt"
    f.write_text("tools/forge_b.py\n", encoding="utf-8")
    assert sel.liste_depuis_fichier(str(f), racine=tmp_path / "autre") == (["tools/forge_b.py"], "PRESENT")


def test_sans_racine_illisible_reste_illisible(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mods, etat = sel.liste_depuis_fichier("absente.txt")
    assert mods == [] and etat.startswith("ILLISIBLE")


def test_ci_local_passe_sa_racine():
    src = (RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert "liste_depuis_fichier(_liste, racine=ROOT)" in src
