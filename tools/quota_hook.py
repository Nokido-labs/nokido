#!/usr/bin/env python3
"""
quota_hook.py v3 — Hook SessionStart Gemini CLI
================================================
Au boot : Gemini rapporte son état quota via hub notify,
puis injecte le contexte dans GEMINI.md projet.

Le quota RÉEL vient de Gemini CLI lui-même (/model).
On ne peut pas le lire par fichier — Gemini doit le reporter.
"""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
# --- amorce namespace (point d'entree) : la RACINE avant tout import nokido_agent,
# sinon ModuleNotFoundError quand ce fichier est lance par son chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
from nokido_agent.app.forge_secrets import get_secret

ROOT = Path(__file__).resolve().parent.parent
HUB = "http://127.0.0.1:8766/mcp"
# SECURITY 2026-05-02 : hardcoded fallback token removed.
TOKEN = get_secret("FORGE_MCP_TOKEN") or ""
if not TOKEN:
    print("[quota_hook] WARN: FORGE_MCP_TOKEN env not set.", file=sys.stderr)
GEMINI_MD = ROOT / "GEMINI.md"
QUOTA_DB = ROOT / "RAG" / "quota_state.json"
sys.path.insert(0, str(ROOT))


def hub_call(name, args):
    try:
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": args},
            }
        ).encode()
        req = urllib.request.Request(
            HUB,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {TOKEN}",
                "X-Agent-Name": "GEMINI_HOOK",
            },
            method="POST",
        )
        return json.loads(urllib.request.urlopen(req, timeout=5).read())["result"]["content"][0][
            "text"
        ]
    except Exception as e:
        return f"ERR:{e}"


def read_quota_state() -> dict:
    """Lit le dernier état quota reporté par Gemini."""
    if QUOTA_DB.exists():
        try:
            return json.loads(QUOTA_DB.read_text(encoding="utf-8"))
        except:
            pass
    return {}


def get_best_available(quota_state: dict) -> str:
    """
    Choisit le meilleur modèle disponible selon quota reporté.
    Règle : inconnu = disponible (optimiste). Connu >= 80% = épuisé.
    Ordre : meilleur modèle d'abord.
    """
    candidates = [
        ("gemini-3.1-pro-preview", quota_state.get("preview_pro")),
        ("gemini-2.5-pro", quota_state.get("pro")),
        ("gemini-3.1-flash-lite-preview", quota_state.get("preview_lite")),
        ("gemini-2.5-flash", quota_state.get("flash")),
        ("gemini-2.5-flash-lite", quota_state.get("flash_lite")),
    ]
    for model, pct in candidates:
        if pct is None or pct < 80:  # inconnu = disponible
            return model
    return "gemini-2.5-flash-lite"


def get_rag_filters() -> str:
    """Retourne des query refs compactes — pas de texte long, juste les accès."""
    return """**🔎 CONTEXTE NOKIDO (lazy-load) :**
  known_issues  → `query sql="SELECT id,SUBSTR(text,1,80) FROM rag_chunks WHERE domain='known_issues'"`
  policy_rules  → `query sql="SELECT id,SUBSTR(text,1,80) FROM rag_chunks WHERE domain='policy_rules'"`
  snapshot      → `query sql="SELECT text FROM rag_chunks WHERE id='snapshot_20260429'"`"""


# 1. Lire état quota précédent
quota_state = read_quota_state()
# Reset quotidien des compteurs si la date a changé
if quota_state.get("ts", "").split("T")[0] != datetime.now().strftime("%Y-%m-%d"):
    for k in list(quota_state.keys()):
        if k.startswith("tokens_"):
            quota_state[k] = 0
    quota_state["ts"] = datetime.now().isoformat()
model = get_best_available(quota_state)

# 2. Lire messages hub en attente
msgs = hub_call("hub", {"action": "poll"})
pending = "" if not msgs or msgs == "Aucune notification." else msgs[:500]

# 3. Construire BOOT CONTEXT dans GEMINI.md
ts = datetime.now().strftime("%Y-%m-%d %H:%M")
session_id = f"gemini_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
os.environ["X_SESSION_ID"] = session_id
os.environ["X_AGENT_NAME"] = "GEMINI"
lines = [
    f"## BOOT CONTEXT — {ts}",
    "",
    f"**Modèle recommandé :** `{model}`",
    f"**Session ID :** `{session_id}`",
]

if quota_state:
    lines += [
        "",
        "**État quota (reporté session précédente) :**",
        f"  Flash      : {quota_state.get('flash', '?')}%",
        f"  Flash-Lite : {quota_state.get('flash_lite', '?')}%",
        f"  Pro 2.5    : {quota_state.get('pro', '?')}%",
        f"  Pro 3.1    : {quota_state.get('preview_pro', '?')}%  ← pool séparé",
    ]
else:
    lines += ["", "**Quota :** état inconnu — fais `/model` pour voir les vrais %"]

if pending:
    lines += ["", "**Messages en attente :**", "```", pending[:300], "```"]

rag_section = get_rag_filters()
if rag_section:
    lines += ["", rag_section]

lines += [
    "",
    "**Actions OBLIGATOIRES au boot :**",
    "1. `/model` → noter les % réels → `hub action=quota_report flash=X flash_lite=Y pro=Z preview_pro=W`",
    "2. Appliquer le bon modèle selon les vrais %",
    "3. Lire les messages en attente ci-dessus",
    "",
    "---",
    "",
]

boot_section = "\n".join(lines)
current = GEMINI_MD.read_text(encoding="utf-8") if GEMINI_MD.exists() else ""
current = re.sub(r"## BOOT CONTEXT.*?---\n", "", current, flags=re.DOTALL)
GEMINI_MD.write_text(boot_section + current, encoding="utf-8")

# 4. Notifier hub
hub_call(
    "hub",
    {
        "action": "notify",
        "message": f"[GEMINI][BOOT] modele_recommande={model} quota_state={quota_state}",
    },
)

print(f"[hook] OK model={model} quota={quota_state}")
