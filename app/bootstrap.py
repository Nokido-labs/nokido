from __future__ import annotations
from nokido_agent.app.forge_secrets import get_secret

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_batch_bootstrap_stderr_fix
#FORGE:[score:85|agent:claude-mcp|temp:0.00|risk:0.10|ast:OK|test:OK|lint:OK|color:GREEN|attempt:2]
CONTRAINTE: rediriger prints bootstrap sur stderr pour ne pas polluer le canal MCP stdio JSON-RPC
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:85|agent:claude-mcp|temp:0.00|risk:0.10|ast:OK|test:OK|lint:OK|color:GREEN|attempt:2]"
"""
bootstrap.py — Contexte Nokido pré-chargé
===========================================
Appelé via : python -m bootstrap <script_ou_code>

Pré-charge l'environnement Nokido UNE SEULE FOIS :
  - sys.path
  - os.environ depuis Nokido.env
  - ROOT, DB_PATH, SANDBOX
  - forge_state (mmap)
  - Logging configuré

Élimine le overhead de re-import sys/pathlib/subprocess
à chaque action=python du MCP.

Usage interne Hub/MCP :
  exec(code, BOOTSTRAP_GLOBALS)

FIX 2026-04-24: tous les prints [bootstrap] sont rediriges sur stderr
via _blog() helper. Cela evite de polluer le canal MCP stdio JSON-RPC
quand forge_runner.py (qui importe bootstrap) est lui-meme importe par
le serveur MCP STDIO. Symptome avant fix: 'Unexpected token b, [bootstrap]
is not valid JSON' dans Claude Desktop au premier appel outil.
"""


import os
import sys
import logging
from pathlib import Path


def _blog(msg: str) -> None:
    """Bootstrap log : toujours sur stderr pour ne pas polluer stdout MCP."""
    print(msg, file=sys.stderr, flush=True)


# ── Racine projet ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
SANDBOX = ROOT / "sandbox"
DB_PATH = str(ROOT / "RAG" / "embeddings.db")

# ── sys.path ──────────────────────────────────────────────────────────────────
for _p in [str(APP_DIR), str(ROOT / "tools")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Secrets : NOMS dans Nokido.env, VALEURS au coffre (decision owner 2026-10-01) ──
# Ce bloc recopiait le fichier EN CLAIR dans os.environ (herite par chaque enfant). Le .env
# ne sert qu'a faire entrer un secret au coffre : tools/forge_env_to_vault.py.
try:
    from nokido_agent.app.forge_secrets import injecter_env_depuis_coffre as _injecter

    _bilan_coffre = _injecter(ROOT / "Nokido.env")
    if _bilan_coffre["absentes"] or _bilan_coffre["illisibles"]:
        print("[secrets] absents du coffre : %s ; illisibles : %s -> forge_env_to_vault"
              % (_bilan_coffre["absentes"], _bilan_coffre["illisibles"]), flush=True)
except Exception as _e_coffre:  # noqa: BLE001 - dit, jamais avale
    print("[secrets] coffre indisponible (%s) : aucun secret injecte depuis Nokido.env"
          % type(_e_coffre).__name__, flush=True)

# ── Logging ───────────────────────────────────────────────────────────────────
# Convention UNIQUE d'horodatage : forge_timecode (UTC, ISO-8601, ms, suffixe Z).
# MESURE 2026-07-26 : 109 modules définissaient chacun leur format. 101 d'entre
# eux n'appellent que `logging.basicConfig`, qui est un NO-OP dès que la racine
# porte déjà un handler (vérifié en direct) — configurer la racine ICI les fait
# donc adopter la convention sans éditer une seule de leurs lignes. Les 8 autres
# posent leur propre handler et se traitent un par un.
try:
    from nokido_agent.app.forge_timecode import configure_logging as _configure_logging

    _configure_logging(level=logging.WARNING)
except Exception:  # noqa: BLE001 - le socle ne doit jamais casser sur son logger
    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

# ── Imports communs pré-chargés ───────────────────────────────────────────────
import json
import sqlite3
import threading
import subprocess
import time

# ── forge_state (mmap) ───────────────────────────────────────────────────────
try:
    from nokido_agent.app.forge_state import state
except Exception:
    state = None

# DEBUG_REVIVE_REGISTRY: brancher ForgeRegistry singleton (2026-04-16)
# Avant : reg = _g("_forge_registry") retournait None -> persistance silencieusement morte
# Apres : singleton charge depuis data/forge_registry.json + expose sur __main__
try:
    from nokido_agent.app.forge_registry import ForgeRegistry as _ForgeRegistry

    forge_registry_instance = _ForgeRegistry().load()
    # Patch sur __main__ pour que get_app_attr("_forge_registry") le trouve
    _main_mod = sys.modules.get("__main__")
    if _main_mod is not None:
        _main_mod._forge_registry = forge_registry_instance
    _blog(f"[bootstrap] ForgeRegistry singleton charge: {forge_registry_instance.summary()}")
except Exception as _e:
    forge_registry_instance = None
    _blog(f"[bootstrap] ForgeRegistry init echoue: {_e}")

# DEBUG_REVIVE_IDLE: brancher IdleWatchdog (2026-04-16)
# Arret automatique du serveur MCP si inactif au-dela de LAFORGE_IDLE_TIMEOUT
try:
    from nokido_agent.app.forge_idle_watchdog import IdleWatchdog as _IdleWatchdog

    idle_watchdog_instance = _IdleWatchdog(
        service_name="NokidoMCP",
        idle_timeout=int(os.environ.get("LAFORGE_IDLE_TIMEOUT", "0")),  # 0 = desactive par defaut
        check_interval=60,
    )
    idle_watchdog_instance.start()
    # Patch sur __main__ pour que les handlers puissent .ping() apres chaque action
    _main_mod_iw = sys.modules.get("__main__")
    if _main_mod_iw is not None:
        _main_mod_iw._idle_watchdog = idle_watchdog_instance
    if idle_watchdog_instance._enabled:
        _blog(f"[bootstrap] IdleWatchdog actif (timeout={idle_watchdog_instance.idle_timeout}s)")
    else:
        _blog("[bootstrap] IdleWatchdog disponible mais inactif (LAFORGE_IDLE_TIMEOUT=0)")
except Exception as _e:
    idle_watchdog_instance = None
    _blog(f"[bootstrap] IdleWatchdog init echoue: {_e}")

# DEBUG_REVIVE_PB: PromptBuilder disponible (2026-04-16)
# Permet codegen enrichi (bugfix/docstring/refactor) avec contexte RAG
try:
    from nokido_agent.app.forge_prompt_builder import PromptBuilder as _PromptBuilder

    prompt_builder_instance = _PromptBuilder()
    _blog(f"[bootstrap] PromptBuilder pret: {prompt_builder_instance}")
except Exception as _e:
    prompt_builder_instance = None
    _blog(f"[bootstrap] PromptBuilder init echoue: {_e}")

# DEBUG_REVIVE_4MORE: 4 modules supplementaires exposes (2026-04-16)
# cascade_oracle: decision S1/S2 BM25+CrossEncoder
try:
    from nokido_agent.app.forge_cascade_oracle import CascadeOracle as _CascadeOracle

    cascade_oracle_instance = _CascadeOracle(tau=-4.0, lazy_load=True)
    _blog("[bootstrap] CascadeOracle pret (lazy CE)")
except Exception as _e:
    cascade_oracle_instance = None
    _blog(f"[bootstrap] CascadeOracle init echoue: {_e}")

# safe_integration: verification post-@loop (12 funcs)
try:
    from nokido_agent.app import forge_safe_integration as _safe_integration

    _blog("[bootstrap] forge_safe_integration disponible")
except Exception as _e:
    _safe_integration = None
    _blog(f"[bootstrap] forge_safe_integration import echoue: {_e}")

# Capacité déportée (lab borné) : chargée SEULEMENT si le lab est explicitement
# activé (NOKIDO_REDTEAM_INTENTS_JSON). Sinon le cœur n'importe pas le module et
# _sanitizer_analyst reste None. Gel, pas suppression.
_sanitizer_analyst = None
if os.environ.get("NOKIDO_REDTEAM_INTENTS_JSON"):
    try:
        # Corps déporté PHYSIQUEMENT hors du cœur (dépôt privé laforge-redteam,
        # dossier redteam/laforge_redteam/ sibling du superrepo). Import nu depuis
        # ce home, jamais depuis nokido_agent.app (le module n'y est plus). Absent
        # du checkout (dépôt séparé, gitignore) -> import échoue -> _sanitizer_analyst
        # reste None : c'est l'état voulu quand le lab n'est pas déployé localement.
        import sys as _sys
        import pathlib as _pl

        _rtd = os.environ.get("LAFORGE_REDTEAM_DIR") or str(
            _pl.Path(__file__).resolve().parents[2] / "redteam" / "laforge_redteam"
        )
        if os.path.isdir(_rtd) and _rtd not in _sys.path:
            _sys.path.insert(0, _rtd)
        import forge_sanitizer_analyst as _sanitizer_analyst

        _blog("[bootstrap] capacité déportée du lab chargée (lab actif, home redteam)")
    except Exception as _e:
        _sanitizer_analyst = None
        _blog(f"[bootstrap] capacité déportée du lab import echoue: {_e}")

# trauma_vault: memoire echecs STDP (lie a error_learning)
try:
    from nokido_agent.app import forge_trauma_vault as _trauma_vault

    _blog("[bootstrap] forge_trauma_vault disponible")
except Exception as _e:
    _trauma_vault = None
    _blog(f"[bootstrap] forge_trauma_vault import echoue: {_e}")

# DEBUG_REVIVE_DEFER: 2 modules DEFER ressuscites (2026-04-16)
# vec_ledger: audit crypto SHA256+HMAC sur embeddings
try:
    from nokido_agent.app import forge_vec_ledger as _vec_ledger

    _blog("[bootstrap] forge_vec_ledger disponible (audit crypto)")
except Exception as _e:
    _vec_ledger = None
    _blog(f"[bootstrap] forge_vec_ledger import echoue: {_e}")

# noise_inject: anti-fingerprinting cloud (complement sovereign_mapper)
try:
    from nokido_agent.app import forge_noise_inject as _noise_inject

    _blog("[bootstrap] forge_noise_inject disponible (anti-fingerprint)")
except Exception as _e:
    _noise_inject = None
    _blog(f"[bootstrap] forge_noise_inject import echoue: {_e}")

# DEBUG_REVIVE_INTEGRITY: brancher IntegrityManager + token DEV (2026-04-16)
# Capability tokens HMAC pour securite par rings (MASTER/SYSTEM/DEV/TRUSTED/COLLAB/UNTRUSTED)
try:
    from nokido_agent.app.forge_integrity import IntegrityManager as _IM, IntegrityRing as _IR

    _secret_iam = get_secret("MCP_DEV_SECRET") or ""
    if not _secret_iam:
        raise RuntimeError("MCP_DEV_SECRET vide dans Nokido.env")
    integrity_manager_instance = _IM(_secret_iam)
    # Creer un token DEV pour Claude (8h TTL, scopes complets DEV)
    claude_dev_token = integrity_manager_instance.create_manifest(
        "claude-mcp",
        _IR.DEV,
        scopes={
            "fs": ["read", "write", "exec"],
            "rag": ["query", "ingest", "admin"],
            "sql": ["read"],
            "tasks": ["claim", "result", "create", "review"],
            "system": ["audit_view", "sentinel_bypass"],
        },
        duration_s=8 * 3600,
    )
    # Patch sur __main__ pour les handlers
    _main_iam = sys.modules.get("__main__")
    if _main_iam is not None:
        _main_iam._integrity_manager = integrity_manager_instance
        _main_iam._claude_dev_token = claude_dev_token
    _blog("[bootstrap] IntegrityManager actif + token DEV claude-mcp (TTL 8h)")
except Exception as _e:
    integrity_manager_instance = None
    claude_dev_token = None
    _blog(f"[bootstrap] IntegrityManager init echoue: {_e}")

# ── Globals exposés aux scripts exec() ───────────────────────────────────────
BOOTSTRAP_GLOBALS = {
    "__builtins__": __import__("builtins"),
    "ROOT": ROOT,
    "APP_DIR": APP_DIR,
    "SANDBOX": SANDBOX,
    "DB_PATH": DB_PATH,
    "Path": Path,
    "os": os,
    "sys": sys,
    "json": json,
    "sqlite3": sqlite3,
    "threading": threading,
    "subprocess": subprocess,
    "time": time,
    "state": state,
    "logging": logging,
    # DEBUG_REVIVE_REGISTRY: registry accessible depuis exec() MCP
    "forge_registry_instance": forge_registry_instance,
    # DEBUG_REVIVE_PB: prompt builder pour codegen enrichi
    "prompt_builder_instance": prompt_builder_instance,
    # DEBUG_REVIVE_4MORE: oracle + 3 modules importes
    "cascade_oracle_instance": cascade_oracle_instance,
    "forge_safe_integration": _safe_integration,
    "forge_sanitizer_analyst": _sanitizer_analyst,
    "forge_trauma_vault": _trauma_vault,
    # DEBUG_REVIVE_DEFER: 2 modules DEFER ressuscites
    "forge_vec_ledger": _vec_ledger,
    "forge_noise_inject": _noise_inject,
    # DEBUG_REVIVE_INTEGRITY: capability tokens
    "integrity_manager_instance": integrity_manager_instance,
    "claude_dev_token": claude_dev_token,
}


def run_code(code: str) -> str:
    """
    Exécute du code Python dans le contexte bootstrap.
    Capture stdout/stderr pour ne JAMAIS polluer le canal stdio JSON-RPC.
    Retourne str(result) ou captured output ou code d'erreur compact.
    """
    import io as _io

    # SESSION_STICKY_NS_V1 — namespace persistant entre appels MCP
    if "_SESSION_NS" not in BOOTSTRAP_GLOBALS:
        BOOTSTRAP_GLOBALS["_SESSION_NS"] = {}
    loc = BOOTSTRAP_GLOBALS["_SESSION_NS"]
    _old_stdout = sys.stdout
    _old_stderr = sys.stderr
    _cap = _io.StringIO()
    try:
        sys.stdout = _cap
        sys.stderr = _cap
        loc.pop("result", None)  # reset result avant exec
        exec(code, BOOTSTRAP_GLOBALS, loc)
        sys.stdout = _old_stdout
        sys.stderr = _old_stderr
        captured = _cap.getvalue()
        # Priorité: stdout capturé > variable result explicite
        if captured.strip():
            out = captured.strip()
            # Tronquer si > 3500 chars pour éviter buffer overflow MCP
            if len(out) > 3500:
                out = out[:3500] + "\n...[tronqué]"
            return out
        result_val = loc.get("result", None)
        if result_val is not None:
            out = str(result_val)
            return out[:3500] + "...[tronqué]" if len(out) > 3500 else out
        return "OK"
    except Exception as e:
        sys.stdout = _old_stdout
        sys.stderr = _old_stderr
        return f"ERR:{type(e).__name__}:{str(e)[:120]}"


def run_file(path: str) -> str:
    """Exécute un fichier .py dans le contexte bootstrap."""
    src = Path(path).read_text(encoding="utf-8")
    return run_code(src)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m bootstrap <file.py|--code 'code'>")
        sys.exit(1)
    if sys.argv[1] == "--code":
        print(run_code(" ".join(sys.argv[2:])))
    else:
        print(run_file(sys.argv[1]))
