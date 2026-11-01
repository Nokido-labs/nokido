"""forge_cli_swarm.py — Swarm multi-CLI SOUVERAIN, appelé depuis Nokido.

__FORGE_COLOR__ = "locomoteur-orchestration"

Dispatch UN task à N providers (CLI OAuth + cloud rapide) en PARALLÈLE, collecte, synthèse.
Réutilise `forge_agent_proxy.ask` (primitive atomique — NE la duplique pas) ; ce module = le
COMPOSEUR panel par-dessus, déportable (claude_cli/gemini_cli lents -> lancer via run_job).
PAS le tool Workflow de Claude (règle d'or Nokido : swarm souveraine via le hub).

Anti-dup : LeadOrchestrator (forge_swarm_team) = panel parallèle MAIS orienté providers API +
async-non-déportable. Ici = panel sur les CLI OAuth (claude_cli/gemini_cli) + cloud free, en
script CLI déportable. Membres par défaut = OAuth Max/Ultra (quota frais) + groq/cerebras rapides.

Usage:
  LAFORGE_PYTHON tools/forge_cli_swarm.py "<task>" [provider1,provider2,...]
  (déporté: run action=run_job script=tools/forge_cli_swarm.py online=true)

Secours de la synthèse, flux en 3 temps (garde de ring conservée : le job, ring 4, ne dépose jamais) :
  1. job : aucun rédacteur -> le JSON résultat porte `demande_synthese` {pointeur, consigne, executeurs, raison} ;
  2. lanceur (ring <= 3) : `task assign` vers un exécuteur avec la consigne de `demande_synthese` -> task_id ;
  3. job : `forge_cli_swarm.py --integrer-secours <resultat.json> <task_id> [--agent X]` (lecture seule du statut,
     mêmes gardes : juge d'ancrage + anti-répétition) -> `synthesis`, `secours_integre` ; demande retirée.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import types
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_agent_proxy import ask  # primitive atomique réutilisée

# Registre des membres VIVANTS ecrit par `forge_free_tier_census.py --essaim` (GREEN AGY cb3f1114f, 21/10).
REGISTRE = ROOT / "sandbox" / "swarm_membres_vivants.json"

# Repli SANS client mort ni abonnement owner (24/10 : claude_cli + gemini_cli = 0 reponse sur 2) ; meme exclusion que
# forge_free_tier_census.EXCLUS_PROXY (NR test_swarm_membres_defaut_gratuits_nr).
DEFAULT_MEMBERS = ["groq", "cerebras", "mistral_free", "openrouter_free"]
# Reduce en LOCAL (ollama) : les réponses du swarm peuvent contenir des internals Nokido ;
# synthétiser sur un cloud (groq) = egress -> DLP firewall bloque (constat 2026-06-10). Local = 0 egress.
SYNTH_PROVIDER = os.environ.get("LAFORGE_SWARM_SYNTH", "ollama")


# `_classer` (liste BLANCHE : n'est OK que la vraie reponse) et la primitive `Mesure` vivent dans
# app/forge_mesure.py (module LEger, source unique). Re-exportes ici pour les appelants historiques.
from app.forge_mesure import (  # noqa: E402,F401
    Mesure, MesureIllisible, STATUTS_MESURE, _MARQUES_ERREUR, _MARQUES_ILLISIBLE,
    _classer, agreger_sain, contexte_courant, depuis_http,
)


def membres_par_defaut(chemin=None, maintenant=None, max_age_s=6 * 3600) -> tuple:
    """(membres, raison) : registre de forge_free_tier_census.ecrire_membres_vivants FRAIS -> ses membres OK et "" ;
    absent, illisible, vide ou perime -> la liste historique DEFAULT_MEMBERS et la raison DITE (RED 1da121b2a ; GREEN
    d'OPENCODE_GLM cb9637e1f repris le 20/10). Le chemin par defaut de l'essaim n'est pas encore cable ici."""
    p = Path(chemin) if chemin else None
    if p is None or not p.exists():
        return DEFAULT_MEMBERS, "registre absent"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_MEMBERS, "registre illisible"
    membres = doc.get("membres_ok") or []
    if not membres:
        return DEFAULT_MEMBERS, "registre vide"
    age = (time.time() if maintenant is None else maintenant) - float(doc.get("mesure_le") or 0)
    if age > max_age_s:
        return DEFAULT_MEMBERS, "registre perime (%d s)" % int(age)
    if "membres" in doc and not any(isinstance(m, dict) and m.get("force") is not None for m in doc["membres"] or []):
        return DEFAULT_MEMBERS, "registre sans force mesurée"
    return membres, ""


async def _one(member: str, task: str, max_tokens: int) -> dict:
    # Membre = "provider" OU "provider:model" -> pioche un modèle PRÉCIS d'un même backend
    # (LMStudio :1234 / Ollama hébergent N modèles joignables). Ex: "lmstudio_native:qwen2.5-7b",
    # "lmstudio_native:phi-4", "ollama:laforge-qwen:latest". partition sur le 1er ':' (les ids
    # ollama gardent leur ':tag'). Sans ':' = comportement historique (modèle défaut du provider).
    provider, _sep, model = member.partition(":")
    t0 = time.time()
    try:
        r = await ask(provider, task, max_tokens=max_tokens, rag_context=False, model=(model or None))
        texte = (r.get("text") or "").strip()
        etat = _classer(bool(r.get("ok")), texte, r.get("error"))
        return {
            "provider": member,  # label COMPLET (provider:model) pour distinguer les membres d'un même backend
            "ok": etat == "OK",
            "etat": etat,
            "text": texte,
            "model": r.get("model") or (model or None),
            "ms": int((time.time() - t0) * 1000),
            "error": r.get("error"),
        }
    except Exception as e:  # noqa: BLE001
        return {"provider": member, "ok": False, "etat": _classer(False, "", e), "text": "",
                "error": str(e), "ms": int((time.time() - t0) * 1000)}


SEUIL_CONSIGNE = int(os.environ.get("LAFORGE_SWARM_SEUIL", "12000"))
SONDE = ROOT / "sandbox" / "tool_call_probe.json"
TASKS_DB = ROOT / "sandbox" / "tasks.db"
RAG_DB = Path("%NOKIDO_DATA%\embeddings.db")
SORTIE_DIR = ROOT / "sandbox"
RACINES_LECTURE = [ROOT / "sandbox" / "workspace", ROOT / "docs", Path("C:/tmp/laforge_jobs")]


def _caviarder(texte: str) -> str:
    """Toute sortie d'outil passe par redact_text ; firewall indisponible -> rien ne part (fail-closed)."""
    try:
        from app.forge_semantic_firewall import redact_text
        return redact_text(str(texte))[0]
    except Exception as e:  # noqa: BLE001
        return f"[sortie retenue : caviardage indisponible ({type(e).__name__})]"


_CHEMIN_CITE = re.compile(r"(?:[A-Za-z]:[\\/]|(?<![\w.])(?:app|tools|tests|docs|sandbox)/)[^\s'\"`<>|,;()\[\]]+")
# 29/10 : les chemins du depot contiennent des ESPACES (« Script python IA ») ; coupes aux blancs, aucun fichier cite
# n'entrait au perimetre. Formes ajoutees : chemin ENTRE GUILLEMETS, et chemin ABSOLU termine par une extension connue.
_CHEMIN_GUILLEMETS = re.compile(r"[\"'`]([A-Za-z]:[\\/][^\"'`\n<>|]+|(?:app|tools|tests|docs|sandbox)/[^\"'`\n<>|]+)[\"'`]")
_CHEMIN_ABSOLU_EXT = re.compile(r"[A-Za-z]:[\\/][^\n\"'`<>|]*?\.(?:py|md|json|jsonl|txt|toml|ts|ya?ml|csv|log)\b")


def _chemins_cites(texte: str) -> list:
    """Candidats chemins d'une description (le filtre is_file + racine de perimetre tranche ensuite)."""
    t = str(texte or "")
    return (_CHEMIN_GUILLEMETS.findall(t) + [m.group(0) for m in _CHEMIN_ABSOLU_EXT.finditer(t)]
            + _CHEMIN_CITE.findall(t))


def _sous_racine_perimetre(r: Path) -> bool:
    return any(r.is_relative_to(Path(b).resolve()) for b in (ROOT, Path("C:/tmp/laforge_jobs")))


def _perimetre_pointeurs(pointeurs: list) -> list:
    """Fichiers (chemins resolus, jamais de dossier) designes par la tache : pointeurs chemin + chemins
    cites dans la description d'un pointeur tasks.db:<id> (lecture par cle primaire)."""
    out: list = []

    def ajouter(c: str) -> None:
        try:
            p = Path(c.rstrip(".:"))
            if ".." in p.parts:
                return
            r = (p if p.is_absolute() else Path(ROOT) / p).resolve()
            if r.is_file() and _sous_racine_perimetre(r) and str(r) not in out:
                out.append(str(r))
        except (OSError, ValueError):
            return

    for ptr in pointeurs or []:
        ptr = str(ptr)
        if ptr.startswith("tasks.db:"):
            try:
                con = sqlite3.connect(f"file:{Path(TASKS_DB).as_posix()}?mode=ro", uri=True)
                try:
                    row = con.execute("SELECT description FROM tasks WHERE id = ?", (ptr[9:],)).fetchone()
                finally:
                    con.close()
            except sqlite3.Error as e:
                print("[swarm][perimetre] %s illisible (%s) : aucun fichier cite admis" % (ptr, type(e).__name__),
                      file=sys.stderr)
                continue
            for c in _chemins_cites(str(row[0]) if row and row[0] else ""):
                ajouter(c)
        else:
            ajouter(ptr)
    return out


def _outils_lecture(autorises: list | None = None) -> dict:
    """3 outils LECTURE SEULE executes localement ; chaque sortie est caviardee.
    autorises : fichiers designes par la tache (liste blanche en plus des racines)."""
    blanche = set()
    for a in autorises or []:
        try:
            blanche.add(str(Path(a).resolve()))
        except (OSError, ValueError) as e:
            print("[swarm][perimetre] fichier %r ecarte de la liste blanche (%s)" % (a, type(e).__name__),
                  file=sys.stderr)

    def lire_tache(task_id: str) -> str:
        """Lit une tache de tasks.db (description, result) en lecture seule."""
        try:
            con = sqlite3.connect(f"file:{Path(TASKS_DB).as_posix()}?mode=ro", uri=True)
            try:
                row = con.execute("SELECT description, result FROM tasks WHERE id = ?", (str(task_id),)).fetchone()
            finally:
                con.close()
        except sqlite3.Error as e:
            return _caviarder(f"ERR lecture tasks.db : {e}")
        if row is None:
            return f"tache inconnue : {task_id}"
        return _caviarder(f"description: {row[0]}\nresult: {row[1]}")

    def lire_fichier(chemin: str, debut: int = 0, taille: int = 6000) -> str:
        """Lit une fenetre d'un fichier d'une racine autorisee (sandbox/workspace, docs, laforge_jobs)."""
        try:
            p = Path(str(chemin))
            if ".." in p.parts:
                return "refus : '..' interdit"
            if not p.is_absolute():
                p = ROOT / p
            r = p.resolve()
            if str(r) not in blanche and not any(r.is_relative_to(Path(x).resolve()) for x in RACINES_LECTURE):
                return "refus : chemin hors des racines autorisees"
            if not r.is_file():
                return "refus : fichier introuvable"
            debut = max(0, int(debut))
            taille = max(1, min(int(taille), 6000))
            texte = r.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError) as e:
            return f"refus : {type(e).__name__}"
        fen = texte[debut:debut + taille]
        fin = debut + len(fen)
        suite = f", suite : debut={fin}" if fin < len(texte) else ", fin du fichier"
        return _caviarder(fen) + f"\n[{fin - debut}/{len(texte)} car. depuis {debut}{suite}]"

    def rag_fts(terme: str, limite: int = 5) -> str:
        """Recherche plein texte (index FTS, bm25) dans embeddings.db ; 5 resultats max."""
        limite = max(1, min(int(limite), 5))
        sql = "SELECT * FROM rag_fts WHERE rag_fts MATCH ? ORDER BY bm25(rag_fts) LIMIT ?"
        try:
            if not Path(RAG_DB).exists():
                return "rag indisponible : base absente"
            con = sqlite3.connect(f"file:{Path(RAG_DB).as_posix()}?mode=ro", uri=True)
            try:
                plan = " ".join(str(r[-1]) for r in con.execute("EXPLAIN QUERY PLAN " + sql, (str(terme), limite)))
                if "VIRTUAL TABLE INDEX" not in plan.upper() or "rag_chunks" in plan:
                    return "refus : plan de requete sans index FTS (balayage interdit)"
                rows = con.execute(sql, (str(terme), limite)).fetchall()
            finally:
                con.close()
        except sqlite3.Error as e:
            return f"ERR rag_fts : {e}"
        return _caviarder("\n---\n".join(" | ".join(str(c)[:600] for c in r) for r in rows) or "aucun resultat")

    return {"lire_tache": lire_tache, "lire_fichier": lire_fichier, "rag_fts": rag_fts}


def _membres_pointeur(membres: list, sonde=None) -> tuple:
    """(retenus, ecartes) : seuls les endpoints APPELLE de la sonde ; sonde absente/illisible -> aucun (UNKNOWN != NO)."""
    p = Path(sonde) if sonde else Path(SONDE)
    try:
        lignes = json.loads(p.read_text(encoding="utf-8")).get("resultats") or []
    except (OSError, ValueError, AttributeError):
        return [], [{"provider": m, "raison": "sonde tool_call_probe absente ou illisible : capacite inconnue"}
                    for m in membres]
    retenus, ecartes = [], []
    for m in membres:
        prov, _s, modele = m.partition(":")
        liees = [r for r in lignes if isinstance(r, dict) and r.get("fournisseur")
                 and (prov == r["fournisseur"] or prov.startswith(str(r["fournisseur"])))
                 and (not modele or r.get("modele") == modele)]
        if any(r.get("etat") == "APPELLE" for r in liees):
            retenus.append(m)
        elif liees:
            ecartes.append({"provider": m, "raison": "; ".join(sorted({f"{r.get('etat')} {r.get('motif', '')}".strip() for r in liees}))[:200]})
        else:
            ecartes.append({"provider": m, "raison": "absent de la sonde : capacite inconnue"})
    return retenus, ecartes


def _consigne_pointeur(consigne: str, pointeurs: list) -> str:
    lst = "\n".join(f"- {x}" for x in pointeurs)
    return (f"{consigne}\n\nPOINTEURS (lis-les avec tes outils lire_tache / lire_fichier / rag_fts, "
            f"ne devine rien) :\n{lst}")


MAX_TOURS_DUR = 10
PAUSE_REPRISE_S = 3
CONSIGNE_FINALE = "Reponds maintenant avec ce que tu as lu ; ne cite que les extraits lus."


def _tour(hf, agent, messages: list, avec_outils: bool) -> dict:
    """Un tour ; 1 seule reprise apres 3 s sur 5xx / timeout, aucune sur 4xx."""
    for essai in (0, 1):
        resp = hf._llm_round(agent, messages, with_tools=avec_outils)
        meta = resp.get("_router_meta") or {}
        if not (meta.get("tools") and meta.get("ok") is False):
            return resp
        code = meta.get("http")
        err = str(meta.get("error", ""))
        retentable = (isinstance(code, int) and code >= 500) or (code is None and "timeout" in err.lower())
        if essai == 0 and retentable:
            time.sleep(PAUSE_REPRISE_S)
            continue
        return resp
    return resp


def _condenser(consigne: str, messages: list, trace: dict) -> str:
    """Consigne neuve : consigne d'origine + extraits d'outils (deja caviardes) + CONSIGNE_FINALE.
    Au-dela de SEUIL_CONSIGNE, chaque extrait est tronque proportionnellement ; l'ecart est trace."""
    lus = [(m.get("name") or "unknown", str(m.get("content", ""))) for m in messages if m.get("role") == "tool"]
    total = sum(len(c) for _, c in lus)
    if total > SEUIL_CONSIGNE:
        ratio = SEUIL_CONSIGNE / total
        coupes = [(n, c[:int(len(c) * ratio)]) for n, c in lus]
        trace["condense_ecarte_car"] = total - sum(len(c) for _, c in coupes)
        lus = coupes
    extraits = "\n".join(f"- {n}: {c}" for n, c in lus)
    return f"{consigne}\n\nEXTRAITS LUS :\n{extraits}\n\n{CONSIGNE_FINALE}"


def _sonde_mod():
    import forge_tool_call_probe as p
    return p


def _lecture(meta: dict) -> tuple:
    """(finish_reason, longueur raisonnement) : lus dans le meta du tour seulement."""
    return meta.get("finish_reason"), meta.get("raisonnement_car")


def _motif_vide(trace: dict) -> str:
    """Motif d'un texte vide : finish_reason + longueur du raisonnement (jamais son texte)."""
    fr, rc = trace.get("finish_reason"), trace.get("raisonnement_car")
    if fr is None and rc is None:
        return "reponse vide"
    return f"finish_reason={fr}, raisonnement {rc or 0} car."


def _motif_http(meta: dict) -> str:
    ra = meta.get("retry_after")
    if meta.get("http") == 429 and ra is not None:
        ra = int(ra) if float(ra).is_integer() else ra
        return f"HTTP 429 (Retry-After {ra} s)"
    return f"HTTP {meta.get('http')}"


def _boucle_membre(hf, agent, texte: str, max_tours: int, trace: dict | None = None) -> tuple:
    """Boucle outils ; au dernier tour : sans outils (tour final volontaire, pas un agent inerte)."""
    from app import forge_handoff as reel  # primitives partagees (hf peut etre un faux : _llm_round seul)
    trace = trace if trace is not None else {}
    trace.setdefault("post_flight", [])

    def _tour(hf_, ag_, msgs_, avec_outils):  # noqa: F811 - meme contrat, releve le verdict post_flight du tour
        resp_ = globals()["_tour"](hf_, ag_, msgs_, avec_outils)
        pf_ = (resp_.get("_router_meta") or {}).get("post_flight")
        if isinstance(pf_, dict):
            trace["post_flight"].append(pf_)
        return resp_

    messages = [{"role": "user", "content": texte}]
    n = 0
    for n in range(1, max_tours + 1):
        final = n == max_tours and max_tours > 1 and any(m.get("role") == "tool" for m in messages)
        act = agent
        if final:
            # tour final sur la VOIE UNIQUE : outils declares (l'historique en contient), appel interdit.
            # La voie aplatie (with_tools=False) ecrasait l'historique d'outils et rendait un contenu vide (28/10).
            act = dataclasses.replace(agent)
            act.tool_choice = "none"
            messages.append({"role": "user", "content": CONSIGNE_FINALE})
        resp = _tour(hf, act, messages, avec_outils=True)
        if final and not ((resp.get("message") or {}).get("content") or "").strip():
            fr, rc = _lecture(resp.get("_router_meta") or {})
            if fr == "length":
                with _sonde_mod().max_tokens_double():
                    resp = _tour(hf, act, messages, avec_outils=True)
                trace["reprise_length"] = True
            elif fr == "tool_calls" or resp.get("tool_calls"):
                # le modele ignore tool_choice=none et l'historique structure lui fait refabriquer des appels :
                # UNE reprise, voie unique, messages NEUFS sans role tool ni tool_calls
                nu = dataclasses.replace(act, tools=[])
                nu.voie_outils_vide = True  # fait emprunter la voie avec outils a un agent sans outils
                neufs = [{"role": "user", "content": _condenser(texte, messages, trace)}]
                resp = _tour(hf, nu, neufs, avec_outils=True)
                trace["reprise_condensee"] = True
        msg = resp.get("message", {})
        appels = [] if final else (resp.get("tool_calls") or msg.get("tool_calls") or [])
        content = msg.get("content", "") or ""
        meta = resp.get("_router_meta") or {}
        if not content.strip():
            trace["finish_reason"], trace["raisonnement_car"] = _lecture(meta)
        if meta.get("tools") and meta.get("ok") is False:
            err = meta.get("error", "echec transport")
            if meta.get("http") == 429:
                err = _motif_http({"http": 429, "retry_after": meta.get("retry_after")})
            motif = f"[provider {meta.get('provider')} unavailable: {err}]"
            messages.append({"role": "assistant", "content": motif})
            return messages, n
        messages.append(reel._message_assistant(content, appels))
        for tc in appels:
            nom, res, ids = reel._executer_appel(tc, agent.tools)
            messages.append({"role": "tool", "name": nom or "unknown", "content": str(res), **ids})
        if not appels and content:
            return messages, n
    return messages, n


def _tourner_membre(membre: str, texte: str, max_tours: int, autorises: list | None = None) -> dict:
    from app import forge_handoff
    prov, _s, modele = membre.partition(":")
    outils = list(_outils_lecture(autorises).values())
    agent = forge_handoff.Agent(
        name=f"pointeur_{prov}", instructions="Tu reponds en lisant les pointeurs avec tes outils lecture seule.",
        tools=outils, model=modele or "general", text_handoff=False, provider=prov)
    t0 = time.time()
    trace: dict = {}
    try:
        msgs, n_tours = _boucle_membre(forge_handoff, agent, texte, max(1, min(int(max_tours), MAX_TOURS_DUR)),
                                       trace)
    except Exception as e:  # noqa: BLE001
        return {"provider": membre, "ok": False, "text": "", "tours": 0, "outils_appeles": [],
                "chars_envoyes": 0, "error": str(e)[:200], "ms": int((time.time() - t0) * 1000),
                "post_flight": _agreger_post_flight(trace.get("post_flight") or [])}
    r = types.SimpleNamespace(messages=msgs, n_rounds=n_tours)
    finale = next((m["content"] for m in reversed(msgs) if m.get("role") == "assistant" and m.get("content")), "")
    appeles = [m.get("name") for m in msgs if m.get("role") == "tool"]
    ok = bool(finale.strip()) and not finale.startswith("[provider ")
    extra = {}
    if trace.get("reprise_length"):
        extra["reprise_length"] = "tour final repris a max_tokens double"
    if trace.get("reprise_condensee"):
        extra["reprise_condensee"] = "tour final repris sur historique condense"
    if trace.get("condense_ecarte_car"):
        extra["condense_ecarte_car"] = trace["condense_ecarte_car"]
    if not finale.strip():
        extra["error"] = _motif_vide(trace)
    if ok and not appeles:
        ok = False
        extra["error"] = "aucun pointeur lu : reponse non fondee"
    extraits = _extraits(msgs)
    return {"provider": membre, "ok": ok, **extra,
            "text": finale.strip(), "tours": r.n_rounds,
            "extraits": extraits, "ancrage": _juger_ancrage(finale, extraits + [texte]),
            "outils_appeles": appeles,
            "chars_envoyes": sum(len(str(m.get("content", ""))) for m in msgs),
            "ms": int((time.time() - t0) * 1000),
            "post_flight": _agreger_post_flight(trace.get("post_flight") or [])}


def _agreger_post_flight(metas: list) -> dict:
    """Agrege les verdicts post_flight observes ; rien n'est deduit (aucune meta -> {'vus': 0}, UNKNOWN)."""
    metas = [m for m in metas if isinstance(m, dict)]
    if not metas:
        return {"vus": 0}
    motifs: list = []
    for m in metas:
        for c in m.get("motifs") or []:
            if c not in motifs:
                motifs.append(c)
    return {"vus": len(metas), "ok": sum(1 for m in metas if m.get("ok") is True),
            "alertes": sum(1 for m in metas if m.get("ok") is False),
            "illisibles": sum(1 for m in metas if m.get("ok") is None), "motifs": motifs}


import re as _re

_ESPACES = _re.compile(r"[    ]")
# EXCLUSIONS (documentees, jamais comptees comme chiffres a ancrer) : numeros de ligne/§ de citation, refs L12,
# fichier:ligne et ports (:8766), identifiants job_*, sha hex (>=7 car. avec lettre ET chiffre), annees 19xx/20xx seules.
_EXCL = [
    _re.compile(r"\b(?:lignes?|lines?|ll?\.)\s*\d+(?:\s*[-–]\s*\d+)?", _re.I),
    _re.compile(r"§+\s*\d+(?:\.\d+)*"),
    _re.compile(r"\bL\d+(?:-L?\d+)?\b"),
    _re.compile(r"\bjob_\w+"),
    _re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b", _re.I),
    _re.compile(r":\d{2,5}\b"),
    _re.compile(r"\b(?:19|20)\d{2}\b(?!\s?[%×])"),
    # identifiants (29/10) : `ministral-8b-2512`, `gpt-oss-120b`, `qwen2.5-coder` -- lettre en tete, segment(s) apres
    # tiret/deux-points, au moins un chiffre : un nom de modele n'est pas une mesure a ancrer
    _re.compile(r"\b(?=[\w.:-]*\d)[A-Za-z][\w.]*(?:[-:][\w.]+)+"),
]
_NOMBRE = _re.compile(r"(?<![\w.])(×|(?<![A-Za-z])x(?=\d))?\s?(\d+(?: \d{3}(?!\d))*(?:[.,]\d+)?)\s?(%|×|x(?![A-Za-z0-9]))?")
# « 15–20 % » = deux pourcentages (29/10 : la plage laissait « 15 » nu, ancre par n'importe quel 15 des sources)
_PLAGE_PCT = _re.compile(r"(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)\s*%")


def _norm_nombre(brut: str) -> str:
    n = brut.replace(" ", "").replace(",", ".")
    if "." in n:
        n = n.rstrip("0").rstrip(".") or "0"
    return n


def _extraire(texte: str, exclure: bool, tous: bool) -> list:
    t = _ESPACES.sub(" ", str(texte or "")).replace("−", "-")
    t = _PLAGE_PCT.sub(r"\1 % \2 %", t)
    if exclure:
        for rx in _EXCL:
            t = rx.sub(" ", t)
    sortie = []
    for pre, num, suf in _NOMBRE.findall(t):
        entiers = _re.sub(r"\D", "", num.split(",")[0].split(".")[0].replace(" ", ""))
        signif = bool(pre or suf) or "," in num or "." in num or len(entiers) >= 2
        if signif or tous:
            sortie.append(_norm_nombre(num) + ("%" if suf == "%" else "x" if (pre or suf) else ""))
    return sortie


def _chiffres(texte: str) -> list:
    """Nombres significatifs a ancrer : entiers >= 2 chiffres, decimaux, pourcentages, multiplicateurs (x2, 0,10x).
    Normalises (virgule->point, espaces fines/milliers retires, signe ignore). Exclusions : voir _EXCL."""
    return _extraire(texte, True, False)


def _nus(formes) -> set:
    return {f.rstrip("%x") for f in formes}


def _juger_ancrage(texte: str, sources: list) -> dict:
    """Chaque chiffre de texte doit apparaitre dans au moins une source, AVEC SON UNITE : un pourcentage ou un
    multiplicateur exige la meme forme typee (« 30 % » n'est pas ancre par « 30 s », mesure 29/10) ; un nombre nu
    s'ancre sur toute occurrence de sa valeur."""
    types: set = set()
    nus: set = set()
    for s in sources or []:
        for forme in (str(s or ""), _re.sub(r"(?<=\d) (?=\d{3}(?!\d))", "", str(s or ""))):
            f = _extraire(forme, False, True)
            types |= set(f)
            nus |= _nus(f)
        nus |= {_norm_nombre(m) for m in _re.findall(r"\d+(?:[.,]\d+)?", _ESPACES.sub(" ", str(s or "")))}
    ch = _chiffres(texte)
    sans = [c for c in ch if (c not in types if c[-1:] in ("%", "x") else c not in nus)]
    n = len(ch)
    return {"chiffres": n, "ancres": n - len(sans), "sans_source": sans, "taux": (n - len(sans)) / n if n else None}


def _ancrer_synthese(texte: str, sources: list) -> tuple:
    """(texte, info) : retire chaque ligne a chiffre sans source ; la mention finale est ajoutee par l'appelant."""
    gardees, retirees, sans = [], 0, []
    for ligne in texte.splitlines():
        j = _juger_ancrage(ligne, sources)
        if j["sans_source"]:
            retirees += 1
            sans += [c for c in j["sans_source"] if c not in sans]
        else:
            gardees.append(ligne)
    info = {**_juger_ancrage(texte, sources), "lignes_retirees": retirees}
    return "\n".join(gardees), info


def _extraits(msgs: list) -> list:
    """Sources d'un membre : resultats d'outils ET arguments de ses appels (bornes lues, requetes FTS)."""
    sortie = [str(m.get("content", "")) for m in msgs if m.get("role") == "tool"]
    sortie += [str((tc.get("function") or {}).get("arguments") or "") for m in msgs if m.get("role") == "assistant"
               for tc in (m.get("tool_calls") or [])]
    return sortie


MAX_REPETITION = 2
CONSIGNE_SYNTHESE = ("Fusionne sans répéter ; une ligne par mécanisme ; garde la source citée par le membre ; "
                     "signale les désaccords.")


def _garde_repetition(texte: str) -> tuple:
    """(texte, n_ecartees) : ligne significative normalisee vue plus de MAX_REPETITION fois -> suivantes ecartees.
    Lignes vides et separateurs de tableau jamais comptes."""
    vues: dict = {}
    sortie, ecartees = [], 0
    for ligne in texte.splitlines():
        cle = " ".join(ligne.split())
        if not cle or (cle.startswith("|") and set(cle) <= set("|-: ")):
            sortie.append(ligne)
            continue
        vues[cle] = vues.get(cle, 0) + 1
        if vues[cle] > MAX_REPETITION:
            ecartees += 1
            continue
        sortie.append(ligne)
    return ("\n".join(sortie) if ecartees else texte), ecartees


def _synthetiser(membre: str, materiau: str, consigne: str, max_tours: int = 1) -> dict:
    """Synthese par un membre CLOUD, voie unique des membres : aucun outil, pas de voie aplatie, pas de local."""
    from app import forge_handoff
    prov, _s, modele = membre.partition(":")
    agent = forge_handoff.Agent(name=f"synthese_{prov}", instructions=consigne, tools=[],
                                model=modele or "general", text_handoff=False, provider=prov)
    agent.voie_outils_vide = True
    trace: dict = {}
    texte = f"{consigne}\n\n{materiau}"
    r: dict = {}

    def _derniere(msgs):
        return next((m["content"] for m in reversed(msgs) if m.get("role") == "assistant" and m.get("content")), "")

    try:
        msgs, _n = _boucle_membre(forge_handoff, agent, texte, 1, trace)
        finale = _derniere(msgs)
        if not finale.strip() and trace.get("finish_reason") == "length":
            # recette 29/10 : synthese vide (modele a raisonnement, budget consomme) -> UNE reprise x2
            with _sonde_mod().max_tokens_double():
                msgs, _n = _boucle_membre(forge_handoff, agent, texte, 1, trace)
            finale = _derniere(msgs)
            r["reprise_length"] = True
    except Exception as e:  # noqa: BLE001
        return {"text": "", "error": str(e)[:200], "post_flight": _agreger_post_flight(trace.get("post_flight") or [])}
    r.update(text=finale.strip(), post_flight=_agreger_post_flight(trace.get("post_flight") or []))
    if finale.startswith("[provider "):
        r.update(text="", error=finale[:200])
    elif not r["text"]:
        r["error"] = _motif_vide(trace)
    return r


# Regle owner 29/10 : un petit modele reste MEMBRE, jamais REDACTEUR (ministral-8b a redige une synthese inutile,
# puis inventait des chiffres). Liste EXPLICITE (pas de deduction par la taille du nom) des membres admis a rediger.
REDACTEURS_FORTS = (
    "ollama_cloud_gptoss:gpt-oss:120b",
    "ollama_cloud_ultra:nemotron-3-ultra",
)
# Repli du redacteur : primitives EXISTANTES de forge_agent_proxy.ask (aucun transport cree).
# claude_cli = ClaudeCLI (OAuth Max) ; gemini_cli = GeminiCLI redirige vers agy.exe (OAuth du profil owner).
VOIES_REPLI = (("claude", "claude_cli"), ("agy", "gemini_cli"))
DELAI_REDACTEUR_S = 180


def _pre_flight_envoi(texte: str, voie: str) -> tuple:
    """(ok, motif) : pre_flight du firewall AVANT tout envoi cloud (regle d'or 4). Fail-closed : firewall introuvable
    ou illisible = refus (ILLISIBLE), jamais d'envoi non filtre."""
    try:
        from nokido_agent.app.forge_semantic_firewall import get_firewall
        pf = get_firewall().pre_flight(texte, context="", ring=3, provider=voie)
    except Exception as e:  # noqa: BLE001
        return False, "ILLISIBLE: pre_flight indisponible (%s)" % str(e)[:120]
    if getattr(pf, "injection", False) or not getattr(pf, "ok", True):
        return False, "pre_flight refuse: %s" % str(getattr(pf, "reason", "veto DLP/injection"))[:120]
    return True, None


def _appeler_voie(voie: str, prompt: str, timeout: int = DELAI_REDACTEUR_S) -> dict:
    """Un appel borne par la primitive ask du proxy. Depuis un thread sans boucle (to_thread)."""
    try:
        r = asyncio.run(ask(voie, prompt, max_tokens=1500, timeout=timeout, rag_context=False, raw=True))
    except Exception as e:  # noqa: BLE001
        return {"text": "", "error": "ILLISIBLE: %s" % str(e)[:160]}
    return {"text": (r.get("text") or "").strip(), "error": r.get("error"), "latency_ms": r.get("latency_ms"),
            "cout": r.get("usage") or "non rendu par la voie"}


# Recette 29/10 11 h 40 : gpt-oss:120b a rendu « We need to fetch the file. » (26 car.) comme synthese, acceptee car
# non vide. Sous ce seuil, une synthese est SANS SUBSTANCE : comptee comme vide, la cascade passe au redacteur suivant.
SYNTHESE_MIN_CAR = 120


def _sans_substance(texte: str) -> str | None:
    """Motif si la synthese est trop courte pour etre une synthese, None sinon."""
    n = len((texte or "").strip())
    return None if n >= SYNTHESE_MIN_CAR else "synthèse trop courte (%d car. < %d)" % (n, SYNTHESE_MIN_CAR)


def _synthese_cascade(ok_ans: list, materiau: str) -> tuple:
    """(synthese, redacteur retenu ou None, essais). (a) membres ok FORTS, du moins sans_source au plus lu ;
    (b) Claude ; (c) AGY ; (d) rien. Jamais un membre non fort, jamais local."""
    forts = [a for a in ok_ans if a["provider"] in REDACTEURS_FORTS]
    ordre = sorted(forts, key=lambda a: (len((a.get("ancrage") or {}).get("sans_source") or []),
                                         -len(a.get("outils_appeles") or [])))
    essais, s = [], {}
    for a in ordre:
        s = _synthetiser(a["provider"], materiau, CONSIGNE_SYNTHESE)
        texte = (s.get("text") or "").strip()
        court = _sans_substance(texte) if texte else None
        essais.append({"membre": a["provider"], "ok": bool(texte) and not court, "motif": court or s.get("error")})
        if texte and not court:
            return s, a["provider"], essais
    prompt = f"{CONSIGNE_SYNTHESE}\n\n{materiau}"
    for etiquette, voie in VOIES_REPLI:
        nom = f"{etiquette}:{voie}"
        ok, motif = _pre_flight_envoi(prompt, voie)
        if not ok:
            essais.append({"membre": nom, "ok": False, "motif": motif})
            continue
        r = _appeler_voie(voie, prompt, DELAI_REDACTEUR_S)
        texte = (r.get("text") or "").strip()
        court = _sans_substance(texte) if texte else None
        texte = "" if court else texte
        essais.append({"membre": nom, "ok": bool(texte),
                       "motif": court or (None if texte else (r.get("error") or "réponse vide")),
                       **({"cout": r["cout"]} if texte and r.get("cout") else {})})
        if texte:
            return {"text": texte, "post_flight": {"vus": 0}}, nom, essais
    # Executeurs : depot RESERVE au lanceur (ring <= 3), voir _demande_synthese ; le job ne depose plus.
    return {}, None, essais


def _consigne_secours(chemin: str) -> str:
    # chemin ENTRE GUILLEMETS : il contient des espaces (« Script python IA »), un lecteur qui coupe aux blancs le cassait
    return (f"Synthétise les réponses du fichier \"{chemin}\" : une ligne par mécanisme, source citée par le membre, "
            f"désaccords signalés, AUCUN chiffre absent des extraits ; rends le texte seul. "
            # 29/10 : sans « lecture seule », le juge de l'executeur attendait un commit (« fichier » = livrable)
            # et classait la synthese ERR_INTERNAL « commits produits : 0 ».
            f"Lecture seule : ne modifie aucun fichier, ne committe rien.")


def _demande_synthese(ok_ans: list) -> dict:
    chemin = _ecrire_json_synthese(ok_ans)
    return {"pointeur": chemin, "consigne": _consigne_secours(chemin), "executeurs": list(EXECUTEURS_SECOURS),
            "raison": "depot reserve au lanceur (ring <= 3)"}


# Secours 29/10 : les CLI du profil owner sont invisibles du bac a sable (ask -> « backend non pret »). Les EXECUTEURS
# (compte owner) consomment tasks.db : depot via la primitive existante forge_task_bus.create_task, POINTEUR vers le
# JSON des reponses (jamais le texte), statut via get_task, attente bornee. Les voies ask restent en tete (rapides).
EXECUTEURS_SECOURS = ("CLAUDE_HEADLESS", "ANTIGRAVITY")
SECOURS_ATTENTE_S = 600
SECOURS_PAS_S = 10
_ETATS_FINIS = {"review", "done", "completed", "approved"}
_ETATS_ECHEC = {"failed", "error", "rejected", "cancelled"}


def _secours_actif() -> bool:
    v = os.environ.get("LAFORGE_SECOURS_EXECUTEURS")
    if v is None:
        return "pytest" not in sys.modules  # jamais de vrai depot depuis une suite de tests non declaree
    return v == "1"


def _horloge() -> float:
    return time.monotonic()


def _dormir(s: float) -> None:
    time.sleep(s)


def _ecrire_json_synthese(ok_ans: list) -> str:
    """JSON des reponses (answers + ancrage + extraits deja caviardes) ; rend le chemin absolu."""
    dossier = Path(SORTIE_DIR) / "workspace"
    dossier.mkdir(parents=True, exist_ok=True)
    p = dossier / f"swarm_synthese_{time.strftime('%Y%m%d_%H%M%S')}.json"
    p.write_text(json.dumps({"answers": ok_ans}, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p.resolve())


def _appel_hub(outil: str, arguments: dict) -> str:
    """Client hub EXISTANT (app.forge_mpc_executor._hub_call, jeton du coffre) ; texte brut de l'outil.
    Aucune garde contournee : un refus d'authentification remonte tel quel (« ERR:... »)."""
    from app.forge_mpc_executor import _hub_call
    return _hub_call(outil, arguments)


def _json_hub(brut: str) -> dict:
    if str(brut).startswith("ERR:"):
        raise RuntimeError(str(brut)[:160])
    try:
        d = json.loads(brut)
    except ValueError as e:
        raise RuntimeError("réponse hub illisible: %s" % str(brut)[:120]) from e
    return d if isinstance(d, dict) else {}


def _deposer_tache(executeur: str, titre: str, consigne: str) -> str:
    d = _json_hub(_appel_hub("task", {"action": "assign", "agent": executeur, "intent": "HANDOFF_NEXT",
                                      "task": "%s\n%s" % (titre, consigne)}))
    if not d.get("ok") or not d.get("task_id"):
        raise RuntimeError("assign refusé: %s" % json.dumps(d, ensure_ascii=False)[:120])
    return str(d["task_id"])


def _statut_tache(tid: str) -> dict:
    d = _json_hub(_appel_hub("task", {"action": "status", "task_id": tid}))
    texte = d.get("result_summary") or d.get("result") or ""
    return {"status": d.get("status") or "", "results": json.dumps([{"text": str(texte)}]) if texte else "[]"}


def _texte_resultat(results) -> str:
    try:
        liste = json.loads(results) if isinstance(results, str) else (results or [])
    except ValueError:
        return str(results).strip()
    morceaux = []
    for r in liste if isinstance(liste, list) else [liste]:
        if isinstance(r, dict):
            r = next((r[k] for k in ("text", "result", "output", "content") if r.get(k)), "")
        if str(r).strip():
            morceaux.append(str(r).strip())
    return "\n".join(morceaux)


def _secours_executeur(executeur: str, chemin: str) -> tuple:
    """(texte, motif) : depot par pointeur puis sondage borne (SECOURS_PAS_S, au plus SECOURS_ATTENTE_S)."""
    consigne = _consigne_secours(chemin)
    try:
        tid = _deposer_tache(executeur, "Synthèse swarm", consigne)
    except Exception as e:  # noqa: BLE001
        return "", "dépôt impossible: %s" % str(e)[:120]
    debut = _horloge()
    while True:
        try:
            st = _statut_tache(tid)
        except Exception as e:  # noqa: BLE001
            return "", "ILLISIBLE: statut %s" % str(e)[:120]
        etat = str(st.get("status") or "")
        if etat in _ETATS_FINIS:
            texte = _texte_resultat(st.get("results"))
            return (texte, None) if texte else ("", "tâche %s terminée sans texte" % tid)
        if etat in _ETATS_ECHEC:
            return "", "tâche %s en échec (%s)" % (tid, etat)
        if _horloge() - debut >= SECOURS_ATTENTE_S:
            return "", "délai de %d s dépassé (tâche %s, état %s)" % (SECOURS_ATTENTE_S, tid, etat or "inconnu")
        _dormir(SECOURS_PAS_S)


async def swarm_pointeur(consigne: str, pointeurs: list, membres=None, max_tours: int = 6,
                         max_tokens: int = 900) -> dict:
    """Mode POINTEUR : consigne courte + pointeurs ; membres APPELLE de la sonde, outils lecture seule."""
    membres = list(membres) if membres else list(DEFAULT_MEMBERS)
    retenus, ecartes = _membres_pointeur(membres)
    texte = _consigne_pointeur(consigne, pointeurs)
    perimetre = _perimetre_pointeurs(pointeurs)
    suppl = (perimetre,) if perimetre else ()
    answers = list(await asyncio.gather(*[asyncio.to_thread(_tourner_membre, m, texte, max_tours, *suppl)
                                          for m in retenus]))
    ok_ans = [a for a in answers if a["ok"]]
    synthesis = None
    extra: dict = {}
    if not ok_ans:
        extra["synthese_motif"] = "aucun membre ok : pas de synthese (aucun repli local)"
    else:
        materiau = "\n\n".join(
            f"### {a['provider']} (outils lus : {', '.join(a.get('outils_appeles') or []) or 'aucun'})\n{a['text']}"
            for a in ok_ans)
        s, par, essais = await asyncio.to_thread(_synthese_cascade, ok_ans, materiau)
        premier = essais[0]["membre"] if essais else None
        extra["synthese_par"] = par
        extra["synthese_essais"] = essais
        extra["synthese_post_flight"] = s.get("post_flight") or {"vus": 0}
        brut = (s.get("text") or "").strip()
        if brut:
            sources = [e for a in ok_ans for e in (a.get("extraits") or [])] + [texte]
            brut, info = _ancrer_synthese(brut, sources)
            extra["synthese_ancrage"] = info
            if not brut.strip():
                extra["synthese_motif"] = ("juge d'ancrage : toutes les lignes de la synthèse portent des chiffres "
                                           "sans source (%s)" % ", ".join(info["sans_source"]))
            else:
                synthesis, n = _garde_repetition(brut)
                if n:
                    synthesis += f"\n[garde anti-répétition : {n} ligne(s) répétée(s) écartée(s)]"
                    extra["synthese_garde"] = {"declenche": True, "lignes_ecartees": n}
                if info["lignes_retirees"]:
                    synthesis += (f"\n[juge d'ancrage : {info['lignes_retirees']} ligne(s) retirée(s), "
                                  f"chiffres sans source : {', '.join(info['sans_source'])}]")
        else:
            extra["synthese_motif"] = "synthese vide par %s: %s" % (premier, " ; ".join(
                "%s: %s" % (e["membre"], e["motif"] or "réponse vide") for e in essais))
        if not synthesis and not extra.get("synthese_ancrage") and _secours_actif():
            extra["demande_synthese"] = _demande_synthese(ok_ans)
    answers =[{k: v for k, v in a.items() if k != "extraits"} for a in answers]  # extraits : interne, non expose
    return {"task": texte, "members": retenus, "answers": answers, "ecartes": ecartes, "synthesis": synthesis,
            "perimetre_lecture": perimetre, **extra}


async def swarm(task: str, members: list[str], max_tokens: int = 900) -> dict:
    """Map (parallèle) -> Reduce (synthèse). Règle d'or : pure orchestration, 0 garde sémantique ici."""
    if len(task) > SEUIL_CONSIGNE:
        refus = (f"consigne de {len(task)} car. > seuil {SEUIL_CONSIGNE} : passer par "
                 f"swarm_pointeur(pointeurs=...) ou distiller")
        return {"task": task[:200], "members": members, "answers": [], "synthesis": None, "refus": refus}
    answers = await asyncio.gather(*[_one(p, task, max_tokens) for p in members])
    ok_ans = [a for a in answers if a["ok"] and a["text"]]
    synthesis = None
    if len(ok_ans) >= 2:
        joined = "\n\n".join(f"### {a['provider']} ({a.get('model')})\n{a['text']}" for a in ok_ans)
        s = await ask(
            SYNTH_PROVIDER,
            f"Synthétise ces {len(ok_ans)} réponses d'un swarm multi-CLI en UNE réponse consolidée "
            f"(garde les divergences notables, cite le provider):\n\n{joined}",
            max_tokens=max_tokens,
            rag_context=False,
        )
        synthesis = (s.get("text") or "").strip()
        if not synthesis:
            synthesis = f"[synthèse indisponible — {SYNTH_PROVIDER}: {s.get('error') or 'réponse vide'} (modèle local KO ? override LAFORGE_SWARM_SYNTH)]"
    return {"task": task, "members": members, "answers": answers, "synthesis": synthesis}


def _passer_lanceur(dossier) -> None:
    """Un passage de tools/forge_secours_lanceur.py (depot des demandes neuves, integration des secours finis).
    Choix owner 29/10 : enchaine au job du swarm (le lanceur ne marche qu'en job : 401 sous le compte owner)."""
    try:
        import forge_secours_lanceur as lz
    except ImportError:
        from tools import forge_secours_lanceur as lz
    lz.passer(Path(dossier))


def _main_pointeur(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pointeur", required=True, help="fichier contenant la consigne")
    ap.add_argument("--ptr", action="append", default=[], help="tasks.db:<id> ou chemin (repetable)")
    ap.add_argument("--membres", default="")
    ap.add_argument("--max-tours", type=int, default=6)
    a = ap.parse_args(argv)
    consigne = Path(a.pointeur).read_text(encoding="utf-8")
    membres = a.membres.split(",") if a.membres else None
    res = asyncio.run(swarm_pointeur(consigne, a.ptr, membres=membres, max_tours=min(a.max_tours, MAX_TOURS_DUR)))
    SORTIE_DIR.mkdir(parents=True, exist_ok=True)
    out = SORTIE_DIR / f"cli_swarm_ptr_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SWARM POINTEUR {sum(1 for x in res['answers'] if x.get('ok'))}/{len(res['answers'])} ok -> {out}")
    for e in res.get("ecartes", []):
        print(f"  ECARTE {e['provider']}: {e['raison']}")
    if res.get("synthesis"):
        print(f"SYNTHÈSE: {res['synthesis'][:300]}")
    elif res.get("demande_synthese") and _secours_actif():
        try:
            _passer_lanceur(SORTIE_DIR)
        except Exception as e:  # noqa: BLE001 - le secours ne casse jamais le swarm
            print(f"SECOURS : passage du lanceur impossible ({type(e).__name__}: {str(e)[:120]}) ; à relancer en job")
    return 0


def _integrer_secours(chemin_json: str, task_id: str, agent: str | None = None, texte: str | None = None) -> int:
    """LECTURE SEULE de la tache (statut hub) ; memes gardes que la cascade ; ecrit dans le JSON des resultats.

    `texte` (fichier) : fourni par le LANCEUR. Mesure 29/10 11 h 19 : `task status` est aussi reserve au ring <= 3
    (GATE_DENIED ring 4 depuis un job) -- garde conservee : le lanceur lit le statut, le job n'applique que les gardes."""
    p = Path(chemin_json)
    res = json.loads(p.read_text(encoding="utf-8"))
    demande = res.get("demande_synthese") or {}
    agent = agent or (demande.get("executeurs") or ["CLAUDE_HEADLESS"])[0]
    if texte is not None:
        try:
            brut = Path(texte).read_text(encoding="utf-8").strip()
        except OSError as e:
            print("texte du lanceur illisible (%s) : rien écrit" % type(e).__name__)
            return 3
    else:
        try:
            st = _statut_tache(task_id)
        except Exception as e:  # noqa: BLE001
            print("ILLISIBLE: statut %s" % str(e)[:120])
            return 3
        etat = str(st.get("status") or "")
        if etat in _ETATS_ECHEC:
            print("tâche %s en échec (%s) : rien écrit" % (task_id, etat))
            return 4
        if etat not in _ETATS_FINIS:
            print("tâche %s pas terminée (état %s) : rien écrit" % (task_id, etat or "inconnu"))
            return 2
        brut = _texte_resultat(st.get("results"))
    # 29/10 : un verdict JSON de l'executeur (« {"intent": "ERR_INTERNAL" ... ») a ete integre comme synthese ; et un
    # texte sans substance doit subir le meme garde que la cascade.
    if (brut or "").lstrip().startswith('{"intent"'):
        print("tâche %s : verdict JSON de l'exécuteur, pas une synthèse : rien écrit" % task_id)
        return 4
    court = _sans_substance(brut or "")
    if brut and court:
        print("tâche %s : %s : rien écrit" % (task_id, court))
        return 4
    if not brut:
        print("tâche %s terminée sans texte : rien écrit" % task_id)
        return 4
    sources = [str(res.get("task") or "")]
    ptr = demande.get("pointeur")
    if ptr and Path(ptr).is_file():
        sources += [e for a in json.loads(Path(ptr).read_text(encoding="utf-8")).get("answers", [])
                    for e in (a.get("extraits") or [])]
    brut, info = _ancrer_synthese(brut, sources)
    res["synthese_ancrage"] = info
    res["synthese_par"] = "executeur:%s" % agent
    if not brut.strip():
        res["synthese_motif"] = ("juge d'ancrage : toutes les lignes de la synthèse portent des chiffres "
                                 "sans source (%s)" % ", ".join(info["sans_source"]))
    else:
        synthesis, n = _garde_repetition(brut)
        if n:
            synthesis += f"\n[garde anti-répétition : {n} ligne(s) répétée(s) écartée(s)]"
            res["synthese_garde"] = {"declenche": True, "lignes_ecartees": n}
        if info["lignes_retirees"]:
            synthesis += (f"\n[juge d'ancrage : {info['lignes_retirees']} ligne(s) retirée(s), "
                          f"chiffres sans source : {', '.join(info['sans_source'])}]")
        res["synthesis"] = synthesis
    res.pop("demande_synthese", None)
    if res.get("synthesis"):
        res.pop("synthese_motif", None)  # le motif « synthese vide » est obsolete une fois le secours integre
    res["secours_integre"] = {"task_id": task_id, "agent": agent}
    p.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SECOURS INTÉGRÉ (%s, tâche %s) -> %s" % (agent, task_id, p))
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--integrer-secours" in argv:
        import argparse
        ap = argparse.ArgumentParser()
        ap.add_argument("--integrer-secours", nargs=2, metavar=("RESULTAT_JSON", "TASK_ID"), required=True)
        ap.add_argument("--agent", default=None)
        ap.add_argument("--texte", default=None, help="fichier ecrit par le LANCEUR (ring <= 3) : resultat de la tache")
        a = ap.parse_args(argv)
        return _integrer_secours(a.integrer_secours[0], a.integrer_secours[1], a.agent, a.texte)
    if "--pointeur" in argv:
        return _main_pointeur(argv)
    sys.argv = [sys.argv[0]] + list(argv)
    task = sys.argv[1] if len(sys.argv) > 1 else "Swarm test : en 1 phrase, qui es-tu (modèle réel) et ton ring ?"
    if len(sys.argv) > 2:
        members = sys.argv[2].split(",")
    else:
        members, raison = membres_par_defaut(REGISTRE)
        if raison:
            print(f"[essaim] membres par defaut : {raison}")
    res = asyncio.run(swarm(task, members))
    if res.get("refus"):
        print(f"REFUS: {res['refus']}")
        return 2
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = ROOT / "sandbox" / f"cli_swarm_{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    okc = sum(1 for a in res["answers"] if a["ok"])
    print(f"SWARM {okc}/{len(members)} ok -> {out}")
    for a in res["answers"]:
        tag = a.get("etat") or ("OK" if a["ok"] else "KO")
        print(f"  [{a['provider']:12}] {tag} {a['ms']}ms  {(a.get('error') or a['text'][:90])}")
    if res["synthesis"]:
        print(f"SYNTHÈSE: {res['synthesis'][:300]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
