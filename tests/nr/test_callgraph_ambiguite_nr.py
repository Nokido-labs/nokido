"""NR — `callers()` doit DECLARER quand il ne sait pas de quelle classe il parle.

Ne dans le debat CLAUDE<->AGY du 2026-08-31 sur l'index structurel du code.

Le defaut, mesure et non suppose : `_call_name` rend `f.attr` pour un
`ast.Attribute` — le nom de la methode SANS son receveur. Quand plusieurs
classes definissent le meme nom, chaque appelant est attribue AU HASARD parmi
elles. Sur `app/` + `tools/` : 874 des 2322 noms de methode (37,6 %) sont
partages par >= 2 classes, et 50,6 % des 109 972 appels `x.methode()` visent
l'un de ces noms. `get_tools` est defini par 87 classes et `callers()` rendait
80 appelants — sans un mot de reserve.

Un agent lisait « 80 usages, ne supprime pas » ou « 0 usage, supprime » avec la
meme confiance, alors que la reponse pouvait etre fausse dans les deux sens. Un
outil qui se tait sur son incertitude est plus dangereux qu'un outil absent,
parce qu'on AGIT dessus.

Lever l'ambiguite exige une inference de type inter-fichier (index type SCIP) ;
la DECLARER ne coute rien. Ces tests verrouillent la declaration.

HERMETIQUE : le banc est construit dans `tmp_path` et le module est pointe
dessus. Aucun test ne depend de l'etat du working tree — un compteur du depot
reel (« 87 classes ») changerait au premier commit venu.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus rg (code appele) (l.109)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app import forge_callgraph_jit as jit  # noqa: E402


@pytest.fixture()
def banc(tmp_path, monkeypatch):
    """Le banc d'AGY, mais DANS le perimetre balaye.

    Sa demonstration initiale vivait dans `sandbox/`, que `_SCAN_ROOTS` n'inclut
    pas : l'outil n'y voyait rien, et le vide se lisait a tort comme une
    refutation. Ici le banc est a l'interieur, donc le resultat mesure le
    mecanisme et non le perimetre.
    """
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod1.py").write_text(
        "class Dog:\n"
        "    def speak(self):\n"
        "        return 'wouf'\n"
        "\n"
        "class Robot:\n"
        "    def speak(self):\n"
        "        return 'bip'\n"
        "\n"
        "class Dog2:\n"
        "    def unique_a_une_classe(self):\n"
        "        return 1\n",
        encoding="utf-8")
    (pkg / "mod2.py").write_text(
        "from pkg.mod1 import Dog\n"
        "\n"
        "def make_sound(obj):\n"
        "    return obj.speak()\n"
        "\n"
        "def appelle_unique(o):\n"
        "    return o.unique_a_une_classe()\n",
        encoding="utf-8")
    monkeypatch.setattr(jit, "ROOT", tmp_path)
    monkeypatch.setattr(jit, "_SCAN_ROOTS", ("pkg",))
    jit._DEP_CACHE.clear()          # le cache TTL 60 s traverserait les tests
    return tmp_path


# ── les trois etats ─────────────────────────────────────────────────────────
def test_un_nom_porte_par_deux_classes_est_AMBIGU(banc):
    a = jit.ambiguite("speak")
    assert a["etat"] == jit.AMBIGU
    assert a["classes"] == 2
    assert any("Dog" in d for d in a["definie_par"])
    assert any("Robot" in d for d in a["definie_par"])


def test_un_nom_porte_par_une_seule_classe_est_RESOLU(banc):
    assert jit.ambiguite("unique_a_une_classe")["etat"] == jit.RESOLU


def test_un_nom_introuvable_est_ILLISIBLE_pas_RESOLU(banc):
    """« Je n'ai pas trouve » n'autorise PAS a conclure « pas d'usage ».

    C'est le troisieme etat : le confondre avec RESOLU ferait supprimer du code
    sur une absence de preuve.
    """
    a = jit.ambiguite("methode_qui_nexiste_pas")
    assert a["etat"] == jit.ILLISIBLE
    assert a["classes"] == 0


# ── la reserve voyage AVEC chaque appelant ──────────────────────────────────
def test_chaque_appelant_porte_la_reserve(banc):
    """Un appelant lu isolement doit porter l'incertitude avec lui.

    Mettre l'avertissement uniquement en tete de reponse ne suffit pas : les
    entrees sont filtrees, triees et re-affichees ailleurs.
    """
    cs = jit.callers("speak")
    assert cs, "le banc doit produire au moins un appelant"
    assert all(c["resolution"] == jit.AMBIGU for c in cs)


def test_un_appelant_non_ambigu_est_estampille_RESOLU(banc):
    cs = jit.callers("unique_a_une_classe")
    assert cs
    assert all(c["resolution"] == jit.RESOLU for c in cs)


# ── le verbe expose au consommateur ─────────────────────────────────────────
def test_le_compteur_d_appelants_ne_part_plus_sans_sa_reserve(banc):
    """`callers_count: 80` se lisait comme 80 usages certains."""
    d = jit.get_function_dependencies("speak")
    assert d["ambiguite"]["etat"] == jit.AMBIGU
    assert "avertissement" in d
    assert "n'est PAS un nombre d'usages" in d["avertissement"]


def test_pas_d_avertissement_quand_l_attribution_est_sure(banc):
    d = jit.get_function_dependencies("unique_a_une_classe")
    assert d["ambiguite"]["etat"] == jit.RESOLU
    assert "avertissement" not in d


# ── definitions() : la brique sous-jacente ──────────────────────────────────
def test_definitions_distingue_methode_et_fonction_de_module(banc):
    """Une fonction de module a `classe=None` : c'est ce qui rend 62 % du corps
    non ambigu, et il ne faut pas le compter comme une classe."""
    (banc / "pkg" / "mod3.py").write_text(
        "def fonction_de_module():\n    return 0\n", encoding="utf-8")
    defs = jit.definitions("fonction_de_module")
    assert defs and all(d["classe"] is None for d in defs)
    assert jit.ambiguite("fonction_de_module")["etat"] == jit.RESOLU


def test_le_garde_sait_mordre(banc):
    """Contre-epreuve : sans le correctif, tout serait RESOLU.

    Un test qui ne peut pas echouer ne garde rien — on verifie que les deux
    verdicts sont bien produits par le MEME banc.
    """
    etats = {jit.ambiguite(n)["etat"]
             for n in ("speak", "unique_a_une_classe", "absent_xyz")}
    assert etats == {jit.AMBIGU, jit.RESOLU, jit.ILLISIBLE}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
