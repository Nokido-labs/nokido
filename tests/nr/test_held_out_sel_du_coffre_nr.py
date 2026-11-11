# -*- coding: utf-8 -*-
"""NR (owner 4/11, ensemble mis de cote) : le jeu held-out du juge (24 NR) est tire par sha256(sel + chemin) ; le sel
venait SEULEMENT de LAFORGE_HELD_OUT_SEL, absent de l'environnement du service -> jeu PREVISIBLE par qui lit le code
(le juge le disait : sel absent). Le sel est un secret : il vient desormais du coffre (forge_secrets.get_secret) a
defaut de l'environnement. Coffre muet ou illisible : « absent », dit, jamais un sel invente."""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nokido_agent.app import forge_mutation_judge as J  # noqa: E402


def _arbre(tmp_path):
    (tmp_path / "tests" / "nr").mkdir(parents=True)
    for i in range(12):
        (tmp_path / "tests" / "nr" / ("test_n%02d_nr.py" % i)).write_text("def test_x():\n    pass\n", encoding="utf-8")
    return tmp_path


def _coffre(monkeypatch, valeur):
    def get_secret(nom, *a, **k):
        if valeur is Exception:
            raise RuntimeError("coffre illisible")
        return valeur if nom == "LAFORGE_HELD_OUT_SEL" else None
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secrets", types.SimpleNamespace(get_secret=get_secret))


def test_le_sel_vient_du_coffre(monkeypatch, tmp_path):
    monkeypatch.delenv("LAFORGE_HELD_OUT_SEL", raising=False)
    r = _arbre(tmp_path)
    _coffre(monkeypatch, None)
    sans = J.held_out([], n=5, racine=r)
    _coffre(monkeypatch, "sel-secret-du-coffre")
    avec = J.held_out([], n=5, racine=r)
    assert sans["sel"] == "absent" and avec["sel"] == "present"
    assert avec["tests"] != sans["tests"] or len(sans["tests"]) < 5   # le sel change le tirage


def test_coffre_illisible_reste_absent(monkeypatch, tmp_path):
    monkeypatch.delenv("LAFORGE_HELD_OUT_SEL", raising=False)
    _coffre(monkeypatch, Exception)
    assert J.held_out([], n=5, racine=_arbre(tmp_path))["sel"] == "absent"


def test_l_environnement_prime(monkeypatch, tmp_path):
    monkeypatch.setenv("LAFORGE_HELD_OUT_SEL", "env")
    _coffre(monkeypatch, None)
    assert J.held_out([], n=5, racine=_arbre(tmp_path))["sel"] == "present"
