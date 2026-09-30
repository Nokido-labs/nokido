"""forge_proprioception.py — Conscience corporelle élargie Nokido.

Mapping bio↔code :
- Proprioception (kinesthésie) = conscience de la position et de l'état des organes
- Schéma corporel              = carte mentale anatomique mise à jour en continu
- Phantome (membre absent)     = module attendu mais manquant
- Hypotrophie / atrophie       = organe peu utilisé (LRU)
- Hypertrophie                 = organe sur-sollicité

DIFFÉRENCE AVEC forge_health_diagnostic
=======================================
- health_diag : mesure des SYMPTÔMES (pct vec, mailbox unread, services up)
- proprioception : INVENTAIRE corporel structurel + score de vitalité par axe

AXES MESURÉS (chacun 0-100)
============================
1. Connaissance : chunks RAG par domaine + qualité moyenne
2. Souvenir    : lessons (anchor_solution) + sessions historiques
3. Code        : modules Python forge_*.py — vitalité (récents/utilisés vs orphelins)
4. Mémoires    : .md docs + DB tables + agent_messages
5. Régulation  : hormones actives + récepteurs câblés
6. Évolution   : commits récents + skill_proposals + biblio nouveaux

OUTPUT
======
- sandbox/proprioception_<date>.json     : machine-readable atlas complet
- sandbox/proprioception_report_<date>.md : lisible humain par axe
- table proprioception_snapshots          : historique (delta vs T-7j)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
SANDBOX = ROOT / "sandbox"
APP_DIR = ROOT / "app"
DOCS_DIR = ROOT / "docs"


# ============================================================================
# MAPPING ORGANE → MODULE (extension de CLAUDE.md §10)
# ============================================================================

ORGAN_MAP: dict[str, list[str]] = {
    "cortex_prefrontal": ["forge_cognitive_router"],
    "cervelet": ["forge_spike_router"],
    "moelle_epiniere": ["forge_byte_router"],
    "sn_peripherique": ["forge_mcp_registry"],
    "metabolisme_energetique": ["forge_llm_router", "forge_token_monitor"],
    "hippocampe": ["forge_self_correction"],
    "cortex_sensoriel": ["forge_rag_engine", "forge_rag_warmup"],
    "synapses": ["forge_hebbian_linker", "forge_post_commit"],
    "barriere_hematoenc": ["forge_semantic_firewall"],
    "anticorps_inne": ["forge_prompt_guard"],
    "membrane_cellulaire": ["forge_sovereign_membrane"],
    "macrophages": ["forge_clawhub_bridge"],  # SkillGuardian
    "hla_rbac": ["forge_integrity", "forge_rbac"],
    "noise_filter": ["forge_silo_fragmenter"],
    "bulbe_rachidien": ["forge_inspector"],
    "sympathique": ["forge_idle_watchdog", "forge_ping_monitor"],
    "parasympathique": ["forge_provider_watcher"],
    "digestif_oesophage": ["forge_browser_tool", "forge_crawl_tool"],
    "digestif_estomac": ["forge_ingest_self", "forge_ingest_pipeline"],
    "digestif_grele": ["forge_rag_qualify"],
    "foie_detox": ["forge_secret_guard"],
    "muscles_stries": ["forge_silo_engine"],
    "squelette": ["forge_runtime", "forge_runner"],
    "articulations": ["forge_message_frame", "forge_broker_base"],
    # === Nouveaux modules biomimétiques (chantier 2026-04-30) ===
    "endocrinien_hypophyse": ["forge_endocrine"],
    "endocrinien_hypothalamus": ["forge_health_diagnostic"],
    "rein_clairance": ["forge_renal_clearance"],
    "coagulation_cascade": ["forge_coagulation_cascade"],
    "immunite_adaptative": ["forge_immune_adaptive"],
    "cellules_souches": ["forge_pluripotent_workers"],
    "snc_autonome": ["forge_homeostasis_orchestrator"],
    "selection_naturelle": ["forge_tool_efficiency"],
    "dsl_compacteur": ["forge_dsl"],
    "proprioception": ["forge_proprioception"],
    "circadien": ["forge_circadian_loop"],
    "skill_capitalisation": ["forge_skill_enricher"],
    "biblio_curation": ["forge_biblio_worker", "forge_biblio_core", "forge_biblio_sanitizer"],
    "veille_externe": ["forge_rss_watcher"],
}


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB), timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    return c


# ============================================================================
# AXE 1 : CONNAISSANCE (RAG)
# ============================================================================


def measure_knowledge(conn) -> dict:
    # Lu chez le PRODUCTEUR (forge_memory_availability.snapshot, calcule hors chemin
    # chaud, la nuit) : quatre agregats sur rag_chunks (2 COUNT, GROUP BY domain, AVG)
    # a CHAQUE cycle de proprioception lisaient la base de 24,9 Go en boucle -- 4e
    # incarnation du balayage complet, ce qui a fait couper Homeostasis et
    # ParietalFusion le 05/09. Un snapshot perime est LU quand meme (ses valeurs
    # datent, c'est dit dans `mesure`), jamais recompte ; absent -> None partout :
    # une absence de mesure n'est pas un zero.
    from nokido_agent.app.forge_memory_availability import snapshot
    snap = snapshot(age_max_s=10 * 86400)
    rows_total = snap.get("total")
    if rows_total is None:
        return {"score": None, "chunks_total": None, "vectorized_pct": None, "avg_quality": None,
                "domains_top": [], "mesure": "INCONNUE : " + str(snap.get("raison"))}
    rows_vec = snap.get("vector_available") or 0
    by_dom = snap.get("by_domain") or []
    avg_q = snap.get("avg_quality")
    pct_vec = round(rows_vec * 100 / max(rows_total, 1), 1)
    score = round((pct_vec / 100) * 0.5 * 100 + ((avg_q or 0.0) / 1.0) * 0.5 * 100)
    age = float(snap.get("age_s") or 0)
    return {
        "score": min(100, score),
        "chunks_total": rows_total,
        "vectorized_pct": pct_vec,
        "avg_quality": round(avg_q, 3) if avg_q is not None else None,
        "domains_top": [{"domain": d, "n": n} for d, n in by_dom],
        "mesure": "snapshot vieux de %.0f s%s" % (
            age, "" if snap.get("frais") else " (PERIME : %s)" % snap.get("raison")),
    }


# ============================================================================
# AXE 2 : SOUVENIR (lessons + sessions)
# ============================================================================


def measure_memory(conn) -> dict:
    # GLOB et non LIKE : meme defaut mesure le 2026-09-04 dans `forge_health_diagnostic`
    # et `forge_self_correction`. Un motif de prefixe en `LIKE` neutralise l'index de la
    # cle primaire (insensibilite a la casse) ; en `GLOB` le plan devient
    # `SEARCH ... USING COVERING INDEX`. La proprioception s'echantillonne en boucle :
    # le balayage etait donc paye a chaque mesure.
    sol_count = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE id GLOB 'lesson_sol_*'").fetchone()[0]
    err_count = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE id GLOB 'lesson_err_*'").fetchone()[0]
    last_24h = conn.execute(
        "SELECT COUNT(*) FROM rag_chunks "
        "WHERE (id GLOB 'lesson_sol_*' OR id GLOB 'lesson_err_*') "
        "AND ingested_at >= datetime('now', '-24 hours')"
    ).fetchone()[0]

    # Sessions historiques Claude
    claude_sessions_dir = Path.home() / ".claude" / "projects"
    n_sessions = 0
    n_jsonl_total = 0
    if claude_sessions_dir.exists():
        for proj in claude_sessions_dir.iterdir():
            if proj.is_dir():
                jsonls = list(proj.glob("*.jsonl"))
                n_jsonl_total += len(jsonls)
                if jsonls:
                    n_sessions += 1

    # lessons_learned.md
    ll_md = ROOT / "logs" / "lessons_learned.md"
    ll_size = ll_md.stat().st_size if ll_md.exists() else 0

    score_lessons = min(60, sol_count + err_count * 0.5)  # plafond
    score_recent = min(20, last_24h * 5)
    score_sessions = min(20, n_jsonl_total * 0.5)
    score = int(score_lessons + score_recent + score_sessions)
    return {
        "score": min(100, score),
        "lessons_solutions": sol_count,
        "lessons_errors": err_count,
        "lessons_24h": last_24h,
        "claude_session_projects": n_sessions,
        "claude_jsonl_files": n_jsonl_total,
        "lessons_md_size_kb": round(ll_size / 1024, 1),
    }


# ============================================================================
# AXE 3 : CODE (modules forge_*.py)
# ============================================================================


def measure_code() -> dict:
    if not APP_DIR.exists():
        return {"score": 0, "modules": 0, "err": "app/ missing"}
    modules = sorted(APP_DIR.glob("forge_*.py"))
    total = len(modules)
    now = time.time()
    fresh = []  # modifiés < 7j
    aged = []  # modifiés > 90j
    sizes = []
    for p in modules:
        st = p.stat()
        age_days = (now - st.st_mtime) / 86400
        sizes.append(st.st_size)
        if age_days < 7:
            fresh.append({"name": p.stem, "age_d": round(age_days, 1)})
        elif age_days > 90:
            aged.append({"name": p.stem, "age_d": int(age_days)})

    avg_size_kb = round(sum(sizes) / max(len(sizes), 1) / 1024, 1)
    pct_fresh = round(len(fresh) * 100 / max(total, 1), 1)

    # Score : équilibre fresh / aged
    score = min(100, int(60 + pct_fresh - len(aged) * 0.3))

    return {
        "score": max(0, score),
        "modules_total": total,
        "fresh_7d_count": len(fresh),
        "fresh_pct": pct_fresh,
        "aged_90d_count": len(aged),
        "avg_size_kb": avg_size_kb,
        "fresh_top10": sorted(fresh, key=lambda x: x["age_d"])[:10],
        "aged_top10": sorted(aged, key=lambda x: -x["age_d"])[:10],
    }


# ============================================================================
# AXE 4 : MÉMOIRES (.md + DB tables + agent_messages)
# ============================================================================


# Dossiers dont le CONTENU n'apprend rien sur le savoir du corps : copies de
# travail, caches, artefacts. `sandbox/` porte a lui seul des dizaines de
# worktrees et d'archives (mesure : 131 copies pour le seul motif « scalene »).
_STORAGE_ELAGUES = frozenset({
    "sandbox", ".git", "__pycache__", "build", "dist", "_attic",
    "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache",
})


def measure_storage(conn) -> dict:
    # .md files — parcours ELAGUE, jamais un `rglob` global.
    #
    # MESURE 2026-09-13. `ROOT.rglob("*.md")` descendait dans TOUT le depot,
    # `sandbox/` compris, et le filtre venait APRES : on payait l'integralite du
    # balayage pour en jeter la majeure partie. Coût : plus de 30 s, timeout de
    # pytest, et le bloc 3 de la CI mourait AVANT d'ecrire son JUnit -- un quart
    # de la suite SANS VERDICT, ni vert ni rouge.
    #
    # Meme famille que les `COUNT(*)` deja retires de cet organe le 2026-09-06 :
    # un balayage qui recompte ce qu'on n'a pas besoin de voir. Ironie mesuree :
    # le test qui tombait s'appelle `test_balayeurs_lisent_le_producteur_nr`.
    #
    # `os.walk` avec elagage EN PLACE (`_sous[:] = ...`) n'entre jamais dans les
    # dossiers ecartes -- c'est ce qui change le cout, pas le filtre final.
    md_files: list[Path] = []
    for _dossier, _sous, _fichiers in os.walk(ROOT):
        _sous[:] = [d for d in _sous
                    if d not in _STORAGE_ELAGUES and not d.startswith(".")]
        for _f in _fichiers:
            if _f.endswith(".md"):
                md_files.append(Path(_dossier) / _f)
    md_size = sum(p.stat().st_size for p in md_files)

    # DB tables count + rows
    tbls = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    # MAX(rowid) : instantane (index) la ou COUNT(*) BALAYE chaque table -- dont
    # rag_chunks (24,9 Go) a chaque cycle. BORNE SUPERIEURE (les suppressions ne
    # rendent pas leur rowid), dite dans `db_rows_note`. Meme choix que le schema
    # de handle_query depuis le 03/09.
    rows_per_tbl = {}
    total_rows = 0
    for t in tbls:
        try:
            n = int(conn.execute(f'SELECT MAX(rowid) FROM "{t}"').fetchone()[0] or 0)
            rows_per_tbl[t] = n
            total_rows += n
        except Exception:
            pass

    # DB physical size
    db_size_mb = round(Path(str(DB)).stat().st_size / 1024 / 1024, 1) if Path(str(DB)).exists() else 0

    # Working memory : agent_messages by status
    # Scission M2M : compter dans la base des agent_messages (interrupteur sandbox/
    # m2m.switch), pas dans la copie figee que la base du RAG conservera.
    import sqlite3 as _sq3
    from nokido_agent.app.forge_db_path import m2m_path as _m2m_path
    try:
        _m = _sq3.connect(_m2m_path(), timeout=3)
        am_total = _m.execute("SELECT COUNT(*) FROM agent_messages").fetchone()[0]
        am_unread = _m.execute("SELECT COUNT(*) FROM agent_messages WHERE status='unread'").fetchone()[0] if am_total > 0 else 0
        _m.close()
    except Exception as _e:  # noqa: BLE001
        print(f"[proprioception] agent_messages illisible ({type(_e).__name__}) : compte a 0, pas mesure", flush=True)
        am_total, am_unread = 0, 0

    # Score : équilibre richesse vs saturation
    pct_unread = round(am_unread * 100 / max(am_total, 1), 1)
    score = 100
    if pct_unread > 50:
        score -= 30
    if db_size_mb > 5000:
        score -= 10
    if len(md_files) < 20:
        score -= 10
    return {
        "score": max(0, score),
        "md_files_count": len(md_files),
        "md_total_kb": round(md_size / 1024, 1),
        "db_size_mb": db_size_mb,
        "db_tables_count": len(tbls),
        "db_total_rows": total_rows,
        "db_rows_note": "MAX(rowid) par table = borne superieure, pas COUNT(*) (balayage interdit)",
        "agent_messages_unread_pct": pct_unread,
        "biggest_tables": sorted([(t, n) for t, n in rows_per_tbl.items()], key=lambda x: -x[1])[:10],
    }


# ============================================================================
# AXE 5 : RÉGULATION (endocrine + récepteurs)
# ============================================================================


def measure_regulation(conn) -> dict:
    try:
        sys.path.insert(0, str(APP_DIR))
        from nokido_agent.app.forge_endocrine import scan as hormone_scan

        hormones = hormone_scan()
        n_active = len(hormones)
        avg_level = round(sum(h.level for h in hormones) / max(n_active, 1), 3)
    except Exception:
        n_active = 0
        avg_level = 0.0

    # Récepteurs câblés (présence des hooks)
    hooks_status = {}
    files_to_grep = {
        "llm_router_cortisol": (APP_DIR / "forge_llm_router.py", "CORTISOL_QUOTA_CLOUD"),
        "rag_warmup_tsh": (APP_DIR / "forge_rag_warmup.py", "TSH_VECTORIZATION"),
        "pluripotent_perceive": (APP_DIR / "forge_pluripotent_workers.py", "perceive_environment"),
        "health_releases": (APP_DIR / "forge_health_diagnostic.py", "_release_hormones_from_audit"),
    }
    for name, (path, needle) in files_to_grep.items():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            hooks_status[name] = needle in text
        except Exception:
            hooks_status[name] = False

    n_hooks = sum(1 for v in hooks_status.values() if v)
    # Score : 50% hormones actives + 50% hooks câblés
    score = int((n_active * 10) + (n_hooks * 12.5))
    return {
        "score": min(100, score),
        "active_hormones": n_active,
        "avg_hormone_level": avg_level,
        "receptors_wired": n_hooks,
        "receptors_total": len(hooks_status),
        "hooks_status": hooks_status,
    }


# ============================================================================
# AXE 6 : ÉVOLUTION (git + skill proposals + biblio nouveaux)
# ============================================================================


def measure_evolution(conn) -> dict:
    # git commits 7d
    n_commits_7d = 0
    try:
        # errors="replace" obligatoire : en mode texte sans lui, un octet non-UTF8
        # dans un message de commit fait crasher le thread lecteur de subprocess
        # (anti-regression de l'incident 47 Go).
        out = subprocess.run(
            ["git", "log", "--since=7.days", "--oneline"], cwd=str(ROOT),
            capture_output=True, text=True, errors="replace", timeout=10
        )
        n_commits_7d = len([l for l in out.stdout.splitlines() if l.strip()])
    except Exception:
        pass

    # Skill proposals
    proposals_dir = SANDBOX / "skill_proposals"
    n_proposals = len(list(proposals_dir.glob("*.md"))) if proposals_dir.exists() else 0

    # Biblio reviewed récents
    n_biblio_24h = conn.execute(
        "SELECT COUNT(*) FROM biblio_raw WHERE updated_at >= datetime('now', '-24 hours') AND status='reviewed'"
    ).fetchone()[0]

    # DSL templates créés
    try:
        n_dsl = conn.execute("SELECT COUNT(*) FROM dsl_templates").fetchone()[0]
    except sqlite3.OperationalError:
        n_dsl = 0

    score = min(100, n_commits_7d * 5 + n_proposals * 8 + n_biblio_24h * 3 + n_dsl * 2)
    return {
        "score": score,
        "commits_7d": n_commits_7d,
        "skill_proposals": n_proposals,
        "biblio_reviewed_24h": n_biblio_24h,
        "dsl_templates": n_dsl,
    }


# ============================================================================
# ATLAS organe → module
# ============================================================================


def _load_body_regulation() -> dict:
    """Verdict d'INNERVATION par module (tools/forge_body_regulation_audit.py).

    Complète `vitality`, qui ne mesure que la PRÉSENCE du fichier : un module peut
    exister sur le disque sans être tenu par le corps — ni lancé, ni importé, ni
    invoqué. Tissu présent mais non innervé. Ici on lit un cache produit hors ligne ;
    le scan qui l'alimente coûte ~1 min et n'a rien à faire dans un cycle de mesure.
    """
    try:
        p = ROOT / "sandbox" / "workspace" / "body_regulation.json"
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_atlas() -> dict:
    """Pour chaque organe attendu : module présent ? innervé ? size? mtime? → vitalité."""
    regul = _load_body_regulation()
    atlas = {}
    phantom_organs = []  # organes attendus mais pas de module présent
    denervated = []  # présents sur le disque, mais que rien ne tient
    for organ, modules in ORGAN_MAP.items():
        organ_status = {"organ": organ, "modules": [], "vitality": 0, "innervation": None}
        living_modules = 0
        innerves = 0
        for mod in modules:
            mod_path = APP_DIR / f"{mod}.py"
            if mod_path.exists():
                st = mod_path.stat()
                age_d = round((time.time() - st.st_mtime) / 86400, 1)
                reg = regul.get(f"{mod}.py", {})
                statut = reg.get("statut")
                entry = {
                    "name": mod,
                    "size_kb": round(st.st_size / 1024, 1),
                    "age_days": age_d,
                    "alive": True,
                }
                if statut:
                    entry["regulation"] = statut
                    if statut == "ZONE_MORTE":
                        denervated.append(f"{organ}/{mod}")
                    else:
                        innerves += 1
                organ_status["modules"].append(entry)
                living_modules += 1
            else:
                organ_status["modules"].append({"name": mod, "alive": False})
        organ_status["vitality"] = round(living_modules * 100 / max(len(modules), 1))
        if regul:
            organ_status["innervation"] = round(innerves * 100 / max(len(modules), 1))
        atlas[organ] = organ_status
        if living_modules == 0:
            phantom_organs.append(organ)

    # Vue du corps ENTIER, pas seulement des organes canoniques : ORGAN_MAP en
    # nomme ~45, le census en classe plus de 1400. Sans ce total, un atlas « tout
    # vert » masquerait des centaines de modules que rien ne tient.
    census: dict[str, int] = defaultdict(int)
    for meta in regul.values():
        census[meta.get("statut", "?")] += 1
    return {
        "atlas": atlas,
        "phantom_organs": phantom_organs,
        "organs_total": len(ORGAN_MAP),
        "organs_alive": len([o for o in atlas.values() if o["vitality"] > 0]),
        "denervated_modules": sorted(denervated),
        "body_census": dict(census),
        "body_modules_total": len(regul),
        "body_dead_zones": census.get("ZONE_MORTE", 0),
        "regulation_source": "body_regulation.json" if regul else "ABSENT (audit jamais lance)",
    }


# ============================================================================
# CYCLE PRINCIPAL
# ============================================================================


def run_cycle() -> dict:
    conn = _conn()
    t0 = time.time()
    knowledge = measure_knowledge(conn)
    memory = measure_memory(conn)
    code = measure_code()
    storage = measure_storage(conn)
    regulation = measure_regulation(conn)
    evolution = measure_evolution(conn)
    atlas = build_atlas()
    conn.close()

    # Score global = moyenne pondérée
    weights = {"knowledge": 0.20, "memory": 0.15, "code": 0.20, "storage": 0.15, "regulation": 0.15, "evolution": 0.15}
    global_score = round(
        knowledge["score"] * weights["knowledge"]
        + memory["score"] * weights["memory"]
        + code["score"] * weights["code"]
        + storage["score"] * weights["storage"]
        + regulation["score"] * weights["regulation"]
        + evolution["score"] * weights["evolution"]
    )

    out = {
        "ts": datetime.now().isoformat(),
        "duration_s": round(time.time() - t0, 2),
        "global_score": global_score,
        "axes": {
            "knowledge": knowledge,
            "memory": memory,
            "code": code,
            "storage": storage,
            "regulation": regulation,
            "evolution": evolution,
        },
        "atlas": atlas,
    }

    SANDBOX.mkdir(parents=True, exist_ok=True)
    json_path = SANDBOX / f"proprioception_{datetime.now().strftime('%Y-%m-%d_%H%M')}.json"
    json_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path = write_report(out)
    out["json_path"] = str(json_path)
    out["report_path"] = str(md_path)

    # Snapshot dans DB pour delta T-7j
    try:
        conn = _conn()
        conn.execute("""CREATE TABLE IF NOT EXISTS proprioception_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            global_score INTEGER,
            axes_json TEXT,
            atlas_json TEXT
        )""")
        conn.execute(
            "INSERT INTO proprioception_snapshots(ts, global_score, axes_json, atlas_json) VALUES (?, ?, ?, ?)",
            (
                out["ts"],
                global_score,
                json.dumps(out["axes"], ensure_ascii=False)[:8000],
                json.dumps(atlas, ensure_ascii=False)[:8000],
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    return out


def write_report(out: dict) -> Path:
    date = datetime.now().strftime("%Y-%m-%d_%H%M")
    path = SANDBOX / f"proprioception_report_{date}.md"
    a = out["axes"]
    md = [
        f"# Proprioception Nokido — {date}",
        "",
        f"## Score global : **{out['global_score']}/100**",
        "",
        "## Axes mesurés",
        "",
        "| Axe | Score | Détail |",
        "|---|---|---|",
        f"| 🧠 Connaissance | **{a['knowledge']['score']}/100** | {a['knowledge']['chunks_total']:,} chunks ({a['knowledge']['vectorized_pct']}% vec, q={a['knowledge']['avg_quality']}) |",
        f"| 💭 Souvenir | **{a['memory']['score']}/100** | {a['memory']['lessons_solutions']} sol + {a['memory']['lessons_errors']} err, {a['memory']['lessons_24h']} en 24h, {a['memory']['claude_jsonl_files']} sessions |",
        f"| 💻 Code | **{a['code']['score']}/100** | {a['code']['modules_total']} modules ({a['code']['fresh_pct']}% fresh, {a['code']['aged_90d_count']} aged>90j) |",
        f"| 🗄️ Mémoires | **{a['storage']['score']}/100** | {a['storage']['md_files_count']} .md, {a['storage']['db_tables_count']} tables, {a['storage']['db_size_mb']} MB |",
        f"| ⚗️ Régulation | **{a['regulation']['score']}/100** | {a['regulation']['active_hormones']} hormones, {a['regulation']['receptors_wired']}/{a['regulation']['receptors_total']} récepteurs |",
        f"| 🌱 Évolution | **{a['evolution']['score']}/100** | {a['evolution']['commits_7d']} commits 7j, {a['evolution']['skill_proposals']} props, {a['evolution']['dsl_templates']} DSL templates |",
        "",
        f"## Atlas anatomique ({out['atlas']['organs_alive']}/{out['atlas']['organs_total']} organes vivants)",
        "",
    ]
    if out["atlas"]["phantom_organs"]:
        md.append(f"### 👻 Organes phantômes ({len(out['atlas']['phantom_organs'])})")
        for o in out["atlas"]["phantom_organs"]:
            md.append(f"- {o}")
        md.append("")

    cens = out["atlas"].get("body_census") or {}
    if cens:
        md.append(f"### 🧩 Innervation du corps entier ({out['atlas']['body_modules_total']} modules)")
        md.append("")
        md.append("| Statut | Modules |")
        md.append("|---|---|")
        for st, n in sorted(cens.items(), key=lambda kv: -kv[1]):
            md.append(f"| {st} | {n} |")
        md.append("")
        md.append(
            "REGULE = supervisé + heartbeat · SUPERVISE = lancé sans heartbeat (mort "
            "silencieuse) · CABLE = importé · INVOQUE = cité par un hook/config/script · "
            "OUTIL = lancé à la demande · ZONE_MORTE = rien ne le tient."
        )
        md.append("")
        if out["atlas"].get("denervated_modules"):
            md.append("**Organes canoniques dénervés** (fichier présent, rien ne l'appelle) :")
            for m in out["atlas"]["denervated_modules"]:
                md.append(f"- {m}")
            md.append("")
    else:
        md.append(
            "_Innervation non mesurée : lancer `tools/forge_body_regulation_audit.py`._")
        md.append("")

    md.append("### Organes vivants (top 15)")
    organs = sorted(out["atlas"]["atlas"].items(), key=lambda x: -x[1]["vitality"])[:15]
    md.append("| Organe | Vitalité | Modules |")
    md.append("|---|---|---|")
    for organ, data in organs:
        mods = ", ".join(f"{m['name']}{'❌' if not m['alive'] else ''}" for m in data["modules"][:3])
        md.append(f"| {organ} | {data['vitality']}% | {mods} |")

    md.append("")
    md.append("## Top domaines RAG")
    for d in a["knowledge"]["domains_top"][:5]:
        md.append(f"- `{d['domain']}` : {d['n']:,} chunks")
    md.append("")
    md.append("## Modules récemment modifiés (< 7 jours)")
    for f in a["code"]["fresh_top10"]:
        md.append(f"- `{f['name']}` ({f['age_d']} j)")
    md.append("")
    md.append(f"_JSON brut : {out.get('json_path', '?')}_")
    path.write_text("\n".join(md), encoding="utf-8")
    return path


# ============================================================================
# CLI
# ============================================================================


def main() -> int:
    ap = argparse.ArgumentParser(description="Nokido proprioception élargie")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=int, default=21600)  # 6h
    args = ap.parse_args()
    if not args.once and not args.daemon:
        ap.error("--once ou --daemon requis")

    while True:
        out = run_cycle()
        a = out["axes"]
        print(f"\n[proprioception] global={out['global_score']}/100", flush=True)
        print(
            f"  🧠 connaissance : {a['knowledge']['score']}/100  ({a['knowledge']['chunks_total']:,} chunks, {a['knowledge']['vectorized_pct']}% vec)",
            flush=True,
        )
        print(
            f"  💭 souvenir    : {a['memory']['score']}/100  ({a['memory']['lessons_solutions']} lessons, {a['memory']['claude_jsonl_files']} sessions)",
            flush=True,
        )
        print(
            f"  💻 code        : {a['code']['score']}/100  ({a['code']['modules_total']} modules, {a['code']['fresh_pct']}% fresh)",
            flush=True,
        )
        print(
            f"  🗄️  mémoires    : {a['storage']['score']}/100  ({a['storage']['db_size_mb']} MB DB, {a['storage']['md_files_count']} .md)",
            flush=True,
        )
        print(
            f"  ⚗️  régulation  : {a['regulation']['score']}/100  ({a['regulation']['active_hormones']} hormones, {a['regulation']['receptors_wired']} récepteurs)",
            flush=True,
        )
        print(
            f"  🌱 évolution   : {a['evolution']['score']}/100  ({a['evolution']['commits_7d']} commits 7j)", flush=True
        )
        print(
            f"  🧬 atlas       : {out['atlas']['organs_alive']}/{out['atlas']['organs_total']} organes vivants",
            flush=True,
        )
        if out["atlas"]["phantom_organs"]:
            print(f"     👻 phantômes : {out['atlas']['phantom_organs']}", flush=True)
        print(f"  → JSON : {out['json_path']}", flush=True)
        print(f"  → Report : {out['report_path']}", flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
