#!/usr/bin/env python3
"""nokido_fix_legacy_paths.py — repare les CHEMINS figes laisses par le renommage.

Le renommage du 2026-08-11 (`nokido_deep_rename.py`) a traite les `.py` : 94 sites
sur 71 fichiers. Il n'a PAS traite les wrappers `.bat` / `.ps1` / `.cmd` ni les
configs `.json` / `.toml`. Mesure du 2026-08-12 : **63 fichiers sur 116 configs**
pointaient encore vers `Script python IA\\LaForge`, un dossier qui n'existe plus.
Consequence vue en production : 3 des 5 serveurs MCP de Claude Desktop et les deux
entrees Cline lancaient un bridge introuvable.

POURQUOI UN OUTIL SEPARE plutot que `nokido_deep_rename.py` : celui-la renomme
`laforge` -> `nokido` PARTOUT. Or il reste des `laforge` parfaitement VIVANTS qu'il
ne faut surtout pas toucher — le service `LaForge-Master`, les comptes sandbox
`LaForgeSbxOffline` / `LaForgeTrusted`, l'env conda `laforge_py314`, l'en-tete
`LaForge-Agent-Name`. Ici on ne substitue QUE la sous-chaine de CHEMIN, ce qui rend
l'operation sure par construction : `LaForge-Master` ne contient pas
`Script python IA/LaForge`.

Dry-run par defaut. `--apply` pour ecrire. Les `.json` sont re-parses apres
substitution : une config cassee ne part pas sur le disque.
"""

__FORGE_COLOR__ = "infra/rename : repare les chemins figes laisses par le renommage"  # organe declare le 2026-09-06 (audit de raccordement)
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Les deux formes de separateur rencontrees, y compris echappees en JSON.
MOTIFS = [
    ("Script python IA\\\\LaForge", "Script python IA\\\\Nokido"),  # JSON echappe
    ("Script python IA\\LaForge", "Script python IA\\Nokido"),
    ("Script python IA/LaForge", "Script python IA/Nokido"),
]

TEXT_EXT = {".json", ".bat", ".cmd", ".toml", ".ps1", ".ini", ".txt", ".md",
            ".yaml", ".yml", ".cfg", ".sh"}

# Artefacts et archives : un snapshot doit garder le chemin de l'epoque, sinon il
# ne temoigne plus de rien.
# Artefacts, archives et TRANSCRIPTS. Reecrire un historique de conversation le
# falsifie : `.aider.chat.history.md` pesait a lui seul 231 des 351 occurrences
# du premier dry-run, toutes dans des tours de dialogue passes. Un transcript doit
# garder le chemin de son epoque, au meme titre qu'un snapshot de cutover.
EXCLUS = ("sandbox/cutover_", "RAG_plain_bak/", ".git/", "node_modules/",
          "__pycache__/", "logs/", "project_atlas.json", "sandbox/workspace/",
          ".aider.chat.history", ".aider.input.history",
          # AJOUTS 2026-08-30, apres que le parcours recursif a rendu ces fichiers
          # visibles pour la premiere fois. Ils tombent sous la regle deja posee
          # plus haut -- un temoin garde le chemin de son epoque :
          # - `gitingest_*` sont des SNAPSHOTS du depot a une date (292 des 499
          #   occurrences a eux seuls). Les reecrire falsifie la photo.
          # - `NOKIDO_CUTOVER_RUNBOOK.md` DOCUMENTE le renommage : y substituer
          #   LaForge->Nokido produirait « renommer Nokido en Nokido », c'est-a-dire
          #   un mode d'emploi qui ne veut plus rien dire.
          # - `.agents/` porte les briefings et handoffs d'une session multi-agents
          #   passee : c'est un journal, pas une configuration vivante.
          "gitingest_", "NOKIDO_CUTOVER_RUNBOOK", ".agents/",
          "_strategist_drafts/")


# Dossiers jamais parcourus : volumineux, generes, ou temoins d'une epoque.
# Reecrire une archive ou un transcript le FALSIFIE (cf EXCLUS ci-dessus).
_ZONES_MORTES = {".git", "node_modules", "__pycache__", "sandbox", "logs",
                 "logs_archive", "RAG", "RAG_plain_bak", "models", "backups",
                 "_backups", "_archive", "_attic", "archive", "dist_laforge",
                 "transcripts_laforge", ".pytest_cache", ".ruff_cache",
                 ".benchmarks", "versions", "exports", "kaggle_dataset"}


def _candidats(cible: str | None):
    """Parcours RECURSIF depuis la racine (ou un sous-dossier).

    Etait `iterdir()` sur SIX dossiers en dur, donc non recursif et aveugle a
    `.agents/` comme a `docs/`. Mesure 2026-08-30 : l'outil rendait « 0 fichier,
    0 occurrence » alors que `.agents/orchestrator/handoff.md` portait sept
    chemins morts et que 110 `app/agent_*/README.md` en portaient un chacun.
    Un scanner qui ne PEUT PAS voir rend le meme zero qu'un depot propre --
    c'est le pire des resultats, parce qu'il rassure.
    """
    base = (ROOT / cible) if cible else ROOT
    if not base.is_dir():
        return
    vus = set()
    # `os.walk` et NON `rglob` : il faut ELAGUER pendant la descente. Un
    # `rglob("*")` visite `.git`, `sandbox`, `RAG` et `models` AVANT que le filtre
    # ne s'applique -- mesure : la commande expire. On coupe donc les branches
    # mortes a la source, en modifiant `dn` sur place.
    for dp, dn, fn in os.walk(base):
        dn[:] = [d for d in dn if d not in _ZONES_MORTES]
        for nom in sorted(fn):
            f = Path(dp) / nom
            if f.suffix.lower() not in TEXT_EXT:
                continue
            rel = f.relative_to(ROOT).as_posix()
            if any(x in rel for x in EXCLUS) or rel in vus:
                continue
            vus.add(rel)
            yield f, rel


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="ecrit (defaut : dry-run)")
    ap.add_argument("--dir", default=None, help="limiter a un sous-dossier")
    a = ap.parse_args()

    touches, total, refuses = [], 0, []
    scannes = 0
    for f, rel in _candidats(a.dir):
        scannes += 1
        try:
            avant = f.read_text(encoding="utf-8", errors="surrogateescape")
        except Exception as e:
            refuses.append((rel, "lecture: %s" % type(e).__name__))
            continue
        apres, n = avant, 0
        for vieux, neuf in MOTIFS:
            c = apres.count(vieux)
            if c:
                apres = apres.replace(vieux, neuf)
                n += c
        if not n:
            continue
        # Un .json casse est pire que le chemin mort qu'on repare.
        if f.suffix.lower() == ".json":
            try:
                json.loads(apres)
            except Exception as e:
                refuses.append((rel, "JSON invalide apres substitution: %s" % e))
                continue
        touches.append((rel, n))
        total += n
        if a.apply:
            f.write_text(apres, encoding="utf-8", errors="surrogateescape")

    mode = "APPLIQUE" if a.apply else "DRY-RUN (rien ecrit)"
    print("=" * 68)
    print("  Chemins figes 'Script python IA/LaForge' -> Nokido — %s" % mode)
    print("=" * 68)
    for rel, n in touches:
        print("  %3d x  %s" % (n, rel))
    # LE DENOMINATEUR, toujours. Sans lui, « 0 occurrence » ne se distingue pas de
    # « je n'ai rien pu regarder » -- et c'est exactement ce que cet outil a fait
    # croire jusqu'au 2026-08-30, faute d'un parcours recursif.
    print("\n  %d fichier(s) touche(s), %d occurrence(s)  [%d fichier(s) scanne(s)]"
          % (len(touches), total, scannes))
    if refuses:
        print("\n  REFUSES (rien ecrit sur ceux-la) :")
        for rel, why in refuses:
            print("    ! %s — %s" % (rel, why))
    if not a.apply and touches:
        print("\n  Relancer avec --apply pour ecrire.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
