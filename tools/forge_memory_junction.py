#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_memory_junction.py — faire entrer la memoire de Claude Code dans le corps.

Mesure du 2026-09-04 : 776 fiches vivent dans `~/.claude/projects/<projet>/memory/`
et **73 seulement** sont citees par `MEMORY.md`. Surtout, ce dossier est
INACCESSIBLE au corps — remontee d'arborescence sous `LaForgeSbxOnline` :

    %USERPROFILE%                    True    visible
    %USERPROFILE%\\.claude            False   REFUSE ICI

Or Nokido est le seul client dans ce cas : Gemini ecrit dans `GEMINI.md`,
Antigravity dans `.agents/`, tous dans `AGENTS.md` et `RULES_SHARED.md` — deja
versionnes, deja lisibles par le hub. Et `docs/LESSONS_UNIFIED.md` declare la
source canonique : le RAG, alimente par `anchor_solution()`. Les fiches `.claude`
sont donc une memoire PARALLELE qui double le systeme sans jamais le rejoindre.

Une jonction de repertoire resout cela sans toucher une seule ACL : Claude Code
continue d'ecrire au meme chemin, les fichiers atterrissent dans le depot, le hub
les lit. Meme patron que `V:` -> `RAG`, deja eprouve ici.

## Ce que ce script fait DIFFEREMMENT d'un deplacement naif

Un `move` puis `mklink` perd la memoire si le lien echoue apres coup : les fiches
sont ailleurs et Claude Code repart de zero. L'ordre est donc :

    1. eprouver mklink sur un dossier JETABLE  (droits verifies AVANT de bouger)
    2. COPIER, ne pas deplacer                 (la source reste intacte)
    3. verifier la copie par empreinte         (compte ET contenu)
    4. RENOMMER la source, jamais supprimer    (« n'enterre rien »)
    5. creer la jonction, puis la RELIRE       (l'effet, pas le code retour)
    6. au moindre echec : restaurer le nom d'origine

La source renommee `memory.avant_jonction_<horodatage>` n'est jamais effacee.
C'est le filet : si quoi que ce soit tourne mal, elle se remet en place a la main.

Usage (compte OWNER — le hub n'a pas l'acces) :
    LAFORGE_PYTHON tools/forge_memory_junction.py            # dry-run
    LAFORGE_PYTHON tools/forge_memory_junction.py --executer
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/nerf-afferent"

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "memory"

# Deduit du nom du projet, jamais code en absolu : ce script doit suivre le
# profil de qui le lance, pas une machine.
_PROJET = os.environ.get("LAFORGE_CLAUDE_PROJET", "C--Users-user-Script-python-IA")
SOURCE = Path.home() / ".claude" / "projects" / _PROJET / "memory"

_GITIGNORE = """# Memoire episodique des agents — JAMAIS versionnee.
#
# Ces fiches portent des chemins systeme, des noms de machine et des empreintes.
# Les versionner declencherait le gate egress a chaque push et polluerait
# l'historique. Elles doivent rester LISIBLES par le hub (donc dans le depot)
# et INVISIBLES a git.
#
# L'adressabilite passe par le RAG (`anchor_solution` / `rag_fts`), pas par git.
*
!.gitignore
"""


def _est_jonction(p: Path) -> bool:
    """Vrai si `p` est une jonction/lien. Rend False si on ne peut pas savoir.

    `os.path.isjunction` n'existe qu'a partir de 3.12 — le projet l'utilise deja
    avec ce garde dans `forge_body_regulation_audit`.
    """
    try:
        if hasattr(os.path, "isjunction") and os.path.isjunction(p):
            return True
        return p.is_symlink()
    except Exception:
        return False


def _empreinte(dossier: Path) -> dict:
    """{nom: sha256} des fichiers d'un dossier. Sert a PROUVER la copie."""
    out = {}
    for f in sorted(dossier.iterdir()):
        if f.is_file():
            try:
                out[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
            except Exception as exc:
                out[f.name] = "ILLISIBLE:%s" % type(exc).__name__
    return out


def _mklink(lien: Path, cible: Path) -> tuple:
    """Cree une jonction. Rend (ok, detail). Ne leve jamais."""
    try:
        # `errors="replace"` est OBLIGATOIRE : `mklink` repond dans l'encodage
        # de la console (cp850 ici), et un mode-texte sans tolerance fait
        # crasher le thread de lecture de subprocess — anti-regression de
        # l'incident 47 Go, signalee par le gate firehose.
        r = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(lien), str(cible)],
                           capture_output=True, text=True, errors="replace", timeout=30)
    except Exception as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)
    detail = (r.stdout or "").strip() or (r.stderr or "").strip()
    # Le code retour ne suffit pas : on relit l'EFFET.
    return (r.returncode == 0 and _est_jonction(lien)), detail


def _eprouver_les_droits(dry: bool = False) -> tuple:
    """Cree puis defait une jonction JETABLE. C'est le seul test honnete.

    Sans cela, on decouvre l'absence de droits APRES avoir deplace la memoire.

    Il tourne AUSSI en dry-run, et c'est deliberе : il ne cree qu'un dossier
    temporaire aussitot defait, donc il ne coute rien — alors qu'un dry-run qui
    afficherait « OK (non teste) » ferait decider d'executer sur une mesure qui
    n'a pas eu lieu. Premiere version corrigee le 2026-09-04 : elle rendait
    True sans rien eprouver, et l'affichait « OK ».
    """
    base = CIBLE.parent / ("_essai_jonction_%d" % os.getpid())
    lien = CIBLE.parent / ("_essai_lien_%d" % os.getpid())
    try:
        base.mkdir(parents=True, exist_ok=True)
        ok, detail = _mklink(lien, base)
        if lien.exists() or _est_jonction(lien):
            try:
                lien.rmdir()
            except Exception:  # muet-ok
                # Nettoyage d'un lien JETABLE. Son echec n'a aucune consequence
                # sur la migration : il laisse un dossier vide de plus, la
                # journaliser ferait crier un garde sur du bruit sans effet.
                pass
        return ok, detail
    except Exception as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)
    finally:
        try:
            base.rmdir()
        except Exception:  # muet-ok
            # Meme raison : dossier d'essai jetable, sans effet sur la memoire.
            pass


def migrer(dry: bool = True) -> int:
    print("=== jonction memoire — %s ===" % ("DRY-RUN" if dry else "EXECUTION"))
    print("  source : %s" % SOURCE)
    print("  cible  : %s" % CIBLE)
    print("  compte : %s" % os.environ.get("USERNAME"))

    if _est_jonction(SOURCE):
        print("\n[=] la jonction est DEJA en place — rien a faire.")
        return 0
    if not SOURCE.is_dir():
        print("\n[!] source invisible depuis ce compte. Ce script doit tourner "
              "sous le compte OWNER : le hub n'a pas d'acces a `.claude`.")
        return 2

    fiches = [f for f in SOURCE.iterdir() if f.is_file()]
    print("\n  fiches a migrer : %d" % len(fiches))

    ok_droits, detail = _eprouver_les_droits()
    print("  droits mklink   : %s%s" % ("EPROUVES OK" if ok_droits else "REFUSES",
                                        (" — %s" % detail) if detail else ""))
    if not ok_droits:
        # Le refus arrete AUSSI le dry-run : annoncer des etapes qui ne
        # pourraient pas aboutir reviendrait a promettre ce qu'on ne peut tenir.
        print("\n[!] mklink refuse — rien n'a bouge, et rien ne bougera. "
              "Relancer depuis une console owner (elevee si besoin).")
        return 3

    if dry:
        print("\n[dry-run] etapes qui seraient jouees :")
        print("   1. copier %d fiches vers %s" % (len(fiches), CIBLE))
        print("   2. verifier la copie par sha256, fichier par fichier")
        print("   3. renommer la source en memory.avant_jonction_<horodatage>")
        print("   4. mklink /J source -> cible, puis RELIRE la jonction")
        print("   5. tout echec -> restauration du nom d'origine")
        print("\n   la source n'est JAMAIS supprimee, seulement renommee.")
        return 0

    # 1-2. COPIER puis PROUVER. On ne deplace pas : la source reste le filet.
    CIBLE.mkdir(parents=True, exist_ok=True)
    (CIBLE / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")
    avant = _empreinte(SOURCE)
    for f in fiches:
        shutil.copy2(str(f), str(CIBLE / f.name))
    apres = _empreinte(CIBLE)
    manquants = [n for n, h in avant.items() if apres.get(n) != h]
    if manquants:
        print("\n[!] copie NON conforme sur %d fichier(s) : %s" % (len(manquants), manquants[:5]))
        print("    rien n'a ete renomme, la source est intacte.")
        return 4
    print("  copie verifiee  : %d/%d fichiers, empreintes identiques" % (len(avant), len(avant)))

    # 3. RENOMMER, jamais supprimer.
    secours = SOURCE.parent / ("memory.avant_jonction_%s" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    try:
        SOURCE.rename(secours)
    except Exception as exc:
        print("\n[!] renommage impossible (%s) — la source est intacte, rien de casse."
              % type(exc).__name__)
        return 5
    print("  source de secours : %s" % secours.name)

    # 4-5. Jonction, puis relecture de l'EFFET.
    ok, detail = _mklink(SOURCE, CIBLE)
    if not ok:
        try:
            secours.rename(SOURCE)
            print("\n[!] jonction echouee (%s) — source RESTAUREE, memoire intacte." % detail)
        except Exception as exc:
            print("\n[!!] jonction echouee ET restauration impossible (%s). "
                  "La memoire est dans %s — la remettre a la main." % (type(exc).__name__, secours))
        return 6

    lisibles = len([f for f in SOURCE.iterdir() if f.is_file()])
    print("  jonction active : %d fiche(s) lisibles au chemin d'origine" % lisibles)
    if lisibles != len(avant):
        print("  [!] ecart de comptage (%d attendues) — a instruire avant de "
              "toucher au dossier de secours." % len(avant))
    print("\n[+] termine. Le dossier de secours %s n'est PAS supprime : "
          "c'est le filet, a retirer a la main quand tu auras verifie." % secours.name)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Fait entrer la memoire de Claude Code dans le depot")
    p.add_argument("--executer", action="store_true",
                   help="applique reellement (defaut : dry-run)")
    args = p.parse_args(argv)
    return migrer(dry=not args.executer)


if __name__ == "__main__":
    sys.exit(main())
