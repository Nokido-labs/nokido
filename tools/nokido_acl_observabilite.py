# -*- coding: utf-8 -*-
"""Accorde aux trois comptes de service la LECTURE des journaux de prothese.

MANDAT
======
Owner, 2026-09-05, apres mesure : « un icacls en lecture seule (R) pour les trois
comptes de service, sur quatre chemins precis […] = oui ».

CE QUI A ETE MESURE AVANT DE DEMANDER
=====================================
`tools/forge_log_surface.py` a recense la surface d'observation sous les TROIS comptes
puis croise les rapports : **10 761 sources, 10 722 lisibles par au moins un compte,
30 absentes partout, 9 illisibles PARTOUT**. Ces 9 sont toutes dans le profil owner et
ce sont exactement les journaux des protheses — Docker, LM Studio, WSL. Le depot, lui,
est lisible par les trois : l'aveuglement est ENTIEREMENT hors repertoire de travail.

POURQUOI CE SCRIPT EXISTE PLUTOT QU'UNE COMMANDE JETABLE
========================================================
Un elargissement d'ACL doit rester relisible : ce qui a ete donne, a qui, et POURQUOI.
La lecon du 2026-09-03 est qu'elargir une ACL pour contourner autre chose (la, une
erreur de syntaxe `-C` au lieu de `--git-dir`) affaiblit la securite pour rien.

DEUX RESSERREMENTS PAR RAPPORT AU MANDAT — vers MOINS de droits, jamais plus
===========================================================================
1. `~/.lmstudio` n'est PAS ouvert recursivement : il contient les MODELES (plusieurs
   Go) qui ne servent a aucun diagnostic. Seuls le dossier lui-meme (pour le
   traverser), `server-logs/` et `.internal/` sont accordes.
2. `AppData\\Local\\Packages` a ete ECARTE du mandat des la proposition : il porte les
   donnees d'applications tierces. Si la distro WSL devient necessaire, on ciblera son
   paquet nommement.

Aucun droit d'ECRITURE n'est accorde nulle part : `(R)` seulement.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/acl-observabilite"

import argparse
import subprocess
import sys
from pathlib import Path

COMPTES = ("LaForgeSbxOffline", "LaForgeSbxOnline", "LaForgeTrusted")

# (chemin, recursif) — `recursif` vaut (OI)(CI) + /T, a n'utiliser que sur des
# arborescences petites et entierement pertinentes.
CIBLES = [
    (r"%USERPROFILE%\.docker", True),
    (r"%USERPROFILE%\.lmstudio", False),
    (r"%USERPROFILE%\.lmstudio\server-logs", True),
    (r"%USERPROFILE%\.lmstudio\.internal", True),
    (r"%USERPROFILE%\.wslconfig", False),
    # Le PARENT, ajoute le 2026-09-05 : les journaux de Docker Desktop y vivent, et
    # c'est faute d'y acceder qu'on ne sait toujours pas POURQUOI le moteur meurt
    # tout seul 2 a 11 minutes apres un demarrage reussi. La cible `wsl` ci-dessous
    # ne couvrait que la VM. Recursif car les journaux sont ranges en sous-dossiers.
    (r"%USERPROFILE%\AppData\Local\Docker", True),
    (r"%USERPROFILE%\AppData\Local\Docker\wsl", True),
]


def _commande(chemin: str, recursif: bool) -> list:
    argv = ["icacls", chemin]
    for compte in COMPTES:
        argv += ["/grant", "%s:(OI)(CI)(R)" % compte if recursif
                 else "%s:(R)" % compte]
    if recursif:
        argv.append("/T")
    return argv


def _presence(chemin: str) -> str:
    """OUI / NON / INCONNU — trois etats, parce que `exists()` n'en rend que deux.

    Mesure 2026-09-05 : `Path(r"%USERPROFILE%\\.docker").exists()` LEVE
    `PermissionError` au lieu de rendre False. Traiter cette exception comme
    « absent » ferait sauter exactement les chemins que cette ACL doit ouvrir —
    le trou se refermerait sur lui-meme. Symetrique du piege du 04/09, ou
    `exists()` rendait True sur un fichier dont la LECTURE etait refusee.
    """
    try:
        return "OUI" if Path(chemin).exists() else "NON"
    except OSError:
        return "INCONNU"


def _run(argv: list) -> tuple:
    try:
        # `errors="replace"` OBLIGATOIRE : `icacls` sort en francais dans l'encodage
        # de la console (cp850), et un mode texte strict fait crasher le thread de
        # lecture de subprocess — anti-regression de l'incident 47 Go.
        p = subprocess.run(argv, capture_output=True, text=True, timeout=180,
                           encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return -1, "%s: %s" % (type(exc).__name__, exc)


def _dire(texte: str) -> None:
    """Imprime sans jamais casser sur l'encodage de la console.

    Mesure 2026-09-05 : lance depuis PowerShell, ce script est mort en
    `UnicodeEncodeError` (cp1252) sur la sortie FRANCAISE d'`icacls`, apres avoir
    traite la premiere cible. Un outil d'administration qui s'interrompt au milieu
    d'une serie laisse un etat PARTIEL sans le dire — c'est pire que de ne pas
    tourner. Le repli ASCII est degrade, jamais fatal.
    """
    try:
        print(texte)
    except UnicodeEncodeError:
        print(texte.encode("ascii", "replace").decode("ascii"))


def main() -> int:
    # La console d'ou l'owner lance ce script n'est pas forcement en UTF-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — muet-ok : sortie non reconfigurable
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="applique reellement (sinon : dry-run)")
    a = ap.parse_args()
    echecs = 0
    for chemin, recursif in CIBLES:
        # NE JAMAIS conditionner l'action a une presence vue depuis un compte AVEUGLE.
        # Mesure 2026-09-05, les deux comptes mentent differemment sur les MEMES
        # chemins : sous `LaForgeSbxOffline`, `exists()` LEVE `PermissionError` ; sous
        # `LaForgeTrusted`, il rend simplement False — parce que le compte ne peut pas
        # lister `%USERPROFILE%`. Une premiere version a donc saute les six cibles
        # en affichant « ABSENT, pas un probleme d'ACL » : rassurant et faux, le trou
        # se refermant sur lui-meme. Seul `icacls` fait autorite sur l'existence.
        presence = _presence(chemin)
        argv = _commande(chemin, recursif)
        _dire("[presence vue d'ici] %-8s %s" % (presence, chemin))
        if not a.apply:
            _dire("[dry-run] " + " ".join(argv))
            continue
        rc, sortie = _run(argv)
        bas = (sortie or "").lower()
        introuvable = ("introuvable" in bas or "cannot find" in bas
                       or "n'existe pas" in bas)
        etat = ("ABSENT (icacls fait foi)" if introuvable
                else "OK" if rc == 0 else "ECHEC rc=%s" % rc)
        if rc != 0 and not introuvable:
            echecs += 1
        _dire("[%s] %s" % (etat, chemin))
        for ligne in (sortie or "").splitlines()[:4]:
            _dire("    " + ligne[:160])
    if a.apply:
        # VERIFIER l'effet, jamais se fier au code de retour : un `icacls` peut
        # rendre 0 en n'ayant traite aucun fichier (« 0 fichiers traites »).
        print("\n--- verification (relecture des ACL) ---")
        for chemin, _ in CIBLES:
            rc, sortie = _run(["icacls", chemin])
            if "introuvable" in (sortie or "").lower():
                _dire("%-52s ABSENT" % chemin)
                continue
            vus = [c for c in COMPTES if c.lower() in (sortie or "").lower()]
            _dire("%-52s comptes presents: %s" % (chemin, ", ".join(vus) or "AUCUN"))
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
