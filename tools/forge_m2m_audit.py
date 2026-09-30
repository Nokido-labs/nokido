# -*- coding: utf-8 -*-
"""Qui touche `agent_messages`, et sur QUELLE base — lecture seule.

P0 (2026-09-05) : la table quitte RAG/embeddings.db pour la base M2M dediee
(`forge_db_path.m2m_path`). 75 fichiers nomment la table ; ce module les classe
sans les executer :

  REDIRIGE     : le fichier nomme `m2m_path` / `LAFORGE_M2M_DB_PATH`
  A_REDIRIGER  : il nomme `embeddings.db`, `db_path(`, `DB_PATH` ou `LAFORGE_DB`
                 a proximite d'un SQL sur la table
  INDETERMINE  : aucun chemin de base visible (connexion passee en parametre,
                 helper importe) — a lire, pas a supposer
  JETABLE      : script ponctuel (`_batch*`, `_check*`, `_dump*`, `tmp_*`,
                 `patch_*`, `_read_*`, `_fetch_*`, `_resend_*`, `_wait_*`,
                 `_fix_*`) — liste, jamais redirige

Un fichier illisible est compte ILLISIBLE, pas absent. Utilise par
tests/nr/test_m2m_hors_embeddings_nr.py.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOSSIERS = ("app", "tools", "app/web_hub", "tools/hooks")
TABLE = "agent_messages"
_JETABLE = re.compile(r"^(_batch|_check|_dump|_read|_fetch|_resend|_wait|_fix|tmp_|patch_)")
_M2M = re.compile(r"m2m_path|open_m2m|LAFORGE_M2M_DB_PATH")
# Un NOM de variable n'est pas une base : `DB_PATH = Path(m2m_path())` sortait MIXTE
# (mesure 2026-09-06, 5 fichiers migres). Seuls comptent le fichier nomme, le point
# d'acces de la base du RAG et l'env qui la designait.
_GROSSE = re.compile(r"embeddings\.db|\bdb_path\(|LAFORGE_DB\b")
_SQL_TABLE = re.compile(r"(?i)\b(from|into|update|join)\s+" + TABLE + r"\b")


def _fichiers():
    vus = set()
    for d in DOSSIERS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in sorted(base.glob("*.py")):
            if p.resolve() in vus:
                continue
            vus.add(p.resolve())
            yield p


def classer(p: Path) -> dict | None:
    try:
        src = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"fichier": str(p.relative_to(ROOT)), "etat": "ILLISIBLE", "detail": type(e).__name__}
    if TABLE not in src:
        return None
    sql = len(_SQL_TABLE.findall(src))
    rel = str(p.relative_to(ROOT)).replace("\\", "/")
    if _JETABLE.match(p.name):
        etat = "JETABLE"
    elif p.name in ("forge_db_path.py", "forge_m2m_audit.py", "forge_m2m_db_split.py"):
        etat = "REDIRIGE"      # le point d'acces et ses outils
    elif _M2M.search(src) and not _GROSSE.search(src):
        etat = "REDIRIGE"
    elif _M2M.search(src) and _GROSSE.search(src):
        etat = "MIXTE"         # les deux bases nommees : a lire
    elif _GROSSE.search(src):
        etat = "A_REDIRIGER" if sql else "MENTION_SEULE"
    else:
        etat = "INDETERMINE" if sql else "MENTION_SEULE"
    return {"fichier": rel, "etat": etat, "sql_sur_table": sql}


def auditer() -> dict:
    res = [r for p in _fichiers() if (r := classer(p))]
    par_etat: dict[str, list[str]] = {}
    for r in res:
        par_etat.setdefault(r["etat"], []).append(r["fichier"])
    return {"fichiers_touchant_la_table": len(res), "par_etat": par_etat, "detail": res}


def main() -> int:
    a = auditer()
    print(json.dumps({k: v for k, v in a.items() if k != "detail"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
