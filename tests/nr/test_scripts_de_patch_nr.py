"""NR — un script de patch qui touche un CRITICAL_FILE doit se retenir.

`tools/forge_patch_*.py` existe parce que `governed_edit` a DEJA coupe le hub
sur un gros CRITICAL_FILE (2026-08-27). Le chemin sur est un script commite,
lance par `run action=trusted_script`. Mais un script de patch mal ecrit est
pire que l'edition qu'il remplace : il ecrit dans `tools/nokido_hub.py`, et une
ancre approximative peut remplacer autre chose que ce qu'on croit, ou produire
un fichier a moitie ecrit dont le hub ne redemarre pas.

Quatre proprietes verifiees ici, statiquement (aucun import : ces scripts
ECRIVENT, on ne les execute pas pour les tester) :

  1. l'ancre est comptee avant d'etre remplacee -- `count(...) != 1` refuse,
     parce qu'une ancre absente et une ancre AMBIGUE sont deux facons
     differentes de patcher le mauvais endroit ;
  2. le resultat est valide par `ast.parse` AVANT d'atteindre le disque ;
  3. l'ecriture est atomique (`os.replace`), sinon une interruption laisse un
     CRITICAL_FILE tronque ;
  4. le fichier est RELU pour confirmer -- « ecrit sans erreur » n'est pas
     « ecrit », et c'est la meme discipline que `governed_edit` applique.

Ce test nomme aussi `forge_authz_url_dynamiques` et `forge_rules_restore`,
outils du meme chantier, pour qu'ils cessent d'etre des modules qu'aucun test
ne cite -- un module que rien ne nomme n'a aucune chance d'echouer le jour ou
il regresse.
"""

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(ROOT / "app"))

# PORTEE BORNEE, et c'est une correction faite dans la minute : la premiere
# version parametrait sur `TOOLS.glob("forge_patch_*.py")` et imposait donc ces
# quatre exigences a TOUS les scripts de patch du depot -- 194 echecs d'un coup
# sur des scripts historiques, ecrits avant que ces regles existent et hors de
# tout mandat. Un test neuf qui rend rouge l'existant ne durcit rien : il se
# fait desarmer, comme un garde qui crie a faux.
#
# La liste est donc EXPLICITE : les scripts du chantier authz/credentials du
# 2026-09-02, ceux dont je reponds. Un futur script de patch s'ajoute ici, et
# c'est un geste volontaire -- pas une regle retroactive.
PATCHS = [TOOLS / nom for nom in (
    "forge_patch_authz_shadow.py",
    "forge_patch_authz_via_reel.py",
    "forge_patch_login_dpop.py",
    "forge_patch_tool_annotations.py",
    "forge_patch_tools_list_rolescope.py",
    "forge_patch_via_capability.py",
) if (TOOLS / nom).exists()]
AUTRES = ["forge_authz_url_dynamiques", "forge_rules_restore"]


def _source(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def test_il_y_a_bien_des_scripts_de_patch_a_verifier():
    """Garde du garde : si le glob ne trouve rien, les tests parametres
    ci-dessous passeraient tous en silence sur zero fichier."""
    assert PATCHS, "aucun tools/forge_patch_*.py trouve : le garde ne garde rien"


@pytest.mark.parametrize("chemin", PATCHS, ids=lambda p: p.name)
def test_l_ancre_est_comptee_avant_d_etre_remplacee(chemin):
    """Une ancre ABSENTE et une ancre AMBIGUE doivent toutes deux arreter le
    script. `replace()` seul ferait les deux erreurs en silence."""
    src = _source(chemin)
    assert ".count(" in src, (
        "%s remplace sans compter son ancre : une ancre presente deux fois "
        "patcherait deux endroits" % chemin.name)
    assert "!= 1" in src or "== 1" in src, (
        "%s ne verifie pas l'UNICITE de son ancre" % chemin.name)


# `ast.parse` et `compile(..., "exec")` valident tous deux la syntaxe ; refuser
# le second serait exiger une FORME au lieu d'une PROPRIETE. Mesure du
# 2026-09-02 : la premiere version de ce test accusait quatre scripts
# parfaitement corrects parce qu'ils employaient `compile()`. Un garde qui crie
# a faux se fait desarmer -- corrige dans la minute.
_VALIDATEURS = ("ast.parse", "compile(")
# Idem pour l'idempotence : le message importe peu, c'est la sortie anticipee
# qui protege d'un second passage.
_IDEMPOTENCE = ("DEJA APPLIQUE", "DEJA PATCHE", "Rien a faire", "deja applique")


@pytest.mark.parametrize("chemin", PATCHS, ids=lambda p: p.name)
def test_le_resultat_est_valide_avant_d_atteindre_le_disque(chemin):
    src = _source(chemin)
    trouves = [v for v in _VALIDATEURS if v in src]
    assert trouves, (
        "%s ecrit du Python sans en verifier la syntaxe : un CRITICAL_FILE "
        "casse empeche le hub de redemarrer" % chemin.name)
    i_valide = min(src.find(v) for v in trouves)
    i_ecrit = src.find("os.replace")
    if i_ecrit >= 0:
        assert i_valide < i_ecrit, (
            "%s valide APRES avoir ecrit : trop tard" % chemin.name)


@pytest.mark.parametrize("chemin", PATCHS, ids=lambda p: p.name)
def test_l_ecriture_est_atomique(chemin):
    src = _source(chemin)
    assert "os.replace" in src, (
        "%s n'ecrit pas atomiquement : une interruption laisse le "
        "CRITICAL_FILE tronque" % chemin.name)


@pytest.mark.parametrize("chemin", PATCHS, ids=lambda p: p.name)
def test_le_fichier_est_relu_pour_confirmer(chemin):
    """« Ecrit sans erreur » n'est pas « ecrit »."""
    src = _source(chemin)
    assert "read_text" in src and (
        "NON CONFIRMEE" in src or "relu" in src.lower() or "verified" in src), (
        "%s ne relit pas son resultat" % chemin.name)


@pytest.mark.parametrize("chemin", PATCHS, ids=lambda p: p.name)
def test_le_script_est_rejouable_sans_degat(chemin):
    """Relance = pas de second patch. `trusted_script` peut etre rejoue, et un
    remplacement applique deux fois duplique le code injecte."""
    src = _source(chemin)
    assert any(m in src for m in _IDEMPOTENCE), (
        "%s ne detecte pas qu'il a deja tourne" % chemin.name)


@pytest.mark.parametrize("chemin", PATCHS, ids=lambda p: p.name)
def test_le_script_lui_meme_est_syntaxiquement_valide(chemin):
    ast.parse(_source(chemin))


@pytest.mark.parametrize("nom", AUTRES)
def test_les_outils_du_chantier_sont_lisibles_et_valides(nom):
    p = TOOLS / ("%s.py" % nom)
    if not p.exists():
        p = ROOT / "app" / ("%s.py" % nom)
    assert p.exists(), "%s introuvable dans tools/ ni app/" % nom
    arbre = ast.parse(_source(p))
    fonctions = [n.name for n in ast.walk(arbre)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert fonctions, "%s n'expose aucune fonction" % nom
