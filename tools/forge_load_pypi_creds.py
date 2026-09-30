#!/usr/bin/env python3
"""forge_load_pypi_creds.py — charge les tokens PyPI/TestPyPI au coffre DPAPI.

Lit le bloc format .pypirc (`[testpypi]` / `[pypi]`) de `Nokido.env` (gitignored)
et stocke les tokens sous `TESTPYPI_TOKEN` / `PYPI_TOKEN` via `forge_secrets`
(coffre machine_vault, scope machine). Ne relit ni n'affiche JAMAIS les valeurs.

À lancer en `trusted_script` : le coffre `data/machine_vault.dat` appartient à
l'owner ; le user sandbox/hub ne peut pas l'écrire (ACL). LaForgeTrusted, oui.

Usage :
    (hub) run action=trusted_script path=tools/forge_load_pypi_creds.py
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/secret : charge les tokens PyPI au coffre DPAPI"  # organe declare le 2026-09-06 (audit de raccordement)

import configparser
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
from nokido_agent.app import forge_secrets


def _pypirc_block(lines: list[str]) -> str:
    """Isole les lignes des sections pypirc ([testpypi]/[pypi]) — ignore les KEY=VALUE env."""
    out: list[str] = []
    keep = False
    for ln in lines:
        s = ln.strip()
        if s in ("[testpypi]", "[pypi]"):
            keep = True
            out.append(ln)
        elif s.startswith("[") and s.endswith("]"):
            keep = False
        elif keep and " = " in ln:   # entree pypirc (key = value), pas un KEY=VALUE env
            out.append(ln)
    return "\n".join(out)


def load(env_path: Path | None = None) -> list[str]:
    env_path = env_path or (_ROOT / "Nokido.env")
    lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
    cp = configparser.ConfigParser()
    cp.read_string(_pypirc_block(lines))
    pairs = {
        "TESTPYPI_TOKEN": cp.get("testpypi", "password", fallback=""),
        "PYPI_TOKEN": cp.get("pypi", "password", fallback=""),
    }
    stored: list[str] = []
    for k, v in pairs.items():
        if not v:
            print(f"{k}: source vide")
            continue
        ok = forge_secrets.set_secret(k, v)
        stored.append(k)
        print(f"{k} -> vault ok={bool(ok)} (len={len(v)})")
    for k in stored:
        try:
            got = forge_secrets.get_secret(k)
        except Exception as e:  # noqa: BLE001 — relecture best-effort
            got = None
            print(f"relecture {k}: ERREUR {type(e).__name__}")
        print(f"relecture {k}: {'OK' if got else 'VIDE'}")
    return stored


if __name__ == "__main__":
    s = load()
    print("STORED:", s)
    raise SystemExit(0 if s else 1)
