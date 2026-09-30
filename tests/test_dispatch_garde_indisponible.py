"""TDD — comportement du dispatch quand un garde d'autorisation disparait.

CE QUE CE FICHIER EST, ET CE QU'IL N'EST PAS.

  Ce sont des tests de COMPORTEMENT (protocole de DEV, skill forge-tdd) :
  ils repondent a « le comportement logiciel attendu est-il correctement
  implemente ? ». Ils empruntent le CHEMIN REEL — `ToolRegistry.dispatch`,
  la coroutine de 481 lignes que le hub appelle — et non le texte du fichier.

  Le verrou d'invariant de securite vit ailleurs, dans
  `tests/nr/test_rbac_indisponible_failclosed_nr.py`. Les deux sont
  necessaires et ne se remplacent pas : un NR vert sur du texte source ne dit
  rien du comportement, et un test de comportement vert ne verrouille pas
  l'invariant contre une reecriture.

HONNETETE SUR L'ORDRE. Le correctif fail-closed a ete ecrit AVANT ce test,
le 2026-09-12. L'Iron Law (« pas de code de prod sans test rouge d'abord »)
n'a donc pas ete honoree ici, et elle ne peut pas l'etre retroactivement sans
re-regresser volontairement un correctif de securite sur un CRITICAL_FILE.
A la place, la discrimination du test est prouvee par une PAIRE :

    garde absent  -> refus nomme          (si le correctif saute, ROUGE)
    garde present -> PAS ce refus         (si le test etait vacuux, ROUGE)

Sans le second, un dispatch qui refuserait TOUT passerait le premier sans
rien demontrer.

CE QUE CES TESTS NE DEMONTRENT PAS :
  - rien sur le hub VIVANT. Ils s'executent dans un processus de test ; le
    hub charge son propre code au demarrage. La preuve d'effet runtime est
    un artefact separe (`tools/forge_verif_post_restart_securite.py`).
  - rien sur les autres gardes du dispatch. Une seule propriete par test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
for _p in (str(RACINE.parent), str(RACINE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REG = pytest.importorskip("nokido_agent.app.forge_mcp_registry")

#: nom volontairement INEXISTANT : si un garde amont refuse, on le voit ; si
#: aucun ne refuse, le dispatch tombe sur « outil inconnu » sans rien executer.
#: Un vrai nom de tool ferait courir le risque d'une execution reelle le jour
#: ou le garde ne mord pas — c'est-a-dire exactement le cas qu'on teste.
TOOL_SONDE = "__nr_sonde_inexistante__"

MODULE_GARDE = "nokido_agent.app.forge_mcp_rbac"


async def _dispatch(**kw):
    reg = REG.get_registry()
    return await reg.dispatch(name=TOOL_SONDE, args={}, agent="NR_TEST",
                              ring=1, **kw)


@pytest.mark.asyncio
async def test_garde_indisponible_ne_confere_aucune_autorite(monkeypatch):
    """Le defaut mesure : `except ImportError: pass` laissait passer l'appel.

    `sys.modules[nom] = None` fait lever ImportError a l'import suivant —
    c'est la simulation fidele d'un module disparu, pas un mock du garde.
    """
    monkeypatch.setitem(sys.modules, MODULE_GARDE, None)
    res = await _dispatch()

    assert isinstance(res, dict), "le dispatch doit rendre un verdict structure"
    assert res.get("error") == "forbidden", (
        "garde d'autorisation indisponible et l'appel n'est PAS refuse : "
        "verdict=%r" % (res,))
    raison = "%s %s" % (res.get("reason", ""), res.get("error", ""))
    assert "rbac" in raison.lower(), (
        "le refus ne NOMME pas le garde manquant, donc il n'est pas "
        "diagnosticable : %r" % (raison,))


@pytest.mark.asyncio
async def test_le_nominal_n_est_pas_casse_par_la_fermeture(monkeypatch):
    """CONTROLE POSITIF — sans lui, un dispatch qui refuse TOUT serait vert.

    Fermer un fail-open ne doit pas rendre le boot inutilisable : garde
    PRESENT, le meme appel ne doit pas produire le refus d'indisponibilite.
    """
    assert MODULE_GARDE not in sys.modules or sys.modules[MODULE_GARDE] is not None
    res = await _dispatch()

    # MESURE : pour un outil inconnu le dispatch rend une CHAINE
    # ('Outil inconnu: ...'), pas un dict. Le premier jet de ce test exigeait
    # un dict et echouait sur ce seul motif — defaut d'INSTRUMENT, corrige ici
    # et non dans le code. Le contrat de retour du dispatch est heterogene.
    if isinstance(res, dict):
        raison = "%s" % (res.get("reason", ""),)
        assert not (res.get("error") == "forbidden"
                    and "indisponible" in raison.lower()), (
            "le garde est PRESENT et le dispatch rend quand meme le refus "
            "d'indisponibilite : la fermeture du fail-open a casse le nominal. "
            "verdict=%r" % (res,))
        return

    # Assertion POSITIVE, plus forte que « pas de refus » : l'appel a bel et
    # bien TRAVERSE le garde jusqu'au chemin « outil inconnu ». C'est ce qui
    # rend la paire discriminante — sans elle, un dispatch qui retournerait
    # n'importe quoi passerait ce test.
    assert "inconnu" in str(res).lower(), (
        "le garde est PRESENT mais l'appel n'atteint pas le chemin nominal "
        "'outil inconnu' : %r" % (res,))
