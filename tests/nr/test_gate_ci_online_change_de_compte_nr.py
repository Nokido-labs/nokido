#!/usr/bin/env python3
"""test_gate_ci_online_change_de_compte_nr.py — `online` sur la CI change le COMPTE.

INCIDENT GARDE, mesure du 2026-09-11. Deux runs de `tools/ci_local.py` sur le MEME
depot a quelques heures d'ecart :

    sandbox/ci_LaForgeSbxOffline/pytest_pur_junit.xml   9293 tests   0 failure
    sandbox/ci_LaForgeSbxOnline/pytest_pur_junit.xml    9297 tests  11 failures

Le second avait ete lance avec `online=true`, par continuite avec un job PyPI qui,
lui, avait besoin du reseau. Or ce drapeau ne fait pas qu'ouvrir l'egress : il change
le COMPTE d'execution (`LaForgeSbxOnline`), donc les ACL. Les 11 echecs sont TOUS des
operations git -- `git init` rc=1, `.git/index.lock: Permission denied`, historique
introuvable -- et ils sont verts sous le compte par defaut. La CI n'a AUCUN besoin de
reseau ; elle a besoin des droits git.

POURQUOI UNE REGEX NE SUFFIT PAS, et c'est tout l'interet de ce garde : `online` est
un champ BOOLEEN de l'entree, absent de `_texte_commande()` -- qui ne concatene que
`code`, `commands`, `script_args`, `script` et `path`. Une regle posee dans REGLES ne
pourrait donc JAMAIS se declencher. La selection doit lire l'ENTREE, exactement comme
`_regles_du_shell` le fait deja pour `sandbox`. Sans ce test, on ajouterait une regle
branchee sur un signal que personne n'emet -- le motif que le corps documente ailleurs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
for _p in (RACINE / "tools", RACINE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hook_capability_gate as hcg  # noqa: E402

MARQUEUR = "LaForgeSbxOnline"      # propre a la regle du compte, pas au nudge notifieur


def nudges(entree: dict) -> list[str]:
    """Les messages que le gate produirait pour cette entree, sans le lancer."""
    txt = hcg._texte_commande(entree)
    return [msg for rx, msg in hcg._regles_du_shell(entree) if rx.search(txt)]


def test_une_ci_lancee_avec_online_est_signalee():
    msgs = nudges({"action": "run_job", "script": "tools/ci_local.py", "online": True})
    assert any(MARQUEUR in m for m in msgs), (
        "un run_job de ci_local avec online=true doit rappeler que le drapeau change "
        f"le COMPTE (11 faux rouges mesures le 2026-09-11). Nudges obtenus : {msgs}")


def test_la_meme_ci_sans_online_ne_declenche_pas_cette_regle():
    """Anti-faux-positif : un garde qui crie a tort se fait desarmer, et on perd
    alors les vrais avec. La CI par defaut est le cas NORMAL, elle ne doit rien dire."""
    msgs = nudges({"action": "run_job", "script": "tools/ci_local.py"})
    assert not any(MARQUEUR in m for m in msgs), (
        f"la CI SANS online est la forme correcte, elle ne doit pas etre signalee : {msgs}")


def test_le_drapeau_network_est_traite_comme_online():
    """`network=true` est l'autre nom du meme levier d'egress (contrat du schema)."""
    msgs = nudges({"action": "run_job", "script": "tools/ci_local.py", "network": True})
    assert any(MARQUEUR in m for m in msgs), f"network=true doit valoir online : {msgs}"


def test_un_autre_job_avec_online_n_est_pas_concerne():
    """La regle vise la CI, pas tout travail deporte : un job PyPI a BESOIN du reseau."""
    msgs = nudges({"action": "run_job", "script": "sandbox/workspace/preuve_pypi.py",
                   "online": True})
    assert not any(MARQUEUR in m for m in msgs), (
        f"un job qui a legitimement besoin d'egress ne doit pas etre signale : {msgs}")


def test_le_champ_online_est_invisible_au_texte_de_commande():
    """Le fait qui RENDAIT une regex impossible, verrouille ici.

    Si un jour `_texte_commande` se met a exposer `online`, ce test echoue et invite
    a simplifier la selection -- plutot que de laisser deux mecanismes concurrents.
    """
    txt = hcg._texte_commande({"action": "run_job", "script": "tools/ci_local.py",
                               "online": True})
    assert "online" not in txt.lower(), (
        "`online` apparait desormais dans le texte de commande : la selection par "
        f"l'ENTREE peut etre reexaminee. Texte = {txt!r}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
