"""Le resume ne se contredit pas lui-meme, et n'affiche jamais vert un NON JUGE.

CE QUI A ETE PAYE (mesure du 2026-09-14, certification de `3ecc8d5a3`). Le meme
ecran affichait, a trois lignes d'intervalle :

    ✅ ui-acceptance (contrat web_hub :7400) [NON JUGE]
    ❔ ui-acceptance (contrat web_hub :7400) : NON MESURE (aucun supplement declare)
    Tous les gates bloquants passent (2 non mesure(s), tous supplees)

Le detail dit la verite, l'agregat ment, et la coche est verte sur un gate qui
porte « NON JUGE » dans son propre libelle.

CAUSE, MESUREE : **le libelle sert de cle**. `results` enregistre
« ui-acceptance (contrat web_hub :7400) [NON JUGE] », `_INCONCLUS` enregistre
« ui-acceptance (contrat web_hub :7400) », et l'appartenance est testee par
egalite de chaines. La normalisation EXISTE pourtant -- `_cle_garde()` retire le
suffixe d'etat et la parenthese de detail -- mais elle n'etait appliquee qu'a un
seul des deux sites (ligne 1863, pas 3727). Une primitive juste, employee a
moitie.

CE FICHIER NE TOUCHE PAS AU GARDE. Rendre `bloquants_inconclus` exact ferait
passer la CI au ROUGE tant qu'`ui-acceptance` n'est pas repare ou supplee -- un
arbitrage qui appartient a l'owner. Ici on corrige uniquement ce que le resume
DIT : ne plus afficher vert ce qui n'est pas juge, et ne plus affirmer « tous
supplees » quand ce n'est pas vrai.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))


@pytest.fixture()
def ci():
    try:
        import ci_local
    except Exception as exc:  # noqa: BLE001
        pytest.fail("ci_local ne s'importe pas : %s: %s" % (type(exc).__name__, exc))
    return ci_local


# --------------------------------------------------------------------------
# La marque : un NON JUGE n'est jamais vert
# --------------------------------------------------------------------------

def test_un_gate_NON_JUGE_ne_s_affiche_pas_vert(ci):
    """LE cas du 2026-09-14 : le suffixe de libelle cassait l'appariement."""
    cles = {"ui-acceptance"}
    marque = ci.marque_resume("ui-acceptance (contrat web_hub :7400) [NON JUGE]",
                              True, cles)
    assert marque != "OK", "un gate non juge s'affiche comme un succes"
    assert marque == "INCONNU", marque


def test_un_gate_reellement_vert_reste_vert(ci):
    """CONTRE-EPREUVE : sans elle, tout marquer INCONNU passerait le test d'avant."""
    assert ci.marque_resume("bandit", True, {"ui-acceptance"}) == "OK"


def test_un_gate_en_echec_reste_en_echec(ci):
    assert ci.marque_resume("pytest (suite pure)", False, set()) == "ECHEC"


def test_l_inconclusion_prime_sur_le_booleen(ci):
    """`_run` rend True pour un UNKNOWN (« pas un echec du CODE ») : c'est
    justement pourquoi la marque ne peut pas se lire sur le booleen seul."""
    assert ci.marque_resume("pip-audit", True, {"pip-audit"}) == "INCONNU"


# --------------------------------------------------------------------------
# La phrase finale : elle compte, elle n'affirme pas
# --------------------------------------------------------------------------

def test_la_phrase_ne_dit_TOUS_SUPPLEES_que_si_c_est_vrai(ci):
    """Le cas reel : un supplee, un sans suppleant."""
    phrase = ci.phrase_non_mesures([
        ("pip-audit", False, "mesure deportee pip_audit_2026-09-09.json"),
        ("ui-acceptance (contrat web_hub :7400)", False, ""),
    ])
    bas = phrase.lower()
    assert "tous supplees" not in bas, phrase
    assert "ui-acceptance" in bas, "le gate sans suppleant doit etre NOMME : %s" % phrase
    assert "1" in phrase, phrase


def test_quand_tous_sont_supplees_la_phrase_peut_le_dire(ci):
    phrase = ci.phrase_non_mesures([("gitleaks", False, "pre-commit secret-guard")])
    assert "tous supplees" in phrase.lower(), phrase


def test_aucun_supplee_se_dit_aussi(ci):
    phrase = ci.phrase_non_mesures([("ui-acceptance", False, "")])
    bas = phrase.lower()
    assert "tous supplees" not in bas, phrase
    assert "ui-acceptance" in bas, phrase


def test_sans_inconclus_la_phrase_est_vide(ci):
    """Rien a signaler ne doit rien ecrire : une parenthese vide inquiete."""
    assert ci.phrase_non_mesures([]) == ""
