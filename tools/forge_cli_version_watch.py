#!/usr/bin/env python3
"""forge_cli_version_watch.py — detecte ce qui a BOUGE chez les CLI et leurs docs.

DEMANDE OWNER 2026-08-20 : « a chaque mise a jour de claude je veux que tu check
s'il y a du neuf, pareil pour tous les cli ! », dit juste apres « tu ne sais pas
toi-meme utiliser a 100 % tes capacites ». Le probleme n'est pas qu'une capacite
manque : c'est qu'elle est RECENTE et qu'on l'ignore, donc on continue a
bricoler des contournements pour des fonctions deja livrees.

DEUX SIGNAUX, volontairement independants :
  1. la VERSION du binaire CLI (`<cli> --version`) ;
  2. l'EMPREINTE de l'index `llms.txt` de sa doc (taille + sha256).

Le (2) est le plus fiable : il ne depend d'aucun binaire installe, et une doc
qui change signale une capacite nouvelle meme quand la version n'a pas bouge
(ajout de pages, nouveaux endpoints). Le (1) peut etre NON MESURABLE (binaire
absent, subprocess interdit en sandbox) — dans ce cas on ecrit « non mesure »,
JAMAIS « inchange » : un capteur muet ne doit pas se lire comme un verdict
rassurant (lecon 2026-08-20, la sonde qui rendait '' par abstention).

Etat persiste dans `sandbox/cli_versions.json`. Premier run = pas d'alarme,
on pose la reference.

⚠️ EGRESS : le sandbox offline rend `WinError 10013`. Lancer via
`run_job online=true`, jamais en `action=python` direct.

Usage :
    run_job script=tools/forge_cli_version_watch.py online=true
    run_job script=tools/forge_cli_version_watch.py online=true script_args="--ingest-si-neuf"
"""

from __future__ import annotations

__FORGE_COLOR__ = "vegetatif/watcher : detecte ce qui a bouge chez les CLI et leurs docs"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("Nokido.CliWatch")

ROOT = Path(__file__).resolve().parent.parent
ETAT = ROOT / "sandbox" / "cli_versions.json"

# (cle, binaire, index llms.txt de la doc, domain RAG)
#
# OWNER 2026-08-20 : « pour chaque constituant tu dois avoir la doc a jour ».
# Ce registre n'est donc PAS limite aux CLI : il couvre les briques dont Nokido
# depend (protocole, superviseur, base vectorielle, calcul deporte, schemas).
# Sonde du jour sur 12 candidats -> 5 constituants publient un `llms.txt` ;
# crawl4ai, searxng, fastapi, sqlite, numpy, astral et playwright n'en ont PAS
# (404 mesure) : ne pas les remettre ici sans re-sonder, sinon on fabrique du
# bruit d'erreur a chaque passage.
CIBLES = [
    # CLI agentiques
    ("claude", "claude", "https://platform.claude.com/llms.txt", "claude_docs"),
    # 2026-09-24 : la doc de Claude Code vit sur un AUTRE site que l'API. L'index
    # platform.claude.com ne la couvrait pas, et la veille n'avait plus tourne depuis
    # le 2026-08-20 : des capacites livrees entre v2.1.2xx et v2.1.281 (fond automatique
    # des appels MCP longs, nettoyage d'env des sous-processus...) sont restees inconnues.
    ("claude_code", None, "https://code.claude.com/docs/llms.txt", "claude_code_docs"),
    ("antigravity", "agy", "https://antigravity.google/llms.txt", "antigravity_docs"),
    ("openai", "codex", "https://developers.openai.com/llms.txt", "openai_docs"),
    ("gemini", "gemini", None, None),
    # 2026-10-17 : les deux surfaces autonomes branchees les 16-17/10 (owner : « veille introspective de chacun de tes
    # composants »). Mistral publie un llms.txt (200 mesure, 376 pages dont Vibe) ; OpenCode n'en a PAS (404 mesure) :
    # son changelog = ses releases GitHub, suivies par leur flux Atom -- domain None, jamais passe a l'ingesteur.
    ("mistral_vibe", "vibe", "https://docs.mistral.ai/llms.txt", "mistral_docs"),
    ("opencode", "opencode", "https://github.com/anomalyco/opencode/releases.atom", None),
    # Constituants de l'organisme
    ("ollama", "ollama", "https://docs.ollama.com/llms.txt", "ollama_docs"),
    ("mcp", None, "https://modelcontextprotocol.io/llms.txt", "mcp_docs"),
    ("deno", "deno", "https://docs.deno.com/llms.txt", "deno_docs"),
    ("qdrant", None, "https://qdrant.tech/llms.txt", "qdrant_docs"),
    ("modal", "modal", "https://modal.com/docs/llms.txt", "modal_docs"),
    ("pydantic", None, "https://docs.pydantic.dev/llms.txt", "pydantic_docs"),
    ("crawl4ai", None, "https://pypi.org/pypi/crawl4ai/json", None),
    ("lean4", None, "https://github.com/leanprover/lean4/releases.atom", None),
]

# Sources natives pour les changelogs / releases (Atom GitHub ou JSON PyPI)
# DEMANDE OWNER 2026-10-17 : SearXNG est aveugle (moteurs HTML bloques),
# les changelogs doivent venir de flux machines natifs (releases.atom ou pypi json).
SOURCES_NATIVES: dict[str, dict[str, str]] = {
    # CLI agentiques
    "claude_code": {
        "url": "https://github.com/anthropics/claude-code/releases.atom",
        "type": "atom",
        "domain": "claude_code_docs",
    },
    "openai": {  # Codex CLI
        "url": "https://github.com/openai/codex/releases.atom",
        "type": "atom",
        "domain": "openai_docs",
    },
    "mistral_vibe": {  # Vibe CLI
        "url": "https://github.com/mistralai/mistral-vibe/releases.atom",
        "type": "atom",
        "domain": "mistral_docs",
    },
    "opencode": {
        "url": "https://github.com/anomalyco/opencode/releases.atom",
        "type": "atom",
        "domain": "opencode_docs",
    },
    "claude": {
        "url": "https://github.com/anthropics/anthropic-sdk-python/releases.atom",
        "type": "atom",
        "domain": "claude_docs",
    },
    "antigravity": {
        "url": "https://github.com/google/antigravity/releases.atom",
        "type": "atom",
        "domain": "antigravity_docs",
    },
    "gemini": {
        "url": "https://pypi.org/pypi/google-genai/json",
        "type": "pypi",
        "domain": "gemini_docs",
    },
    # Constituants & outils
    "crawl4ai": {
        "url": "https://pypi.org/pypi/crawl4ai/json",
        "type": "pypi",
        "domain": "crawl4ai_docs",
    },
    "mcp": {
        "url": "https://pypi.org/pypi/mcp/json",
        "type": "pypi",
        "domain": "mcp_docs",
    },
    "lean4": {
        "url": "https://github.com/leanprover/lean4/releases.atom",
        "type": "atom",
        "domain": "lean4_docs",
    },
    "ollama": {
        "url": "https://github.com/ollama/ollama/releases.atom",
        "type": "atom",
        "domain": "ollama_docs",
    },
    "deno": {
        "url": "https://github.com/denoland/deno/releases.atom",
        "type": "atom",
        "domain": "deno_docs",
    },
    "qdrant": {
        "url": "https://github.com/qdrant/qdrant/releases.atom",
        "type": "atom",
        "domain": "qdrant_docs",
    },
    "modal": {
        "url": "https://pypi.org/pypi/modal/json",
        "type": "pypi",
        "domain": "modal_docs",
    },
    "pydantic": {
        "url": "https://pypi.org/pypi/pydantic/json",
        "type": "pypi",
        "domain": "pydantic_docs",
    },
}


def version_binaire(exe: str) -> str:
    """Version du CLI, ou un motif de NON-MESURE explicite (jamais 'inchange')."""
    chemin = shutil.which(exe)
    if not chemin:
        return "non mesure: binaire absent du PATH"
    try:
        r = subprocess.run([chemin, "--version"], capture_output=True, text=True,
                           timeout=20, errors="replace")
        out = (r.stdout or r.stderr or "").strip().splitlines()
        return out[0][:120] if out else "non mesure: sortie vide"
    except Exception as e:  # noqa: BLE001
        return "non mesure: %s" % type(e).__name__


def empreinte_doc(url: str) -> dict:
    try:
        rq = urllib.request.Request(url, headers={"User-Agent": "Nokido-cli-watch/1.0"})
        with urllib.request.urlopen(rq, timeout=25) as r:
            b = r.read()
        return {"octets": len(b), "sha256": hashlib.sha256(b).hexdigest()[:16],
                "pages": b.decode("utf-8", "replace").count("](http")}
    except Exception as e:  # noqa: BLE001
        return {"erreur": "%s: %s" % (type(e).__name__, str(e)[:60])}


def charger() -> dict:
    try:
        return json.loads(ETAT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def extraire_notes_atom(contenu_xml: str | bytes) -> tuple[str, str, str]:
    """Extrait (version, url_release, contenu_notes) depuis un flux Atom XML."""
    if isinstance(contenu_xml, str):
        contenu_xml = contenu_xml.encode("utf-8")
    root = ET.fromstring(contenu_xml)
    entry = None
    for elem in root.iter():
        if elem.tag.endswith("entry"):
            entry = elem
            break
    if entry is None:
        raise ValueError("Flux Atom sans balise <entry>")

    title_elem = None
    link_elem = None
    content_elem = None
    for child in entry:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag == "title" and title_elem is None:
            title_elem = child
        elif tag == "link" and link_elem is None:
            link_elem = child
        elif tag in ("content", "summary") and content_elem is None:
            content_elem = child

    version = (title_elem.text or "").strip() if title_elem is not None else ""
    if not version:
        for child in entry:
            if child.tag.endswith("id") and child.text:
                version = child.text.split("/")[-1].strip()
                break
    if not version:
        raise ValueError("Flux Atom: version introuvable dans <entry>")

    release_url = ""
    if link_elem is not None:
        release_url = link_elem.attrib.get("href", "")
    if not release_url:
        for child in entry:
            if child.tag.endswith("id") and child.text and child.text.startswith("http"):
                release_url = child.text
                break

    notes = (content_elem.text or "").strip() if content_elem is not None else ""
    return version, release_url, notes


def extraire_notes_pypi(contenu_json: str | bytes) -> tuple[str, str, str]:
    """Extrait (version, url_release, contenu_notes) depuis l'API JSON PyPI."""
    if isinstance(contenu_json, bytes):
        contenu_json = contenu_json.decode("utf-8", errors="replace")
    data = json.loads(contenu_json)
    if not isinstance(data, dict):
        raise ValueError("PyPI JSON: payload n'est pas un objet")
    info = data.get("info")
    if not isinstance(info, dict):
        raise ValueError("PyPI JSON: champ 'info' manquant ou invalide")
    version = str(info.get("version") or "").strip()
    if not version:
        raise ValueError("PyPI JSON: version absente")
    release_url = str(info.get("release_url") or info.get("project_url") or "").strip()
    notes = str(info.get("description") or info.get("summary") or "").strip()
    return version, release_url, notes


def lire_source_native(cle: str, source_cfg: dict, timeout: int = 25, urlopen_fn=None) -> tuple[str, str, str]:
    """Lit et extrait (version, release_url, notes) d'une source native (Atom ou PyPI JSON)."""
    url = source_cfg.get("url", "")
    if not url:
        raise ValueError("URL absente de la source native")
    type_flux = source_cfg.get("type", "auto")
    if type_flux == "auto":
        type_flux = "atom" if (url.endswith(".atom") or "/releases.atom" in url) else "pypi"

    if urlopen_fn is not None:
        raw = urlopen_fn(url)
        if hasattr(raw, "read"):
            raw = raw.read()
    else:
        rq = urllib.request.Request(url, headers={"User-Agent": "Nokido-cli-watch/1.0"})
        with urllib.request.urlopen(rq, timeout=timeout) as r:
            raw = r.read()

    if type_flux == "atom":
        return extraire_notes_atom(raw)
    elif type_flux == "pypi":
        return extraire_notes_pypi(raw)
    else:
        raise ValueError(f"Type de flux inconnu: {type_flux}")


def ingerer_notes_version(cle: str, version: str, release_url: str, notes: str,
                          domain: str | None = None, conn=None) -> dict:
    """Ingère les notes de version via forge_watch_agent._step_ingest et _step_store."""
    corps = (notes or "").strip()
    if len(corps) < 80:
        corps = (
            f"Release {cle} {version} : {corps or 'Notes de version'}\n"
            f"Mise a jour du composant {cle} vers la version {version}.\n"
            f"URL source: {release_url or 'inconnue'}"
        )

    theme = domain or f"{cle}_docs"
    job_id = f"watch_comp_{cle}_{version}"
    refined = [{
        "url": release_url or f"https://changelogs.nokido.local/{cle}/{version}",
        "title": f"Changelog {cle} {version}",
        "content": corps,
        "relevance": 10,
        "keyword": cle,
        "author": "WatchAgent",
    }]

    fermer_conn = False
    if conn is None:
        try:
            from nokido_agent.app.forge_db_path import db_path
            db_file = Path(db_path()).resolve()
        except Exception:
            db_file = ROOT / "RAG" / "embeddings.db"
        db_file.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_file), timeout=30.0, isolation_level=None)
        fermer_conn = True

    try:
        try:
            from nokido_agent.app.forge_watch_agent import _step_ingest, _step_store
        except ImportError:
            sys.path.insert(0, str(ROOT / "app"))
            from forge_watch_agent import _step_ingest, _step_store

        n_ing = _step_ingest(conn, job_id, theme, refined)
        n_sto = 0
        try:
            n_sto = _step_store(conn, job_id, theme, refined, idea_id="veille_composants")
        except Exception as e_sto:
            logger.debug("[veille] _step_store KO: %s", e_sto)
        return {"ok": True, "n_ingested": n_ing, "n_stored": n_sto, "job_id": job_id, "theme": theme}
    finally:
        if fermer_conn:
            try:
                conn.close()
            except Exception:
                __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_cli_version_watch.py', 349, exc_info=True)


def publier_fait_nouvelle_version(cle: str, version: str, release_url: str) -> dict:
    """Publie un fait au SSoT (blackboard zone discovered_facts) selon la convention de l'organisme."""
    try:
        from nokido_agent.app.forge_swarm_blackboard import apply_fact_sync
        fait = f"Composant {cle}: nouvelle version {version} ({release_url})"
        return apply_fact_sync(
            "discovered_facts",
            fait,
            category="composants",
            source="forge_cli_version_watch",
            ring=2,
        )
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def traiter_flux_natif(cle: str, source_cfg: dict, etat_composant_precedent: dict | None = None,
                       conn=None, dry_run: bool = False, urlopen_fn=None,
                       publier_fn=None) -> dict:
    """Traite une source native pour un composant:
    1. Télécharge et parse le flux (Atom ou PyPI JSON)
    2. Déduplique par (composant, version)
    3. Si nouvelle version: publie au SSoT et ingère les notes via forge_watch_agent
    4. Si flux illisible: le DIT explicitement (composant + raison), jamais silencieux.
    """
    url = source_cfg.get("url")
    if not url:
        return {
            "ok": False,
            "composant": cle,
            "illisible": True,
            "erreur": f"{cle}: flux illisible (URL absente)",
            "raison": "URL absente",
        }

    try:
        version, release_url, notes = lire_source_native(cle, source_cfg, urlopen_fn=urlopen_fn)
    except Exception as e:
        raison = f"{type(e).__name__}: {e}"
        return {
            "ok": False,
            "composant": cle,
            "illisible": True,
            "erreur": f"{cle}: flux illisible ({raison})",
            "raison": raison,
            "url": url,
        }

    etat = dict(etat_composant_precedent or {})
    versions_vues = list(etat.get("versions_vues") or [])
    derniere = etat.get("derniere_version")
    deja_vu = (version in versions_vues) or (derniere == version)

    if deja_vu:
        return {
            "ok": True,
            "composant": cle,
            "version": version,
            "release_url": release_url,
            "notes": notes,
            "nouveau": False,
            "deja_vu": True,
            "versions_vues": versions_vues,
            "message": f"{cle}: version {version} deja vue (ignoree)",
        }

    ing_res = None
    if not dry_run:
        domain = source_cfg.get("domain") or f"{cle}_docs"
        ing_res = ingerer_notes_version(cle, version, release_url, notes, domain=domain, conn=conn)
        publier = publier_fn if publier_fn is not None else publier_fait_nouvelle_version
        publier(cle, version, release_url)

    nouvelles_vues = sorted(list(set(versions_vues + [version])))
    return {
        "ok": True,
        "composant": cle,
        "version": version,
        "release_url": release_url,
        "notes": notes,
        "nouveau": True,
        "deja_vu": False,
        "ingere": ing_res,
        "versions_vues": nouvelles_vues,
        "message": f"{cle}: NOUVELLE VERSION {version} ingeree ({release_url})",
    }


def traiter_toutes_sources_natives(avant: dict, conn=None, dry_run: bool = False,
                                   urlopen_fn=None, publier_fn=None) -> tuple[dict[str, dict], list[str]]:
    """Exécute la veille sur toutes les sources natives déclarées."""
    resultats: dict[str, dict] = {}
    changements: list[str] = []

    for cle, src_cfg in SOURCES_NATIVES.items():
        old_comp = avant.get(cle) or {}
        r = traiter_flux_natif(cle, src_cfg, etat_composant_precedent=old_comp,
                               conn=conn, dry_run=dry_run, urlopen_fn=urlopen_fn,
                               publier_fn=publier_fn)
        resultats[cle] = r
        if not r.get("ok"):
            changements.append(r.get("erreur", f"{cle}: flux illisible"))
        elif r.get("nouveau"):
            changements.append(r.get("message", f"{cle}: NOUVELLE VERSION {r.get('version')}"))

    return resultats, changements


def main() -> int:
    ap = argparse.ArgumentParser(description="Veille des versions CLI + docs")
    ap.add_argument("--ingest-si-neuf", action="store_true",
                    help="relance forge_ingest_llms_txt pour chaque doc qui a change")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    avant = charger()
    apres: dict = {}
    changements: list[str] = []
    premier = not avant

    # 1. Traitement des flux natifs (Atom / PyPI JSON)
    res_natives, chang_natives = traiter_toutes_sources_natives(avant, dry_run=a.dry_run)
    changements.extend(chang_natives)
    for cle, r_nat in res_natives.items():
        cur = apres.setdefault(cle, {})
        if r_nat.get("ok"):
            cur["flux_natif"] = {
                "statut": "ok",
                "version": r_nat.get("version"),
                "url": r_nat.get("release_url"),
            }
            cur["derniere_version"] = r_nat.get("version")
            cur["versions_vues"] = r_nat.get("versions_vues", [])
        else:
            cur["flux_natif"] = {
                "statut": "illisible",
                "erreur": r_nat.get("erreur"),
                "raison": r_nat.get("raison"),
                "url": r_nat.get("url"),
            }
            old_c = avant.get(cle) or {}
            if "versions_vues" in old_c:
                cur["versions_vues"] = old_c["versions_vues"]
            if "derniere_version" in old_c:
                cur["derniere_version"] = old_c["derniere_version"]

    # 2. Mesures historiques (binaires + docs llms.txt)
    for cle, exe, url, domain in CIBLES:
        cur = apres.setdefault(cle, {})
        cur["version"] = version_binaire(exe) if exe else cur.get("version", "n/a: pas un binaire")
        if url:
            cur["doc"] = empreinte_doc(url)
            cur["doc_url"] = url
            cur["domain"] = domain
        old = avant.get(cle) or {}

        ov, nv = old.get("version"), cur["version"]
        if ov and ov != nv and not nv.startswith("non mesure"):
            changements.append("%s: VERSION %r -> %r" % (cle, ov, nv))

        od, nd = (old.get("doc") or {}), (cur.get("doc") or {})
        if od.get("sha256") and nd.get("sha256") and od["sha256"] != nd["sha256"]:
            changements.append(
                "%s: DOC changee (%s -> %s, %d -> %d pages)"
                % (cle, od["sha256"], nd["sha256"], od.get("pages", 0), nd.get("pages", 0)))

    apres["_ts"] = datetime.now(timezone.utc).isoformat()
    rapport = {"premier_run": premier, "changements": changements,
               "cibles": {k: v for k, v in apres.items() if k != "_ts"}}
    print(json.dumps(rapport, ensure_ascii=False, indent=2), flush=True)

    if not a.dry_run:
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        ETAT.write_text(json.dumps(apres, ensure_ascii=False, indent=2), encoding="utf-8")

    if a.ingest_si_neuf and changements and not premier:
        for cle, _exe, url, domain in CIBLES:
            # une cible sans domain RAG (flux de releases, pas un llms.txt) n'est jamais envoyee a l'ingesteur
            if not url or not domain or not any(c.startswith(cle + ": DOC") for c in changements):
                continue
            print("[reingest] %s -> %s" % (cle, domain), flush=True)
            r = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "forge_ingest_llms_txt.py"),
                 "--url", url, "--domain", domain, "--pause", "0.15"],
                capture_output=True, text=True, errors="replace", timeout=3600)
            print((r.stdout or "")[-600:], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
