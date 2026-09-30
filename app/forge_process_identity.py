"""forge_process_identity.py — signature d'appartenance au hub pour chaque process.

Décision owner 2026-08-21 : ne plus JAMAIS identifier un process du hub par son
nom ou sa cmdline (`ps | grep python` = le piège du 21/08 au soir : un python de
12,7 Go inidentifiable, cmdline invisible cross-compte). Chaque spawn porte :
  - env NOKIDO_HUB_RUN_ID / NOKIDO_SERVICE_ID / NOKIDO_INSTANCE (métadonnées),
  - une ligne au REGISTRE superviseur (pid + start_time = identité non
    réutilisable) — la source d'AUTORITÉ côté Windows, où lire l'env d'un autre
    process exige des privilèges.
Phase 2 prévue : Job Objects Windows (appartenance noyau, kill d'arbre, caps RSS).
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/integrity : signature d'appartenance au hub de chaque process"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import os
import time
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_REG = _ROOT / "sandbox" / "process_registry.jsonl"
_RUN_ID_FILE = _ROOT / "sandbox" / "hub_run_id"
_run_id: str | None = None


def get_hub_run_id() -> str:
    """Identifiant de GÉNÉRATION du hub : stable pour la vie du process,
    régénéré à chaque boot. Écrit dans un fichier pour visibilité externe."""
    global _run_id
    if _run_id:
        return _run_id
    _run_id = os.environ.get("NOKIDO_HUB_RUN_ID") or (
        time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    )
    os.environ["NOKIDO_HUB_RUN_ID"] = _run_id
    try:
        _RUN_ID_FILE.write_text(_run_id, encoding="utf-8")
    except Exception:  # muet-ok : visibilité externe best-effort
        pass
    return _run_id


def stamp_env(env: dict, service_id: str, instance: str = "") -> dict:
    """Pose la signature dans l'env d'un enfant. Retourne env (mutée)."""
    env["NOKIDO_HUB_RUN_ID"] = get_hub_run_id()
    env["NOKIDO_SERVICE_ID"] = service_id
    if instance:
        env["NOKIDO_INSTANCE"] = str(instance)
    return env


def record(pid: int, service_id: str, instance: str = "", extra: dict | None = None) -> None:
    """Inscrit le spawn au registre (append JSONL). pid+start_time = identité."""
    try:
        import psutil
        st = psutil.Process(pid).create_time()
    except Exception:
        st = None
    row = {"pid": pid, "start_time": st, "run_id": get_hub_run_id(),
           "service_id": service_id, "instance": instance,
           "ts": time.time(), **(extra or {})}
    try:
        _REG.parent.mkdir(parents=True, exist_ok=True)
        with _REG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # muet-ok : le registre ne doit jamais faire échouer un spawn
        pass


def identify_process(pid: int) -> dict:
    """Identité d'un pid : registre (autorité) + env quand lisible.
    Un pid réutilisé est démasqué par start_time (tolérance 2 s)."""
    out: dict = {"pid": pid, "known": False}
    try:
        import psutil
        p = psutil.Process(pid)
        out["start_time"] = p.create_time()
        out["name"] = p.name()
        try:
            env = p.environ()
            for k in ("NOKIDO_HUB_RUN_ID", "NOKIDO_SERVICE_ID", "NOKIDO_INSTANCE"):
                if env.get(k):
                    out[k.lower()] = env[k]
        except Exception:  # muet-ok : env cross-compte illisible sous Windows
            pass
    except Exception as e:
        out["error"] = type(e).__name__
        return out
    try:
        if _REG.exists():
            for line in _REG.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("pid") == pid and row.get("start_time") and out.get("start_time") \
                        and abs(row["start_time"] - out["start_time"]) < 2.0:
                    out.update({"known": True, "run_id": row.get("run_id"),
                                "service_id": row.get("service_id"),
                                "instance": row.get("instance")})
    except Exception:  # muet-ok : lecture registre best-effort
        pass
    return out
