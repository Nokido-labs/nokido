"""NR — les deux regles posees le 2026-09-19 MORDENT, et ne crient pas a faux.

Directive owner : « une impossibilite s'enonce APRES mesure, jamais avant »,
prononcee apres trois reprises dans la meme heure — et avec le reproche qui
compte : *« y en a marre de te reprendre alors que tu as la solution deja
faite »*. La doctrine est dans `RULES_SHARED.md` ; ici on garde sa forme
EXECUTABLE, parce que le depot l'exige : une regle qu'on peut lire et ignorer
n'est pas un garde, c'est une note.

Les trois cas payes le 19/09, tous de la meme famille :
  - « aucun compte du hub ne peut ecrire dans le superrepo » -> `LaForgeTrusted`
    le fait, et la carte du 09/09 le disait ; j'ai bumpe au git BRUT alors que
    `forge_bump_superrepo.py` existait ;
  - « la CI certifiante est hors de portee » -> `--reference <sha>` existait ;
  - « le mode ne s'est pas enclenche » -> il tournait, mon motif ne matchait pas.

Chaque test a sa CONTRE-EPREUVE : un garde qui crie a faux se fait desarmer.
"""
import importlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
hcg = importlib.import_module("hook_capability_gate")


def _regle(motif: str):
    """La regle dont le message porte ce motif, ou un echec qui le DIT."""
    trouvees = [(p, m) for p, m in hcg.REGLES if motif in m]
    assert len(trouvees) == 1, \
        "attendu 1 regle portant `%s`, vu %d" % (motif, len(trouvees))
    p, m = trouvees[0]
    return re.compile(p, re.IGNORECASE), m


# ─────────────────────────────── outil gouverne saute ───────────────────────

def test_le_bump_au_git_BRUT_declenche_le_rappel():
    rx, msg = _regle("outil_gouverne_saute")
    assert rx.search('git -c safe.directory=* -C "C:/U/N/Script python IA" add Nokido')
    assert rx.search("git -C /depot add Nokido && git commit -m x")
    assert "forge_bump_superrepo.py" in msg, \
        "un rappel qui ne NOMME pas l'outil gouverne ne sert a rien"
    assert "trusted_script" in msg, "et il doit nommer le CANAL qui marche"


def test_il_ne_crie_PAS_sur_les_gestes_legitimes():
    """Contre-epreuve : indexer un fichier du submodule, ou passer par l'outil."""
    rx, _ = _regle("outil_gouverne_saute")
    for sain in (
        "git -C /depot add app/forge_token_monitor.py",
        "git -C /depot add tests/nr/test_x_nr.py tools/ci_local.py",
        "run action=trusted_script path=tools/forge_bump_superrepo.py",
        "git -C /depot commit -m 'Nokido: un sujet qui parle de Nokido'",
    ):
        assert not rx.search(sain), sain


# ───────────────────────────────── ci sans reference ────────────────────────

def test_une_CI_sans_reference_declenche_le_rappel():
    rx, msg = _regle("ci_sans_reference")
    assert rx.search("run action=run_job script=tools/ci_local.py")
    assert rx.search("python tools/ci_local.py --fast")
    assert "PROOF_ROOT_MISSING" in msg, "nommer CE que le juge rend"
    assert "--reference" in msg, "et le drapeau qui corrige"
    assert "HEAD de l'INSTANT" in msg, \
        "dire POURQUOI le sha imprime ne certifie pas — sinon on le croit"


def test_une_CI_AVEC_reference_ne_declenche_PAS():
    """Contre-epreuve : le mode certifiant ne doit pas etre rappele a l'ordre."""
    rx, _ = _regle("ci_sans_reference")
    for sain in (
        "python tools/ci_local.py --reference c3c55d69a136",
        "run action=run_job script=tools/ci_local.py script_args=\"--reference abc123\"",
        "run action=run_job script=tools/ci_local.py --impacte --reference abc123",
    ):
        assert not rx.search(sain), sain


def test_PARLER_de_ci_local_n_est_pas_le_LANCER(monkeypatch):
    """Faux positif paye dans la MINUTE qui a suivi la pose de la regle.

    Le motif etait `ci_local\\.py` nu : il a tire sur `git add tools/ci_local.py`,
    c'est-a-dire sur un commit, pas sur un lancement de CI. Un garde qui crie a
    faux se fait desarmer — corriger le DIAGNOSTIC, jamais contourner le garde.
    """
    rx, _ = _regle("ci_sans_reference")
    for sain in (
        "git -c safe.directory=* -C /depot add tools/ci_local.py",
        "git -C /depot add RULES_SHARED.md tools/ci_local.py tests/nr/test_x_nr.py",
        'findstr /n /c:"PURE_TESTS" tools\\ci_local.py',
        "governed_edit path=tools/ci_local.py",
        # 2e faux positif, paye dix minutes apres le 1er : le CHEMIN DU DEPOT
        # contient le mot-clef. Une ancre par proximite de mot ne tient pas ;
        # il faut la FORME D'INVOCATION (interpreteur colle au script).
        'git -C "C:/Users/N/Script python IA/Nokido" add tools/ci_local.py',
        'git -C "/d/Script python IA/Nokido" commit -m "touche a tools/ci_local.py"',
    ):
        assert not rx.search(sain), "faux positif sur : %s" % sain


def test_le_lancement_reste_detecte_malgre_un_chemin_piege():
    """Contre-contre-epreuve : en durcissant, ne pas rendre le garde AVEUGLE.

    Un garde qu'on borne trop cesse de tirer quand il faudrait — c'est la
    moitie silencieuse de la correction d'un faux positif, et personne ne la
    voit passer.
    """
    rx, _ = _regle("ci_sans_reference")
    for lancement in (
        '"C:/Users/N/Script python IA/miniforge3/python.exe" tools/ci_local.py',
        'python.exe tools\\ci_local.py --fast',
        "python -u tools/ci_local.py",
        "run action=run_job script=tools/ci_local.py",
    ):
        assert rx.search(lancement), "ne tire plus sur un VRAI lancement : %s" % lancement


# ─────────────────────────────────── cablage ────────────────────────────────

def test_les_deux_regles_sont_REELLEMENT_compilees_par_le_gate():
    """Une regle ajoutee a REGLES mais absente de _COMPILED ne tirerait jamais :
    c'est la dette de cablage que le depot appelle « un garde non branche ».
    """
    motifs = [m for _p, m in hcg.REGLES]
    compiles = [m for _rx, m in hcg._COMPILED]
    for cle in ("outil_gouverne_saute", "ci_sans_reference"):
        assert any(cle in m for m in motifs), cle
        assert any(cle in m for m in compiles), \
            "%s est declaree mais pas compilee — elle ne tirera jamais" % cle


def test_la_doctrine_est_ANCREE_dans_le_fichier_de_regles():
    """L'owner a demande le fichier ADAPTE : la regle vit dans RULES_SHARED,
    pas seulement dans une memoire de session qui disparait avec elle.
    """
    src = (ROOT / "RULES_SHARED.md").read_text(encoding="utf-8")
    assert "IMPOSSIBILITÉ s'énonce APRÈS mesure" in src
    assert "aucune conclusion ne se tire d'un" in src, \
        "le corollaire (le silence) est plus large que l'impossibilite"
    assert "hook_capability_gate" in src, \
        "la doctrine doit pointer sa forme EXECUTABLE, sinon elle reste une note"


@pytest.mark.parametrize("cle", ["outil_gouverne_saute", "ci_sans_reference"])
def test_chaque_message_porte_sa_MESURE_datee(cle):
    """Une regle sans mesure se discute ; une regle datee et chiffree se suit."""
    _rx, msg = _regle(cle)
    assert "2026-09-19" in msg, "la regle doit porter la date de ce qu'elle a coute"
