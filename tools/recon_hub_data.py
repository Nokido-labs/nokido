"""Recon des vraies sources pour cabler les vues /hub (federation/cap/persona).
Trusted_script (env serveur). Imprime les SHAPES reelles pour batir les endpoints."""
import sys
import json
import traceback

ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[1])
for p in (ROOT, ROOT + "/app"):
    if p not in sys.path:
        sys.path.insert(0, p)
out = {}

# 1) FEDERATION : agents/clients gouvernes (mappings RBAC)
try:
    from app.web_hub.rbac_views import _mod
    maps = _mod().list_mappings()
    out["rbac_count"] = len(maps)
    out["rbac_sample"] = maps[:3]
except Exception:
    out["rbac_err"] = traceback.format_exc()[-220:]

# 2) PERSONA : nb de souvenirs reels (lessons)
try:
    from nokido_agent.app.forge_self_correction import read_lessons
    t = read_lessons(9000) or ""
    out["persona_solutions"] = t.lower().count("solution valid") or t.lower().count("solution")
    out["persona_len"] = len(t)
except Exception:
    out["persona_err"] = traceback.format_exc()[-160:]

# 3) CAP : dernier roadmap indexe
try:
    import sqlite3
    con = sqlite3.connect(ROOT + "/RAG/embeddings.db", timeout=4)
    row = con.execute(
        "SELECT source, substr(text,1,160) FROM rag_chunks "
        "WHERE lower(source) LIKE '%roadmap%' ORDER BY created_at DESC LIMIT 2"
    ).fetchall()
    out["roadmap"] = row
    con.close()
except Exception:
    out["roadmap_err"] = traceback.format_exc()[-160:]

# 4) CAP steps : commits recents (vrai travail fait)
try:
    import subprocess
    r = subprocess.run(["git", "-C", ROOT, "log", "--oneline", "-6"],
                       capture_output=True, text=True, timeout=8, errors="replace")
    out["commits"] = r.stdout.strip().split("\n")
except Exception:
    out["commits_err"] = traceback.format_exc()[-160:]

print(json.dumps(out, ensure_ascii=False, default=str)[:2200])
