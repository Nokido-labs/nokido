"""
app/forge_knowledge_distiller.py
==================================
Distille la connaissance Nokido vers un nouveau projet.

Extrait :
  1. system_rules (ring 0-2) — logique, lois absolues, patterns
  2. Patterns architecturaux depuis rag_chunks (forge_core, ia)
  3. Best practices (anti-lenteur, sécurité, tests)
  4. Glossaire des concepts clés

Produit :
  - {project}_knowledge.json  — règles + architecture portable
  - {project}_rag.db          — SQLite avec chunks distillés
  - {project}_primer.md       — README lisible par un LLM vierge

Usage CLI :
  python forge_knowledge_distiller.py --project mon-projet --output /chemin/
  python forge_knowledge_distiller.py --list-rules
"""

from __future__ import annotations
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"


# ── Extraction ────────────────────────────────────────────────────────────────


def extract_system_rules(conn: sqlite3.Connection, rings: list[int | None] = None) -> list[dict[str, str]]:
    rings = rings or [0, 1, 2]
    placeholders = ",".join("?" * len(rings))
    rows = conn.execute(
        f"SELECT tag, ring, title, content FROM system_rules WHERE ring IN ({placeholders}) ORDER BY ring, id", rings
    ).fetchall()
    return [{"tag": r[0], "ring": r[1], "title": r[2], "content": r[3]} for r in rows]


def extract_architecture_patterns(conn: sqlite3.Connection) -> list:
    """Extrait les chunks qui décrivent des décisions architecturales."""
    rows = conn.execute(
        "SELECT source, domain, text FROM rag_chunks "
        "WHERE domain IN ('forge_core','ia','code') "
        "AND (text LIKE '%DETACHED%' OR text LIKE '%mmap%' OR text LIKE '%watchdog%' "
        "     OR text LIKE '%state machine%' OR text LIKE '%security%' "
        "     OR text LIKE '%async%' OR text LIKE '%broadcast%' "
        "     OR text LIKE '%ring%' OR text LIKE '%RAG%') "
        "ORDER BY rowid DESC LIMIT 200"
    ).fetchall()
    return [{"source": r[0], "domain": r[1], "text": r[2][:500]} for r in rows]


def extract_best_practices(conn: sqlite3.Connection) -> list:
    """Extrait les best practices et anti-patterns."""
    rows = conn.execute(
        "SELECT source, domain, text FROM rag_chunks "
        "WHERE text LIKE '%NEVER%' OR text LIKE '%JAMAIS%' "
        "   OR text LIKE '%TOUJOURS%' OR text LIKE '%ALWAYS%' "
        "   OR text LIKE '%anti-lenteur%' OR text LIKE '%blocklist%' "
        "   OR text LIKE '%py_compile%' OR text LIKE '%PASS%' "
        "ORDER BY rowid DESC LIMIT 100"
    ).fetchall()
    return [{"source": r[0], "domain": r[1], "text": r[2][:500]} for r in rows]


def build_primer(project: str, rules: list, patterns: list, practices: list) -> str:
    """Génère un README markdown lisible par un LLM vierge."""
    lines = [
        f"# {project} — Knowledge Primer (distillé depuis Nokido v17)",
        "",
        "Ce document contient la connaissance distillée d'un projet IA Nokido.",
        "Il est conçu pour bootstrapper un nouveau projet avec les mêmes patterns.",
        "",
        "## Lois absolues (system_rules ring 0)",
        "",
    ]
    for r in [r for r in rules if r["ring"] == 0][:10]:
        lines.append(f"### {r['title']}")
        lines.append(r["content"][:300])
        lines.append("")

    lines += [
        "## Patterns architecturaux clés",
        "",
        "- **MMap** : Communication inter-process via fichier mémoire (live_bridge.map) — < 1µs, zéro réseau",
        "- **DETACHED_PROCESS** : Tout subprocess lancé avec `creationflags=0x00000008 + DEVNULL` — jamais bloquant",
        "- **State Machine Swarm** : IDLE → THINKING → STREAMING → SYNCING_RAG → IDLE",
        "- **Security by design** : Credentials dans singleton _Config, inputs validés, SSH blocklist",
        "- **Watchdog** : Process indépendant surveille heartbeat mmap, `TerminateProcess` si freeze > 10s",
        "- **RAG ring** : Chunks humains = ring 2 (TRUSTED), agents = ring 3, web = ring 4",
        "",
        "## Anti-patterns à éviter",
        "",
        "- ❌ `while proc.poll() is None` dans le thread principal → DÉTACHE le process",
        "- ❌ `open(file, 'w')` en écriture bloquante sur le hot path → DEVNULL ou async",
        "- ❌ Import lourd au top-level dans un worker → importer dans `run()`",
        "- ❌ Socket UDP pour IPC local → MMap ou file mmap",
        "- ❌ Credentials en clair dans le code → singleton Config lu une seule fois",
        "",
        "## Patterns de test",
        "",
        "- `py_compile.compile()` avant tout commit",
        "- `ast.parse()` pour vérifier la structure sans importer",
        "- NR headless : tests sans UI, sans import bloquant",
        "- fast_check : 8-16 tests AST en < 5s",
        "",
        "## Statistiques",
        f"- {len(rules)} system_rules distillées",
        f"- {len(patterns)} patterns architecturaux",
        f"- {len(practices)} best practices",
        f"- Généré le {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────


def distill(project: str, output_dir: Path, include: list = None, rings: list = None):
    include = include or ["rules", "arch", "practices"]
    rings = rings or [0, 1, 2]
    output_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB), timeout=10)

    rules = extract_system_rules(conn, rings) if "rules" in include else []
    patterns = extract_architecture_patterns(conn) if "arch" in include else []
    practices = extract_best_practices(conn) if "practices" in include else []
    conn.close()

    # 1. JSON knowledge
    knowledge = {
        "project": project,
        "source": "Nokido v17",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "system_rules": rules,
        "architecture_patterns": patterns,
        "best_practices": practices,
        "meta": {
            "rules_count": len(rules),
            "patterns_count": len(patterns),
            "practices_count": len(practices),
        },
    }
    json_out = output_dir / (project + "_knowledge.json")
    json_out.write_text(json.dumps(knowledge, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Knowledge JSON → {json_out}")

    # 2. RAG DB externe
    db_out = output_dir / (project + "_rag.db")
    conn2 = sqlite3.connect(str(db_out))
    conn2.execute("""CREATE TABLE IF NOT EXISTS rag_chunks
        (id INTEGER PRIMARY KEY, source TEXT, domain TEXT, text TEXT,
         meta TEXT DEFAULT '{}')""")
    conn2.execute("""CREATE TABLE IF NOT EXISTS embeddings
        (id INTEGER PRIMARY KEY, file_path TEXT, vector BLOB)""")
    all_chunks = (
        [(r["source"], r["domain"], r["text"]) for r in patterns]
        + [(r["source"], r["domain"], r["text"]) for r in practices]
        + [("system_rules", "rules", r["content"]) for r in rules]
    )
    conn2.executemany("INSERT INTO rag_chunks(source,domain,text) VALUES(?,?,?)", all_chunks)
    conn2.commit()
    conn2.close()
    print(f"✅ RAG DB externe → {db_out} ({len(all_chunks)} chunks)")

    # 3. Primer markdown
    primer_out = output_dir / (project + "_primer.md")
    primer_out.write_text(build_primer(project, rules, patterns, practices), encoding="utf-8")
    print(f"✅ Primer MD → {primer_out}")

    return {
        "ok": True,
        "json": str(json_out),
        "db": str(db_out),
        "primer": str(primer_out),
        "rules": len(rules),
        "patterns": len(patterns),
        "practices": len(practices),
    }


def main():
    parser = argparse.ArgumentParser(description="Nokido Knowledge Distiller")
    parser.add_argument("--project", required=False, default="distilled", help="Nom du projet cible")
    parser.add_argument("--output", default=str(ROOT / "distilled"), help="Dossier de sortie")
    parser.add_argument(
        "--include", default="rules,arch,practices", help="Contenu à inclure (rules,arch,practices,full)"
    )
    parser.add_argument("--rings", default="0,1,2", help="Rings system_rules à inclure")
    parser.add_argument("--list-rules", action="store_true", help="Lister les system_rules disponibles")
    args = parser.parse_args()

    if args.list_rules:
        conn = sqlite3.connect(str(DB), timeout=5)
        rows = conn.execute("SELECT ring, tag, title FROM system_rules ORDER BY ring, id").fetchall()
        conn.close()
        for r in rows:
            print(f"[ring={r[0]}] {r[1]:20s} {r[2]}")
        return

    result = distill(
        project=args.project,
        output_dir=Path(args.output),
        include=args.include.split(","),
        rings=[int(r) for r in args.rings.split(",")],
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
