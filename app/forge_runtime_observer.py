# -*- coding: utf-8 -*-
"""app/forge_runtime_observer.py — ORGANE SENSORIEL en lecture seule.

Un pair distant (analyse externe, revue, autre agent) qui n'a que le depot voit
le code LIVRE, jamais l'etat CHARGE. Cet organe comble ce manque sans ouvrir la
moindre surface d'execution : il OBSERVE et rend un constat.

    exposer un constat  !=  exposer le corps

Ce module ne remplace aucun agregateur existant. `forge_health_diagnostic` et
`forge_organ_agents` mesurent deja beaucoup ; ce qu'aucun ne porte, c'est le
CONTRAT DE SORTIE ci-dessous. Cet organe delegue et qualifie, il ne recalcule pas.

## LE CONTRAT, et pourquoi chaque case existe

    OBSERVATION   qui mesure, quand, depuis quel compte -- sans quoi un verdict
                  local se lit comme un verdict systeme
    FAITS         mesure directe, ici, maintenant
    DECLARE       ce qu'une configuration ANNONCE. Jamais un fait.
    INCONNU       ce qu'on n'a PAS pu voir, nomme. Jamais un zero.
    LIMITES       ce que cet observateur ne peut pas voir PAR CONSTRUCTION

`DECLARE != OBSERVE` n'est pas une precaution de style, c'est une erreur payee le
2026-09-18 : un rapport annoncait `wal_autocheckpoint = 1000` pour la base RAG.
C'etait le defaut de SA PROPRE SONDE -- ce PRAGMA est par CONNEXION. Le meme jour,
il a annonce une contention `rag`/`access_switches` parce que le compte qui
l'executait n'avait pas la variable que `services.toml` pose pour le SERVICE.
Deux fois, l'observateur a decrit son bac en le prenant pour le systeme.

## CE QUE CET ORGANE NE PEUT PAS FAIRE, ET C'EST VERIFIE

Pas une promesse : un INVARIANT relu par AST dans
`tests/nr/test_runtime_observer_lecture_seule_nr.py` --

    aucun subprocess, aucun os.system, aucun eval/exec,
    aucune ouverture de fichier en ecriture, aucun INSERT/UPDATE/DELETE,
    aucune lecture de valeur de variable d'environnement (seule sa PRESENCE),
    aucun chemin de profil utilisateur en sortie.

Un module qui se DECLARE inoffensif sans le prouver est exactement la dette que
ce depot traque. Le NR est le garde ; ce texte n'est que son motif.

## CE QU'IL N'EXPOSE JAMAIS

Valeurs de secrets, jetons, chemins du profil owner, contenu de fichier,
resultat de commande. Les chemins sortent generifies (`<NOKIDO>`, `<HOME>`), et
d'une variable d'environnement on ne rend que `True`/`False` : posee ou non.
"""

from __future__ import annotations

__FORGE_COLOR__ = "sensoriel/observabilite : etat runtime en lecture seule"

import datetime
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Contrat de capacite, lisible par un appelant AVANT d'appeler. Il decrit ce que
# le NR verifie ; il ne s'y substitue pas.
CAPACITES = {
    "mode": "READ_ONLY",
    "effets_de_bord": False,
    "expose_des_secrets": False,
    "execute_des_processus": False,
    "portee_fichiers": "ALLOWLIST (bases declarees par forge_db_path)",
    "invariant_verifie_par": "tests/nr/test_runtime_observer_lecture_seule_nr.py",
}

PORTEES = ("identite", "db", "queues")


# La generification vit chez le PRODUCTEUR du rapport, pas ici. Le gate
# `duplication` a refuse une premiere version ou cette fonction existait a
# l'identique dans les deux fichiers : deux copies d'une regle de publication,
# c'est la garantie qu'un jour l'une laissera passer un chemin que l'autre
# masque -- et personne ne saura laquelle a servi.
from tools.forge_db_contention_report import _generifier  # noqa: E402


def _observation(portee: str) -> dict:
    """QUI observe. Sans cette case, un constat local passe pour un constat systeme."""
    return {
        "horodatage": datetime.datetime.now().isoformat(timespec="seconds"),
        "compte": getpass.getuser(),
        "pid": os.getpid(),
        "portee": portee,
        "note": ("Ce constat decrit l'environnement qui l'execute. Un service "
                 "lance par le superviseur peut avoir une configuration "
                 "DIFFERENTE -- il n'herite du TOML que par lui."),
    }


def _portee_identite() -> dict:
    from app import forge_db_path as dbp

    # D'une variable d'environnement on ne rend QUE sa presence. Sa valeur
    # pourrait porter un chemin de profil, voire un secret.
    surveillees = ("LAFORGE_DB", "LAFORGE_M2M_DB_PATH", "LAFORGE_TASKS_DB_PATH",
                   "LAFORGE_SWITCHES_DB_PATH")
    return {
        "faits": {
            "compte": getpass.getuser(),
            "python": "%d.%d.%d" % sys.version_info[:3],
            "racine": _generifier(ROOT),
            "interrupteurs_actifs": {
                "m2m": dbp.m2m_switch_actif(),
                "task_queue": dbp.tasks_switch_actif(),
            },
        },
        "declare": {
            "variables_de_chemin_posees": {v: bool(os.environ.get(v)) for v in surveillees},
        },
        "inconnu": {
            "configuration_des_services": (
                "non lue ici : elle vit dans proxy_deno/core/services.toml et "
                "n'est effective que pour un service lance par le superviseur"),
        },
    }


def _portee_db() -> dict:
    """Delegue au rapport de contention : un seul producteur de cette mesure."""
    from tools.forge_db_contention_report import rapport

    r = rapport()
    return {
        "faits": {
            "identite_physique": r["identite_physique"],
            "bases": r["bases"],
        },
        "declare": {"interrupteurs": r["interrupteurs"]},
        "inconnu": {n: "non mesure" for n in r["non_mesure"]},
    }


def _portee_queues() -> dict:
    """Etat des files, par leur lecture NORMALE -- aucun acces direct au fichier."""
    faits, inconnu = {}, {}
    try:
        from app import forge_task_queue as tq

        faits["task_queue"] = {"par_statut": tq.queue_status(),
                               "base": _generifier(str(tq.DB))}
    except Exception as e:  # noqa: BLE001
        inconnu["task_queue"] = "%s : %s" % (type(e).__name__, str(e)[:80])
    return {"faits": faits, "declare": {}, "inconnu": inconnu}


_PORTEES = {"identite": _portee_identite, "db": _portee_db, "queues": _portee_queues}


def observer(portee: str = "identite") -> dict:
    """Rend un constat CONTRACTUEL pour une portee.

    Une portee inconnue n'est pas une erreur muette : elle est nommee, avec la
    liste de ce qui existe. Un appelant distant doit pouvoir se corriger seul.
    """
    if portee not in _PORTEES:
        return {
            "observation": _observation(portee),
            "faits": {},
            "declare": {},
            "inconnu": {"portee": "inconnue"},
            "limites": ["portees disponibles : %s" % ", ".join(PORTEES)],
        }
    try:
        bloc = _PORTEES[portee]()
    except Exception as e:  # noqa: BLE001 — un observateur ne casse jamais son appelant
        bloc = {"faits": {}, "declare": {},
                "inconnu": {"mesure": "%s : %s" % (type(e).__name__, str(e)[:120])}}
    return {
        "observation": _observation(portee),
        "faits": bloc.get("faits", {}),
        "declare": bloc.get("declare", {}),
        "inconnu": bloc.get("inconnu", {}),
        "limites": [
            "LECTURE SEULE : aucun processus lance, aucune ecriture, aucun secret lu.",
            "Les chemins sont generifies ; d'une variable d'environnement seule la "
            "PRESENCE est rendue, jamais la valeur.",
            "Les connexions ouvertes par les AUTRES processus ne sont pas visibles "
            "depuis ce compte : INCONNU, jamais zero.",
            "Un constat pris ici ne vaut pas pour un service lance par le superviseur.",
        ],
        "capacites": CAPACITES,
    }


def observer_tout() -> dict:
    return {p: observer(p) for p in PORTEES}


if __name__ == "__main__":
    import json

    _p = sys.argv[1] if len(sys.argv) > 1 else "tout"
    print(json.dumps(observer_tout() if _p == "tout" else observer(_p),
                     ensure_ascii=False, indent=1, default=str))
