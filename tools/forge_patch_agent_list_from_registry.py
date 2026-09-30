# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "securite/identite-clients"
PATCH : le hub charge les jetons de TOUTES les identites declarees, pas d'une liste figee.

LE DEFAUT
=========
`tools/nokido_hub.py` porte `_AGENT_LIST`, un tuple ECRIT A LA MAIN, et ne charge
depuis le coffre que les jetons `FORGE_TOKEN_<AGENT>` de ce tuple. A cote vit
`config/agent_identities.json`, le registre VIVANT (recharge au mtime, sans restart)
qui declare ring, canal et transport de chaque identite.

Consequence mesuree le 2026-08-05 : trois identites nouvellement declarees
(ORGAN_PULSE, COAGULATION, RESCUE), avec leurs jetons PROVISIONNES au coffre et
verifies presents, ont continue de recevoir 401 apres redemarrage du hub -- parce
que leur nom n'etait pas dans le tuple. Le registre disait qui elles etaient, le
coffre avait leurs clefs, et le hub ne les regardait pas.

C'est le motif « regex figee = organes invisibles » (2026-07-22) applique a
l'identite, et il est ADVERSE a la directive owner « aucun manque d'identification
des clients » : chaque nouvelle identite atterrit anonyme, en silence, jusqu'a ce
que quelqu'un pense a editer un tuple.

LE REMEDE
=========
`_AGENT_LIST` devient un PLANCHER, pas la source : on charge l'UNION du tuple et
des clefs du registre. Le tuple reste, donc aucune regression possible si le
registre est illisible -- et cette illisibilite se DIT, elle ne se devine pas.

VOIE D'APPLICATION
==================
`nokido_hub.py` est CRITICAL_FILE : `governed_edit` le refuse et
`LAFORGE_ALLOW_CRITICAL_WRITE` vit dans l'environnement du hub, qui ne se recharge
pas a chaud. D'ou ce script git-tracke, lance en `trusted_script` -- doctrine
« privilege = code revu ». Idempotent par sentinelle, ancres devant apparaitre
EXACTEMENT une fois sinon abandon, `compile()` avant ecriture, sauvegarde
horodatee, relecture verifiee, dry-run par defaut.

    LAFORGE_PYTHON tools/forge_patch_agent_list_from_registry.py          # dry-run
    LAFORGE_PYTHON tools/forge_patch_agent_list_from_registry.py --apply

L'effet n'apparait qu'au PROCHAIN REDEMARRAGE du hub (les jetons sont lus au boot).
Retour arriere : `git checkout -- tools/nokido_hub.py` ou la sauvegarde
`nokido_hub.py.avant-agentlist-<horodatage>.bak` deposee a cote.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "tools" / "nokido_hub.py"

SENTINELLE = "_agents_a_charger"

ANCRE = '''    tokens: dict[str, str] = {}
    missing: list[str] = []
    for agent in _AGENT_LIST:
'''

REMPLACEMENT = '''    tokens: dict[str, str] = {}
    missing: list[str] = []
    for agent in _agents_a_charger():
'''

ANCRE_DEF = '''def _load_agent_tokens() -> dict[str, str]:
'''

HELPER = '''def _agents_a_charger() -> tuple:
    """Identites dont on charge le jeton : UNION du tuple fige et du registre VIVANT.

    `_AGENT_LIST` reste un PLANCHER (aucune regression si le registre est
    illisible), mais il n'est plus la source : `config/agent_identities.json` l'est.
    Mesure du 2026-08-05 : ORGAN_PULSE, COAGULATION et RESCUE etaient declarees au
    registre, leurs jetons provisionnes au coffre, et le hub leur rendait 401 parce
    que leur nom manquait au tuple -- une identite invisible au chargeur est une
    identite anonyme, ce que la directive owner interdit explicitement.

    Un registre illisible se DIT (log WARNING) : sans ca, « je n'ai pas pu lire »
    passerait pour « il n'y a rien de plus a charger ».
    """
    import json as _json
    import logging as _logging

    noms = list(_AGENT_LIST)
    registre = Path(__file__).resolve().parent.parent / "config" / "agent_identities.json"
    try:
        declarees = (_json.loads(registre.read_text(encoding="utf-8")) or {}).get("agents") or {}
    except Exception as exc:  # noqa: BLE001
        _logging.getLogger("forge.hub").warning(
            "[identite] registre %s ILLISIBLE (%s: %s) -- repli sur la liste figee "
            "(%d agents) ; consequence: toute identite declaree hors de ce tuple "
            "recevra 401 et comptera comme trafic anonyme",
            registre.name, type(exc).__name__, str(exc)[:80], len(noms))
        return tuple(noms)
    ajoutes = [a for a in declarees if a not in noms]
    if ajoutes:
        _logging.getLogger("forge.hub").info(
            "[identite] %d identite(s) chargee(s) depuis le registre en plus du "
            "tuple fige : %s", len(ajoutes), ", ".join(sorted(ajoutes)))
    return tuple(noms + ajoutes)


def _load_agent_tokens() -> dict[str, str]:
'''


def _echec(msg: str) -> int:
    print("[patch] ABANDON — %s" % msg)
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fait deriver le chargement des jetons du registre d'identites")
    ap.add_argument("--apply", action="store_true",
                    help="ecrit reellement (defaut : dry-run)")
    a = ap.parse_args(argv)

    if not CIBLE.exists():
        return _echec("cible absente : %s" % CIBLE)
    src = CIBLE.read_text(encoding="utf-8")

    if SENTINELLE in src:
        print("[patch] DEJA APPLIQUE (sentinelle '%s' presente) — rien a faire"
              % SENTINELLE)
        return 0

    # Les ancres doivent apparaitre EXACTEMENT une fois. Zero = le fichier a change ;
    # plusieurs = on ne sait pas laquelle patcher. Dans les deux cas on s'abstient
    # plutot que de deviner sur un fichier critique.
    for nom, ancre in (("boucle de chargement", ANCRE), ("def _load_agent_tokens", ANCRE_DEF)):
        n = src.count(ancre)
        if n != 1:
            return _echec("ancre '%s' vue %d fois (attendu 1)" % (nom, n))

    patche = src.replace(ANCRE_DEF, HELPER, 1).replace(ANCRE, REMPLACEMENT, 1)

    try:
        compile(patche, str(CIBLE), "exec")
    except SyntaxError as e:
        return _echec("le resultat ne compile pas (%s ligne %s)" % (e.msg, e.lineno))

    print("[patch] cible      : %s (%d octets -> %d)" % (CIBLE, len(src), len(patche)))
    print("[patch] helper     : _agents_a_charger() insere avant _load_agent_tokens")
    print("[patch] boucle     : `for agent in _AGENT_LIST` -> `_agents_a_charger()`")
    print("[patch] compile    : OK")
    if not a.apply:
        print("[patch] DRY-RUN — relancer avec --apply pour ecrire")
        return 0

    sauvegarde = CIBLE.with_suffix(
        ".py.avant-agentlist-%s.bak" % time.strftime("%Y%m%d-%H%M%S"))
    sauvegarde.write_text(src, encoding="utf-8")
    CIBLE.write_text(patche, encoding="utf-8")
    relu = CIBLE.read_text(encoding="utf-8")
    if relu != patche:
        CIBLE.write_text(src, encoding="utf-8")
        return _echec("relecture differente de l'ecriture — restauration effectuee")
    print("[patch] ECRIT. sauvegarde : %s" % sauvegarde.name)
    print("[patch] EFFET AU PROCHAIN REDEMARRAGE DU HUB (jetons lus au boot).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
