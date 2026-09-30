"""NR — forge_rule_distiller : distiller un garde d'un correctif, sans inventer.

Ce que ces tests protegent, ce sont les deux facons dont la boucle
« echec -> garde » peut produire pire que rien :

  * une regle nommee d'apres un nom de VARIABLE. Mesure du 2026-08-18, premiere
    passe reelle : le distillateur a propose `appel_interdit depuis.items`
    parce qu'une boucle locale avait ete refactoree. Une telle regle ne veut
    rien dire hors du fichier ou elle est nee.
  * une regle BAVARDE sur HEAD. Toujours le 2026-08-18, le commit 8c0b0089 a
    donne `sqlite3.connect sans timeout` — juste, mais 363 sites existants.
    Un garde qui crie 363 fois des sa naissance est desarme dans la semaine.

Aucun appel a git ici : on teste la traduction AST -> formes closes et le
verdict du backtest, avec `collect` neutralise (hermetique).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_rule_distiller as D  # noqa: E402
import forge_golden_rules_ast as G  # noqa: E402

AVANT_KW = "import subprocess\nsubprocess.run(['a'])\nsubprocess.run(['b'], check=True)\n"
APRES_KW = ("import subprocess\nsubprocess.run(['a'], timeout=5)\n"
            "subprocess.run(['b'], check=True, timeout=5)\n")


def _candidats(avant: str, apres: str) -> list[dict]:
    return D.candidats(D.appels(avant), D.appels(apres),
                       D.racines_importees(avant), D.racines_importees(apres))


def test_un_kwarg_ajoute_partout_devient_une_forme_appel_sans_kwarg():
    obtenu = _candidats(AVANT_KW, APRES_KW)
    assert obtenu == [{"forme": "appel_sans_kwarg", "cible": "subprocess.run",
                       "kwarg": "timeout"}]


def test_un_kwarg_deja_present_avant_ne_prouve_rien():
    # `check` etait deja la sur l'un des appels et le fix n'y a pas touche :
    # en faire une regle serait confondre style et correctif.
    obtenu = _candidats("import subprocess\nsubprocess.run(['b'], check=True)\n",
                        "import subprocess\nsubprocess.run(['b'], check=True)\n")
    assert obtenu == []


def test_une_methode_sur_variable_locale_est_ignoree():
    avant = "def f(depuis):\n    for k in depuis.items():\n        print(k)\n"
    apres = "def f(depuis):\n    for k in depuis:\n        print(k)\n"
    assert _candidats(avant, apres) == [], "`depuis` est une variable, pas un module"


def test_un_module_importe_disparu_devient_appel_interdit():
    avant = "import os\nos.system('dir')\n"
    apres = "import subprocess\nsubprocess.run(['dir'])\n"
    obtenu = _candidats(avant, apres)
    assert [(c["forme"], c["cible"]) for c in obtenu] == [("appel_interdit", "os.system")]


def test_une_disparition_sans_substitution_ne_prouve_rien():
    # MESURE sur les 25 derniers correctifs : sans cette condition, un simple
    # deplacement de code donnait « json.dumps interdit », « os.path.dirname
    # interdit », « argparse.ArgumentParser interdit » — 12 candidates sur 13.
    avant = "import json\nimport os\nprint(json.dumps({}), os.path.dirname('x'))\n"
    apres = "import json\nimport os\nprint(json.dumps({}))\n"
    assert _candidats(avant, apres) == []


def test_la_regle_de_substitution_nomme_la_remplacante():
    obtenu = _candidats("import os\nos.system('dir')\n",
                        "import subprocess\nsubprocess.run(['dir'])\n")
    assert obtenu[0]["remplace_par"] == ["subprocess.run"]
    assert "subprocess.run" in D._regle(obtenu[0], "deadbeef1234")["message"]


def test_les_racines_importees_couvrent_alias_et_from():
    noms = D.racines_importees("import os\nimport os.path as chemin\nfrom shutil import which\n")
    assert {"os", "chemin", "which"} <= noms


def test_l_identifiant_de_regle_est_lisible_et_stable():
    regle = D._regle({"forme": "appel_sans_kwarg", "cible": "sqlite3.connect",
                      "kwarg": "timeout"}, "8c0b0089abcdef")
    assert regle["id"] == "apprise-sqlite3-connect-sans-timeout"
    assert regle["severity"] == "WARNING"
    assert "8c0b0089" in regle["message"]


def test_une_regle_muette_sur_la_version_fautive_est_rejetee(monkeypatch):
    monkeypatch.setattr(G, "collect", lambda paths: [])
    regle = D._regle({"forme": "appel_sans_kwarg", "cible": "subprocess.run",
                      "kwarg": "timeout"}, "deadbeef")
    verdict = D.backtest([regle], APRES_KW, "app/x.py", 0)[regle["id"]]
    assert verdict["retenue"] is False
    assert "n'aurait rien vu" in verdict["motif"]


def test_une_regle_qui_mord_sur_le_fautif_et_se_tait_sur_head_est_retenue(monkeypatch):
    monkeypatch.setattr(G, "collect", lambda paths: [])
    regle = D._regle({"forme": "appel_sans_kwarg", "cible": "subprocess.run",
                      "kwarg": "timeout"}, "deadbeef")
    verdict = D.backtest([regle], AVANT_KW, "app/x.py", 0)[regle["id"]]
    # AVANT_KW porte DEUX appels sans timeout : le compteur compte les sites,
    # pas les fichiers — c'est lui qui alimente le « --tolerance N » du rapport.
    assert verdict == {"mord_sur_fautif": 2, "sur_head": 0, "retenue": True, "motif": ""}


def test_une_regle_bavarde_sur_head_est_rejetee_mais_chiffree(tmp_path, monkeypatch):
    bruyant = tmp_path / "bruyant.py"
    bruyant.write_text(AVANT_KW, encoding="utf-8")
    monkeypatch.setattr(G, "collect", lambda paths: [str(bruyant)])
    regle = D._regle({"forme": "appel_sans_kwarg", "cible": "subprocess.run",
                      "kwarg": "timeout"}, "deadbeef")
    verdict = D.backtest([regle], AVANT_KW, "app/x.py", 0)[regle["id"]]
    assert verdict["retenue"] is False
    assert verdict["sur_head"] == 2
    assert "--tolerance 2" in verdict["motif"], "le rapport doit dire comment l'admettre"


def test_la_tolerance_admet_une_dette_connue(tmp_path, monkeypatch):
    bruyant = tmp_path / "bruyant.py"
    bruyant.write_text(AVANT_KW, encoding="utf-8")
    monkeypatch.setattr(G, "collect", lambda paths: [str(bruyant)])
    regle = D._regle({"forme": "appel_sans_kwarg", "cible": "subprocess.run",
                      "kwarg": "timeout"}, "deadbeef")
    assert D.backtest([regle], AVANT_KW, "app/x.py", 2)[regle["id"]]["retenue"] is True
