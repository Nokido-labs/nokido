#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
forge_client_bootstrap.py  (DEPORTED — dry-run par defaut, 0 ecriture config)
Orchestrateur d'onboarding/harmonisation client<->hub Nokido.
NE REIMPLEMENTE RIEN : detecte l'etat REEL (parse les configs MCP) puis chaine
les primitives existantes (forge_provision_clients / forge_connect_clients /
forge_skill_sync / forge_ssot). --apply non implemente ici (phase confirmee).

Sortie : plan d'apply PAR surface (ce que --apply ferait) + skill_sync dry-run.
Corrige les faux-negatifs de l'audit (l'audit ne lisait que ~/.claude.json).
"""
import os, sys, re, json, time, glob, traceback
try:
    import tomllib
except Exception:
    tomllib = None

HOME = __import__("os").path.expanduser(r"~")
# Racine DERIVEE du fichier (phase 0 du renommage vers Nokido) : tools/ -> parent.parent.
LF   = str(__import__("pathlib").Path(__file__).resolve().parent.parent)
PROJ = os.path.dirname(LF)
OUT  = r"C:\tmp\harmonize"
os.makedirs(OUT, exist_ok=True)
for p in (LF, os.path.join(LF, "app"), os.path.join(LF, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

_log = open(os.path.join(OUT, "bootstrap.log"), "w", encoding="utf-8")
def L(*a):
    s = " ".join(str(x) for x in a); print(s); _log.write(s + "\n"); _log.flush()

def rd(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def parse_any(path):
    raw = rd(path)
    if raw is None:
        return None, None
    if path.endswith(".toml"):
        if tomllib:
            try: return tomllib.loads(raw), raw
            except Exception: return None, raw
        return None, raw
    try: return json.loads(raw), raw
    except Exception: return None, raw

def find_hub_server(obj, raw):
    """Detecte si une config MCP pointe vers le hub :8766 + extrait header/token."""
    res = {"points_hub": False, "agent_header": None, "has_token": False, "server_keys": []}
    if raw and "8766" in raw:
        res["points_hub"] = True
    if raw:
        mh = re.search(r'LaForge-Agent-Name["\']?\s*[:=]\s*["\']?([A-Z_]+)', raw)
        if mh: res["agent_header"] = mh.group(1)
        if re.search(r'FORGE_TOKEN_|Bearer\b|"token"\s*:', raw): res["has_token"] = True
    # cles de serveurs
    if isinstance(obj, dict):
        for k in ("mcpServers", "mcp_servers", "servers", "context_servers"):
            v = obj.get(k)
            if isinstance(v, dict):
                res["server_keys"] = list(v.keys())
    return res

# ---- modele des surfaces (chemins candidats multiples, on prend le 1er present)
SURFACES = [
    dict(name="Claude Code CLI", lineage="CLAUDE", kind="cli",
         mcp=[os.path.join(PROJ, ".mcp.json"), os.path.join(HOME, ".claude.json"),
              os.path.join(HOME, ".claude", "settings.json")],
         instr=[os.path.join(PROJ, "CLAUDE.md")],
         home_skills=os.path.join(HOME, ".claude", "skills")),
    dict(name="Claude Desktop", lineage="CLAUDE_DESKTOP", kind="desktop",
         mcp=[os.path.join(HOME, "AppData", "Roaming", "Claude", "claude_desktop_config.json")],
         instr=[], home_skills=None),
    dict(name="Antigravity agy CLI", lineage="ANTIGRAVITY", kind="cli",
         mcp=[os.path.join(HOME, ".gemini", "config", "mcp_config.json"),
              os.path.join(HOME, ".gemini", "settings.json")],
         instr=[os.path.join(HOME, ".gemini", "GEMINI.md"), os.path.join(LF, "GEMINI.md")],
         home_skills=os.path.join(HOME, ".gemini", "skills")),
    dict(name="Antigravity agy Desktop", lineage="ANTIGRAVITY", kind="desktop",
         mcp=[os.path.join(HOME, "AppData", "Roaming", "Antigravity", "User", "globalStorage", "mcp.json"),
              os.path.join(HOME, "AppData", "Roaming", "Antigravity", "User", "settings.json"),
              os.path.join(HOME, "AppData", "Roaming", "Antigravity", "mcp_config.json")],
         instr=[os.path.join(HOME, ".gemini", "GEMINI.md")],
         home_skills=os.path.join(HOME, ".gemini", "skills")),
    dict(name="Antigravity agi IDE", lineage="ANTIGRAVITY", kind="ide",
         mcp=[os.path.join(HOME, "AppData", "Roaming", "Antigravity", "User", "globalStorage", "mcp.json"),
              os.path.join(HOME, ".antigravity", "mcp.json")],
         instr=[os.path.join(HOME, ".gemini", "GEMINI.md")],
         home_skills=os.path.join(HOME, ".gemini", "skills")),
    dict(name="Codex CLI", lineage="CODEX", kind="cli",
         mcp=[os.path.join(HOME, ".codex", "config.toml")],
         instr=[os.path.join(PROJ, "AGENTS.md"), os.path.join(LF, "AGENTS.md"),
                os.path.join(HOME, ".codex", "AGENTS.md")],
         home_skills=os.path.join(HOME, ".codex", "skills")),
    dict(name="Codex Desktop", lineage="CODEX", kind="desktop",
         mcp=[os.path.join(HOME, "AppData", "Roaming", "Codex", "config.toml"),
              os.path.join(HOME, ".codex", "config.toml")],
         instr=[os.path.join(HOME, ".codex", "AGENTS.md")], home_skills=None),
    dict(name="VSCode", lineage="VSCODE", kind="ide",
         mcp=[os.path.join(HOME, "AppData", "Roaming", "Code", "User", "mcp.json"),
              os.path.join(HOME, "AppData", "Roaming", "Code", "User", "settings.json")],
         instr=[os.path.join(PROJ, ".github", "copilot-instructions.md")], home_skills=None),
]

def identities():
    d = json.loads(rd(os.path.join(LF, "config", "agent_identities.json")) or "{}")
    out = {}
    for k, v in (d.get("agents", {}) or {}).items():
        out[k] = v.get("ring") if isinstance(v, dict) else v
    return out

def audit_surface(s, rings):
    r = {"name": s["name"], "lineage": s["lineage"], "kind": s["kind"]}
    # MCP : 1er chemin present
    mcp_path = next((m for m in s["mcp"] if os.path.exists(m)), None)
    r["mcp_path"] = mcp_path
    if mcp_path:
        obj, raw = parse_any(mcp_path)
        hub = find_hub_server(obj, raw)
        r.update({"mcp_present": True, "points_hub": hub["points_hub"],
                  "agent_header": hub["agent_header"], "has_token": hub["has_token"],
                  "server_keys": hub["server_keys"]})
    else:
        r.update({"mcp_present": False, "points_hub": False})
    # instr
    ip = next((p for p in s["instr"] if os.path.exists(p)), None)
    r["instr_path"] = ip
    r["instr_present"] = bool(ip)
    r["rules_shared"] = bool(ip and "RULES_SHARED" in (rd(ip) or ""))
    # skills home
    hs = s["home_skills"]
    r["skills_dir"] = hs
    r["skills_count"] = len([p for p in glob.glob(os.path.join(hs, "*")) if os.path.isdir(p)]) if hs and os.path.isdir(hs) else (0 if hs else None)
    # ring
    r["ring"] = rings.get(s["lineage"])
    # PLAN d'apply
    plan = []
    if not r.get("mcp_present"):
        plan.append("WRITE mcp config -> hub :8766 (forge_connect_clients --agent %s)" % s["lineage"])
    elif not r.get("points_hub"):
        plan.append("PATCH mcp config: ajouter serveur nokido :8766 + header %s" % s["lineage"])
    if s["instr"] and not r["instr_present"]:
        plan.append("CREATE instr (%s) qui @import RULES_SHARED" % os.path.basename(s["instr"][0]))
    elif r["instr_present"] and not r["rules_shared"]:
        plan.append("EDIT instr (%s): ajouter @import RULES_SHARED" % os.path.basename(r["instr_path"]))
    if r["skills_count"] == 0 and r["skills_dir"]:
        plan.append("SKILL_SYNC -> %s" % r["skills_dir"])
    if r["ring"] is None:
        plan.append("ADD identity ring (config/agent_identities.json)")
    r["apply_plan"] = plan or ["RAS (deja harmonise)"]
    return r

def skill_sync_dry():
    try:
        from nokido_agent.tools import forge_skill_sync as fss
        plan = fss.plan_or_apply(apply=False, copy=True)
        # condense
        return {"ok": True, "summary": {k: (len(v) if isinstance(v, (list, dict)) else v)
                                        for k, v in plan.items()} if isinstance(plan, dict) else str(plan)[:400]}
    except Exception as e:
        return {"ok": False, "err": "%s" % e}

def ssot_check():
    try:
        from nokido_agent.app import forge_ssot as fs
        return {"ok": True, "domains": list(fs.list_domains().keys())}
    except Exception as e:
        return {"ok": False, "err": "%s" % e}

def _import_marker(path):
    """Append idempotent du pointeur RULES_SHARED dans un fichier d'instructions."""
    MARK = "<!-- LAFORGE_HARMONIZATION -->"
    cur = rd(path)
    if cur and MARK in cur:
        return "skip(present)"
    abs_rs = os.path.join(LF, "RULES_SHARED.md").replace("\\", "/")
    block = (f"\n\n{MARK}\n# Nokido regles communes (emanation) — voir aussi hub "
             f"`point rules` / `point roadmap`\n@{abs_rs}\n")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if cur is not None:
        with open(path + ".bak", "w", encoding="utf-8") as f: f.write(cur)
        with open(path, "w", encoding="utf-8") as f: f.write(cur + block)
    else:
        with open(path, "w", encoding="utf-8") as f: f.write(block.lstrip())
    return "appended"


def apply_all():
    """OWNER only. Chaine les primitives existantes + fix agy. Reversible (.bak / rollback)."""
    L("\n===== APPLY (owner) =====")
    try:
        from nokido_agent.tools import forge_connect_clients as fcc
        from nokido_agent.app.forge_secrets import get_secret
    except Exception as e:
        L("[FATAL] import primitives:", e); return
    # 1. branchement canonique 7 clients (claude_code/desktop, vscode, codex, cline, lmstudio, gemini-settings)
    try:
        fcc.main(); L("[connect_clients] OK (canonique)")
    except Exception as e:
        L("[connect_clients] ERR", e)
    # 2. FIX agy : ecrit ~/.gemini/config/mcp_config.json (le fichier que agy lit vraiment)
    try:
        import pathlib
        mcpc = pathlib.Path(HOME, ".gemini", "config", "mcp_config.json")
        mcpc.parent.mkdir(parents=True, exist_ok=True)
        r = fcc._merge_json(mcpc, "mcpServers", "laforge-sovereign-hub",
                            {"url": fcc.URL,
                             "headers": fcc._hdr("ANTIGRAVITY", get_secret("FORGE_TOKEN_ANTIGRAVITY") or ""),
                             "timeout": 30000}, False)
        L("[agy mcp_config.json]", r)
    except Exception as e:
        L("[agy] ERR", e)
    # 3. @import RULES_SHARED dans les instr (emanation)
    for p in [os.path.join(HOME, ".gemini", "GEMINI.md"),
              os.path.join(LF, "GEMINI.md"),
              os.path.join(HOME, ".codex", "AGENTS.md"),
              os.path.join(PROJ, ".github", "copilot-instructions.md")]:
        try: L("[instr]", os.path.basename(p), "->", _import_marker(p))
        except Exception as e: L("[instr] ERR", p, e)
    # 4. distribution skills
    try:
        from nokido_agent.tools import forge_skill_sync as fss
        res = fss.plan_or_apply(apply=True, copy=True)
        L("[skill_sync apply]", {k: (len(v) if isinstance(v, (list, dict)) else v)
                                  for k, v in res.items()} if isinstance(res, dict) else str(res)[:300])
    except Exception as e:
        L("[skill_sync] ERR", e)
    # 5. SSoT (le nouveau CLI voit regles + roadmap)
    try:
        from nokido_agent.app import forge_ssot as fs
        for dom in ("rules", "roadmap"):
            pt = fs.point("point %s" % dom)
            L("[ssot %s]" % dom, (str(pt)[:160] if pt else "n/a"))
    except Exception as e:
        L("[ssot] ERR", e)
    L("===== APPLY DONE — relancer le hub (stop/start) pour recharger, puis tester whoami par CLI =====")


def main():
    t0 = time.time()
    mode = "APPLY" if "--apply" in sys.argv else "DRY-RUN"
    L("=== forge_client_bootstrap (%s) ===" % mode, time.strftime("%Y-%m-%d %H:%M:%S"))
    rings = identities()
    res = [audit_surface(s, rings) for s in SURFACES]
    L("\n[SURFACES — etat reel + plan d'apply]")
    for r in res:
        L(f"\n* {r['name']}  (ring {r['ring']}, {r['kind']})")
        L(f"    mcp: {'present' if r.get('mcp_present') else 'ABSENT'}"
          + (f" path={r['mcp_path']}" if r.get('mcp_path') else "")
          + (f" -> hub={'OUI' if r.get('points_hub') else 'NON'}" if r.get('mcp_present') else "")
          + (f" header={r.get('agent_header')} token={r.get('has_token')}" if r.get('mcp_present') else "")
          + (f" servers={r.get('server_keys')}" if r.get('server_keys') else ""))
        L(f"    instr: {'present' if r['instr_present'] else 'ABSENT'} RULES_SHARED={r['rules_shared']}"
          + (f" ({r['instr_path']})" if r.get('instr_path') else ""))
        L(f"    skills_home: {r['skills_count']} ({r['skills_dir']})")
        for a in r["apply_plan"]:
            L(f"      -> {a}")
    ss = skill_sync_dry(); L("\n[SKILL_SYNC dry-run]", ss)
    so = ssot_check();      L("[SSoT domains]", so)

    summary = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "elapsed_s": round(time.time()-t0, 1),
               "surfaces": res, "skill_sync_dry": ss, "ssot": so}
    with open(os.path.join(OUT, "bootstrap_plan.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    if "--apply" in sys.argv:
        apply_all()
    n_clean = sum(1 for r in res if r["apply_plan"] == ["RAS (deja harmonise)"])
    L(f"\n=== DONE: {n_clean}/{len(res)} deja harmonisees — plan ecrit C:/tmp/harmonize/bootstrap_plan.json — {round(time.time()-t0,1)}s ===")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        L("FATAL\n" + traceback.format_exc())
    finally:
        _log.close()
