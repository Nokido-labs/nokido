#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_memory_index_export.py — le nerf afferent entre les fiches et le corps.

Mesure du 2026-09-04 : 776 fiches memoire vivent dans le profil Claude
(`~/.claude/projects/<projet>/memory/`), et **73 seulement** sont citees par
`MEMORY.md`. Les ~700 autres ne sont atteignables ni par parcours, ni par
recherche — le corps ne peut pas les lire du tout.

La cause n'est pas architecturale. Nokido possede deja tous les organes :
Qdrant (`nokido_sovereign_rag`, 1,29 M points), `forge_conv_indexer`,
`forge_graph_universal`, `forge_hebbian_linker`, `forge_knowledge_distiller`,
et une consolidation nocturne cablee en NREM1 (`memory_consolidation`).
Ce qui manque est un NERF : les fiches sont hors du corps.

Mesure de l'obstacle, par remontee d'arborescence (le seul moyen de distinguer
« absent » de « refuse ») :

    %USERPROFILE%                             True    visible
    %USERPROFILE%\\.claude                     False   REFUSE ICI
    ...\\.claude\\projects\\<projet>\\memory        False

Les deux comptes de service (`LaForgeSbxOffline`, `LaForgeSbxOnline`) sont
arretes au niveau `.claude`. C'est une ACL, pas une absence.

## Le choix retenu, et ce qu'il refuse

Trois chemins existaient : elargir l'ACL, decouper en index thematiques, ou
exporter un index. L'owner a retenu l'export — et ce script **n'exporte JAMAIS
le corps d'une fiche**. Il ne sort que ce qui sert a la retrouver : nom,
description, type, date, liens, empreinte. Le profil Claude contient aussi des
transcripts et d'eventuels secrets colles en conversation ; les faire entrer
dans le depot pour gagner de la recherche serait un mauvais echange.

## Pourquoi il tourne sous le compte OWNER

Il doit lire `.claude`, ce qu'aucun compte de service ne peut faire. Il est
git-tracke pour etre auditable, et il est en LECTURE SEULE sur les fiches : sa
seule ecriture est le JSONL de sortie, dans le depot.

Usage :  LAFORGE_PYTHON tools/forge_memory_index_export.py [--verifier]
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/nerf-afferent"

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SORTIE = ROOT / "docs" / "memory_index.jsonl"

# Le dossier de fiches, deduit du nom du projet. Ne JAMAIS coder un chemin
# absolu : ce script doit suivre le profil, pas une machine.
_PROJET = "C--Users-user-Script-python-IA"
DOSSIER = Path.home() / ".claude" / "projects" / _PROJET / "memory"

# Motifs de secret. Une description qui en contient n'est PAS exportee : mieux
# vaut une fiche non indexee qu'un secret publie. Le refus est COMPTE et RENDU.
_SECRETS = re.compile(
    r"(?:[A-Za-z0-9+/]{40,}={0,2}"          # base64 long
    r"|\b[0-9a-f]{40,}\b"                    # hex long (jeton, sha512)
    r"|gh[pousr]_[A-Za-z0-9]{20,}"           # jeton GitHub
    r"|sk-[A-Za-z0-9]{20,}"                  # cle style OpenAI
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)")

_RX_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_RX_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
_RX_MDLINK = re.compile(r"\]\(([A-Za-z0-9_.\-]+\.md)\)")


def _frontmatter(texte: str) -> dict:
    """Champs du frontmatter YAML, sans dependance a un parseur.

    Volontairement tolerant : une fiche sans frontmatter reste indexable par son
    nom de fichier. Exiger un format ferait disparaitre les plus anciennes, qui
    sont justement celles que personne ne retrouve.
    """
    m = _RX_FRONT.match(texte)
    if not m:
        return {}
    champs: dict = {}
    for ligne in m.group(1).splitlines():
        if ligne.startswith((" ", "\t")) or ":" not in ligne:
            continue
        cle, _, val = ligne.partition(":")
        champs[cle.strip()] = val.strip().strip('"').strip("'")
    # `type` vit sous `metadata:` — on le recupere a plat.
    m_type = re.search(r"^\s+type:\s*(\S+)", m.group(1), re.M)
    if m_type:
        champs["type"] = m_type.group(1)
    return champs


def _resume(texte: str, front: dict, limite: int = 240) -> str:
    """Description de la fiche. JAMAIS son corps.

    On prefere la `description` du frontmatter ; a defaut, le premier titre ou
    la premiere phrase utile. C'est ce qui sera vectorise, donc ce qui decide
    si la fiche se retrouve.
    """
    if front.get("description"):
        return front["description"][:limite]
    corps = _RX_FRONT.sub("", texte, count=1)
    for ligne in corps.splitlines():
        ligne = ligne.strip().lstrip("#").strip()
        if len(ligne) > 25 and not ligne.startswith(("---", "|", "```")):
            return ligne[:limite]
    return ""


def recenser(dossier: Path = DOSSIER) -> tuple:
    """Rend (entrees, diagnostic). Ne LIT que, n'ecrit rien ici."""
    diag = {"dossier": str(dossier), "vu": dossier.is_dir(), "fiches": 0,
            "illisibles": [], "refusees_secret": [], "sans_frontmatter": 0}
    if not dossier.is_dir():
        # « je n'ai pas pu regarder » n'est pas « il n'y a rien » : sous un
        # compte de service ce chemin rend False alors qu'il EXISTE.
        diag["erreur"] = ("dossier invisible depuis ce compte (%s) — ce script "
                          "doit tourner sous le compte OWNER" % os.environ.get("USERNAME"))
        return None, diag

    entrees = []
    for fiche in sorted(dossier.glob("*.md")):
        if fiche.name == "MEMORY.md":
            continue
        try:
            texte = fiche.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            diag["illisibles"].append("%s (%s)" % (fiche.name, type(exc).__name__))
            continue
        diag["fiches"] += 1
        front = _frontmatter(texte)
        if not front:
            diag["sans_frontmatter"] += 1
        description = _resume(texte, front)
        if _SECRETS.search(description):
            # Mieux vaut une fiche non indexee qu'un secret publie.
            diag["refusees_secret"].append(fiche.name)
            continue
        liens = sorted(set(_RX_WIKILINK.findall(texte)) |
                       {c[:-3] for c in _RX_MDLINK.findall(texte)})
        entrees.append({
            "name": front.get("name") or fiche.stem,
            "fichier": fiche.name,
            "type": front.get("type") or "inconnu",
            "description": description,
            "liens": liens[:20],
            "octets": len(texte),
            "modifie": datetime.fromtimestamp(fiche.stat().st_mtime, timezone.utc).isoformat(),
            # L'empreinte permet de savoir qu'une fiche a CHANGE sans exporter
            # son contenu : la reindexation devient incrementale.
            "sha256": hashlib.sha256(texte.encode("utf-8", "replace")).hexdigest()[:16],
        })
    return entrees, diag


def ecrire(entrees, cible: Path = SORTIE) -> Path | None:
    refus = []
    for candidat in (cible, ROOT / "sandbox" / cible.name):
        try:
            candidat.parent.mkdir(parents=True, exist_ok=True)
            with candidat.open("w", encoding="utf-8") as fh:
                for e in entrees:
                    fh.write(json.dumps(e, ensure_ascii=False) + "\n")
            return candidat
        except Exception as exc:
            refus.append("%s : %s" % (candidat, type(exc).__name__))
    print("[export] aucune cible accessible — %s" % " | ".join(refus))
    return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Exporte l'index des fiches memoire (SANS leur corps)")
    p.add_argument("--verifier", action="store_true",
                   help="recense et rapporte, sans rien ecrire")
    args = p.parse_args(argv)

    entrees, diag = recenser()
    if entrees is None:
        print("NO_VERDICT — %s" % diag.get("erreur"))
        return 2

    orphelines = 0
    index = ROOT.parent / ".claude"  # jamais lu ici, mentionne pour la trace
    cites = set()
    memoire_index = DOSSIER / "MEMORY.md"
    try:
        cites = {c[:-3] for c in _RX_MDLINK.findall(memoire_index.read_text(encoding="utf-8"))}
    except Exception:
        cites = set()
    if cites:
        orphelines = sum(1 for e in entrees if e["fichier"][:-3] not in cites)

    print("fiches recensees   : %d" % diag["fiches"])
    print("sans frontmatter   : %d" % diag["sans_frontmatter"])
    print("illisibles         : %d %s" % (len(diag["illisibles"]), diag["illisibles"][:3]))
    print("refusees (secret)  : %d %s" % (len(diag["refusees_secret"]), diag["refusees_secret"][:3]))
    if cites:
        print("citees par MEMORY  : %d  -> ORPHELINES : %d" % (len(cites), orphelines))
    else:
        print("citees par MEMORY  : index illisible — orphelines NON mesurees")
    if args.verifier:
        print("\n--verifier : rien ecrit")
        return 0
    pose = ecrire(entrees)
    print("index ecrit        : %s (%d entrees)" % (pose or "NON POSE", len(entrees)))
    print("\nLe corps des fiches n'est PAS exporte : seuls nom, description, type,")
    print("liens, taille, date et empreinte sortent du profil.")
    return 0 if pose else 1


if __name__ == "__main__":
    sys.exit(main())
