"""
__FORGE_COLOR__ : digestif/sens (ingestion) + qualité (skills)

forge_skill_forge — Génération NATIVE de SKILL.md depuis une source (URL doc / texte).

Réimplémentation SOUVERAINE du subset utile de Skill_Seekers (yusufkaraaslan, MIT). AUCUN code
tiers, AUCUNE dépendance pip externe : on COMPOSE les primitives Nokido existantes (anti-dup) —
  fetch     = forge_crawl_tool.crawl_url   (trafilatura → markdown épuré)
  structure = forge_agent_proxy.ask        (LLM LOCAL/souverain — JAMAIS API claude/gemini bare)
  review    = forge_clawhub_bridge.SkillGuardian.review (patterns + LLM + SAST)
  install   = action PRIVILÉGIÉE gatée (écrit docs/skills/ uniquement sur confirm+owner)

La capacité ÉMANE de Nokido (exposée comme tool hub dynamique `skill_forge`) → remplace le POC
« voie B » externe (registre upstream du serveur MIT). Comme c'est réimplémenté natif, « la
mention [MIT] n'est plus utile » : 0 ligne de Skill_Seekers ici. Le SKILL.md généré est écrit en
PROPOSITION (sandbox/skill_proposals), jamais directement dans docs/skills (privilégié).
"""
from __future__ import annotations

import asyncio
import json as _json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # LaForge/
PROPOSALS = ROOT / "sandbox" / "skill_proposals"
SKILLS_DIR = ROOT / "docs" / "skills"

# providers souverains autorisés. Règle owner NON négociable : jamais d'API claude/gemini bare.
_SAFE_PROVIDERS = ("router", "router_local", "groq", "cerebras", "ollama", "lmstudio",
                   "llamacpp", "sambanova", "docker")
_FORBIDDEN = ("claude", "gemini", "anthropic", "google")

_FM = re.compile(r"^\s*---\s*\n.*?\n---\s*\n", re.DOTALL)

STRUCT_PROMPT = (
    "Tu transformes de la DOCUMENTATION en un fichier SKILL.md pour un agent. Produis UNIQUEMENT "
    "le contenu markdown du SKILL.md, rien d'autre.\n"
    "1) Frontmatter YAML en tête : `name: {slug}` puis `description:` (un paragraphe listant les "
    "TRIGGERS = quand déclencher ce skill).\n"
    "2) Corps : sections '## Quand se déclencher', '## Usage', '## Exemples', '## Anti-patterns'.\n"
    "Reste fidèle à la doc, n'invente pas d'API. Concis."
)


def _safe_provider(p: str) -> str:
    """Force un provider souverain. API claude/gemini bare interdite → fallback 'router'."""
    p = (p or "router").strip().lower()
    if any(p == b or p.startswith(b) for b in _FORBIDDEN):
        return "router"
    return p if p in _SAFE_PROVIDERS else "router"


def _slugify(s: str) -> str:
    s = re.sub(r"^https?://", "", (s or "").strip().lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:48] or "skill-auto"


def _ensure_frontmatter(md: str, slug: str, source: str) -> str:
    """Garantit un frontmatter YAML name/description (sinon en injecte un minimal)."""
    if _FM.match(md):
        return md
    desc = f"Skill auto-généré depuis {source} (review SkillGuardian requise avant install)."
    return f"---\nname: {slug}\ndescription: >\n  {desc}\n---\n\n" + md.lstrip()


def _extract_text(r) -> str:
    if isinstance(r, dict):
        return (r.get("text") or r.get("response") or r.get("content") or r.get("answer") or "").strip()
    return str(r or "").strip()


async def _structure(doc_md: str, slug: str, source: str, provider: str) -> str:
    from nokido_agent.app.forge_agent_proxy import ask

    msg = (f"{STRUCT_PROMPT.replace('{slug}', slug)}\n\n## SOURCE\n{source}\n\n"
           f"## DOCUMENTATION (markdown)\n{doc_md[:24000]}")
    try:
        r = await ask(_safe_provider(provider), msg, rag_context=False, max_tokens=1800, timeout=120)
        text = _extract_text(r)
    except Exception as e:  # noqa: BLE001
        text = ""
    if not text:
        text = f"## Quand se déclencher\nDoc : {source}\n\n## Usage\n{doc_md[:2000]}"
    return _ensure_frontmatter(text, slug, source)


def _build_clawskill(slug: str, skill_md: str):
    from nokido_agent.app.forge_clawhub_bridge import ClawSkill

    body = _FM.sub("", skill_md).strip()
    desc = next((ln.strip("# ").strip() for ln in body.splitlines() if ln.strip()), slug)[:200]
    return ClawSkill(slug=slug, name=slug, description=desc, version="0.1.0-auto",
                     author="laforge-skill-forge", skill_md=skill_md)


def _write_proposal(slug: str, skill_md: str, meta: dict) -> str:
    d = PROPOSALS / f"_new_{slug}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (d / "_meta.json").write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(d / "SKILL.md")


async def forge_skill_from_text(doc_md: str, slug: str, source: str = "text", provider: str = "router") -> dict:
    t0 = time.time()
    slug = _slugify(slug)
    skill_md = await _structure(doc_md, slug, source, provider)
    status, risk, reason = "unreviewed", 0.0, "guardian indispo"
    try:
        from nokido_agent.app.forge_clawhub_bridge import SkillGuardian

        status, risk, reason = await SkillGuardian().review(_build_clawskill(slug, skill_md))
    except Exception as e:  # noqa: BLE001
        reason = f"review skip: {e!r}"
    meta = {"slug": slug, "source": source, "provider": _safe_provider(provider),
            "review_status": status, "risk": risk, "reason": reason,
            "elapsed_s": round(time.time() - t0, 1)}
    proposal = _write_proposal(slug, skill_md, meta)
    return {"ok": True, "proposal_path": proposal, **meta}


async def forge_skill_from_url(url: str, slug: str = None, provider: str = "router") -> dict:
    from nokido_agent.app.forge_crawl_tool import crawl_url

    try:
        md = crawl_url(url)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"crawl échec {url}: {e!r}"}
    if not md or len(md) < 80:
        return {"ok": False, "error": f"crawl vide/insuffisant pour {url}"}
    return await forge_skill_from_text(md, slug or url, source=url, provider=provider)


def install_skill(slug: str, confirm: bool = False, owner: bool = False) -> dict:
    """ACTION PRIVILÉGIÉE : merge la proposition → docs/skills/<slug>/ (tracké). Default-deny :
    requiert confirm=True ET owner=True (à coordonner via blackboard/owner). Jamais d'install solo."""
    slug = _slugify(slug)
    src = PROPOSALS / f"_new_{slug}" / "SKILL.md"
    if not src.exists():
        return {"ok": False, "error": f"proposition absente: {src}"}
    if not (confirm and owner):
        return {"ok": False, "blocked": "action privilégiée: requiert confirm=True + owner=True",
                "proposal_path": str(src)}
    dst = SKILLS_DIR / slug
    dst.mkdir(parents=True, exist_ok=True)
    dst_md = dst / "SKILL.md"
    dst_md.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return {"ok": True, "installed": str(dst_md)}


# ── wrappers sync pour le tool hub / CLI ─────────────────────────────────────────────
def from_url(url: str, slug: str = None, provider: str = "router") -> dict:
    return asyncio.run(forge_skill_from_url(url, slug=slug, provider=provider))


def from_text(doc_md: str, slug: str, source: str = "text", provider: str = "router") -> dict:
    return asyncio.run(forge_skill_from_text(doc_md, slug, source=source, provider=provider))
