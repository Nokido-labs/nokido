"""Context firewall -- reduire ce que Claude RECOIT, sans rien lui cacher.

__FORGE_COLOR__ = "immunitaire/guard : reduction des sorties d'outils"

ARBITRAGE OWNER 2026-09-11, qui corrige la direction precedente :

    outil produit 30k -> PostToolUse -> Claude recoit 300

vaut mieux que :

    outil produit 30k -> interdire l'appel

La premiere forme PRESERVE LA CAPACITE en reduisant le contexte ; la seconde
economise des tokens en detruisant le moyen de travailler. Le `deny` reste
pour les vraies boucles et les appels absurdes -- pas pour les grosses sorties.

Mecanisme MESURE dans ce runtime avant d'etre employe : `updatedToolOutput`
est present dans le binaire (sonde findstr, 4 temoins negatifs muets), il vaut
pour TOUS les outils, et sa forme est
`{"hookSpecificOutput": {"hookEventName": "PostToolUse",
  "updatedToolOutput": {"text": ..., "isError": ...}}}`.

LE DANGER EST LE MECANISME LUI-MEME. Un firewall qui coupe la ligne qui
comptait fabrique du faux calme -- et le faux calme ne se detecte pas. Trois
protections, toutes tenues par des tests :

  1. TOUT signal d'erreur survit, avec son contexte.
  2. L'ORIGINAL EST ARCHIVE sur disque AVANT toute reduction, et son chemin
     est cite dans le texte rendu. Reduire n'est acceptable que si rien n'est
     PERDU : la sortie complete cesse d'etre re-facturee a chaque tour, elle
     ne cesse pas d'exister.
  3. FAIL-CLOSED SUR LA REECRITURE (l'inverse du garde bloquant) : au moindre
     doute, on ne touche a RIEN. Une sortie amputee par un bug serait
     indetectable et mensongere, alors qu'une sortie entiere ne coute que des
     tokens.

Ce qu'il ne fait JAMAIS : cacher une erreur, inventer un succes, transformer
UNKNOWN en PASS, supprimer une preuve.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

# En dessous, reduire ajoute un risque pour un gain nul : la depense vient des
# sorties ENORMES. ~8 Ko = ~2 000 tokens.
SEUIL_OCTETS = 8_000

# Lignes gardees en tete et en queue : un debut de commande et un verdict final
# portent presque toujours l'essentiel.
TETE = 15
QUEUE = 15
CONTEXTE = 2  # lignes conservees autour de chaque signal

DOSSIER_ARCHIVE = Path(
    os.environ.get("LAFORGE_FIREWALL_DIR")
    or (Path.home() / ".claude" / "runtime" / "sorties"))

# BORNE DURE du pire cas. Mesure du 2026-09-11 sur le log de CI reel : la
# premiere version evitait 88,8 % ... et rendait encore 305 Ko, soit ~76 000
# tokens. Un taux de reduction n'est pas un verdict -- ce qui compte est ce
# qui ARRIVE dans le contexte. Un motif, si fin soit-il, ne borne rien : sur
# un log ou tout matche, il garde tout.
PLAFOND_LIGNES = 300

# SIGNAUX FORTS : ce qui decide. Survit toujours, y compris sous le plafond.
MOTIFS_FORTS = re.compile(
    r"FAILED|ERROR|FATAL|CRITICAL|Traceback|Exception|[A-Za-z]{2,}Error"
    r"|\bOOM\b|Killed|panic|denied|refus|\b\d+ failed\b|rc=[1-9]"
    r"|exit code [1-9]|Permission",
    re.I)

# SIGNAUX FAIBLES : utiles en contexte, sacrifiables avant les forts. C'est
# `passed`/`\bE\s` qui gonflaient la sortie -- ils matchent chaque ligne de
# progression d'une suite de tests.
MOTIFS_FAIBLES = re.compile(
    r"warn|skipped|timeout|deprecat|\bOK\b|passed|erreur", re.I)

MOTIFS_SIGNAL = MOTIFS_FORTS  # conserve pour les lecteurs externes


def _archiver(texte):
    """Ecrit l'original AVANT toute reduction. Leve si ca echoue -- volontaire :
    sans archive, on ne reduit pas, sinon on supprime une preuve."""
    DOSSIER_ARCHIVE.mkdir(parents=True, exist_ok=True)
    nom = "sortie_%d_%s.txt" % (
        int(time.time()),
        hashlib.sha1(texte.encode("utf-8", "replace")).hexdigest()[:8])
    chemin = DOSSIER_ARCHIVE / nom
    chemin.write_text(texte, encoding="utf-8")
    return chemin


def _indices_gardes(lignes):
    """Indices a conserver, sous plafond, sans jamais couper au hasard.

    LES BORDS SONT GARANTIS D'ABORD. Defaut mesure le 2026-09-11 sur le log de
    CI reel : remplir avec les lignes fortes puis les bords semblait logique,
    et donnait 99 % de reduction avec CINQ signaux decisifs perdus. Un vrai log
    porte des milliers de lignes ERROR / refus / Permission (flake8, scan de
    secrets) : elles saturaient le plafond, et le VERDICT -- qui vit a la fin --
    disparaissait. 15 tests synthetiques etaient verts ; seule la mesure sur
    cas reel l'a vu.

    Ordre : bords (entete + verdict) -> forts -> contexte -> faibles. Et quand
    les forts debordent, on garde les PREMIERS ET LES DERNIERS : dans un log
    long, la cause est au debut et la consequence a la fin ; ne prendre que le
    debut, c'est arriver avant le probleme et repartir avant sa conclusion.
    """
    n = len(lignes)
    forts, contexte, faibles = [], set(), set()

    bords = set(range(min(TETE, n))) | set(range(max(0, n - QUEUE), n))

    for i, ligne in enumerate(lignes):
        if MOTIFS_FORTS.search(ligne):
            forts.append(i)
            contexte |= set(range(max(0, i - CONTEXTE), min(n, i + CONTEXTE + 1)))
        elif MOTIFS_FAIBLES.search(ligne):
            faibles.add(i)

    garde = set(sorted(bords)[:PLAFOND_LIGNES])

    reste = PLAFOND_LIGNES - len(garde)
    if reste > 0 and forts:
        if len(forts) <= reste:
            garde |= set(forts)
        else:
            moitie = reste // 2
            garde |= set(forts[:moitie]) | set(forts[len(forts) - (reste - moitie):])

    for niveau in (contexte, faibles):
        for i in sorted(niveau):
            if len(garde) >= PLAFOND_LIGNES:
                break
            garde.add(i)
    return sorted(garde)


def reduire(tool_name, tool_output, tool_succeeded):
    """Texte reduit, ou None pour ne RIEN changer.

    None est le cas normal et le cas sur : il laisse la sortie d'origine
    intacte.
    """
    try:
        if not isinstance(tool_output, str):
            return None
        if len(tool_output) < SEUIL_OCTETS:
            return None

        lignes = tool_output.splitlines()
        gardes = _indices_gardes(lignes)
        # Rien de gagne : ne pas payer le risque d'une reecriture pour rien.
        if len(gardes) >= len(lignes) * 0.9:
            return None

        # L'archive AVANT la reduction. Si elle echoue, l'exception remonte et
        # la sortie d'origine est preservee telle quelle.
        archive = _archiver(tool_output)

        morceaux = []
        precedent = -1
        for i in gardes:
            if precedent >= 0 and i > precedent + 1:
                morceaux.append("    ... %d ligne(s) sans signal ..."
                                % (i - precedent - 1))
            morceaux.append(lignes[i])
            precedent = i

        retirees = len(lignes) - len(gardes)
        bandeau = (
            "[context-firewall] sortie REDUITE : %d lignes -> %d "
            "(%d retirees, %d Ko economises a CHAQUE tour).\n"
            "  Integral conserve : %s\n"
            "  Garde : entete, fin, et toute ligne portant un signal d'erreur "
            "avec son contexte. Rien n'est perdu, seulement deporte."
            % (len(lignes), len(gardes), retirees,
               (len(tool_output) - sum(len(m) for m in morceaux)) // 1024,
               archive.name))
        return bandeau + "\n\n" + "\n".join(morceaux)
    except Exception:  # noqa: BLE001 - muet-ok
        # muet-ok : FAIL-CLOSED sur la reecriture. En cas de doute on ne touche
        # a rien -- une sortie tronquee par un bug serait indetectable.
        return None


def traiter(ev):
    """N'ecrit QUE s'il y a une reduction a proposer."""
    try:
        if str((ev or {}).get("hook_event_name") or "") != "PostToolUse":
            return 0
        scratch = (ev or {}).get("scratchpad_dir")
        if scratch:
            global DOSSIER_ARCHIVE
            DOSSIER_ARCHIVE = Path(scratch) / "sorties_outils"
        succes = (ev or {}).get("tool_succeeded")
        reduit = reduire((ev or {}).get("tool_name") or "",
                         (ev or {}).get("tool_output"), succes)
        if reduit is None:
            return 0  # cas normal : rien, pas un mot
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "updatedToolOutput": {
                    "text": reduit,
                    # Un firewall ne transforme JAMAIS un echec en succes.
                    "isError": succes is False,
                },
            }
        }))
        return 0
    except Exception:  # noqa: BLE001 - muet-ok
        return 0


def main():
    try:
        ev = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - muet-ok
        return 0
    return traiter(ev)


if __name__ == "__main__":
    sys.exit(main())
