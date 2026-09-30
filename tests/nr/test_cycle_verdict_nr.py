"""Le verdict d'un cycle de dev collaboratif se PROUVE, et la cible ne bouge pas.

POURQUOI CET OUTIL EXISTE (2026-09-07). `forge_swarm_evidence` porte deja la bonne
these depuis le 2026-08-20 -- `Tentative` est une OBSERVATION, `arbitrer` tranche sans
voter, l'abstention y est une reussite. Mais il a **un seul importeur** : une these
juste, non branchee. C'est la « dette de cablage » nommee le 07/09 : ne jamais confondre
l'existence d'un mecanisme avec son effet. On ne reecrit donc pas d'arbitre, on lui
donne de quoi manger.

LE TROU QU'IL FERME. Le contrat de delegation retenu (veille `watch_e9ef7213e2_294`,
« define tests upfront as completion signals ») ne tient que si le test ne peut pas
etre deplace par celui qu'il juge. Un executant qui rend le NR vert **en modifiant le
NR** satisfait la lettre du contrat et en detruit le sens. L'empreinte du signal de
completion fait donc partie de la preuve, au meme titre que le resultat.

TROIS ETAGES (methode owner 2026-09-07) :
  UNITAIRE     l'empreinte et la lecture du temoin, sans lancer aucun test.
  SIMULATION   des tentatives fabriquees, dont une qui a deplace la cible.
  INTEGRATION  le chemin reel : pytest lance, JUnit relu, verdict rendu.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python -m pylint (code appele)
#   (l.201)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# --------------------------------------------------------------------------- UNITAIRE

def test_l_empreinte_du_signal_de_completion_est_lisible(tmp_path):
    """PROPRIETE 1. Trois etats : lue / absente / illisible -- jamais une chaine vide.

    Une empreinte vide comparee a une empreinte vide serait « identique » : le garde
    s'ouvrirait precisement quand il ne peut pas voir.
    """
    import forge_cycle_verdict as fcv  # noqa: PLC0415

    cible = tmp_path / "nr.py"
    cible.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    e1 = fcv.empreinte(cible)
    assert e1 and e1 != "ABSENT" and len(e1) >= 16

    cible.write_text("def test_x():\n    assert True  # touche\n", encoding="utf-8")
    assert fcv.empreinte(cible) != e1, "une modification doit changer l'empreinte"

    assert fcv.empreinte(tmp_path / "jamais.py") == "ABSENT", (
        "un fichier absent se DIT, il ne rend pas une empreinte vide")


def test_le_verdict_se_lit_sur_le_JUnit_pas_sur_le_code_de_retour(tmp_path):
    """PROPRIETE 2. Le temoin STRUCTURE fait foi ; un JUnit absent n'est pas un vert.

    Paye deux fois le 2026-09-07 : « aucun test n'echoue » conclu a l'oeil quand le
    JUnit disait `failures="1"` ; puis pytest tue avant d'ecrire son rapport, rc non
    nul et aucune preuve -- le gate a eu raison de ne pas racheter.
    """
    import forge_cycle_verdict as fcv  # noqa: PLC0415

    bon = tmp_path / "ok.xml"
    bon.write_text('<testsuites><testsuite tests="6" failures="0" errors="0"/>'
                   '</testsuites>', encoding="utf-8")
    assert fcv.lire_junit(bon) == {"tests": 6, "failures": 0, "errors": 0}

    rouge = tmp_path / "ko.xml"
    rouge.write_text('<testsuites><testsuite tests="6" failures="2" errors="0"/>'
                     '</testsuites>', encoding="utf-8")
    assert fcv.lire_junit(rouge)["failures"] == 2

    assert fcv.lire_junit(tmp_path / "absent.xml") is None, (
        "rapport absent -> None (INDETERMINE), jamais un bilan a zero echec")
    illisible = tmp_path / "casse.xml"
    illisible.write_text("<testsuites", encoding="utf-8")
    assert fcv.lire_junit(illisible) is None, "rapport illisible -> None, pas un vert"


# ------------------------------------------------------------------------- SIMULATION

def _tentative(fcv, **kw):
    base = {"agent": "WORKER_CODE", "modele": "qwen", "strategie": "patch",
            "solution_id": "busy_ms", "junit": {"tests": 6, "failures": 0, "errors": 0},
            "empreinte_attendue": "abc123", "empreinte_constatee": "abc123"}
    base.update(kw)
    return fcv.tentative(**base)


def test_une_tentative_qui_DEPLACE_la_cible_n_est_pas_utilisable():
    """PROPRIETE 3. Le coeur du garde : rendre vert en modifiant le NR ne vaut rien.

    Ce n'est pas un echec de test -- c'est une mesure INVALIDE. La distinction compte :
    on ne dit pas « ta solution est fausse », on dit « je n'ai pas pu la juger ».
    """
    import forge_cycle_verdict as fcv  # noqa: PLC0415

    t = _tentative(fcv, empreinte_constatee="ZZZ_modifiee")
    assert not t.utilisable, (
        "un NR modifie invalide la mesure : sinon le contrat de completion se satisfait "
        "en deplacant la cible")
    assert t.test_ok is not True, "verts obtenus sur une cible deplacee ne comptent pas"


def test_une_seule_voix_prouvee_ne_suffit_pas_a_ACCEPTER():
    """PROPRIETE 4. `min_voix` est respecte : une preuve seule PROPOSE, elle n'impose."""
    import forge_cycle_verdict as fcv  # noqa: PLC0415

    v = fcv.verdict([_tentative(fcv)], min_voix=2)
    assert v.action != "accept", "une voix unique ne peut pas emporter la decision"

    deux = [_tentative(fcv), _tentative(fcv, agent="AGY", modele="gemini",
                                        strategie="reecriture")]
    assert fcv.verdict(deux, min_voix=2).action == "accept", (
        "deux voix INDEPENDANTES et prouvees emportent la decision")


def test_sans_temoin_structure_on_S_ABSTIENT():
    """PROPRIETE 5. Pas de JUnit -> pas de verdict. L'abstention est la bonne sortie."""
    import forge_cycle_verdict as fcv  # noqa: PLC0415

    v = fcv.verdict([_tentative(fcv, junit=None)], min_voix=2)
    assert v.action in ("abstain", "retry"), (
        "sans preuve deterministe, conclure serait le seul vrai echec")
    assert v.etat != "SUPPORTED"


def test_l_arbitrage_est_DELEGUE_a_l_organe_existant():
    """PROPRIETE 6. Cablage, pas duplication : l'outil ne fabrique aucun verdict.

    Un second arbitre serait un systeme parallele -- exactement ce que la direction du
    07/09 interdit. On verifie donc dans la SOURCE qu'il appelle l'organe.
    """
    src = (ROOT / "tools" / "forge_cycle_verdict.py").read_text(
        encoding="utf-8", errors="replace")
    assert "forge_swarm_evidence" in src, "l'arbitre existant doit etre appele"
    assert "arbitrer(" in src, "le verdict vient de arbitrer(), pas d'une regle maison"


# ---------------------------------------------- LE JUGE CANONIQUE DU MANIFESTO
#
# Declaration 2 du MANIFESTO : « Aucun LLM ne juge un autre LLM dans la voie
# critique. Le verdict est symbolique. » §3.4 precise la chaine :
# `LLM-draft -> forge_scorecard (6 axes deterministes) -> GOAP routing`.
#
# MESURE 2026-09-07 : cette chaine n'existait pas. `evaluate_symbolic`,
# `evaluate_code` et `evaluate_patch` avaient **zero appelant** dans app/, tools/,
# tests/ et proxy_deno/core/ -- les seules traces etaient un TODO
# (`forge_agent_lats:19`) et une phrase de docstring (`forge_repo_map_tools:16`).
# Le seul usage vivant du module (`forge_mcp_registry:5390`) importe `Scorecard`
# comme FORMAT de sortie et construit la fiche depuis un score calcule ailleurs.
# Le juge canonique n'avait par ailleurs aucun test.
#
# Ces proprietes en font le premier appelant REEL, et interdisent le chemin LLM.

def test_le_certificateur_appelle_le_juge_SYMBOLIQUE_et_jamais_le_juge_LLM():
    """PROPRIETE 8. Zero LLM dans l'arbitrage -- verifie dans la SOURCE.

    `evaluate_code` appelle `_llm_judge`. L'employer ici ferait juger un LLM par un
    LLM dans la voie critique : exactement ce que la declaration 2 interdit. Le seul
    chemin admissible est `evaluate_symbolic` (AST, pylint E/F, LOC, graphe de deps,
    McCabe, budget tokens).

    UN INSTRUMENT NE LIT JAMAIS SON PROPRE VOCABULAIRE -- piege deja paye cinq fois
    en trois jours, et une sixieme ici meme : la premiere version de ce test
    cherchait la CHAINE `evaluate_code` et la trouvait dans le commentaire qui
    explique precisement qu'on ne l'emploie pas. On mesure donc un APPEL et un
    IMPORT, par AST. La propriete est inchangee ; seule sa mesure devient honnete.
    """
    import ast  # noqa: PLC0415

    src = (ROOT / "tools" / "forge_cycle_verdict.py").read_text(
        encoding="utf-8", errors="replace")
    arbre = ast.parse(src)

    noms: set = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.Call):
            f = n.func
            noms.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))
            noms.update(k.arg or "" for k in n.keywords)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            noms.update(a.name for a in n.names)

    assert "evaluate_symbolic" in noms, (
        "le juge canonique du manifesto n'est ni importe ni appele : le verdict "
        "d'un cycle reste hors de la chaine declaree en 3.4")
    for interdit in ("evaluate_code", "_llm_judge", "judge_model"):
        assert interdit not in noms, (
            "chemin LLM %r reellement emprunte : la declaration 2 du manifesto "
            "interdit qu'un LLM juge un LLM dans la voie critique" % interdit)


def test_le_scorecard_rend_un_grade_par_fichier_et_DIT_l_absent(tmp_path):
    """PROPRIETE 9. Trois etats. Un fichier absent ne vaut pas un grade neutre."""
    import forge_cycle_verdict as fcv  # noqa: PLC0415

    bon = tmp_path / "propre.py"
    bon.write_text("def f(x):\n    return x + 1\n", encoding="utf-8")

    fiches = fcv.scorecard([bon, tmp_path / "jamais.py"])
    assert str(bon) in fiches or bon.name in str(fiches)
    manquant = [v for k, v in fiches.items() if "jamais" in str(k)]
    assert manquant and manquant[0]["etat"] == "ABSENT", (
        "un fichier introuvable se DIT ABSENT ; lui donner un score serait "
        "inventer une mesure")


def test_un_fichier_livre_qui_ne_PARSE_PAS_est_un_VETO(tmp_path):
    """PROPRIETE 10. L'AST est un veto -- meme avec des tests verts.

    Le manifesto en fait le premier axe (0.20, veto si echec). Un JUnit vert sur un
    arbre dont un fichier livre ne parse pas signifie que ce fichier n'est pas
    exerce : ce n'est pas une preuve, c'est un angle mort.
    """
    import forge_cycle_verdict as fcv  # noqa: PLC0415

    casse = tmp_path / "casse.py"
    casse.write_text("def f(:\n    pass\n", encoding="utf-8")

    t = fcv.tentative(agent="X", modele="m", strategie="s", solution_id="sol",
                      junit={"tests": 3, "failures": 0, "errors": 0},
                      empreinte_attendue="a", empreinte_constatee="a",
                      scorecard=fcv.scorecard([casse]))
    assert not t.utilisable, (
        "un fichier livre qui ne parse pas doit invalider la livraison, "
        "quels que soient les tests")


def test_le_grade_du_juge_entre_dans_les_PREUVES(tmp_path):
    """PROPRIETE 11. Le verdict est traçable jusqu'a la metrique qui l'a produit.

    « Tu peux remonter chaque verdict a une metrique calculee » (manifesto §2.3).
    Un scorecard qui ne laisse pas de trace dans la preuve ne sert a rien.
    """
    import forge_cycle_verdict as fcv  # noqa: PLC0415

    bon = tmp_path / "propre.py"
    bon.write_text("def f(x):\n    return x + 1\n", encoding="utf-8")

    t = fcv.tentative(agent="X", modele="m", strategie="s", solution_id="sol",
                      junit={"tests": 3, "failures": 0, "errors": 0},
                      empreinte_attendue="a", empreinte_constatee="a",
                      scorecard=fcv.scorecard([bon]))
    assert any("scorecard" in str(p) for p in t.preuves), (
        "le grade doit figurer dans les preuves, sinon le verdict n'est pas "
        "remontable a sa metrique")


def test_le_juge_symbolique_est_DETERMINISTE(tmp_path):
    """PROPRIETE 12. « CERTIFICATION doit etre deterministe » (direction 07/09).

    Deux passages sur le meme contenu rendent le meme score. C'est ce qui distingue
    un instrument de certification d'une heuristique de selection.
    """
    import forge_cycle_verdict as fcv  # noqa: PLC0415

    f = tmp_path / "stable.py"
    f.write_text("def g(a, b):\n    return a * b\n", encoding="utf-8")

    a = fcv.scorecard([f])
    b = fcv.scorecard([f])
    va, vb = list(a.values())[0], list(b.values())[0]
    assert va["score"] == vb["score"] and va["grade"] == vb["grade"], (
        "le juge symbolique doit etre reproductible : %r vs %r" % (va, vb))


# ------------------------------------------------------------------------ INTEGRATION

def test_le_chemin_REEL_lance_pytest_et_conclut_sur_le_rapport(tmp_path):
    """PROPRIETE 7. Le point d'entree traverse le vrai chemin : pytest -> JUnit -> verdict.

    `check()` qui passe pendant que `--check` meurt en NameError a deja ete paye : un NR
    emprunte le chemin reel, pas seulement la fonction.
    """
    import forge_cycle_verdict as fcv  # noqa: PLC0415

    nr = tmp_path / "test_faux_nr.py"
    nr.write_text("def test_vrai():\n    assert True\n", encoding="utf-8")
    bilan, empreinte = fcv.mesurer(nr, tmp_path)
    assert empreinte != "ABSENT"
    assert bilan is not None, "le rapport JUnit doit avoir ete ECRIT et relu"
    assert bilan["failures"] == 0 and bilan["tests"] == 1

    nr_ko = tmp_path / "test_faux_ko_nr.py"
    nr_ko.write_text("def test_faux():\n    assert False\n", encoding="utf-8")
    bilan_ko, _ = fcv.mesurer(nr_ko, tmp_path)
    assert bilan_ko is not None and bilan_ko["failures"] == 1, (
        "un echec reel doit etre LU dans le rapport, pas deduit du code de retour")
