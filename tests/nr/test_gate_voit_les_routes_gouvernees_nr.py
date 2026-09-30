# -*- coding: utf-8 -*-
"""NR — le gate de capacités doit VOIR les routes gouvernées, sinon il ne garde rien.

__FORGE_COLOR__ = "immunitaire/guard : non-regression de la visibilite du gate de capacites"

CE QUI A ÉTÉ MESURÉ (2026-09-07). `hook_capability_gate` est câblé `PreToolUse` sur
**chaque** appel `run` et injecte la bonne forme avant l'erreur. Son extracteur lisait
`code`, `command`, `commands`, `script_args` — **jamais `script` ni `path`**. Mesure à
l'oracle :

    run_job{script: "tools/ci_local.py"}              -> ''  (0 caractere)
    trusted_script{path: "tools/forge_npu_bench.py"}  -> ''  (0 caractere)
    shell{code: "git status"}                         -> 'git status'

**Deux classes d'appel entières étaient donc invisibles** — et ce sont exactement les
routes que les règles PRESCRIVENT : « déporter le long en `run_job` », « `trusted_script`
pour le privilégié ». Le garde était aveugle là où il devait le plus voir.

Conséquence payée le soir même : une CI suivie par polling client alors qu'un notifieur
existait. Récidive **déjà consignée le 2026-09-03** — le savoir était dans
`RULES_SHARED`, dans le message de `forge_tool_gate` et dans l'index d'enquêtes, mais
aucun de ces trois dépôts ne parle au moment de décider. Seul ce gate le fait, et il ne
pouvait rien voir.

Ce NR verrouille la VISIBILITÉ, pas le contenu du catalogue : une règle qu'on ajoute est
inutile si l'extracteur ne lui donne rien à lire.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import hook_capability_gate as g  # noqa: E402


def _nudges(entree: dict) -> list:
    """Les messages que le gate injecterait pour cet appel.

    Passe par `_regles_du_shell`, c'est-a-dire le CHEMIN REEL de selection, et non
    par `_COMPILED` en vrac : un NR qui court-circuite la selection ne teste pas ce
    qui tourne. Regle payee le 2026-09-06 (`check()` vert pendant que `--check`
    mourait en NameError)."""
    texte = g._texte_commande(entree)
    return [msg for rx, msg in g._regles_du_shell(entree) if rx.search(texte)]


# --- visibilité : le gate voit-il seulement l'action ? ---------------------------

def test_le_gate_voit_le_script_d_un_run_job() -> None:
    t = g._texte_commande({"action": "run_job", "script": "tools/ci_local.py", "lane": "ci"})
    assert "ci_local" in t, (
        "sans `script`, un run_job n'expose RIEN au gate : aucune regle ne peut s'y "
        "declencher, quelle qu'elle soit")


def test_le_gate_voit_le_path_d_un_trusted_script() -> None:
    t = g._texte_commande({"action": "trusted_script", "path": "tools/forge_npu_bench.py"})
    assert "forge_npu_bench" in t, (
        "trusted_script est la route du PRIVILEGIE : c'est la derniere ou le gate "
        "devrait etre aveugle")


def test_le_shell_reste_vu_comme_avant() -> None:
    """Non-regression du chemin qui marchait deja."""
    assert "git status" in g._texte_commande({"action": "shell", "code": "git status"})


# --- les deux règles mesurées le 2026-09-07 --------------------------------------

def test_lancer_la_ci_rappelle_le_notifieur_et_le_temoin() -> None:
    msgs = _nudges({"action": "run_job", "script": "tools/ci_local.py", "lane": "ci"})
    assert msgs, "lancer la CI doit rappeler quelque chose : c'est un TRAVAIL LONG"
    joint = " ".join(msgs)
    assert "forge_job_watch_notify" in joint, "le notifieur doit etre NOMME"
    assert "junit" in joint.lower(), (
        "le rc est un signal, pas le verdict : le temoin structure doit etre rappele")


def test_le_notifieur_mal_appele_est_rattrape() -> None:
    """Il meurt en rc=2 DES LE LANCEMENT, sans rien signaler : on attend alors une
    notification qui ne viendra jamais. Paye le 2026-09-07."""
    mauvais = {"action": "run_job", "script": "tools/forge_job_watch_notify.py",
               "script_args": "--rc sandbox/jobs/x.rc --agent CLAUDE"}
    msgs = _nudges(mauvais)
    assert any("--to" in m for m in msgs), (
        "`--agent` n'existe pas et `--progress` est obligatoire : le gate doit le dire "
        "AVANT le lancement, pas apres 13 minutes d'attente")


def test_le_notifieur_correctement_appele_ne_declenche_pas_l_alerte() -> None:
    """Un garde qui crie a faux se fait desarmer : pas de nudge sur la bonne forme."""
    bon = {"action": "run_job", "script": "tools/forge_job_watch_notify.py",
           "script_args": "--progress sandbox/jobs/x.progress.json --rc "
                          "sandbox/jobs/x.rc --to CLAUDE"}
    assert not [m for m in _nudges(bon) if "--to" in m], (
        "la forme correcte ne doit produire aucun rappel")


def test_pas_de_faux_positif_sur_un_appel_ordinaire() -> None:
    """Mesure de bruit : un shell banal ne doit rien declencher des deux regles neuves."""
    msgs = _nudges({"action": "shell", "code": "git -C repo log --oneline -3"})
    assert not [m for m in msgs
                if "forge_job_watch_notify" in m or "TRAVAIL LONG" in m]


def test_stager_le_fichier_de_ci_n_est_pas_lancer_la_ci() -> None:
    """FAUX POSITIF PAYE le 2026-09-07, trois minutes apres l'ecriture de la regle.

    Placee dans REGLES (lexical), elle tirait sur `git add tools/ci_local.py` : le
    chemin apparait, la regle croit a un lancement. La selection se fait desormais
    par CLASSE D'ACTION -- les pieges du travail deporte ne valent que pour
    `run_job` / `trusted_script`. Un garde qui crie a faux se fait desarmer."""
    msgs = _nudges({"action": "shell",
                    "code": "git -c safe.directory=* -C repo add tools/ci_local.py"})
    assert not [m for m in msgs if "TRAVAIL LONG" in m], (
        "stager le fichier n'est pas le lancer : la regle doit dependre de la CLASSE "
        "d'action, pas de la presence du chemin dans le texte")


def test_la_classe_d_action_selectionne_les_regles() -> None:
    """Le selecteur par classe est le premier etage ; le lexical reste le repli."""
    job = g._regles_du_shell({"action": "run_job", "script": "tools/ci_local.py"})
    shell = g._regles_du_shell({"action": "shell", "code": "echo x"})
    assert len(job) > len(g._COMPILED), (
        "un travail deporte doit recevoir ses regles propres EN PLUS des generales")
    assert all(r in job for r in g._COMPILED), "les regles generales restent actives"
    assert not any(r in shell for r in g._COMPILED_JOB), (
        "les pieges du travail deporte ne doivent pas s'armer sur un shell")
