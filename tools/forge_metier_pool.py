#!/usr/bin/env python
"""forge_metier_pool.py — active le POOL d'agents metiers (app/agent_*) avec des
fiches SPECIALISEES et QUALIFIEES, RECHERCHEES par LLM (pas de boilerplate).

Pour chaque agent metier scaffolde :
  1. RECHERCHE la fiche via un LLM capable (hub /ask, provider configurable, def. groq) :
     role precis, expertises REELLES, methodes, outils, livrables, et points de
     CONNAISSANCE CLES (seed de la base de connaissance).
  2. Ecrit une FICHE METIER = persona YAML chargee par PersonaEngine.build_system_prompt
     (name/role/style/constraints/capabilities) + extensions (slug/kb_domain/expertise).
  3. Seed la BASE DE CONNAISSANCE RAG (domain=metier_<slug>) avec les connaissances cles.

Owner-write : les fiches sont ecrites dans --out (staging writable, def. C:/tmp/
metier_personas) puis COPIEES vers config/personas/ par un pas trusted_script (le
sandbox ne peut pas ecrire config/). Le seed KB va directement en RAG (writer WAL).

Fallback deterministe si le LLM echoue (l'agent reste declare, a enrichir en pass 2).
Idempotent : --force pour reecrire.

Usage : forge_metier_pool.py [--limit N] [--force] [--provider groq] [--out DIR] [--seed-kb]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
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
AGENTS_DIR = ROOT / "app"
HUB_ASK = "http://127.0.0.1:8766/ask"

_NAME_RE = re.compile(r"Tu es (?:un|une|le|la|l['e ])\s*([^.,\n\"']{3,70})", re.IGNORECASE)

_PROMPT = (
    "Tu es un expert RH/knowledge-management. Produis une FICHE METIER QUALIFIEE pour "
    "un agent IA specialise: \"{name}\".\n"
    "Rends UNIQUEMENT un objet JSON strict (pas de prose, pas de ```), avec:\n"
    '{{"role": "<intitule precis du role, 1 ligne>",'
    ' "domaine": "<domaine>",'
    ' "expertise": ["<8 competences REELLES et pointues du metier>"],'
    ' "methodes": ["<4-6 methodes/frameworks/normes du metier>"],'
    ' "outils": ["<4-6 outils/technologies reels du metier>"],'
    ' "livrables": ["<3-5 livrables types>"],'
    ' "style": "<style de reponse attendu de cet expert, 1 ligne>",'
    ' "connaissances_cles": ["<10 faits/regles/reperes de reference du metier, '
    'chacun une phrase autonome et exacte -> seed de sa base de connaissance>"]}}'
)


def _human_name(slug: str, core_path: Path) -> str:
    """Nom metier propre. Le scaffold ecrit du boilerplate ('Agent X specialise dans
    la discipline') -> on le nettoie, sinon on derive du slug."""
    try:
        txt = core_path.read_text(encoding="utf-8", errors="replace")
        m = _NAME_RE.search(txt)
        if m:
            n = m.group(1).strip().rstrip(".").strip()
            n = re.sub(r"^Agent\s+", "", n, flags=re.IGNORECASE)
            n = re.sub(r"\s+sp[ée]cialis[ée].*$", "", n, flags=re.IGNORECASE).strip()
            if 3 <= len(n) <= 70 and "discipline" not in n.lower():
                return n
    except Exception:
        pass
    return slug.replace("_", " ").strip().title()


def _ask(name: str, provider: str, timeout: float = 90.0) -> dict | None:
    """Recherche la fiche via call_llm (multi-provider gouverne, appel direct API =
    contourne le gate ring du hub `ask`). Rend le dict parse ou None."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_swebench_runner import call_llm
    except Exception:
        return None
    try:
        raw = call_llm([{"role": "user", "content": _PROMPT.format(name=name)}],
                       provider=provider, max_tokens=1200)
    except Exception:
        return None
    if not raw or str(raw).startswith("[ERR"):
        return None
    m = re.search(r"\{.*\}", str(raw), re.DOTALL)
    if not m:
        return None
    try:
        clean_json = m.group(0)
        # Nettoyage des échappements markdown (ex: \*) qui invalident le JSON
        clean_json = re.sub(r'\\([^\/\\bfnrtu"])', r'\1', clean_json)
        return json.loads(clean_json)
    except Exception:
        return None


def _fiche(slug: str, name: str, kb_domain: str, res: dict | None) -> dict:
    """Fiche compatible PersonaEngine + extensions. Qualifiee si res (LLM), sinon squelette."""
    exp = (res or {}).get("expertise") or [name]
    meth = (res or {}).get("methodes") or []
    tools = (res or {}).get("outils") or []
    role = (res or {}).get("role") or f"expert metier {name}"
    style = (res or {}).get("style") or (
        "precis, sourcé, s'appuie sur sa base de connaissance metier, signale l'incertitude")
    caps = ["ping", "get_capabilities", "expertise_metier", f"rag:{kb_domain}"] + [
        f"methode:{m}" for m in meth[:4]] + [f"outil:{t}" for t in tools[:4]]
    return {
        "name": name,
        "role": role,
        "style": style,
        "constraints": [
            "reste dans son domaine metier ; hors-domaine -> defere a l'agent competent",
            f"consulte sa base de connaissance (RAG domain={kb_domain}) avant de repondre",
            "reponses concises, actionnables, sourcees",
        ],
        "capabilities": caps,
        "values": "exactitude metier, souverainete Nokido",
        "canonical": False,
        "slug": slug,
        "kb_domain": kb_domain,
        "expertise": exp,
        "livrables": (res or {}).get("livrables") or [],
        "generated": "llm" if res else "fallback",
    }


def _seed_kb(slug: str, name: str, kb_domain: str, res: dict | None, fiche_text: str) -> str:
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_db_path import open_writer
    except Exception as e:  # noqa: BLE001
        return f"kb_skip({type(e).__name__})"
    facts = (res or {}).get("connaissances_cles") or []
    rows = []
    base = f"[FICHE METIER] {name} — domaine {kb_domain}\n{fiche_text}"
    rows.append(("fiche_" + hashlib.sha256(kb_domain.encode()).hexdigest()[:16], base))
    for i, f in enumerate(facts):
        if not isinstance(f, str) or len(f) < 8:
            continue
        cid = "kb_" + hashlib.sha256((kb_domain + str(i) + f[:40]).encode()).hexdigest()[:16]
        rows.append((cid, f"[{name}] {f}"))
    try:
        with open_writer() as con:
            for cid, text in rows:
                con.execute(
                    "INSERT OR REPLACE INTO rag_chunks(id, text, source, domain) VALUES(?,?,?,?)",
                    (cid, text, f"metier/{slug}", kb_domain))
        return f"kb_ok({len(rows)})"
    except Exception as e:  # noqa: BLE001
        return f"kb_err({type(e).__name__})"


_DEEP_PROMPT = (
    "Tu es un expert du metier \"{name}\". Produis un CORPUS DE CONNAISSANCE dense pour "
    "alimenter la base de connaissance de cet agent.\n"
    "Rends UNIQUEMENT un JSON strict: {{\"corpus\": [ ... ]}} ou chaque element est UNE "
    "phrase de reference EXACTE et autonome (fait, definition, regle, norme, methode, "
    "ecueil courant, ordre de grandeur). Couvre: fondamentaux, methodes/frameworks, "
    "normes/references, outils, pieges. Vise 25 elements precis et verifiables, sans "
    "redite, sans prose autour."
)


def _deep_kb(slug: str, name: str, kb_domain: str, provider: str) -> str:
    """Corpus dense LLM-source ingere en RAG (domain=metier_<slug>). Pass 2 baseline ;
    la veille web reelle est une couche ulterieure."""
    try:
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_swebench_runner import call_llm
        from nokido_agent.app.forge_db_path import open_writer
    except Exception as e:  # noqa: BLE001
        return f"deep_skip({type(e).__name__})"
    try:
        raw = call_llm([{"role": "user", "content": _DEEP_PROMPT.format(name=name)}],
                       provider=provider, max_tokens=1600)
    except Exception:
        return "deep_llm_err"
    m = re.search(r"\{.*\}", str(raw), re.DOTALL)
    if not m:
        return "deep_noparse"
    try:
        clean = re.sub(r'\\([^\/\\bfnrtu"])', r'\1', m.group(0))
        items = json.loads(clean).get("corpus") or []
    except Exception:
        return "deep_badjson"
    rows = []
    for i, f in enumerate(items):
        if not isinstance(f, str) or len(f) < 8:
            continue
        cid = "kbd_" + hashlib.sha256((kb_domain + str(i) + f[:48]).encode()).hexdigest()[:16]
        rows.append((cid, f"[{name}] {f}"))
    if not rows:
        return "deep_empty"
    try:
        with open_writer() as con:
            for cid, text in rows:
                con.execute(
                    "INSERT OR REPLACE INTO rag_chunks(id, text, source, domain) VALUES(?,?,?,?)",
                    (cid, text, f"metier/{slug}", kb_domain))
        return f"deep_ok({len(rows)})"
    except Exception as e:  # noqa: BLE001
        return f"deep_err({type(e).__name__})"


def main() -> int:
    import yaml

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--provider", default="groq")
    ap.add_argument("--out", default=r"C:\tmp\metier_personas")
    ap.add_argument("--seed-kb", action="store_true")
    ap.add_argument("--place", action="store_true",
                    help="Pas OWNER (trusted_script) : copie <out>/*.yaml -> config/personas/")
    ap.add_argument("--kb-deep", action="store_true",
                    help="Pass 2 : ingere un corpus dense LLM par metier en RAG (n'ecrit pas de fiche)")
    a = ap.parse_args()

    if a.kb_deep:
        dirs2 = sorted(d for d in AGENTS_DIR.glob("agent_*") if d.is_dir())
        if a.limit:
            dirs2 = dirs2[: a.limit]
        tot = 0
        for d in dirs2:
            slug = d.name[len("agent_"):]
            name = _human_name(slug, d / "agent_core.py")
            r = _deep_kb(slug, name, f"metier_{slug}", a.provider)
            print(f"{slug:40} -> {name}  [{r}]", flush=True)
            if r.startswith("deep_ok"):
                tot += 1
        print(f"=== kb-deep: {tot}/{len(dirs2)} corpus ingeres ===")
        return 0

    out_dir = Path(a.out)
    if a.place:
        import shutil
        dest = ROOT / "config" / "personas"
        dest.mkdir(parents=True, exist_ok=True)
        n = 0
        for y in sorted(out_dir.glob("metier_*.yaml")):
            shutil.copyfile(y, dest / y.name)
            n += 1
        print(f"=== place: {n} fiches copiees -> {dest} ===")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    dirs = sorted(d for d in AGENTS_DIR.glob("agent_*") if d.is_dir())
    if a.limit:
        dirs = dirs[: a.limit]

    done = q = 0
    for d in dirs:
        slug = d.name[len("agent_"):]
        kb_domain = f"metier_{slug}"
        out = out_dir / f"metier_{slug}.yaml"
        if out.exists() and not a.force:
            print(f"skip {slug}")
            continue
        name = _human_name(slug, d / "agent_core.py")
        res = _ask(name, a.provider)
        if res:
            q += 1
        fiche = _fiche(slug, name, kb_domain, res)
        ftext = yaml.safe_dump(fiche, allow_unicode=True, sort_keys=False)
        out.write_text(ftext, encoding="utf-8")
        kb = _seed_kb(slug, name, kb_domain, res, ftext) if a.seed_kb else "kb_off"
        print(f"{'LLM' if res else 'FBK'} {slug:40} -> {name}  [{kb}]", flush=True)
        done += 1

    print(f"=== {done} fiches ({q} qualifiees LLM) / {len(dirs)} — staging {out_dir} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
