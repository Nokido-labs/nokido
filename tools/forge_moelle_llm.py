"""Moelle d'usage optimal des LLM -- phase B (owner 24/10 : « substantifique moelle a extraire des
connaissances ingerees sur l'utilisation optimum de chaque LLM et la possibilite de Nokido de bien
les orchestrer »).

Pour chaque THEME (prompting, outils, cache, effort, contexte, batch, conseiller, cout, quotas,
sorties structurees) : extraits PAR INDEX FTS (rag_chunks_fts MATCH, filtre par colonne `source`,
plafond par page contre la sur-fragmentation mesuree en phase A -- ac669d992), brouillon par le
free tier, relecture par le conseiller (patron advisor souverain), version corrigee. Sortie : un
.md par theme qui CITE ses sources et ses fournisseurs, + index.json.

Interdits : aucun balayage de la base (EXPLAIN verifie : `VIRTUAL TABLE INDEX`) ; jamais Claude dans
la cascade d'un travail de masse (slots_gratuits) ; un theme sans source ou sans reponse est ecrit
INDISPONIBLE, jamais invente. Le pare-feu (pre_flight, redact_text, SecretGuard) est applique par
call_cascade du routeur -- pas refait ici.

Usage : LAFORGE_PYTHON tools/forge_moelle_llm.py [--themes cache,effort] [--sortie DIR] [--plan]
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/consolidation_semantique"

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _racine_donnees():
    """DONNEES par forge_db_path.racine_donnees() (cliquet racine_donnees) ; repli : racine du code, comme avant."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        try:
            from forge_db_path import racine_donnees
        except ImportError:
            return RACINE
    return racine_donnees()


_RACINE_DONNEES = _racine_donnees()
BASE = "%NOKIDO_DATA%\embeddings.db"
SORTIE = _RACINE_DONNEES / "sandbox" / "workspace" / "moelle_llm"

THEMES = {
    "prompting": ["prompt", "best", "practices"],
    "outils": ["tool", "use", "definitions"],
    "cache": ["prompt", "caching"],
    "effort_thinking": ["reasoning", "effort"],
    "contexte": ["context", "window", "compaction"],
    "batch": ["batch", "api"],
    "conseiller_multi_agents": ["subagents", "orchestration"],
    "cout": ["pricing", "tokens", "cost"],
    "quotas": ["rate", "limits"],
    "sorties_structurees": ["structured", "outputs", "json"],
}
# Phrases FTS sur la colonne `source` (unicode61 coupe `claude_docs` en « claude docs »).
SURFACES = {
    "anthropic": ["claude docs", "claude code docs", "anthropic"],
    "openai_codex": ["openai", "codex"],
    "google_gemini": ["gemini", "google", "antigravity"],
    "mistral": ["mistral"],
    "ollama_groq_openrouter": ["ollama", "groq", "openrouter"],
    "deepseek": ["deepseek"],
}


def requete_fts(mots, prefixes) -> str:
    """Mots quotes un par un (ET implicite), sources en phrases OU -- jamais de terme brut dans MATCH."""
    q = lambda m: '"%s"' % str(m).replace('"', '""')  # noqa: E731
    return "(%s) AND (%s)" % (" ".join(q(m) for m in mots), " OR ".join("source:%s" % q(p) for p in prefixes))


def extraits(cx, requete, max_pages=3, par_page=2, max_car=1800, candidats=40):
    """(source, texte) classes par bm25, au plus `par_page` morceaux par page et `max_pages` pages."""
    vus, out = {}, []
    for source, texte in cx.execute(
            "SELECT source, text FROM rag_chunks_fts WHERE rag_chunks_fts MATCH ? "
            "ORDER BY bm25(rag_chunks_fts) LIMIT ?", (requete, candidats)):
        if source not in vus and len(vus) >= max_pages:
            continue
        if vus.get(source, 0) >= par_page:
            continue
        vus[source] = vus.get(source, 0) + 1
        out.append((source, " ".join(str(texte or "").split())[:max_car]))
    return out


def slots_gratuits(chaine) -> int:
    """Nombre de slots en TETE de cascade avant le premier slot Claude (oauth/claude/anthropic)."""
    n = 0
    for s in chaine:
        if any(m in str(s).lower() for m in ("oauth", "claude", "anthropic")):
            break
        n += 1
    return n


def _ecrire(sortie, theme, corps, sources, etat, fournisseurs):
    lignes = ["# Moelle LLM -- %s" % theme, "", "Etat : **%s** -- fournisseurs : %s -- %s" % (
        etat, ", ".join(f or "?" for f in fournisseurs) or "aucun", time.strftime("%Y-%m-%d %H:%M")), "",
        corps, "", "## Sources (rag_chunks, par index)", ""]
    lignes += ["- `%s`" % s for s in sorted(set(sources))] or ["- aucune"]
    Path(sortie).mkdir(parents=True, exist_ok=True)
    (Path(sortie) / ("%s.md" % theme)).write_text("\n".join(lignes) + "\n", encoding="utf-8")


def traiter_theme(cx, theme, mots, surfaces, appel, sortie) -> dict:
    """Brouillon (free tier) -> avis du conseiller -> version corrigee. `appel(prompt) -> dict` du routeur."""
    blocs, sources = [], []
    for surf, prefixes in surfaces.items():
        ex = extraits(cx, requete_fts(mots, prefixes))
        sources += [s for s, _ in ex]
        if ex:
            blocs.append("### %s\n" % surf + "\n".join("[%s] %s" % (s, t) for s, t in ex))
    res = {"theme": theme, "sources": sorted(set(sources)), "fournisseurs": [], "etat": "INDISPONIBLE"}
    if not blocs:
        _ecrire(sortie, theme, "INDISPONIBLE : aucun extrait trouve par l'index pour %s." % mots, [], "INDISPONIBLE", [])
        return res
    doc = "\n\n".join(blocs)[:14000]
    etapes = [
        "A partir des extraits de documentation ci-dessous (anglais), redige en FRANCAIS une synthese "
        "pratique du theme « %s » : par surface, ce qu'il faut faire pour un usage OPTIMAL (cout, qualite, "
        "latence) et comment un orchestrateur multi-modeles (Nokido) devrait en tirer parti. Chaque affirmation "
        "cite sa source entre crochets. N'invente rien : ce qui n'est pas dans les extraits est INCONNU.\n\n%s" % (theme, doc),
        None, None]
    textes = []
    for i in range(3):
        if i == 1:
            p = ("Tu es un conseiller exigeant. Releve dans ce brouillon les erreurs, affirmations non sourcees "
                 "et omissions importantes au regard des extraits. Avis court et actionnable.\n\nBROUILLON:\n%s"
                 "\n\nEXTRAITS:\n%s" % (textes[0], doc[:8000]))
        elif i == 2:
            p = ("Corrige le brouillon selon l'avis, garde les citations [source], francais, sans rien inventer."
                 "\n\nAVIS:\n%s\n\nBROUILLON:\n%s" % (textes[1], textes[0]))
        else:
            p = etapes[0]
        r = appel(p) or {}
        if not r.get("ok") or not (r.get("text") or "").strip():
            res["erreur"] = "etape %d : %s" % (i, str(r.get("error") or "reponse vide")[:200])
            _ecrire(sortie, theme, "INDISPONIBLE : %s" % res["erreur"], sources, "INDISPONIBLE", res["fournisseurs"])
            return res
        textes.append(r["text"].strip())
        res["fournisseurs"].append(r.get("provider"))
    res["etat"] = "FAIT"
    _ecrire(sortie, theme, textes[2] + "\n\n## Avis du conseiller\n\n" + textes[1], sources, "FAIT", res["fournisseurs"])
    return res


def _appel_routeur(max_tokens=1600):
    sys.path[:0] = [str(RACINE), str(RACINE / "app")]
    import forge_llm_router as R  # noqa: PLC0415

    n = slots_gratuits(R.USE_CASE_CHAINS["conseil"])
    if n == 0:
        raise SystemExit("cascade conseil sans slot gratuit en tete : refus (pas de Claude en masse)")
    return lambda p: R.get_router().call_cascade(p, use_case="conseil", max_tokens=max_tokens, max_attempts=n)


def main(argv=None) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--themes", default=",".join(THEMES))
    a.add_argument("--sortie", default=str(SORTIE))
    a.add_argument("--plan", action="store_true", help="EXPLAIN QUERY PLAN seulement")
    o = a.parse_args(argv)
    cx = sqlite3.connect("file:%s?mode=ro" % BASE, uri=True, timeout=10)
    themes = [t for t in o.themes.split(",") if t in THEMES]
    if o.plan:
        q = requete_fts(THEMES[themes[0]], SURFACES["anthropic"])
        plan = [r[3] for r in cx.execute("EXPLAIN QUERY PLAN SELECT source FROM rag_chunks_fts WHERE "
                                         "rag_chunks_fts MATCH ? ORDER BY bm25(rag_chunks_fts) LIMIT 40", (q,))]
        print(json.dumps(plan, ensure_ascii=False))
        return 0 if any("VIRTUAL TABLE INDEX" in p for p in plan) else 2
    appel = _appel_routeur()
    bilan = [traiter_theme(cx, t, THEMES[t], SURFACES, appel, o.sortie) for t in themes]
    (Path(o.sortie) / "index.json").write_text(json.dumps(bilan, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps([{k: b[k] for k in ("theme", "etat", "fournisseurs")} | {"n_sources": len(b["sources"])}
                      for b in bilan], ensure_ascii=False))
    return 0 if all(b["etat"] == "FAIT" for b in bilan) else 1


if __name__ == "__main__":
    sys.exit(main())
