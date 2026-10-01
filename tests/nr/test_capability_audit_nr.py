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


# --- tableau « Project status » face a la politique des services -------------
# Mesure 2026-09-30 : le README affichait A2A « operational » alors que NokidoA2A
# est disabled, et l'homeostasie « daemon deliberately stopped » alors qu'elle
# tourne. Seize controles etaient ALIGNES : aucun ne lisait ce bloc.

def _readme_statut(*lignes, vivant=True):
    prose = "Live state on your machine: `nokido-doctor --vivant`.\n\n" if vivant else ""
    return ("# 🔬 Project status\n\n" + prose + "```text\nCOMMUNICATION\n"
            + "\n".join(lignes) + "\n```\n")


def _toml(**services):
    return "".join('[[service]]\nname = "%s"\ndisabled = %s\n'
                   % (nom, "true" if coupe else "false")
                   for nom, coupe in services.items())


def test_un_service_coupe_affiche_operationnel_est_detecte():
    m = _audit()
    r = m.c_statut(_readme_statut("  A2A Tier-1                      ✅ operational"),
                   "", toml=_toml(NokidoA2A=True))
    assert r["statut"] == m.DIVERGE
    assert "A2A" in r["note"]


def test_un_service_actif_dit_arrete_est_detecte():
    m = _audit()
    r = m.c_statut(_readme_statut(
        "  Emergency homeostasis           ✅ achieved (safeguard mode: the",
        "                                  regulation daemon is deliberately",
        "                                  stopped since 2026-09-05)"),
        "", toml=_toml(NokidoHomeostasis=False))
    assert r["statut"] == m.DIVERGE
    assert "homeostasis" in r["note"].lower()


def test_un_tableau_aligne_ne_declenche_rien():
    m = _audit()
    r = m.c_statut(_readme_statut(
        "  A2A Tier-1                      ⏸️ paused            `NokidoA2A`, disabled by default",
        "  Emergency homeostasis           ✅ achieved          `NokidoHomeostasis`, enabled by default"),
        "", toml=_toml(NokidoA2A=True, NokidoHomeostasis=False))
    assert r["statut"] == m.ALIGNE, r


def test_un_tableau_sans_service_connu_le_DIT():
    """Aucune ligne confrontable n'est pas un tableau juste : c'est une mesure absente."""
    m = _audit()
    r = m.c_statut(_readme_statut("  A2A Tier-1                      ✅ operational       `forge_a2a_card`"),
                   "", toml="")
    assert r["statut"] == m.INDETERMINE


# --- un corps VIVANT ne se fige pas dans un README (owner 2026-10-01) ------------

def test_not_measured_est_une_divergence():
    m = _audit()
    r = m.c_statut(_readme_statut("  Swarm                           🟡 hardening         not measured by this table"),
                   "", toml=_toml())
    assert r["statut"] == m.DIVERGE and "not measured" in r["note"]


def test_un_check_sans_preuve_du_depot_est_une_divergence():
    m = _audit()
    r = m.c_statut(_readme_statut("  M2M                             ✅ operational       protocol in use"),
                   "", toml=_toml())
    assert r["statut"] == m.DIVERGE and "M2M" in r["note"]


def test_une_preuve_citee_qui_n_existe_pas_est_une_divergence():
    m = _audit()
    r = m.c_statut(_readme_statut("  M2M                             ✅ operational       `forge_m2m_inexistant`"),
                   "", toml=_toml())
    assert r["statut"] == m.DIVERGE and "forge_m2m_inexistant" in r["note"]


def test_une_preuve_citee_qui_existe_est_acceptee():
    m = _audit()
    r = m.c_statut(_readme_statut(
        "  M2M                             ✅ operational       `forge_m2m_protocol` validator",
        "  CI architectural gate           ✅ achieved          `anatomie` gate, blocking",
        "  Emergency homeostasis           ✅ achieved          `NokidoHomeostasis`, enabled by default"),
        "", toml=_toml(NokidoHomeostasis=False))
    assert r["statut"] == m.ALIGNE, r


def test_la_section_doit_designer_la_mesure_vivante():
    m = _audit()
    r = m.c_statut(_readme_statut(
        "  Emergency homeostasis           ✅ achieved          `NokidoHomeostasis`, enabled by default",
        vivant=False), "", toml=_toml(NokidoHomeostasis=False))
    assert r["statut"] == m.DIVERGE and "--vivant" in r["note"]


def test_les_traductions_portent_le_MEME_tableau_que_le_README():
    """Le controle lit README.md ; les 7 traductions copient son tableau. Mesure
    2026-10-01 : elles avaient garde l'ancien tableau (A2A « operational ») apres la
    correction de l'anglais -- deux fois en une semaine. Le bloc doit etre identique."""
    import re
    motif = re.compile(r"\n# 🔬[^\n]*\n.*?```text\n(.*?)```", re.S)
    ref = motif.search((ROOT / "README.md").read_text(encoding="utf-8"))
    assert ref, "tableau de statut introuvable dans README.md"
    for p in sorted((ROOT / "docs" / "i18n").glob("README.*.md")):
        m = motif.search(p.read_text(encoding="utf-8"))
        assert m, "%s : tableau de statut introuvable" % p.name
        assert m.group(1) == ref.group(1), "%s : tableau different du README" % p.name


def test_le_controle_du_tableau_est_cable_dans_l_audit():
    """Le chemin reel : auditer() doit le jouer, pas seulement la fonction exister."""
    m = _audit()
    assert "tableau de statut" in [nom for nom, _ in m.CONTROLES]


# --- bloc pip genere (decision owner 2026-10-01) -------------------------------

_PYPROJECT_PIP = "[project]\nname = \"nokido-agent\"\n"


def test_un_bloc_pip_retouche_a_la_main_diverge():
    m = _audit()
    readme = ("<!-- PIP:BEGIN nokido-agent version=0.21.0 -->\n"
              "```bash\npip install nokido-agent==0.22.0\n```\n<!-- PIP:END -->\n")
    assert m.c_bloc_pip(readme, _PYPROJECT_PIP)["statut"] == m.DIVERGE


def test_le_controle_du_bloc_pip_est_cable_dans_l_audit():
    m = _audit()
    assert "bloc pip" in [nom for nom, _ in m.CONTROLES]
