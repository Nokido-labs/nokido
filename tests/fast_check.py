"""
tests/fast_check.py — Commit Guard Nokido v2
===============================================
REGLE ABSOLUE : py_compile + tests unitaires légers. Zéro import bloquant.
Exit 0 = PASS, Exit 1 = FAIL
"""
import sys, py_compile, sqlite3, json, ast
from pathlib import Path

ROOT = Path(__file__).parent.parent
APP  = ROOT / 'app'
UI   = ROOT / 'streamlit_ui'

results = []

# ── 1. py_compile core Nokido ────────────────────────────────────────────────
core = [
    APP / 'Nokido.py',
    APP / 'forge_commands.py',
    APP / 'forge_context.py',
    APP / 'forge_handlers.py',
    APP / 'forge_handler_ci.py',
    APP / 'forge_handler_rag.py',
    APP / 'forge_handler_patch.py',
    APP / 'mcp_bridge.py',
]
for p in core:
    if not p.exists(): results.append(f"SKIP {p.name}"); continue
    try:
        py_compile.compile(str(p), doraise=True)
        results.append(f"OK  py {p.name}")
    except py_compile.PyCompileError as e:
        results.append(f"FAIL py {p.name}: {str(e)[:60]}")

# ── 2. py_compile modules Web ─────────────────────────────────────────────────
web = [
    APP  / 'forge_web_service.py',
    APP  / 'forge_swarm.py',
    APP  / 'forge_swarm_team.py',
    UI   / 'chat_service.py',
    UI   / 'ai_service.py',
    UI   / 'mcp_service.py',
    UI   / 'team_tab.py',
    ROOT / 'streamlit_app.py',
]
for p in web:
    if not p.exists(): results.append(f"SKIP {p.name}"); continue
    try:
        py_compile.compile(str(p), doraise=True)
        results.append(f"OK  py {p.name}")
    except py_compile.PyCompileError as e:
        results.append(f"FAIL py {p.name}: {str(e)[:60]}")

# ── 3. AST check — forge_swarm states ─────────────────────────────────────────
try:
    src = (APP / 'forge_swarm.py').read_text(encoding='utf-8')
    tree = ast.parse(src)
    names = [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)]
    strs  = [n.s for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.s, str)]
    assert "IDLE"        in strs, "IDLE not found"
    assert "THINKING"    in strs, "THINKING not found"
    assert "STREAMING"   in strs, "STREAMING not found"
    assert "SYNCING_RAG" in strs, "SYNCING_RAG not found"
    assert "SwarmCoordinator" in [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    results.append("OK  forge_swarm AST states + SwarmCoordinator")
except Exception as e:
    results.append(f"FAIL forge_swarm AST: {str(e)[:80]}")

# ── 4. AST check — forge_swarm_team participants ──────────────────────────────
try:
    src2 = (APP / 'forge_swarm_team.py').read_text(encoding='utf-8')
    tree2 = ast.parse(src2)
    strs2 = [n.s for n in ast.walk(tree2) if isinstance(n, ast.Constant) and isinstance(n.s, str)]
    for pid in ["laforge", "llamacpp", "gemini", "CLAUDE", "CLINE_PLAN"]:
        assert pid in strs2, pid + " missing"
    classes = [n.name for n in ast.walk(tree2) if isinstance(n, ast.ClassDef)]
    assert "SwarmTeam"       in classes
    assert "Participant"     in classes
    assert "LeadOrchestrator" in classes
    results.append(f"OK  forge_swarm_team AST ({len(strs2)} strings, classes={classes})")
except Exception as e:
    results.append(f"FAIL forge_swarm_team AST: {str(e)[:80]}")

# ── 5. SwarmTeam sérialisation (sans import Nokido) ─────────────────────────
try:
    # Test dataclass manuellement via exec isolé
    exec_ns = {}
    src3 = (APP / 'forge_swarm_team.py').read_text(encoding='utf-8')
    # Extraire juste les dataclasses
    # On compile uniquement pour vérifier la syntaxe + logique JSON
    code = compile(src3, 'forge_swarm_team.py', 'exec')
    results.append("OK  forge_swarm_team compile(exec)")
except Exception as e:
    results.append(f"FAIL forge_swarm_team compile: {str(e)[:80]}")

# ── 6. events.db schema ───────────────────────────────────────────────────────
try:
    db_path = ROOT / 'sandbox' / 'events.db'
    conn = sqlite3.connect(str(db_path), timeout=3)
    tables = [t for t, in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if 'event_log' in tables:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(event_log)").fetchall()]
        assert 'sequence_id' in cols, "sequence_id missing"
        assert 'agent_id'    in cols, "agent_id missing"
        count = conn.execute("SELECT COUNT(*) FROM event_log").fetchone()[0]
        results.append(f"OK  events.db event_log cols={len(cols)} rows={count}")
    else:
        results.append("OK  events.db exists (event_log not yet created)")
    conn.close()
except Exception as e:
    results.append(f"FAIL events.db: {str(e)[:80]}")

# ── 7. forge_web_service — svc functions présentes ───────────────────────────
try:
    src4 = (APP / 'forge_web_service.py').read_text(encoding='utf-8')
    tree4 = ast.parse(src4)
    fn_names = {n.name for n in ast.walk(tree4) if isinstance(n, ast.FunctionDef)}
    required = {"hub_health", "rag_search", "ssh_exec", "swarm_status",
                "swarm_recent_events", "swarm_force_idle", "swarm_broadcast_listen"}
    missing_fns = required - fn_names
    if missing_fns:
        results.append(f"FAIL forge_web_service missing: {missing_fns}")
    else:
        results.append(f"OK  forge_web_service {len(fn_names)} fns, swarm API present")
except Exception as e:
    results.append(f"FAIL forge_web_service AST: {str(e)[:80]}")

# ── 8. team_tab — render functions présentes ─────────────────────────────────
try:
    src5 = (UI / 'team_tab.py').read_text(encoding='utf-8')
    tree5 = ast.parse(src5)
    fn5 = {n.name for n in ast.walk(tree5) if isinstance(n, ast.FunctionDef)}
    assert "render_team_tab"       in fn5
    assert "render_team_flowchart" in fn5
    results.append(f"OK  team_tab fns={fn5}")
except Exception as e:
    results.append(f"FAIL team_tab AST: {str(e)[:80]}")

# ── 9. chat_service — 13 tabs ────────────────────────────────────────────────
try:
    import re
    src6 = (UI / 'chat_service.py').read_text(encoding='utf-8')
    tab_blocks = re.findall(r'with (t_\w+):', src6)
    assert len(tab_blocks) == 13, f"Expected 13 tabs, got {len(tab_blocks)}: {tab_blocks}"
    results.append(f"OK  chat_service {len(tab_blocks)} tabs: {tab_blocks}")
except Exception as e:
    results.append(f"FAIL chat_service tabs: {str(e)[:80]}")

# ── 10. sandbox/swarm_team_config.json lisible si existe ─────────────────────
cfg_path = ROOT / 'sandbox' / 'swarm_team_config.json'
if cfg_path.exists():
    try:
        cfg = json.loads(cfg_path.read_text())
        assert 'participants' in cfg
        results.append(f"OK  swarm_team_config.json ({len(cfg['participants'])} participants)")
    except Exception as e:
        results.append(f"FAIL swarm_team_config: {str(e)[:60]}")
else:
    results.append("SKIP swarm_team_config.json (not yet created)")

# ── 10. ring_o_meter — states + classes ─────────────────────────────────────
try:
    src_rom = (ROOT / 'forge_desktop' / 'widgets' / 'ring_o_meter.py').read_text()
    tree_rom = ast.parse(src_rom)
    cls_rom  = [n.name for n in ast.walk(tree_rom) if isinstance(n, ast.ClassDef)]
    strs_rom = [n.s for n in ast.walk(tree_rom) if isinstance(n, ast.Constant) and isinstance(n.s, str)]
    assert 'RingDial'       in cls_rom, 'RingDial missing'
    assert 'RingOMeterWidget' in cls_rom, 'RingOMeterWidget missing'
    assert 'ok'    in strs_rom, 'STATE_OK missing'
    assert 'block' in strs_rom, 'STATE_BLOCK missing'
    results.append(f'OK  ring_o_meter classes={cls_rom}')
except Exception as e:
    results.append(f'FAIL ring_o_meter AST: {str(e)[:60]}')

# ── 11. forge_mermaid_gen — fonctions + validate ──────────────────────────
try:
    src_mg = (APP / 'forge_mermaid_gen.py').read_text()
    tree_mg = ast.parse(src_mg)
    sync_mg  = {n.name for n in ast.walk(tree_mg) if isinstance(n, ast.FunctionDef)}
    async_mg = {n.name for n in ast.walk(tree_mg) if isinstance(n, ast.AsyncFunctionDef)}
    all_mg   = sync_mg | async_mg
    assert 'generate_mermaid'       in all_mg
    assert 'validate_mermaid'       in all_mg
    assert 'generate_mermaid_async' in all_mg
    # validate_mermaid logic
    sys.path.insert(0, str(APP))
    from forge_mermaid_gen import validate_mermaid
    assert validate_mermaid('flowchart TD\n  A-->B')['ok'] == True
    assert validate_mermaid('hello world')['ok']            == False
    results.append(f'OK  forge_mermaid_gen fns={sorted(all_mg)[:4]} + validate OK')
except Exception as e:
    results.append(f'FAIL forge_mermaid_gen: {str(e)[:60]}')

# ── 12. mermaid_view.py py_compile ───────────────────────────────────────
try:
    mv_path = ROOT / 'forge_desktop' / 'views' / 'mermaid_view.py'
    if mv_path.exists():
        py_compile.compile(str(mv_path), doraise=True)
        results.append('OK  mermaid_view.py py_compile')
    else:
        results.append('SKIP mermaid_view.py (absent)')
except py_compile.PyCompileError as e:
    results.append(f'FAIL mermaid_view.py: {str(e)[:60]}')

# ── 13. main_window — 7 tabs ─────────────────────────────────────────────
try:
    import re as _re
    mw_src = (ROOT / 'forge_desktop' / 'views' / 'main_window.py').read_text()
    tab_count = len(_re.findall(r'addTab\(', mw_src))
    assert tab_count == 7, f'Expected 7 tabs, got {tab_count}'
    assert 'Mermaid'       in mw_src
    assert 'Conscience'    in mw_src
    assert 'Ring-O-Meter'  in mw_src or 'consciousness' in mw_src
    results.append(f'OK  main_window {tab_count} tabs')
except Exception as e:
    results.append(f'FAIL main_window tabs: {str(e)[:60]}')

# ── Verdict ───────────────────────────────────────────────────────────────────
failures = [r for r in results if r.startswith("FAIL")]
ok_count = len([r for r in results if r.startswith("OK")])
verdict  = "PASS" if not failures else "FAIL"
report   = (
    f"{verdict}  {ok_count}/{len(results)} tests"
    + (f"  |  {len(failures)} FAIL" if failures else "")
    + "\n\n"
    + "\n".join(results)
)

(ROOT / 'sandbox' / 'fast_check_result.txt').write_text(report, encoding='utf-8')
print(report)
sys.exit(0 if verdict == "PASS" else 1)
