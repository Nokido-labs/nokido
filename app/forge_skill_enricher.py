"""forge_skill_enricher.py — Boucle de capitalisation : leçons + topics → skills.

PATTERN
=======
Scan récurrent (cycle 1h par défaut) :
1. rag_chunks RECENTS contenant `lesson_sol_*` ou `lesson_err_*`
2. biblio_topics avec count >= seuil (topic émergent)
3. cluster par domain (`security`, `llm`, `rag`, `ui`, `biblio`, `watch`, ...)
4. Pour chaque cluster :
   - Si un skill existe déjà dans `docs/skills/<slug>/SKILL.md` → propose un patch
     de section "Apprentissages YYYY-MM" dans `sandbox/skill_proposals/<slug>.md`
   - Sinon → propose un draft de nouveau skill dans `sandbox/skill_proposals/_new_<slug>.md`
5. Anchor une entry pour traçabilité.

PRINCIPE
========
NE PAS ECRIRE dans `docs/skills/`. Génère des **propositions** dans `sandbox/skill_proposals/`.
L'utilisateur (ou un LLM en review SkillGuardian) approuve manuellement, ce qui déclenche
le merge dans `docs/skills/`.

USAGE
=====
    LAFORGE_PYTHON app/forge_skill_enricher.py --once       # 1 cycle, exit
    LAFORGE_PYTHON app/forge_skill_enricher.py --daemon     # boucle 1h
    LAFORGE_PYTHON app/forge_skill_enricher.py --threshold 3   # min count topic

NSSM service :
    nssm install NokidoSkillEnricher python.exe
    nssm set ... AppParameters "app\\forge_skill_enricher.py --daemon"

Version 1.0 — 2026-04-30
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime
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
SKILLS_DIR = ROOT / "docs" / "skills"
PROPOSALS_DIR = ROOT / "sandbox" / "skill_proposals"
STATE_FILE = ROOT / "sandbox" / "skill_enricher_state.json"
HEARTBEAT = ROOT / "sandbox" / "skill_enricher.heartbeat"

DEFAULT_INTERVAL_S = int(os.environ.get("LAFORGE_SKILL_ENRICHER_INTERVAL_S", "3600"))
DEFAULT_THRESHOLD = int(os.environ.get("LAFORGE_SKILL_ENRICHER_THRESHOLD", "2"))

# Mapping domain → skill candidat (heuristique — extensible)
DOMAIN_TO_SKILL = {
    "security": "forge-security-scan",
    "biblio": "forge-skill-seekers",
    "watch": "forge-skill-seekers",
    "ui": None,  # pas de skill dédié → propose nouveau
    "llm": "forge-core",  # routeur LLM = compétence centrale
    "rag": "forge-core",
    "systeme": "forge-core",
    "collab": None,
    "tdd": "forge-tdd",
    "connectors": "forge-connectors",  # Gmail/GCal/GDrive/Notion (Claude only)
}


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {"last_run_ts": 0, "skills_proposed": {}}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_run_ts": 0, "skills_proposed": {}}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _heartbeat(stats: dict) -> None:
    try:
        HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(
            json.dumps(
                {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "pid": os.getpid(),
                    "interval_s": DEFAULT_INTERVAL_S,
                    "last_cycle_stats": stats,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


def scan_recent_lessons(conn: sqlite3.Connection, since_ts: float) -> list[dict]:
    """Récupère les anchor_solution (id LIKE 'lesson_sol_%') depuis since_ts.

    rag_chunks utilise `ingested_at` (string ISO) — pas created_at.
    Pour lesson_*, l'id contient aussi un timestamp suffix (lesson_sol_<hash>_<unix_ts>).
    """
    # GLOB et non LIKE sur ces prefixes : mesure 2026-09-04, `LIKE 'lesson_sol_%'`
    # empeche SQLite d'utiliser l'index de la cle primaire (LIKE est insensible a la
    # casse par defaut) et fait parcourir toute la table ; `GLOB` est sensible a la
    # casse, d'ou un plan `MULTI-INDEX OR` avec deux SEARCH bornes.
    rows = conn.execute(
        "SELECT id, domain, source, substr(text, 1, 800) AS preview, ingested_at "
        "FROM rag_chunks WHERE id GLOB 'lesson_sol_*' OR id GLOB 'lesson_err_*' "
        "ORDER BY ingested_at DESC LIMIT 200"
    ).fetchall()
    out = []
    for r in rows:
        # 1) Tenter parse ingested_at (str ISO)
        t = 0.0
        if r[4]:
            try:
                t = datetime.fromisoformat(str(r[4]).split(".")[0]).timestamp()
            except Exception:
                t = 0.0
        # 2) Fallback : parser le ts suffixe de l'id (lesson_sol_<hash>_<unix_ts>)
        if t == 0.0:
            try:
                parts = (r[0] or "").rsplit("_", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    t = float(parts[1])
            except Exception:
                pass
        if t > since_ts:
            out.append(
                {
                    "id": r[0],
                    "domain": r[1] or "general",
                    "source": r[2] or "",
                    "preview": r[3] or "",
                    "ts": t,
                }
            )
    return out


def scan_emerging_topics(conn: sqlite3.Connection, threshold: int) -> list[tuple[str, int]]:
    """Topics biblio_topics avec count >= threshold."""
    rows = conn.execute(
        "SELECT topic, COUNT(*) as n FROM biblio_topics GROUP BY topic HAVING n >= ? ORDER BY n DESC LIMIT 30",
        (threshold,),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def existing_skill_path(slug: str) -> Path | None:
    """Retourne le path SKILL.md si le skill existe."""
    p = SKILLS_DIR / slug / "SKILL.md"
    return p if p.exists() else None


def propose_skill_update(slug: str, lessons: list[dict], topics: list[tuple[str, int]]) -> Path:
    """Génère une proposition d'update dans sandbox/skill_proposals/<slug>.md."""
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROPOSALS_DIR / f"{slug}.md"
    skill_md = existing_skill_path(slug)

    lines = [
        f"# Proposition d'enrichissement skill `{slug}`",
        "",
        f"**Généré** : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Skill cible** : `{skill_md or '(NOUVEAU — à créer)'}`",
        "**Source** : forge_skill_enricher daemon",
        "",
        "## Section à appendre",
        "",
        "```markdown",
        f"## Apprentissages {datetime.now().strftime('%Y-%m')}",
        "",
    ]
    if lessons:
        lines.append(f"### Leçons ancrées ({len(lessons)})")
        for l in lessons[:10]:
            lines.append(f"- **{l['source']}** ({l['domain']}) — {l['preview'][:200]}")
        lines.append("")
    if topics:
        lines.append("### Topics émergents (biblio_topics)")
        for t, n in topics[:10]:
            lines.append(f"- `{t}` (×{n} entries)")
        lines.append("")
    lines.append("```")
    lines.append("")
    lines.append("## Action recommandée")
    if skill_md:
        lines.append(f"- Append la section ci-dessus à `{skill_md}`")
        lines.append("- Ou submit pour review : `LAFORGE_PYTHON tools/biblio_cli.py promote ...`")
    else:
        lines.append(f"- Créer `docs/skills/{slug}/SKILL.md` depuis ce draft")
        lines.append("- Submit à SkillGuardian : `from forge_clawhub_bridge import SkillGuardian`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Marque ce fichier comme traité en le déplaçant dans `sandbox/skill_proposals/_done/`.")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def run_cycle(threshold: int, since_ts: float, auto_review: bool = False) -> dict:
    """Un cycle : scan → cluster → proposals.

    v0.2 fixes :
    - Dedup par skill cible (nokido n est ecrit qu une fois meme si rag+llm+systeme mappent dessus)
    - Pre-aggregation : on accumule lessons d abord, on ecrit a la fin
    - auto_review=True : appelle SkillGuardian.review() sur les proposals _new_*
    """
    conn = sqlite3.connect(str(DB), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")

    lessons = scan_recent_lessons(conn, since_ts)
    topics = scan_emerging_topics(conn, threshold)

    # 1. Cluster lessons par domain
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for l in lessons:
        by_domain[l["domain"]].append(l)

    # 2. Cluster topics par premier mot (heuristique simple)
    by_topic_root: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for t, n in topics:
        root = t.split()[0] if t else "misc"
        by_topic_root[root].append((t, n))

    # 3. v0.2 : aggregation par skill (pas par domain) AVANT ecriture
    by_skill: dict[str, dict] = defaultdict(lambda: {"lessons": [], "topics": [], "domains": set()})
    for domain, lst in by_domain.items():
        target_skill = DOMAIN_TO_SKILL.get(domain)
        slug = target_skill or f"_new_{domain}"
        by_skill[slug]["lessons"].extend(lst)
        by_skill[slug]["domains"].add(domain)
        # topics adjacents pour ce domain
        for root, ts in by_topic_root.items():
            if root.lower() in domain.lower() or domain.lower() in root.lower():
                by_skill[slug]["topics"].extend(ts)

    # 4. v0.2 : 1 seule ecriture par skill (dedup automatique)
    proposals_created = []
    review_results: list[dict] = []
    for slug, agg in by_skill.items():
        # dedup topics par nom + take top 8
        seen_t = set()
        uniq_topics = []
        for t, n in sorted(agg["topics"], key=lambda x: -x[1]):
            if t not in seen_t:
                seen_t.add(t)
                uniq_topics.append((t, n))
        # dedup lessons par id
        seen_l = set()
        uniq_lessons = []
        for l in agg["lessons"]:
            if l["id"] not in seen_l:
                seen_l.add(l["id"])
                uniq_lessons.append(l)
        path = propose_skill_update(slug, uniq_lessons, uniq_topics[:8])
        proposals_created.append(str(path))

        # 5. v0.2 : auto-review SkillGuardian pour les _new_*
        if auto_review and slug.startswith("_new_"):
            try:
                review_results.append(_review_proposal(path, slug))
            except Exception as e:
                review_results.append({"slug": slug, "ok": False, "err": str(e)[:160]})

    conn.close()
    return {
        "ts": datetime.now().isoformat(),
        "lessons_scanned": len(lessons),
        "topics_scanned": len(topics),
        "proposals_created": len(proposals_created),
        "skills_touched": list(by_skill.keys()),
        "proposals": proposals_created,
        "auto_reviewed": review_results,
    }


def _review_proposal(path: Path, slug: str) -> dict:
    """v0.2 : appelle SkillGuardian.review() sur une proposal _new_*.

    Construit un ClawSkill minimal depuis le markdown de la proposition,
    delegue a forge_clawhub_bridge.SkillGuardian. Stocke le verdict dans
    sandbox/skill_proposals/_review/<slug>.json.
    """
    import asyncio

    sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_clawhub_bridge import SkillGuardian, ClawSkill, SkillFile  # type: ignore
    except ImportError as e:
        return {"slug": slug, "ok": False, "err": f"clawhub import: {e}"}

    md_text = path.read_text(encoding="utf-8")
    skill = ClawSkill(
        slug=slug,
        name=slug.replace("_new_", "").replace("_", "-"),
        description=f"Skill draft proposed by forge_skill_enricher on {datetime.now().isoformat()}",
        version="0.0.1",
        files=[SkillFile(path="SKILL.md", content=md_text)],
    )
    try:
        guardian = SkillGuardian()
        result = asyncio.run(guardian.review(skill))
        verdict, score, reason = result if isinstance(result, tuple) else (str(result), 0.0, "")
        review_dir = PROPOSALS_DIR / "_review"
        review_dir.mkdir(parents=True, exist_ok=True)
        (review_dir / f"{slug}.json").write_text(
            json.dumps(
                {"slug": slug, "verdict": verdict, "score": score, "reason": reason, "ts": datetime.now().isoformat()},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {"slug": slug, "ok": True, "verdict": verdict, "score": round(score, 2)}
    except Exception as e:
        return {"slug": slug, "ok": False, "err": f"{type(e).__name__}: {str(e)[:160]}"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Nokido skill enricher daemon")
    ap.add_argument("--once", action="store_true", help="1 cycle puis exit")
    ap.add_argument("--daemon", action="store_true", help="boucle infinie cycle 1h")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_S)
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD, help="min count topic biblio (default 2)")
    ap.add_argument(
        "--auto-review", action="store_true", help="v0.2 : appel SkillGuardian.review() sur proposals _new_*"
    )
    args = ap.parse_args()

    if not args.once and not args.daemon:
        ap.error("Spécifie --once ou --daemon")

    state = _load_state()
    pid_dump = ROOT / "sandbox" / "skill_enricher.pid"
    if args.daemon:
        try:
            pid_dump.parent.mkdir(parents=True, exist_ok=True)
            pid_dump.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass

    while True:
        since = state.get("last_run_ts", 0)
        print(f"[skill_enricher] cycle start (since_ts={since}, threshold={args.threshold})", flush=True)
        stats = run_cycle(args.threshold, since, auto_review=args.auto_review)
        print(
            f"[skill_enricher] cycle done : "
            f"lessons={stats['lessons_scanned']} topics={stats['topics_scanned']} "
            f"proposals={stats['proposals_created']} skills={stats['skills_touched']}",
            flush=True,
        )
        for p in stats["proposals"]:
            print(f"  → {p}", flush=True)
        if stats.get("auto_reviewed"):
            print("[skill_enricher] SkillGuardian reviews :", flush=True)
            for rv in stats["auto_reviewed"]:
                ok = "✓" if rv.get("ok") else "✗"
                detail = (rv.get("verdict") + f" score={rv.get('score')}") if rv.get("ok") else rv.get("err", "")
                print(f"  {ok} {rv['slug']:30s}  {detail}", flush=True)

        state["last_run_ts"] = time.time()
        state.setdefault("skills_proposed", {})
        for slug in stats["skills_touched"]:
            state["skills_proposed"][slug] = state["skills_proposed"].get(slug, 0) + 1
        _save_state(state)
        _heartbeat(stats)

        if args.once:
            print("[skill_enricher] --once: exit", flush=True)
            return 0

        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
