"""NR — le delai du proxy d'agents se REGLE sans toucher au code.

Defaut mesure le 2026-09-20 en instruisant le BLOCKER de la veille : le
depouillement des 2728 pages restantes echouait systematiquement sur

    "error": "Timeout apres 60s"

`DEFAULT_TIMEOUT = 60` est le defaut du parametre `timeout` de l'appel RPC
(app/forge_agent_proxy.py). Soixante secondes suffisent a un echange court et
NE SUFFISENT PAS au chargement du contexte d'une page entiere par un modele
local. Le defaut n'est donc pas mauvais : il est INADAPTE a un usage, et il
n'existait aucun moyen de l'ajuster sans editer le module.

⚠️ CE QUE CE TEST VERIFIE EST LA VALEUR IMPORTEE, jamais le texte du fichier.
Un correctif peut se relire juste et ne rien changer — mesure du 2026-09-20 :
une constante posee AVANT celle qu'elle remplacait, Python gardant la derniere,
relecture verte et effet nul. Seul l'import tranche.

Pur : aucune ressource externe, aucun service, aucun reseau. On recharge le
module sous un environnement modifie.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

VARIABLE = "LAFORGE_AGENT_PROXY_TIMEOUT_S"


def _recharge():
    """Rend le module REELLEMENT recharge sous l'environnement courant.

    On resout par le meme nom que le module utilise pour lui-meme : deux noms
    d'import donnent deux instances et deux etats (mesure du 2026-09-10), et un
    `reload` sur l'une laisserait l'autre intacte — donc un faux vert.
    """
    mod = importlib.import_module("forge_agent_proxy")
    return importlib.reload(mod)


def test_sans_variable_le_defaut_reste_soixante(monkeypatch):
    """Le correctif ne doit RIEN changer par defaut : un echange court garde sa
    borne courte. Elargir pour tout le monde serait payer la lenteur partout."""
    monkeypatch.delenv(VARIABLE, raising=False)
    m = _recharge()
    assert m.DEFAULT_TIMEOUT == 60, (
        "le defaut a bouge : %r — un delai plus long pour TOUS les appels n'est "
        "pas le correctif demande" % m.DEFAULT_TIMEOUT
    )


def test_la_variable_regle_le_delai(monkeypatch):
    """Le coeur : on doit pouvoir allonger le delai sans editer le module."""
    monkeypatch.setenv(VARIABLE, "300")
    m = _recharge()
    assert m.DEFAULT_TIMEOUT == 300, (
        "le delai ne suit pas %s : valeur IMPORTEE = %r. Le depouillement reste "
        "donc condamne au « Timeout apres 60s »" % (VARIABLE, m.DEFAULT_TIMEOUT)
    )


def test_une_valeur_illisible_ne_casse_pas_le_module(monkeypatch):
    """Une variable mal remplie ne doit pas empecher le proxy de demarrer : elle
    retombe sur le defaut. Un module qui meurt a l'import sur une coquille
    d'environnement emporte tout ce qui en depend."""
    monkeypatch.setenv(VARIABLE, "trois-cents")
    m = _recharge()
    assert m.DEFAULT_TIMEOUT == 60, (
        "une valeur illisible doit retomber sur le defaut, pas propager une "
        "erreur ni une valeur absurde : %r" % m.DEFAULT_TIMEOUT
    )


def test_le_defaut_du_parametre_suit_la_constante():
    """Le garde utile : la constante ne sert a rien si la signature de l'appel
    RPC ne s'en sert plus. Une constante juste et un parametre qui l'ignore,
    c'est la famille du durcissement jamais appele (2026-09-18)."""
    import inspect

    m = _recharge()
    cible = None
    for nom, obj in vars(m).items():
        if inspect.isfunction(obj):
            try:
                sig = inspect.signature(obj)
            except (ValueError, TypeError):
                continue
            p = sig.parameters.get("timeout")
            if p is not None and p.default == m.DEFAULT_TIMEOUT:
                cible = nom
                break
    assert cible is not None, (
        "aucune fonction du module ne prend « timeout » avec DEFAULT_TIMEOUT "
        "pour defaut : la constante est devenue decorative"
    )
