# -*- coding: utf-8 -*-
# __FORGE_COLOR__ = "docker-audit-trail"
"""forge_docker_audit — journal d'audit UNIQUE des actions sur Docker.

Pourquoi (2026-07-22) : Docker s'arretait toutes les 30 s a 4 min et il a fallu
une enquete complete (5 sources croisees, une hypothese fausse) pour eliminer un
par un le keeper, l'homeostat, le monitor et `wsl --shutdown`. Aucun de ces
organes ne laissait de trace : impossible de savoir QUI avait agi.

Ce module est le point de passage OBLIGE. Chaque entree porte l'action, la
RAISON, et surtout la CHAINE D'APPEL capturee automatiquement — on sait donc
quel module, quelle fonction et quelle ligne ont decide.

Propriete la plus utile : le SILENCE est une preuve. Si Docker meurt et que le
journal ne porte aucune entree a cet instant, l'acteur est EXTERNE a Nokido
(Docker Desktop lui-meme, l'utilisateur, une MAJ). C'est exactement la question
qu'on n'arrivait pas a trancher.

Ne leve JAMAIS : un journal qui casse l'appelant serait pire que pas de journal.

Usage (une ligne au point d'entree) :
    from forge_docker_audit import record
    record("stop", reason="reclaim RAM", target="Docker Desktop.exe --quit")

Lecture :
    LAFORGE_PYTHON app/forge_docker_audit.py            # 30 dernieres actions
    LAFORGE_PYTHON app/forge_docker_audit.py --since 14:30
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "sandbox" / "docker_actions.jsonl"

# Actions normalisees : tout ce qui peut faire vivre ou mourir Docker.
ACTIONS = ("start", "stop", "kill", "recycle", "pause", "unpause", "wsl_shutdown", "want")

_MAX_FRAMES = 6


def _callers() -> list:
    """Chaine d'appel lisible (module:fonction:ligne), la plus proche d'abord.

    Sans elle on sait qu'une action a eu lieu, pas qui l'a decidee — c'est
    precisement ce qui manquait pendant l'enquete du 2026-07-22.
    """
    out = []
    try:
        import inspect

        for fr in inspect.stack()[2 : 2 + _MAX_FRAMES]:
            mod = Path(fr.filename).name
            if mod == Path(__file__).name:
                continue
            out.append("%s:%s:%d" % (mod, fr.function, fr.lineno))
    except Exception:  # noqa: BLE001 - l'introspection ne doit jamais casser l'appelant
        pass
    return out


def _whoami() -> dict:
    who = {"pid": os.getpid()}
    try:
        who["user"] = os.environ.get("USERNAME") or ""
    except Exception:  # noqa: BLE001
        pass
    try:
        import psutil

        p = psutil.Process(os.getpid())
        who["proc"] = p.name()
        who["cmdline"] = " ".join(p.cmdline())[:220]
        par = p.parent()
        if par:
            who["parent"] = "%s(%d)" % (par.name(), par.pid)
    except Exception:  # noqa: BLE001 - psutil optionnel
        pass
    return who


def record(action: str, reason: str = "", **extra) -> None:
    """Consigne une action Docker. Best-effort absolu, ne leve jamais.

    Docker n'est qu'un DOMAINE du journal de cycle de vie : on delegue a
    forge_lifecycle_audit pour que toutes les actions de Nokido (llm, service,
    ram, container) vivent dans un seul fichier ordonne dans le temps — sinon on
    ne peut pas correler « qui a arrete quoi » entre organes. Repli local si le
    module generique manque, pour ne jamais perdre une trace.
    """
    try:
        from nokido_agent.app.forge_lifecycle_audit import record as _generic

        _generic(action, domain="docker", reason=reason, **extra)
        return
    except Exception:  # muet-ok : un VRAI repli suit immediatement (journal local
        # ci-dessous), donc l'enregistrement n'est pas perdu — seul le canal change.
        # C'est la difference entre un silence qui cache une perte et un silence qui
        # accompagne une bascule. Le repli, LUI, journalise s'il echoue.
        pass
    try:
        rec = {
            "ts": datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds"),
            "domain": "docker",
            "action": str(action),
            "reason": str(reason)[:200],
            "by": _whoami(),
            "callers": _callers(),
        }
        if extra:
            rec["extra"] = {k: str(v)[:200] for k, v in extra.items()}
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001 - jamais fatal, mais jamais muet non plus
        import logging as _lg

        # DERNIER RECOURS. Le canal generique a deja echoue plus haut ; si celui-ci
        # tombe aussi, l'enregistrement d'audit n'existe NULLE PART. « Jamais fatal »
        # ne veut pas dire « sans consequence ».
        _lg.getLogger(__name__).error(
            "[docker_audit] action '%s' NON enregistree, les DEUX canaux ont echoue "
            "(%s: %s) | consequence: cette action docker n'a laisse aucune trace",
            action, type(e).__name__, str(e)[:90])


def tail(n: int = 30) -> list:
    """Dernieres actions Docker consignees (journal generique en priorite)."""
    try:
        from nokido_agent.app.forge_lifecycle_audit import tail as _generic_tail

        rows = _generic_tail(n, domain="docker")
        if rows:
            return rows
    except Exception:  # noqa: BLE001
        pass
    if not LEDGER.exists():
        return []
    try:
        lines = LEDGER.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def _main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    n = 30
    if "--tail" in argv:
        try:
            n = int(argv[argv.index("--tail") + 1])
        except (IndexError, ValueError):
            pass
    rows = tail(n)
    if not rows:
        print("journal vide: %s" % LEDGER)
        print("SILENCE = aucune action Nokido -> si Docker meurt, l'acteur est EXTERNE.")
        return 0
    for r in rows:
        by = r.get("by", {})
        print("%s  %-12s %-28s %s" % (
            r.get("ts", "")[11:23],
            r.get("action", "?"),
            (r.get("reason") or "")[:28],
            " <- ".join(r.get("callers", [])[:3]) or by.get("proc", ""),
        ))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
