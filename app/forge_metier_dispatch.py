"""forge_metier_dispatch.py — route une tâche vers la BONNE persona métier + sa KB.

Chaînon manquant du pool agentique (89 fiches `config/personas/metier_*.yaml`, KB seedée
`domain=metier_<slug>`, PersonaEngine=92) : les fiches et la KB existaient, mais RIEN ne
routait une tâche vers la bonne persona. `PersonaEngine.route_intent` choisit un MODÈLE
(mots-clés → flash/pro), pas un métier ; `route_by_probe` gère l'escalade. Ni l'un ni
l'autre ne sélectionne parmi les 89 métiers. Ce module comble ce trou.

Routage SÉMANTIQUE (« indexation intelligente au service de la cognition », owner 24/07) :
on embed la tâche (BGE-M3 via forge_embed_router → :8099 souverain) et on la compare au
texte-signature de chaque persona (name + expertise + capabilities). Cosinus, top-1. Repli
LEXICAL déterministe si l'embedder est indisponible — jamais un silence (trois états).

`dispatch(task)` rend un bundle PRÊT à exécuter : persona choisie, alternatives, contexte KB
(RAG `domain=metier_<slug>`), et le system_prompt qualifié (PersonaEngine.build_system_prompt).
L'exécution LLM elle-même reste au client/hub ; ici on ASSEMBLE le bon contexte.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "cognition/aiguillage-metier"

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
CACHE = ROOT / "sandbox" / "workspace" / "metier_route_emb.json"
_MOT = re.compile(r"[a-zA-Zà-ÿ][\wà-ÿ]{2,}")


def _engine():
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_persona_engine import PersonaEngine
    return PersonaEngine()


def _personas_metier(pe) -> list[dict]:
    """Les personas MÉTIER (kb_domain=metier_*), avec leur texte-signature de routage.

    `PersonaEngine.load_all()` PEUPLE `self.personas` mais retourne None (mesuré 02/08) :
    on appelle pour l'effet, puis on lit l'attribut.
    """
    pe.load_all()
    out = []
    for nom, p in pe.personas.items():
        kb = p.get("kb_domain") or ""
        if not kb.startswith("metier_"):
            continue
        sig = " ; ".join([
            str(p.get("name") or nom),
            " ".join(p.get("expertise") or []),
            " ".join(c for c in (p.get("capabilities") or []) if not c.startswith(("ping", "get_", "expertise", "rag:"))),
        ])
        out.append({"name": p.get("name") or nom, "slug": p.get("slug") or kb[7:],
                    "kb_domain": kb, "sig": sig})
    return out


def _embed_batch(texts: list[str]):
    """Embeddings souverains via `embed_batch_fast` (BGE-M3 :8099).

    PAS `embed_batch` : mesuré le 02/08, `forge_embed_router.embed_batch` est défini DEUX
    fois (la 2e shadow la 1re) et la gagnante rend `None` — alors que `embed_batch_fast` ET
    le call direct `_llama8099_call` rendent des vecteurs 1024D. Bug d'infra tracé au roadmap
    (embed_batch_double_def_none). On passe par le chemin qui MARCHE.
    """
    try:
        from nokido_agent.app.forge_embed_router import embed_batch_fast
        vs = embed_batch_fast(texts)
        return [np.asarray(v, dtype=np.float32) if v is not None else None for v in vs]
    except Exception:  # muet-ok : repli lexical
        return [None] * len(texts)


def _embed(text: str):
    """Embedding souverain d'un texte, ou None si indisponible (jamais un vecteur bidon)."""
    vs = _embed_batch([text])
    return vs[0] if vs else None


def _sig_hash(personas: list[dict]) -> str:
    h = hashlib.sha256()
    for p in personas:
        h.update((p["slug"] + "\x1f" + p["sig"]).encode("utf-8"))
    return h.hexdigest()[:16]


def _persona_vecs(personas: list[dict]):
    """Vecteurs-signature des personas, CACHÉS par hash de contenu (évite de ré-embed 89×)."""
    clef = _sig_hash(personas)
    try:
        c = json.loads(CACHE.read_text(encoding="utf-8"))
        if c.get("hash") == clef:
            return {s: np.asarray(v, dtype=np.float32) for s, v in c["vecs"].items()}
    except (OSError, ValueError, KeyError):  # muet-ok : cache absent/perime -> on re-embed
        pass
    vecs = _embed_batch([p["sig"] for p in personas])
    par_slug = {p["slug"]: v for p, v in zip(personas, vecs) if v is not None}
    if par_slug:
        try:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(
                {"hash": clef, "vecs": {s: v.tolist() for s, v in par_slug.items()}},
                ensure_ascii=False), encoding="utf-8")
        except OSError:  # muet-ok : cache best-effort, le routage marche sans
            pass
    return par_slug


def _cos(a, b) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na and nb else 0.0


def _route_lexical(task: str, personas: list[dict], top_k: int) -> list[dict]:
    """Repli déterministe : recouvrement des mots de la tâche avec le texte-signature."""
    mots = {m.group(0).lower() for m in _MOT.finditer(task)}
    scored = []
    for p in personas:
        sig = {m.group(0).lower() for m in _MOT.finditer(p["sig"])}
        inter = len(mots & sig)
        scored.append({**p, "score": inter / (len(mots) or 1)})
    scored.sort(key=lambda x: -x["score"])
    return scored[:top_k]


def route(task: str, top_k: int = 3) -> dict:
    """Rend les personas métier les mieux alignées + la méthode employée (jamais muette)."""
    pe = _engine()
    personas = _personas_metier(pe)
    if not personas:
        return {"methode": "ILLISIBLE", "raison": "aucune persona metier chargee", "candidats": []}
    qv = _embed(task)
    par_slug = _persona_vecs(personas) if qv is not None else {}
    if qv is not None and par_slug:
        scored = [{**p, "score": _cos(qv, par_slug[p["slug"]])}
                  for p in personas if p["slug"] in par_slug]
        scored.sort(key=lambda x: -x["score"])
        return {"methode": "semantique", "candidats": scored[:top_k]}
    return {"methode": "lexical", "candidats": _route_lexical(task, personas, top_k)}


def _kb_context(kb_domain: str, task: str, limite: int = 6) -> list[str]:
    """Connaissances-clés du métier, classées par recouvrement lexical avec la tâche."""
    if not DB.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB))
        rows = conn.execute(
            "SELECT text FROM rag_chunks WHERE domain=? LIMIT 40", (kb_domain,)).fetchall()
        conn.close()
    except sqlite3.Error:
        return []
    mots = {m.group(0).lower() for m in _MOT.finditer(task)}
    scored = []
    for (t,) in rows:
        sig = {m.group(0).lower() for m in _MOT.finditer(t or "")}
        scored.append((len(mots & sig), t))
    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored[:limite]]


def dispatch(task: str) -> dict:
    """Bundle PRÊT à exécuter : persona + alternatives + contexte KB + system_prompt."""
    r = route(task, top_k=3)
    if not r["candidats"]:
        return {"ok": False, "methode": r["methode"], "raison": r.get("raison", "pas de candidat")}
    best = r["candidats"][0]
    pe = _engine()
    try:
        prompt = pe.build_system_prompt(best["name"])
    except Exception as e:  # noqa: BLE001
        prompt = f"(system_prompt indisponible: {type(e).__name__})"
    return {
        "ok": True,
        "methode": r["methode"],
        "persona": best["name"],
        "slug": best["slug"],
        "score": round(best.get("score", 0.0), 4),
        "alternatives": [{"persona": c["name"], "score": round(c.get("score", 0.0), 4)}
                         for c in r["candidats"][1:]],
        "kb_context": _kb_context(best["kb_domain"], task),
        "system_prompt": prompt,
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--task", required=True)
    ap.add_argument("--full", action="store_true", help="inclut system_prompt + KB")
    args = ap.parse_args()
    d = dispatch(args.task)
    if not args.full:
        d.pop("system_prompt", None)
        d["kb_context"] = f"{len(d.get('kb_context') or [])} entree(s) KB"
    print(json.dumps(d, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
