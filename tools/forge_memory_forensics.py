#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_memory_forensics.py — le point complet sur les .md memoire.

Directive owner 2026-08-16 : « j'ai la sensation que tu les utilises mal ou pas
du tout ». Ce module croise TOUTES les sources pour dire, par memoire, ou elle
vit et si elle est perdue :
  - MEMORY.md        (index CHAUD, charge chaque session)
  - MEMORY.md.bak    (ancien index, hooks de memoires peut-etre disparues)
  - MEMORY_ARCHIVE.md(index FROID, jamais charge)
  - *.md sur disque  (la connaissance reelle)
  - _memory_ledger.db(toutes les versions + contenu recuperable)

Verdicts :
  VIVANTE_CHAUDE   fichier present + dans l'index chaud (utilisable au boot)
  VIVANTE_FROIDE   fichier present + seulement en froid (recall uniquement)
  ORPHELINE        fichier present + AUCUN index (invisible, jamais chargee)
  PERDUE_RECUP     referencee (bak/ledger) + fichier ABSENT + contenu au ledger
  PERDUE_SECHE     referencee + fichier ABSENT + AUCUN contenu au ledger (vraie perte)
LECTURE SEULE. --recover ecrit les PERDUE_RECUP sur disque depuis le ledger.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path


# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
from nokido_agent.tools.forge_archeo_socle import cli
from nokido_agent.tools.forge_archeo_socle import liens_memoire as _liens

_LIEN = re.compile(r"\]\(([A-Za-z0-9_.-]+\.md)\)")


# _liens vient du socle (import ci-dessus) : meme extraction que
# forge_memory_compactor._index_liens.


def analyser(mdir: Path) -> dict:
    chaud = _liens(mdir / "MEMORY.md")
    froid = _liens(mdir / "MEMORY_ARCHIVE.md")
    bak = _liens(mdir / "MEMORY.md.bak")
    disque = {p.name for p in mdir.glob("*.md")} - {"MEMORY.md", "MEMORY_ARCHIVE.md", "MEMORY.md.bak"}

    # ledger : fichiers traces + ceux dont le contenu est encore recuperable
    ledger_files, ledger_recup = set(), set()
    db = mdir / "_memory_ledger.db"
    if db.exists():
        con = sqlite3.connect(str(db))
        for (fn,) in con.execute("SELECT DISTINCT fname FROM memory_ledger"):
            ledger_files.add(fn)
        for (fn,) in con.execute(
                "SELECT DISTINCT fname FROM memory_ledger WHERE content!='' AND event!='deleted'"):
            ledger_recup.add(fn)
        con.close()

    reference = chaud | froid | bak | ledger_files
    verdicts = {}
    for f in sorted(disque | reference):
        present = f in disque
        if present and f in chaud:
            v = "VIVANTE_CHAUDE"
        elif present and f in froid:
            v = "VIVANTE_FROIDE"
        elif present:
            v = "ORPHELINE"
        elif f in ledger_recup:
            v = "PERDUE_RECUP"
        else:
            v = "PERDUE_SECHE"
        verdicts[f] = v

    from collections import Counter
    comptes = Counter(verdicts.values())
    return {
        "n_disque": len(disque),
        "n_index_chaud": len(chaud), "n_index_froid": len(froid),
        "n_bak": len(bak), "n_ledger": len(ledger_files),
        "comptes": dict(comptes),
        "PERDUE_RECUP": sorted(f for f, v in verdicts.items() if v == "PERDUE_RECUP"),
        "PERDUE_SECHE": sorted(f for f, v in verdicts.items() if v == "PERDUE_SECHE"),
        "ORPHELINE": sorted(f for f, v in verdicts.items() if v == "ORPHELINE"),
        # memoires du .bak absentes de TOUT index vivant et du disque = candidates a la perte
        "bak_disparues": sorted(f for f in bak if f not in disque),
    }


def recover(mdir: Path, noms: list) -> dict:
    db = mdir / "_memory_ledger.db"
    con = sqlite3.connect(str(db))
    faits = []
    for fn in noms:
        r = con.execute(
            "SELECT content FROM memory_ledger WHERE fname=? AND content!='' AND event!='deleted' "
            "ORDER BY seq DESC LIMIT 1", (fn,)).fetchone()
        if r and r[0]:
            (mdir / fn).write_text(r[0], encoding="utf-8")
            faits.append(fn)
    con.close()
    return {"recuperees": len(faits), "fichiers": faits}


def main() -> int:
    a = cli("Forensique des fichiers memoire (liens morts, disparitions)",
            memory_dir={"required": True},
            recover={"action": "store_true",
                     "help": "restaure les PERDUE_RECUP depuis le ledger"})
    mdir = Path(a.memory_dir)
    res = analyser(mdir)
    if a.recover and res["PERDUE_RECUP"]:
        res["recover"] = recover(mdir, res["PERDUE_RECUP"])
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
