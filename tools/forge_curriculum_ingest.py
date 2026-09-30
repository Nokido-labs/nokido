#!/usr/bin/env python3
"""forge_curriculum_ingest.py — Ingestion de RÉFÉRENCES CANONIQUES par module du cursus
IA dans RAG domain='reference' (cercle de savoir, cf gouvernance épistémique).

Souverain + déporté (run_job). REUSE forge_ingest_pipeline (process_document + store_chunks),
zéro réinvention. Store TEXT-ONLY (embedding=None) -> le daemon forge_embed_auto_trigger
(:8099 BGE-M3) remplit les vecteurs en async = AUCUNE embolie inline (leçon reencode).

Chaque chunk reçoit l'enveloppe épistémique : trust_ring / knowledge_circle / verification
/ provenance / authenticity (cf rag_epistemic_governance). Le pool LOCAL gagne la connaissance.

Usage : LAFORGE_PYTHON tools/forge_curriculum_ingest.py --module 1   (ou --all, --dry)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_ingest_pipeline import process_document, store_chunks  # noqa: E402

UA = "Mozilla/5.0 (Nokido curriculum reference ingester)"

# Sources CANONIQUES libres, statiques (pas de SearXNG/Docker requis : fetch HTTP direct).
MODULES: dict[str, dict] = {
    # Veille owner 2026-07-30 — auto-amelioration de code par BIOMIMETISME. Declaree
    # ici plutot que par un wrapper dedie : `forge_veille_run` ingere tout module
    # `*_eco`, donc ajouter une entree SUFFIT (anti-dup, ids deterministes, ingestion
    # idempotente). Les deux depots Sakana passent par `forge_veille_clone_ingest`
    # (git clone), pas par le crawl : du code se lit au fichier, pas a la page HTML.
    "autoevo_eco": {
        "label": "Auto-amelioration de code par biomimetisme (evolution, immunite, fractal)",
        "subdomain": "autoevolution",
        "urls": [
            ("https://www.frontiersin.org/journals/artificial-intelligence/articles/"
             "10.3389/frai.2025.1662220/full", "frontiers:biomim_selfheal"),
            ("https://research.contrary.com/report/sakana-ai", "contrary:sakana_report"),
        ],
    },
    "1": {"label": "Programmation pour l'IA (Python, qualité code, Git)", "subdomain": "programming", "urls": [
        ("https://peps.python.org/pep-0008/", "python:style"),
        ("https://peps.python.org/pep-0020/", "python:zen"),
        ("https://docs.python.org/3/tutorial/controlflow.html", "python:controlflow"),
        ("https://docs.python.org/3/tutorial/datastructures.html", "python:datastructures"),
        ("https://docs.python.org/3/tutorial/errors.html", "python:errors"),
        ("https://docs.python.org/3/tutorial/classes.html", "python:classes"),
        ("https://docs.python.org/3/tutorial/modules.html", "python:modules"),
        ("https://docs.python.org/3/glossary.html", "python:glossary"),
        ("https://git-scm.com/book/en/v2/Git-Basics-Recording-Changes-to-the-Repository", "git:basics"),
    ]},
    "2": {"label": "Exploratory Data Analysis", "subdomain": "eda", "urls": [
        ("https://pandas.pydata.org/docs/user_guide/10min.html", "pandas:intro"),
        ("https://pandas.pydata.org/docs/user_guide/missing_data.html", "pandas:missing"),
        ("https://pandas.pydata.org/docs/user_guide/groupby.html", "pandas:groupby"),
        ("https://numpy.org/doc/stable/user/absolute_beginners.html", "numpy:basics"),
        ("https://matplotlib.org/stable/users/explain/quick_start.html", "viz:matplotlib"),
    ]},
    "3": {"label": "Infrastructure Data", "subdomain": "data_infra", "urls": [
        ("https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview", "http:overview"),
        ("https://www.postgresql.org/docs/current/tutorial-sql.html", "sql:tutorial"),
        ("https://en.wikipedia.org/wiki/Extract,_transform,_load", "etl:concept"),
        ("https://en.wikipedia.org/wiki/Data_pipeline", "pipeline:concept"),
    ]},
    "4": {"label": "Deep Learning", "subdomain": "deep_learning", "urls": [
        ("https://d2l.ai/chapter_linear-regression/index.html", "dl:linear"),
        ("https://d2l.ai/chapter_multilayer-perceptrons/index.html", "dl:mlp"),
        ("https://d2l.ai/chapter_convolutional-neural-networks/index.html", "dl:cnn"),
        ("https://en.wikipedia.org/wiki/Word_embedding", "dl:embeddings"),
    ]},
    "5": {"label": "IA Générative (LLM, RAG, agents)", "subdomain": "genai", "urls": [
        ("https://en.wikipedia.org/wiki/Transformer_(deep_learning_architecture)", "genai:transformer"),
        ("https://huggingface.co/docs/transformers/index", "genai:hf_transformers"),
        ("https://en.wikipedia.org/wiki/Retrieval-augmented_generation", "genai:rag"),
        ("https://www.promptingguide.ai/techniques", "genai:prompting"),
    ]},
    "6": {"label": "AI Engineering (MLOps/LLMOps)", "subdomain": "ai_engineering", "urls": [
        ("https://ml-ops.org/content/mlops-principles", "mlops:principles"),
        ("https://huggingface.co/docs/hub/spaces", "mlops:hf_spaces"),
        ("https://docs.docker.com/get-started/docker-overview/", "mlops:docker"),
        ("https://en.wikipedia.org/wiki/MLOps", "mlops:concept"),
    ]},
    "rfc": {"label": "RFC identité/nomenclature Nokido (durcissement)", "subdomain": "rfc", "urls": [
        ("https://www.rfc-editor.org/rfc/rfc6648.txt", "rfc:6648-deprecate-X"),
        ("https://www.rfc-editor.org/rfc/rfc5064.txt", "rfc:5064-header-abnf"),
        ("https://www.rfc-editor.org/rfc/rfc6838.txt", "rfc:6838-media-type-ns"),
        ("https://www.rfc-editor.org/rfc/rfc7595.txt", "rfc:7595-uri-scheme"),
        ("https://www.rfc-editor.org/rfc/rfc8615.txt", "rfc:8615-well-known"),
        ("https://www.rfc-editor.org/rfc/rfc4288.txt", "rfc:4288-media-type-reg"),
    ]},
    "gemini_eco": {"label": "Écosystème Gemini/Gemma (veille approfondie)", "subdomain": "gemini_eco", "urls": [
        ("https://ai.google.dev/gemini-api/docs/models", "gemini:models"),
        ("https://ai.google.dev/gemini-api/docs/openai", "gemini:openai-compat"),
        ("https://ai.google.dev/gemini-api/docs/rate-limits", "gemini:rate-limits"),
        ("https://ai.google.dev/gemini-api/docs/function-calling", "gemini:function-calling"),
        ("https://ai.google.dev/gemini-api/docs/structured-output", "gemini:structured"),
        ("https://ai.google.dev/gemini-api/docs/caching", "gemini:context-cache"),
        ("https://ai.google.dev/gemini-api/docs/thinking", "gemini:thinking"),
        ("https://ai.google.dev/gemini-api/docs/grounding", "gemini:grounding"),
        ("https://raw.githubusercontent.com/google-gemini/cookbook/main/README.md", "gemini:cookbook"),
        ("https://raw.githubusercontent.com/google-gemma/cookbook/main/README.md", "gemma:cookbook"),
    ]},
    "codex_eco": {"label": "Écosystème OpenAI/Codex (veille approfondie)", "subdomain": "openai_codex", "urls": [
        ("https://developers.openai.com/codex", "openai:codex"),
        ("https://developers.openai.com/", "openai:platform"),
        ("https://developers.openai.com/codex/cli", "openai:codex-cli"),
        ("https://developers.openai.com/codex/guides/config", "openai:codex-config"),
        ("https://raw.githubusercontent.com/openai/codex/main/README.md", "openai:codex-repo"),
    ]},
    "anthropic_eco": {"label": "Écosystème Anthropic/Claude (veille approfondie)", "subdomain": "anthropic_eco", "urls": [
        ("https://raw.githubusercontent.com/anthropics/claude-cookbooks/main/README.md", "anthropic:cookbooks"),
        ("https://raw.githubusercontent.com/anthropics/anthropic-sdk-python/main/README.md", "anthropic:sdk-python"),
        ("https://raw.githubusercontent.com/anthropics/courses/master/README.md", "anthropic:courses"),
        ("https://docs.claude.com/en/docs/build-with-claude/overview", "anthropic:build-docs"),
        ("https://docs.claude.com/en/docs/agents-and-tools/tool-use/overview", "anthropic:tool-use"),
        ("https://docs.claude.com/en/docs/build-with-claude/mcp", "anthropic:mcp"),
    ]},
}


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:  # noqa: S310 (canonical https docs)
        raw = r.read()
    html = raw.decode("utf-8", "replace")
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")
        for t in soup(["script", "style", "nav", "header", "footer", "noscript"]):
            t.decompose()
        txt = soup.get_text("\n")
    except Exception:
        txt = re.sub(r"<[^>]+>", " ", html)
    txt = re.sub(r"[ \t]{2,}", " ", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def ingest_module(mid: str, dry: bool = False) -> dict:
    m = MODULES[mid]
    total = 0
    report = []
    for url, role in m["urls"]:
        try:
            txt = fetch_text(url)
        except Exception as e:
            report.append({"url": url, "err": f"{type(e).__name__}: {str(e)[:120]}"})
            continue
        chunks = process_document(
            txt, source=url, domain_hint="reference",
            role_hint=f"reference:{m['subdomain']}:{role}", author="curriculum_ingest",
        )
        for c in chunks:
            c.meta.update({
                "trust_ring": "R1", "knowledge_circle": "reference",
                "verification": "canonical", "provenance": url,
                "authenticity": "official_docs", "curriculum_module": mid,
            })
        if not dry and chunks:
            try:
                store_chunks(chunks)
            except Exception as e:
                report.append({"url": url, "store_err": f"{type(e).__name__}: {str(e)[:120]}", "chunks": len(chunks)})
                continue
        total += len(chunks)
        report.append({"url": url, "chunks": len(chunks), "chars": len(txt)})
    return {"module": mid, "label": m["label"], "chunks_total": total, "detail": report}


# Snippets canoniques Nokido — patterns souverains réutilisables (constitués cette
# session), ingérés comme docset reference pour TOUT le swarm (synergie ; trust R0).
SNIPPETS: list[tuple] = [
    ("headless_cli", "reference:snippet:cli_headless",
     "Appeler un CLI OAuth (claude/gemini) en HEADLESS one-shot (PAS de REPL : bare = TUI/TTY qui hang sur un pipe).\n"
     "claude -p --output-format json, prompt sur stdin->EOF, lire stdout jusqu'EOF, parser .result.\n"
     "proc = await asyncio.create_subprocess_exec(bin, '-p','--output-format','json', stdin=PIPE, stdout=PIPE, stderr=PIPE)\n"
     "out,err = await proc.communicate(input=(prompt+'\\n').encode())\n"
     "result = json.loads(out)['result']   # gemini: -p texte, lire stdout brut (pas de JSON)."),
    ("identity_headers", "reference:snippet:identity_rfc",
     "En-têtes identité agent->hub (RFC 6648: PAS de X-, org-scopé ; RFC 5064: 1 valeur/header ABNF).\n"
     "headers = {'Authorization': f'Bearer {token}', 'LaForge-Agent-Name': agent,\n"
     "           'LaForge-Task-ID': task_id, 'LaForge-Agent-Purpose': purpose}\n"
     "# Hub résout LaForge-Agent-Name > Agent-Name (interim) > X-Agent-Name (legacy déprécié)."),
    ("hot_state_axeC", "reference:snippet:tier_ram",
     "Tier RAM hot Axe-C (forge_state mmap <1µs, cross-process, souverain zéro-Redis).\n"
     "from forge_state import publish_health, read_health, crystallize\n"
     "publish_health(cpu_pct=8.1, ram_pct=74.0, hub_up=True)   # santé ms-T, remplace health.json\n"
     "h = read_health()                                         # lecture zéro disque\n"
     "crystallize('mcts_winner', lambda k,v: blackboard_set(k,v))  # volatile->durable A/B"),
    ("dual_projection", "reference:snippet:scanner_AB",
     "Double-projection Axe A (vecteur) + Axe B (SQLite FTS) simultanée d'un flux texte.\n"
     "from forge_ingest_pipeline import process_document, store_chunks\n"
     "chunks = process_document(text, source=src, domain_hint='reference', role_hint='...')\n"
     "store_chunks(chunks)  # embedding=None -> daemon :8099 vectorise async (A) ; texte+FTS = B"),
    ("deport_job", "reference:snippet:deport_long",
     "Déporter une tâche longue/multi-étapes (jamais une série d'appels hub fins, cap 70s).\n"
     "run action=run_job script='tools/x.py' online=true notify_agent='claude'  # détaché, survit restart\n"
     "# poll: run action=job_status job_id=...  ; 1 résultat consolidé + notify à la fin."),
    ("boot_preflight", "reference:snippet:boot_syntax",
     "Preflight AST au boot (un .py cassé sur disque fail-close le gate hub SILENCIEUX au reboot).\n"
     "import ast; ast.parse(open(p, encoding='utf-8', errors='replace').read(), filename=p)\n"
     "# tools/forge_boot_syntax_check.py câblé en tête de nokido_start.ps1 -> alerte ROUGE précoce."),
]


def ingest_snippets(dry: bool = False) -> dict:
    total = 0
    for name, role, body in SNIPPETS:
        src = f"nokido://snippet/{name}"
        chunks = process_document(
            body, source=src, domain_hint="reference", role_hint=role, author="nokido_canonical",
        )
        for c in chunks:
            c.meta.update({
                "trust_ring": "R0", "knowledge_circle": "reference", "verification": "canonical",
                "provenance": src, "authenticity": "nokido_canonical", "snippet": name,
            })
        if not dry and chunks:
            try:
                store_chunks(chunks)
            except Exception:
                pass
        total += len(chunks)
    return {"module": "snippets", "label": "Snippets canoniques Nokido", "chunks_total": total,
            "detail": [s[0] for s in SNIPPETS]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", default="1")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--snippets", action="store_true", help="ingère aussi les snippets canoniques Nokido")
    ap.add_argument("--dry", action="store_true", help="fetch+chunk sans store")
    a = ap.parse_args()
    out = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "dry": a.dry}
    mods = list(MODULES) if a.all else [a.module]
    out["results"] = [ingest_module(m, a.dry) for m in mods]
    if a.snippets or a.all:
        out["results"].append(ingest_snippets(a.dry))
    out["chunks_total"] = sum(r["chunks_total"] for r in out["results"])
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
