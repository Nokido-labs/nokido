#!/usr/bin/env python3
"""forge_cli_version_watch.py — detecte ce qui a BOUGE chez les CLI et leurs docs.

DEMANDE OWNER 2026-08-20 : « a chaque mise a jour de claude je veux que tu check
s'il y a du neuf, pareil pour tous les cli ! », dit juste apres « tu ne sais pas
toi-meme utiliser a 100 % tes capacites ». Le probleme n'est pas qu'une capacite
manque : c'est qu'elle est RECENTE et qu'on l'ignore, donc on continue a
bricoler des contournements pour des fonctions deja livrees.

DEUX SIGNAUX, volontairement independants :
  1. la VERSION du binaire CLI (`<cli> --version`) ;
  2. l'EMPREINTE de l'index `llms.txt` de sa doc (taille + sha256).

Le (2) est le plus fiable : il ne depend d'aucun binaire installe, et une doc
qui change signale une capacite nouvelle meme quand la version n'a pas bouge
(ajout de pages, nouveaux endpoints). Le (1) peut etre NON MESURABLE (binaire
absent, subprocess interdit en sandbox) — dans ce cas on ecrit « non mesure »,
JAMAIS « inchange » : un capteur muet ne doit pas se lire comme un verdict
rassurant (lecon 2026-08-20, la sonde qui rendait '' par abstention).

Etat persiste dans `sandbox/cli_versions.json`. Premier run = pas d'alarme,
on pose la reference.

⚠️ EGRESS : le sandbox offline rend `WinError 10013`. Lancer via
`run_job online=true`, jamais en `action=python` direct.

Usage :
    run_job script=tools/forge_cli_version_watch.py online=true
    run_job script=tools/forge_cli_version_watch.py online=true script_args="--ingest-si-neuf"
"""

from __future__ import annotations

__FORGE_COLOR__ = "vegetatif/watcher : detecte ce qui a bouge chez les CLI et leurs docs"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ETAT = ROOT / "sandbox" / "cli_versions.json"

# (cle, binaire, index llms.txt de la doc, domain RAG)
#
# OWNER 2026-08-20 : « pour chaque constituant tu dois avoir la doc a jour ».
# Ce registre n'est donc PAS limite aux CLI : il couvre les briques dont Nokido
# depend (protocole, superviseur, base vectorielle, calcul deporte, schemas).
# Sonde du jour sur 12 candidats -> 5 constituants publient un `llms.txt` ;
# crawl4ai, searxng, fastapi, sqlite, numpy, astral et playwright n'en ont PAS
# (404 mesure) : ne pas les remettre ici sans re-sonder, sinon on fabrique du
# bruit d'erreur a chaque passage.
CIBLES = [
    # CLI agentiques
    ("claude", "claude", "https://platform.claude.com/llms.txt", "claude_docs"),
    # 2026-09-24 : la doc de Claude Code vit sur un AUTRE site que l'API. L'index
    # platform.claude.com ne la couvrait pas, et la veille n'avait plus tourne depuis
    # le 2026-08-20 : des capacites livrees entre v2.1.2xx et v2.1.281 (fond automatique
    # des appels MCP longs, nettoyage d'env des sous-processus...) sont restees inconnues.
    ("claude_code", None, "https://code.claude.com/docs/llms.txt", "claude_code_docs"),
    ("antigravity", "agy", "https://antigravity.google/llms.txt", "antigravity_docs"),
    ("openai", "codex", "https://developers.openai.com/llms.txt", "openai_docs"),
    ("gemini", "gemini", None, None),
    # Constituants de l'organisme
    ("ollama", "ollama", "https://docs.ollama.com/llms.txt", "ollama_docs"),
    ("mcp", None, "https://modelcontextprotocol.io/llms.txt", "mcp_docs"),
    ("deno", "deno", "https://docs.deno.com/llms.txt", "deno_docs"),
    ("qdrant", None, "https://qdrant.tech/llms.txt", "qdrant_docs"),
    ("modal", "modal", "https://modal.com/docs/llms.txt", "modal_docs"),
    ("pydantic", None, "https://docs.pydantic.dev/llms.txt", "pydantic_docs"),
]


def version_binaire(exe: str) -> str:
    """Version du CLI, ou un motif de NON-MESURE explicite (jamais 'inchange')."""
    chemin = shutil.which(exe)
    if not chemin:
        return "non mesure: binaire absent du PATH"
    try:
        r = subprocess.run([chemin, "--version"], capture_output=True, text=True,
                           timeout=20, errors="replace")
        out = (r.stdout or r.stderr or "").strip().splitlines()
        return out[0][:120] if out else "non mesure: sortie vide"
    except Exception as e:  # noqa: BLE001
        return "non mesure: %s" % type(e).__name__


def empreinte_doc(url: str) -> dict:
    try:
        rq = urllib.request.Request(url, headers={"User-Agent": "Nokido-cli-watch/1.0"})
        with urllib.request.urlopen(rq, timeout=25) as r:
            b = r.read()
        return {"octets": len(b), "sha256": hashlib.sha256(b).hexdigest()[:16],
                "pages": b.decode("utf-8", "replace").count("](http")}
    except Exception as e:  # noqa: BLE001
        return {"erreur": "%s: %s" % (type(e).__name__, str(e)[:60])}


def charger() -> dict:
    try:
        return json.loads(ETAT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Veille des versions CLI + docs")
    ap.add_argument("--ingest-si-neuf", action="store_true",
                    help="relance forge_ingest_llms_txt pour chaque doc qui a change")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    avant = charger()
    apres: dict = {}
    changements: list[str] = []
    premier = not avant

    for cle, exe, url, domain in CIBLES:
        cur = {"version": version_binaire(exe) if exe else "n/a: pas un binaire"}
        if url:
            cur["doc"] = empreinte_doc(url)
            cur["doc_url"] = url
            cur["domain"] = domain
        apres[cle] = cur
        old = avant.get(cle) or {}

        ov, nv = old.get("version"), cur["version"]
        if ov and ov != nv and not nv.startswith("non mesure"):
            changements.append("%s: VERSION %r -> %r" % (cle, ov, nv))

        od, nd = (old.get("doc") or {}), (cur.get("doc") or {})
        if od.get("sha256") and nd.get("sha256") and od["sha256"] != nd["sha256"]:
            changements.append(
                "%s: DOC changee (%s -> %s, %d -> %d pages)"
                % (cle, od["sha256"], nd["sha256"], od.get("pages", 0), nd.get("pages", 0)))

    apres["_ts"] = datetime.now(timezone.utc).isoformat()
    rapport = {"premier_run": premier, "changements": changements,
               "cibles": {k: v for k, v in apres.items() if k != "_ts"}}
    print(json.dumps(rapport, ensure_ascii=False, indent=2), flush=True)

    if not a.dry_run:
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        ETAT.write_text(json.dumps(apres, ensure_ascii=False, indent=2), encoding="utf-8")

    if a.ingest_si_neuf and changements and not premier:
        for cle, _exe, url, domain in CIBLES:
            if not url or not any(c.startswith(cle + ": DOC") for c in changements):
                continue
            print("[reingest] %s -> %s" % (cle, domain), flush=True)
            r = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "forge_ingest_llms_txt.py"),
                 "--url", url, "--domain", domain, "--pause", "0.15"],
                capture_output=True, text=True, errors="replace", timeout=3600)
            print((r.stdout or "")[-600:], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
