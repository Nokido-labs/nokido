"""NR : un echec d'ASSERTION est localise par le symbole que cite pytest (owner 26/10, « go »).

Mesure 26/10 14 h (test_juge_artefact_workdir_nr) : la fonction fautive avait RENDU une valeur sans lever ; aucune
frame app/tools dans la trace -> pointer_ref null. Pytest la nomme pourtant : « <function _artefact_declare_absent
at 0x...> = E._artefact_declare_absent », E etant l'alias importe par le test. On resout l'alias par les imports
du fichier de test, puis la fonction par ast. Ambigu ou introuvable -> null, raison dite.
"""
import sys
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_rel_depuis_junit as rel  # noqa: E402


def _depot(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "forge_cible.py").write_text(
        "def autre():\n    pass\n\n\ndef _declare_absent(detail, wd):\n    return None\n", encoding="utf-8")
    (tmp_path / "tests" / "nr").mkdir(parents=True)
    (tmp_path / "tests" / "nr" / "test_z.py").write_text(
        "import forge_cible as E\n\ndef test_a():\n    assert 'absent' in (E._declare_absent('x', 'y') or '')\n",
        encoding="utf-8")
    return tmp_path


MESSAGE = ("assert 'absent' in ((None or ''))\n +  where None = <function _declare_absent at 0x000001B8BF>('x', 'y')\n"
           " +    where <function _declare_absent at 0x000001B8BF> = E._declare_absent")
TRACE = "    def test_a():\n>       assert 'absent' in ...\nE       AssertionError\n\ntests\\nr\\test_z.py:4: AssertionError"


def test_assertion_localisee_par_le_symbole_cite(tmp_path, monkeypatch):
    monkeypatch.setattr(rel, "ROOT", _depot(tmp_path))
    p = rel.localiser(TRACE, MESSAGE)
    assert p == {"file": "tools/forge_cible.py", "function": "_declare_absent", "line": 5,
                 "source": "symbole_assertion"}


def test_frame_de_pile_prioritaire_sur_le_symbole(tmp_path, monkeypatch):
    monkeypatch.setattr(rel, "ROOT", _depot(tmp_path))
    trace = "tests/nr/test_z.py:4: in test_a\n    f()\napp/forge_x.py:42: in f\n    raise ValueError\nE   ValueError"
    assert rel.localiser(trace, MESSAGE)["file"] == "app/forge_x.py"


def test_alias_introuvable_reste_null(tmp_path, monkeypatch):
    monkeypatch.setattr(rel, "ROOT", _depot(tmp_path))
    msg = MESSAGE.replace("E._declare_absent", "Z._declare_absent")
    assert rel.localiser(TRACE, msg) is None


def test_sans_message_le_comportement_historique_est_garde(tmp_path, monkeypatch):
    monkeypatch.setattr(rel, "ROOT", _depot(tmp_path))
    assert rel.localiser(TRACE) is None
