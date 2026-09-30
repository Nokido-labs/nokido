# -*- coding: utf-8 -*-
"""NR — scalene_cmd cible le BON interpreteur (forge_profiler_hooks).

Mesure 2026-08-19 : scalene_cmd renvoyait `LAFORGE_PY` (miniforge base), un env
MINIMAL sans les deps Nokido (faiss/litellm). Profiler un script Nokido par base
plantait a l'import -- pas scalene, l'env. Le vrai runtime est laforge_py314 ou
scalene est desormais installe (build py314). scalene_cmd doit donc profiler avec
l'interpreteur COURANT (celui qui porte les deps), pas base.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

import forge_profiler_hooks as P  # noqa: E402


def test_defaut_est_l_interpreteur_courant():
    cmd = P.scalene_cmd("mon_script.py")
    assert cmd[0] == sys.executable
    assert cmd[1:] == ["-m", "scalene", "mon_script.py"]


def test_ne_pointe_plus_sur_base_minimal():
    # Regression : ne doit plus renvoyer LAFORGE_PY (base) par defaut.
    assert P.scalene_cmd("s.py")[0] != P.LAFORGE_PY or sys.executable == P.LAFORGE_PY


def test_override_python_respecte():
    py = r"%USERPROFILE%\miniforge3\envs\laforge_py314\python.exe"
    assert P.scalene_cmd("s.py", python=py)[0] == py


def test_forme_de_commande_scalene():
    cmd = P.scalene_cmd("chemin/vers/script.py", python="X")
    assert cmd == ["X", "-m", "scalene", "chemin/vers/script.py"]
