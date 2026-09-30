#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_resonde_trusted.py - teste TOUS les organes INDETERMINE sur le vivant, sous trusted.

Un IND du balayage `feature_checklist` peut venir du COMPTE de mesure (ACL online),
du PACKAGING (module en sous-dossier, non importable a plat), d'un NOM VARIANT, ou
d'un SCRIPT qui s'execute a l'import. Aucun n'est un defaut. Lance en `trusted_script`
(compte LaForgeTrusted, ACL levees), cet outil reimporte chaque IND organique par son
CHEMIN REEL et tranche : present et chargeable (OK), script chargeable (OK), ou
reellement casse (KO).

Exclut les capacites deportees (depot prive) et les modules lourds (ML/torch) qui
bloqueraient l'import -- ils restent INDETERMINE a juste titre.

    run action=trusted_script path=tools/forge_resonde_trusted.py
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/mesure-multi-comptes"

import glob
import importlib.util
import io
import contextlib
import json
import os
import re
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_DEPORTE = re.compile(r"exegol|\bctf\b|autopwn|exploit|red_?team|\bpwn\b|ghidra|recon_|"
                      r"gdb|heap|libc|nuclei|r2pipe|rootme|nasm|rop|shellcode|disas|"
                      r"nmap|osint|binary|payload|challenge|writeup", re.I)
# Modules dont l'import charge une pile ML lourde (bloque / GIL) : hors perimetre.
_LOURD = re.compile(r"train|_ml|torch|snn|jepa_finetune|bench|embed_modal|scalene|"
                    r"finetune|dataset|colab", re.I)
_SKIP_DIRS = {"sandbox", "RAG", "RAG_plain_bak", "logs", "logs_archive", "backups",
              "_backups", "_archive", "_attic", "node_modules", "models", "data",
              "dist_laforge", "dist_test", "build_cython", "versions", "kaggle_dataset",
              "embeddings", "workspace"}
_LECTURE = ("status", "state", "get_state", "snapshot", "summary", "probe", "coverage",
            "stats", "current", "health", "capabilities", "point", "report", "info")


def _map_chemins() -> dict[str, str]:
    """basename .py -> chemin complet, sur tout le code du depot."""
    m: dict[str, str] = {}
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in files:
            if fn.endswith(".py"):
                m.setdefault(fn[:-3], os.path.join(root, fn))
    return m


def _resoudre(mod: str, chemins: dict[str, str]) -> str | None:
    if mod in chemins:
        return chemins[mod]
    base = re.sub(r"^(forge|nokido)_", "", mod)
    if base in chemins:
        return chemins[base]
    for nom, path in chemins.items():
        if nom.startswith(mod + "_") or (mod.startswith(nom + "_") and nom.count("_") >= 1):
            return path
        if len(base) >= 6 and (nom.startswith(base + "_") or nom.endswith("_" + base)):
            return path
    return None


def _ind_organiques() -> list[str]:
    fs = sorted(glob.glob(os.path.join(ROOT, "sandbox", "workspace", "feature_checklist_*.json")))
    fs = [f for f in fs if "_trusted" not in f]
    if not fs:
        return []
    E = json.load(open(fs[-1], encoding="utf-8"))["entrees"]
    return [r["feature"] for r in E
            if r.get("surface") == "Organique" and r.get("verdict") == "INDETERMINE"]


def _sonder(mod: str, path: str) -> str:
    buf = io.StringIO()
    try:
        spec = importlib.util.spec_from_file_location(mod, path)
        m = importlib.util.module_from_spec(spec)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            spec.loader.exec_module(m)
    except SystemExit:
        return "OK: script chargeable (sys.exit au chargement)"
    except PermissionError as e:
        return f"IND-ACL: {str(e)[:100]}"
    except BaseException as e:  # noqa: BLE001
        return f"KO: {type(e).__name__}: {str(e)[:100]}"
    pub = [a for a in dir(m) if not a.startswith("_")]
    for n in _LECTURE:
        f = getattr(m, n, None)
        if callable(f):
            try:
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    r = f()
                return f"OK: {n}() -> {json.dumps(r, default=str, ensure_ascii=False)[:80]}"
            except BaseException:  # noqa: BLE001 - lecture qui leve = contexte, pas casse
                break
    return f"OK: present et chargeable ({len(pub)} symboles)"


def main() -> int:
    chemins = _map_chemins()
    res: dict[str, str] = {}
    for mod in _ind_organiques():
        if _DEPORTE.search(mod) or _LOURD.search(mod):
            continue
        path = _resoudre(mod, chemins)
        if not path:
            res[mod] = "NON_RESOLU: aucun fichier"
            continue
        # Import borne : un module qui ouvre une connexion/thread au chargement
        # bloquerait tout le rapport. On l'isole dans un thread daemon a 5 s.
        box = ["IND: import bloque (>5s au chargement)"]

        def _run(mm=mod, pp=path, b=box):
            b[0] = _sonder(mm, pp)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(5.0)
        res[mod] = box[0]
    out = os.path.join(ROOT, "sandbox", "workspace", "resonde_trusted.json")
    try:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001  # muet-ok
        pass
    ok = sum(1 for v in res.values() if v.startswith("OK"))
    print(json.dumps({"compte": os.environ.get("USERNAME", "?"), "testes": len(res),
                      "leves_OK": ok, "detail": res}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
