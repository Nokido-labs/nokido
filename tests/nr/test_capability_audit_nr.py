"""NR -- l'audit README contre code doit MORDRE, pas seulement rendre vert.

POURQUOI. `forge_capability_audit` rend aujourd'hui 8 ALIGNE sur 8. Un garde
entierement vert est exactement ce qu'on traque ailleurs : il peut l'etre parce
que tout va bien, ou parce qu'il ne mesure plus rien. Ces tests fabriquent des
declarations FAUSSES et exigent la divergence, puis des declarations justes et
exigent le silence.

Ils portent sur les trois controles PURS (README + pyproject passes en
argument). Les autres lisent le depot et sont couverts par l'execution reelle.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

for _zone in ("tools", "app"):
    _p = str(ROOT / _zone)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _audit():
    chemin = ROOT / "tools" / "forge_capability_audit.py"
    assert chemin.exists(), "module absent : %s" % chemin
    spec = importlib.util.spec_from_file_location("forge_capability_audit", chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["forge_capability_audit"] = mod
    sys.modules["nokido_agent.tools.forge_capability_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


_PYPROJECT = """
[project]
name = "nokido-agent"

[project.scripts]
nokido = "x:main"
nokido-hub = "x:hub"

[project.optional-dependencies]
hub = ["a"]
rag = ["b"]
full = ["a", "b"]
all = ["a", "b"]
"""


def test_un_paquet_pip_perime_est_detecte():
    m = _audit()
    faux = "pip install git+https://x#egg=laforge-agent[hub]"
    assert m.c_nom_paquet(faux, _PYPROJECT)["statut"] == m.DIVERGE


def test_le_bon_paquet_pip_ne_declenche_rien():
    m = _audit()
    juste = "pip install git+https://x#egg=nokido-agent[hub]"
    assert m.c_nom_paquet(juste, _PYPROJECT)["statut"] == m.ALIGNE


def test_une_commande_inexistante_est_detectee():
    m = _audit()
    faux = "Entry points : `laforge-hub`, `nokido-hub`."
    r = m.c_entrypoints(faux, _PYPROJECT)
    assert r["statut"] == m.DIVERGE
    assert "laforge-hub" in r["note"]


def test_un_nom_de_modele_n_est_pas_pris_pour_une_commande():
    """`laforge-qwen` est un modele Ollama : le garde ne doit pas exiger un
    entrypoint du meme nom, sinon il crie a faux et se fait desarmer."""
    m = _audit()
    prose = "Ollama sert 12 modeles (qwen2.5-coder, laforge-qwen, deepseek-r1)."
    assert m.c_entrypoints(prose, _PYPROJECT)["statut"] == m.ALIGNE


def test_un_conteneur_docker_n_est_pas_pris_pour_une_commande():
    m = _audit()
    bloc = "```bash\ndocker exec laforge-ollama ollama pull qwen\n```"
    assert m.c_entrypoints(bloc, _PYPROJECT)["statut"] == m.ALIGNE


def test_un_nombre_d_extras_faux_est_detecte():
    m = _audit()
    r = m.c_extras("Nokido se package en **17 extras** modulaires.", _PYPROJECT)
    assert r["statut"] == m.DIVERGE
    assert r["mesure"] == 2  # hub + rag ; full et all sont des bundles


def test_le_bon_nombre_d_extras_ne_declenche_rien():
    m = _audit()
    r = m.c_extras("Nokido se package en **2 extras** modulaires.", _PYPROJECT)
    assert r["statut"] == m.ALIGNE


def test_un_controle_qui_ne_peut_pas_mesurer_le_DIT():
    """INDETERMINE n'est ni un succes ni un echec -- mais il doit exister."""
    m = _audit()
    r = m.c_extras("Nokido se package en **17 extras**.", "[project]\nname = 'x'")
    assert r["statut"] == m.INDETERMINE
