#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_patch_socle.py -- le patron commun aux patchs de CRITICAL_FILE.

POURQUOI (2026-08-29)
=====================
Certains fichiers ne peuvent pas etre edites par `governed_edit` : ce sont des
CRITICAL_FILE, et la derogation `allow_critical` sur un gros fichier a deja fait
tomber le hub (mesure 2026-08-27). Le chemin sur est un patch git-tracke joue en
`trusted_script` -- une ancre, un ajout, un secours, un controle de syntaxe.

Le deuxieme patch ecrit sur ce modele (`forge_patch_vitals_sse`) a ete signale
comme CLONE du premier (`forge_patch_lane_auto`) par le cliquet de duplication.
Le cliquet avait raison : j'avais recopie la structure au lieu de la nommer. Le
patron vit donc ici, une fois.

CE QUE LE SOCLE GARANTIT, et qui doit rester vrai pour tout patch :
  * ANCRE UNIQUE -- zero ou plusieurs occurrences = on REFUSE. Patcher a l'aveugle
    dans un fichier qui a change est pire que ne pas patcher.
  * IDEMPOTENCE par marqueur -- une relance ne double jamais l'ajout.
  * SYNTAXE verifiee AVANT ecriture, sur le resultat complet.
  * TROIS ETATS -- applique / deja applique / illisible. Une cible qu'on n'a pas
    pu lire n'est pas une cible propre.
  * SECOURS ecrit avant modification (et ignore par `.gitignore` via `*.avant_*`).
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/patch-fichier-critique"

from pathlib import Path


def appliquer(cible: Path, ancre: str, ajout: str, marqueur: str,
              suffixe_secours: str, dry_run: bool = True) -> dict:
    """Applique `ajout` a la place de `ancre` dans `cible`. Rend un dict d'etat.

    `marqueur` : chaine presente dans `ajout` qui signe un patch DEJA applique.
    `suffixe_secours` : nom du fichier de sauvegarde (`<cible>.<suffixe>`)."""
    try:
        src = cible.read_text(encoding="utf-8")
    except OSError as e:
        return {"ok": False, "raison": "cible illisible : %s" % e}
    if marqueur in src:
        return {"ok": True, "deja_applique": True, "modifie": False}
    n = src.count(ancre)
    if n != 1:
        return {"ok": False,
                "raison": "ancre absente ou ambigue (%d occurrence(s)) -- le "
                          "fichier a change, relire avant de patcher" % n}
    nouveau = src.replace(ancre, ajout, 1)
    try:
        compile(nouveau, str(cible), "exec")
    except SyntaxError as e:
        return {"ok": False, "raison": "patch invalide l.%s : %s" % (e.lineno, e.msg)}
    if dry_run:
        return {"ok": True, "dry_run": True, "modifie": False,
                "octets_ajoutes_si_applique": len(nouveau) - len(src)}
    secours = cible.with_suffix(cible.suffix + "." + suffixe_secours)
    secours.write_text(src, encoding="utf-8")
    cible.write_text(nouveau, encoding="utf-8")
    return {"ok": True, "modifie": True, "secours": secours.name,
            "octets_ajoutes": len(nouveau) - len(src)}


def rapporter(resultat: dict) -> int:
    """Sortie CLI commune : imprime l'etat et rend le code de retour."""
    print(resultat)
    if resultat.get("ok") and not resultat.get("modifie") and not resultat.get("deja_applique"):
        print("DRY-RUN : rien ecrit. Relancer avec --apply.")
    return 0 if resultat.get("ok") else 1
