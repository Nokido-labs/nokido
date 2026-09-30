# -*- coding: utf-8 -*-
# __FORGE_COLOR__ = "lifecycle-audit-trail"
"""forge_lifecycle_audit — journal UNIQUE des actions de cycle de vie de Nokido.

Generalisation du journal Docker (2026-07-22). Le probleme n'etait pas propre a
Docker : plusieurs organes peuvent demarrer, arreter, tuer ou evincer une charge
(keepers, homeostat, resource_manager, superviseur, monitors), et AUCUN ne
laissait de signature. Diagnostiquer « qui a arrete ca ? » imposait alors une
enquete complete par elimination — c'est ce qui a coute une session entiere.

Invariant vise : **toute action qui change l'etat de vie d'une charge laisse une
trace horodatee et attribuee**. Deux proprietes en decoulent :

  1. On lit l'AUTEUR (chaine module:fonction:ligne), pas seulement l'effet.
  2. Le SILENCE devient une preuve : une charge qui meurt sans entree ici a ete
     tuee par un acteur EXTERNE a Nokido (l'OS, l'editeur du logiciel, l'humain).

Domaines : docker, llm (ollama/llamacpp/lmstudio), service (superviseur), ram
(evictions), container, wsl. Ajouter un domaine = passer une chaine, rien a
declarer.

Ne leve JAMAIS : un journal qui casse son appelant serait pire que pas de journal.

Usage (une ligne au point d'entree) :
    from forge_lifecycle_audit import record
    record("stop", domain="llm", reason="reclaim RAM", target="llama-server:8091")

Lecture :
    LAFORGE_PYTHON app/forge_lifecycle_audit.py                 # 30 dernieres
    LAFORGE_PYTHON app/forge_lifecycle_audit.py --domain docker
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "sandbox" / "lifecycle_actions.jsonl"

ACTIONS = ("start", "stop", "kill", "recycle", "pause", "unpause", "evict",
           "wsl_shutdown", "want", "restart")
DOMAINS = ("docker", "llm", "service", "ram", "container", "wsl", "other")

_MAX_FRAMES = 6


def _callers() -> list:
    """Chaine d'appel lisible (module:fonction:ligne), la plus proche d'abord."""
    out = []
    try:
        import inspect

        for fr in inspect.stack()[2 : 2 + _MAX_FRAMES]:
            mod = Path(fr.filename).name
            if mod == Path(__file__).name or mod == "forge_docker_audit.py":
                continue  # ne pas polluer avec les couches du journal lui-meme
            out.append("%s:%s:%d" % (mod, fr.function, fr.lineno))
    except Exception:  # noqa: BLE001
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


def record(action: str, domain: str = "other", reason: str = "", **extra) -> None:
    """Consigne une action de cycle de vie. Best-effort absolu, ne leve jamais."""
    try:
        rec = {
            "ts": datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds"),
            "domain": str(domain),
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
    except Exception as exc:  # noqa: BLE001 - jamais fatal
        # Panne d'audit INVISIBLE = organe muet qui ignore qu'il est muet
        # (mesure 22-23/07 : ~20h de silence, enquete Docker menee a l'aveugle).
        # Ce puits d'erreur est le seul temoin possible ; best-effort lui aussi.
        try:
            _err = LEDGER.parent / "lifecycle_audit_errors.log"
            with _err.open("a", encoding="utf-8") as f:
                f.write("%s record(%s/%s) FAILED: %r\n" % (
                    datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
                    domain, action, exc))
        except Exception:  # noqa: BLE001
            pass


def tail(n: int = 30, domain: str = "") -> list:
    """Dernieres actions consignees, filtrables par domaine."""
    if not LEDGER.exists():
        return []
    try:
        lines = LEDGER.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if domain and r.get("domain") != domain:
            continue
        out.append(r)
    return out[-n:]


def _main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    n, dom = 30, ""
    if "--tail" in argv:
        try:
            n = int(argv[argv.index("--tail") + 1])
        except (IndexError, ValueError):
            pass
    if "--domain" in argv:
        try:
            dom = argv[argv.index("--domain") + 1]
        except IndexError:
            pass
    rows = tail(n, dom)
    if not rows:
        print("journal vide: %s" % LEDGER)
        print("SILENCE = aucune action Nokido -> une charge qui meurt a un acteur EXTERNE.")
        return 0
    for r in rows:
        print("%s  %-8s %-11s %-26s %s" % (
            r.get("ts", "")[11:23],
            r.get("domain", "?"),
            r.get("action", "?"),
            (r.get("reason") or "")[:26],
            " <- ".join(r.get("callers", [])[:2]) or r.get("by", {}).get("proc", ""),
        ))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
