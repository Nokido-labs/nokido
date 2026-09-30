"""nokido_cutover_verify.py — GATE de securite du rename protege.

Compte deux familles de tokens sur un --root :
  - KEEP : strings fonctionnels couples a l'etat externe NON renomme (env NSSM,
    conteneurs docker, taches, logs, RBAC, id-mcp). DOIVENT rester CONSTANTS avant
    et apres le rename protege. Si un count baisse -> la protection KEEP est
    incomplete -> STOP, ne pas appliquer sur le live.
  - RESIDUAL : traces qui DOIVENT disparaitre (imports laforge, refs module). Apres
    rename ~0 (hors le bruit des domaines DB, renommes en lockstep).

Usage : nokido_cutover_verify.py --root <ABS path du tree a auditer>
"""

__FORGE_COLOR__ = "qualite/quality : gate de securite du rename protege (tokens KEEP)"  # organe declare le 2026-09-06 (audit de raccordement)
import argparse
import os
import re

# INCHANGES (rename staged, cf NOKIDO_CUTOVER_RUNBOOK Phase +N)
KEEP_PATTERNS = {
    "LAFORGE_env": re.compile(r"LAFORGE_[A-Z0-9_]+"),
    "agt_laforge": re.compile(r"agt_laforge"),
    "wrk_laforge": re.compile(r"wrk_laforge"),
    "exegol-laforge": re.compile(r"exegol-laforge"),
    "searxng-laforge": re.compile(r"searxng-laforge"),
    "id-mcp": re.compile(r"laforge-sovereign-hub"),
    "glob_log": re.compile(r"laforge_\*"),
    "sql_default": re.compile(r"(?i)default\s+'laforge'"),
    "schtask_laforge": re.compile(r"schtask_laforge"),
    "dist_laforge": re.compile(r"dist_laforge"),
    "lora_laforge": re.compile(r"lora_laforge"),
    "NokidoMCP": re.compile(r"NokidoMCP"),
    "task_camel": re.compile(r"LaForge-[A-Z]"),
}
# DOIVENT TOMBER (~0)
RESIDUAL = {
    "import_laforge": re.compile(r"(?:from|import)\s+laforge"),
    "laforge_lower_prefix": re.compile(r"\blaforge_[a-z]"),
}

SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache"}
EXT = {
    ".py", ".md", ".json", ".toml", ".ts", ".tsx", ".js", ".jsx", ".html", ".htm", ".css",
    ".bat", ".ps1", ".sh", ".cmd", ".yaml", ".yml", ".xml", ".cfg", ".ini", ".txt", ".rst",
    ".env", ".secrets", ".example",
}


def count(root):
    res = {k: 0 for k in list(KEEP_PATTERNS) + list(RESIDUAL)}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP]
        for f in fn:
            if os.path.splitext(f)[1].lower() not in EXT:
                continue
            try:
                t = open(os.path.join(dp, f), encoding="utf-8", errors="surrogateescape").read()
            except Exception:
                continue
            for k, rx in list(KEEP_PATTERNS.items()) + list(RESIDUAL.items()):
                res[k] += len(rx.findall(t))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    a = ap.parse_args()
    r = count(os.path.abspath(a.root))
    print("=== KEEP (doivent rester CONSTANTS avant/apres) ===")
    for k in KEEP_PATTERNS:
        print("  %-22s %d" % (k, r[k]))
    print("=== RESIDUAL (doivent tomber ~0) ===")
    for k in RESIDUAL:
        print("  %-22s %d" % (k, r[k]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
