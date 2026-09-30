# -*- coding: utf-8 -*-
"""NR — une TACHE M2M doit pouvoir reveiller la boucle, comme un job.

    Une notification deposee dans l'inbox ne REVEILLE PAS la boucle du client
    (mesure 2026-09-09). Seul `Monitor` le fait, et `bash_guard` n'accepte
    qu'UNE forme : `forge_job_watch_cli.py`.

CE QUI A ETE PAYE LE 2026-09-22
    Une tache deposee a ANTIGRAVITY a repondu en quelques minutes. Rien ne m'a
    prevenu : je l'ai vue au tour suivant, par le hook d'inbox, par hasard.
    Le meme jour, un message de GEMINI portant le verdict d'une CI distante
    est reste trois heures non lu.

    Et le resultat disait :

        status=done  intent=OK_DONE  status_code=SUCCESS
        detail="Je suis EN TRAIN d'executer... J'ATTENDS le resultat du
                premier lot."

    L'artefact, lui, n'avait pas bouge : `forge_card_summaries.json`, meme
    taille, meme date qu'un mois plus tot.

        ACCEPTED DECLARE ACHIEVED. Le verdict ment, l'artefact tranche.

CE QUE CE CONTRAT EXIGE
    1. surveiller une TACHE (`tasks.db`) comme on surveille un job (`.rc`) ;
    2. la forme sanctionnee par `bash_guard` doit l'accepter -- sans cela la
       capacite existe et reste hors de portee de `Monitor` ;
    3. l'emission ne dit JAMAIS « termine » : elle dit le statut ET rappelle
       que l'effet se lit sur l'artefact. Un moniteur qui annonce un succes
       fabrique le faux calme qu'il devrait prevenir.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
for _p in (_RACINE, _RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _source(nom: str) -> str:
    return (_RACINE / "tools" / nom).read_text(encoding="utf-8", errors="replace")


# ── LA CAPACITE ─────────────────────────────────────────────────────────

def test_le_cli_accepte_une_tache():
    import forge_job_watch_cli as w  # noqa: PLC0415 — livrable
    assert hasattr(w, "surveiller_tache"), (
        "`surveiller_tache` ABSENTE — une tache M2M ne peut pas reveiller la "
        "boucle, et sa reponse n'est vue qu'au hasard d'un tour suivant")


def test_le_cli_declare_l_option_task():
    src = _source("forge_job_watch_cli.py")
    assert "--task" in src, (
        "l'option `--task` n'est pas declaree : la capacite serait presente et "
        "inatteignable depuis la ligne de commande")


# ── LA FORME SANCTIONNEE DOIT SUIVRE ────────────────────────────────────

def test_bash_guard_accepte_la_forme_task():
    """EXISTS != REACHABLE. Un CLI qui sait surveiller une tache mais que le
    garde refuse reste une capacite morte pour `Monitor`."""
    src = _source("bash_guard.py")
    motif = re.search(r'r"--\(?\w*\|?\w*\)?\\s\+\[A-Za-z0-9_\]\+"', src)
    assert motif is None or "task" in motif.group(0), (
        "la forme sanctionnee n'accepte toujours que `--job` : `Monitor` "
        "refusera la surveillance d'une tache")
    assert "task" in src, (
        "`bash_guard` ne mentionne pas `task` : la forme Monitor n'a pas ete "
        "elargie")


# ── L'EMISSION NE FABRIQUE PAS DE FAUX CALME ────────────────────────────

def test_l_emission_renvoie_a_l_artefact_et_ne_conclut_pas():
    """Le 2026-09-22, une tache `done/OK_DONE/SUCCESS` n'avait rien produit.
    Un moniteur qui relaie ce statut sans reserve propage le mensonge."""
    src = _source("forge_job_watch_cli.py")
    bloc = src[src.find("def surveiller_tache"):] if "def surveiller_tache" in src else ""
    assert bloc, "`surveiller_tache` introuvable : re-mesurer"
    assert "artefact" in bloc.lower(), (
        "l'emission ne renvoie pas a l'artefact : un `status=done` serait lu "
        "comme un effet obtenu, alors qu'il ne dit que ce que l'agent AFFIRME")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
