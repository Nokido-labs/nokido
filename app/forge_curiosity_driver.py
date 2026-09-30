"""forge_curiosity_driver.py — boucle fermee veille auto par gap-detection.

Inspire de :
  - Schmidhuber compression progress driven curiosity (gain d'info marginal)
  - Stanley/Lehman Novelty Search (greatness cannot be planned)
  - Oudeyer developmental robotics intrinsic motivation

Pattern :
  1. SCAN rag_chunks: compute distribution domains/predicates/topics
  2. DETECT zones sous-representees (entropy haute = ignorance)
  3. DETECT nouveautes (claims recents avec faibles connexions = exploration)
  4. GENERATE themes auto via Cerebras llama-3.3-70b
  5. PUSH dans watch_jobs queue (worker existant pick + ingere)
  6. LOOP : nouvelles ingestions reduisent gaps -> recalcule -> nouveaux themes

API :
    curiosity_cycle()                  # 1 cycle complet (scan + generate + push)
    detect_knowledge_gaps()            # juste analyse
    generate_themes_for_gaps(gaps)     # juste LLM gen
"""

from __future__ import annotations
import argparse
import hashlib
import json
import logging
import math
import sqlite3
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("curiosity_driver")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CEREBRAS_URL = "https://api.cerebras.ai/v1/chat/completions"
GAP_THEME_BUDGET_PER_CYCLE = 5  # max themes auto-generes par cycle


def _conn():
    c = sqlite3.connect(str(DB), timeout=30)
    c.row_factory = sqlite3.Row
    return c


# --- 1. Scan distribution ---


def scan_domain_distribution() -> dict[str, int]:
    """Count chunks per domain. Domain entropie haute = bien couvert,
    domain rares = potentiels gaps."""
    c = _conn()
    try:
        rows = c.execute("""
            SELECT domain, COUNT(*) as n
            FROM rag_chunks
            WHERE (active IS NULL OR active = 1)
              AND domain IS NOT NULL
            GROUP BY domain
            ORDER BY n DESC
        """).fetchall()
        return {r["domain"]: r["n"] for r in rows}
    finally:
        c.close()


def scan_predicate_distribution() -> dict[str, int]:
    """Count claims per predicate."""
    c = _conn()
    try:
        rows = c.execute("""
            SELECT predicates FROM chunk_claims
            WHERE predicates IS NOT NULL
        """).fetchall()
        counter = Counter()
        for r in rows:
            try:
                preds = json.loads(r["predicates"] or "[]")
                counter.update(preds)
            except json.JSONDecodeError:
                continue
        return dict(counter)
    finally:
        c.close()


def scan_recency() -> dict[str, float]:
    """Last_ingested per domain. Domains pas updated depuis > 30j = gaps."""
    c = _conn()
    try:
        rows = c.execute("""
            SELECT domain, MAX(ingested_at) as last_ing
            FROM rag_chunks
            WHERE (active IS NULL OR active = 1)
              AND domain IS NOT NULL
            GROUP BY domain
        """).fetchall()
        return {r["domain"]: r["last_ing"] for r in rows}
    finally:
        c.close()


# --- 2. Detect gaps ---


def _entropy(counts: dict[str, int]) -> float:
    """Shannon entropy de la distribution."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    ps = [n / total for n in counts.values() if n > 0]
    return -sum(p * math.log(p, 2) for p in ps)


def detect_self_gaps(max_gaps: int = 8) -> list[dict]:
    """Gaps du CORPS, pas du corpus : ce que Nokido ne sait pas REGULER de lui-meme.

    Owner 2026-07-27 : « une mesure des gaps manquants dans le savoir renforcant les
    bases du systeme pour appeler la soif de connaissance sur SOI ». Jusqu'ici la
    curiosite ne scannait que le corpus (« quel sujet n'ai-je pas lu ? ») ; le savoir
    sur soi vivait a cote, mesure et ignore : `regulation_gaps()` rendait
    **29 morts silencieuses, 194 zones mortes, 16 organes en defaut** sur 1615 modules
    audites — le jour meme ou ces pannes ont ete debusquees A LA MAIN, une par une.

    AGREGE PAR ORGANE, jamais par module : 194 entrees noieraient les 50 gaps du
    corpus et la curiosite ne parlerait plus que d'elle-meme. On remonte le SYMPTOME
    d'organe, le detail reste dans l'audit.

    Fail-safe : toute erreur rend [] — un capteur de soi qui casse ne doit pas
    eteindre la soif du corpus.
    """
    try:
        from nokido_agent.app import forge_organ_agents as _oa

        fn = getattr(_oa, "regulation_gaps", None)
        if not fn:
            return []
        rep = fn() or {}
        by_organ = rep.get("by_organ") or {}
    except Exception:  # noqa: BLE001
        return []

    out: list[dict] = []
    for organe, detail in by_organ.items():
        if not isinstance(detail, dict):
            continue
        morts = detail.get("silent_death") or []
        zones = detail.get("dead_zone") or []
        # Une mort SILENCIEUSE prime : l'organe tombe sans que personne ne le sache.
        # Une zone morte est un angle mort, pas encore une panne.
        if morts:
            out.append({
                "type": "self_regulation_gap", "organ": str(organe), "kind": "silent_death",
                "n": len(morts), "modules": [str(m) for m in morts[:5]], "priority": 9,
            })
        elif len(zones) >= 5:
            out.append({
                "type": "self_regulation_gap", "organ": str(organe), "kind": "dead_zone",
                "n": len(zones), "modules": [str(m) for m in zones[:5]], "priority": 4,
            })
    out.sort(key=lambda g: (g["priority"], g["n"]), reverse=True)
    return out[:max_gaps]


def detect_stack_gaps(max_gaps: int = 6) -> list[dict]:
    """Gaps sur les BRIQUES qui composent Nokido : que sait-il de ses propres outils ?

    Owner 2026-07-27 : « commence par toutes les briques constituantes de Nokido, les
    nouveautes qui t'auraient echappe sur les technos qui le composent ». Le corps le
    signalait deja tout seul : le tout premier theme sorti du scan etait
    « Deno 2025 security sandbox enhancements », marque STALE depuis 82 jours — Deno
    etant le runtime de son propre superviseur.

    LE GAP N'EST PAS « la version est vieille ». C'est « Nokido ignore ce qui a change
    depuis CELLE QU'IL FAIT TOURNER ». D'ou deux choix :
      - la version REELLE entre dans la requete (`deno 2.7.14` et pas `deno`), ce qui
        rend la recherche pointue au lieu de generale ;
      - c'est `coverage_dense` qui tranche, pas une regle d'age : il rend gap=True
        (certain), False (couvert) ou None (zone grise / hors-variete -> ABSTENTION).
        On ne declenche jamais une veille sur un doute.

    Source : config/stack_versions.json — et non data/, qui est dans .gitignore : un
    inventaire du corps doit survivre a un clone, sinon cette fonction retombe sur son
    fail-safe EN SILENCE et la veille sur les briques ne part jamais. Les binaires du
    profil owner (deno, claude, codex) etant invisibles au compte sandbox, l'inventaire
    est mesure puis fige, jamais devine.
    Fail-safe : toute erreur rend [] — une veille en moins est benigne.
    """
    try:
        inv = json.loads((ROOT / "config" / "stack_versions.json").read_text(encoding="utf-8"))
        briques = inv.get("briques") or {}
    except Exception:  # noqa: BLE001
        return []

    # CAPTEUR LEXICAL, ET NON `coverage_dense` (mesure 2026-07-27, capteur ECARTE apres
    # essai). coverage_dense est calibre sur l'ignorance TOTALE — son commentaire le dit :
    # « gaps certains tous < -5 (blanquette -5.7, alpagas -6.7) ». Sur les 10 briques il a
    # rendu 9 `indetermine_abstention`, scores -4,6 a +0,6, en pleine zone grise. C'est
    # LOGIQUE : Nokido parle de deno et d'ollama partout dans son code, donc le dense
    # trouve du contenu proche. Mais la question n'est pas « connais-tu deno ? », c'est
    # « connais-tu deno 2.7.14 ». Un capteur d'ignorance grossiere ne mesure pas un angle
    # mort fin — choisir le capteur d'apres la QUESTION, pas d'apres sa disponibilite.
    # Critere retenu : la version MINEURE installee apparait-elle dans le corpus ? Si
    # « deno 2.7 » n'est cite nulle part, Nokido ne peut rien savoir de ses nouveautes.
    # Deterministe, lexical (FTS5), quasi gratuit — la ou le dense coutait 16,5 s.
    import sqlite3 as _sq

    try:
        from nokido_agent.app.forge_db_path import db_path

        con = _sq.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=15)
    except Exception:  # noqa: BLE001
        return []

    out: list[dict] = []
    try:
        for nom, meta in briques.items():
            ver = str((meta or {}).get("version") or "").strip()
            if not ver:
                continue
            # Majeure.mineure : « 2.7 » plutot que « 2.7.14 » — un correctif de patch
            # n'a pas de notes de version propres, une mineure si.
            mineure = ".".join(ver.split(".")[:2])
            try:
                n_hits = con.execute(
                    "SELECT COUNT(*) FROM rag_fts WHERE rag_fts MATCH ?",
                    (f'"{nom}" AND "{mineure}"',),
                ).fetchone()[0]
            except Exception:  # noqa: BLE001
                continue  # requete FTS invalide sur ce nom -> on s'abstient
            if n_hits > 0:
                continue  # la version est citee quelque part : pas un angle mort
            out.append({
                "type": "stack_version_gap",
                "brique": nom,
                "version": ver,
                "version_mineure": mineure,
                "organe": (meta or {}).get("organe", "?"),
                "role": (meta or {}).get("role", ""),
                "n_hits": n_hits,
                # Au niveau des morts silencieuses : une brique du corps dont on ignore
                # la version en service est une dette structurelle, pas une curiosite.
                "priority": 8,
            })
    finally:
        con.close()
    out.sort(key=lambda g: g["priority"], reverse=True)
    return out[:max_gaps]


def detect_knowledge_gaps(min_domain_floor: int = 3, recency_threshold_days: int = 30) -> list[dict]:
    from nokido_agent.app.forge_epistemic_veille import coverage_dense
    """Identifie gaps multi-types :
    1. domain_under_represented : domain avec < min_domain_floor chunks
    2. domain_stale : domain pas update > recency_threshold_days
    3. predicate_isolated : predicate present dans 1-2 chunks seulement (peut etre veine inexplore)
    4. high_entropy_predicates : predicates les + frequents mais distribution claims floue
    """
    gaps = []
    domain_dist = scan_domain_distribution()
    pred_dist = scan_predicate_distribution()
    recency = scan_recency()

    # Type 1 : domain sous-represente
    for domain, n in sorted(domain_dist.items(), key=lambda x: x[1]):
        if n < min_domain_floor and not domain.startswith("watch_veille"):
            cov = coverage_dense(domain)
            if cov.get("ok") and cov.get("gap") is True:
                gaps.append(
                    {
                        "type": "domain_under_represented",
                        "domain": domain,
                        "n_chunks": n,
                        "priority": 10 - n,  # plus rare = plus prioritaire
                    }
                )

    # Type 2 : domain stale
    now = datetime.now(tz=timezone.utc)
    for domain, last_ing in recency.items():
        if not last_ing:
            continue
        try:
            dt = datetime.fromisoformat(last_ing.replace("Z", "+00:00"))
            # Force tz-aware si naive
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_days = (now - dt).days
        except (ValueError, AttributeError):
            continue
        if age_days > recency_threshold_days and domain_dist.get(domain, 0) > 0:
            gaps.append(
                {
                    "type": "domain_stale",
                    "domain": domain,
                    "age_days": age_days,
                    "priority": min(10, age_days // 7),
                }
            )

    # Type 3 : predicates isoles (claims rares = vein exploration)
    for pred, n in pred_dist.items():
        if 1 <= n <= 2 and len(pred) > 4 and not pred.isdigit():
            gaps.append(
                {
                    "type": "predicate_isolated",
                    "predicate": pred,
                    "n_claims": n,
                    "priority": 3,  # exploration tentative
                }
            )

    # Type 4 : gaps du CORPS (cf detect_self_gaps). La soif se retourne vers soi.
    gaps.extend(detect_self_gaps())

    # Type 5 : gaps sur les BRIQUES qui composent Nokido (cf detect_stack_gaps).
    gaps.extend(detect_stack_gaps())

    # Sort par priorite descendante
    gaps.sort(key=lambda g: g.get("priority", 0), reverse=True)
    return gaps[:50]  # top 50 gaps


# --- 3. Generate themes via Cerebras ---


# 2000 et non 600 (mesure 2026-07-27) : `gpt-oss-120b` est un modele a RAISONNEMENT
# et le budget est PARTAGE entre son raisonnement et sa reponse. A 600, il epuisait
# son quota a reflechir : la reponse sortait tronquee en plein milieu d'un rationale
# (755 chars, objet racine JAMAIS referme) -- ou vide, d'ou le repli `reasoning` plus
# bas qui rendait sa reflexion en clair. Resultat : 20 gaps reels, 0 theme, a CHAQUE
# cycle. Le symptome ressemblait a un probleme de parsing ; c'etait une famine de tokens.
def _cerebras_call(prompt: str, key: str, max_tokens: int = 2000) -> str:
    body = json.dumps(
        {
            "model": "gpt-oss-120b",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.7,  # plus haut pour creativite themes
        }
    ).encode()
    req = urllib.request.Request(
        CEREBRAS_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key.strip()}",
            "User-Agent": "Mozilla/5.0 LaForge-Agent",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read())
    msg = data["choices"][0]["message"]
    return msg.get("content") or msg.get("reasoning", "")


GENERATE_THEMES_PROMPT = """You are a curiosity-driven research scout for an AI system.
The knowledge base has gaps in the following areas:

{gaps_summary}

Generate {n} research themes (in English) that would fill these gaps.
Each theme should be:
- A specific, searchable query (3-10 words)
- Focused on a CONCRETE technical or scientific topic
- Diverse: cover different gap types (under-represented domains AND stale areas AND isolated predicates)
- Recent: prefer 2024-2026 topics
- NOT a duplicate of common LLM/AI cliches

Output STRICT JSON:
{{"themes": [{{"theme":"...","rationale":"why this fills a gap","gap_type":"..."}}]}}"""


def _extract_json(raw: str, require_key: str | None = None) -> dict:
    """Extrait le premier objet JSON d'une reponse LLM, meme precedee de prose.

    MESURE 2026-07-27 : l'appel Cerebras REUSSIT, mais le modele prefixe sa sortie
    par son raisonnement en clair ("We need to produce 3 research themes, each a
    specific searchable query...") avant le JSON. `json.loads(raw)` levait alors
    JSONDecodeError -> except -> return [] -> 20 gaps reels rendaient 0 theme,
    chaque cycle, depuis toujours, avec pour seule trace un logger.warning que
    personne ne lit. La soif fonctionnait de bout en bout : on jetait sa reponse.

    Tolere : JSON nu, bloc ```json ... ```, et prose avant/apres.
    """
    import re  # local : `re` n'est PAS un global de ce module (NameError mesure 2026-07-27,
    # qui frappait justement le cas reel "prose avant JSON" et etait avale par l'except).

    if not isinstance(raw, str):
        raise json.JSONDecodeError("reponse non textuelle", str(raw), 0)
    def _ok(obj):
        """Un objet ne convient que s'il porte la cle attendue.

        SANS ce garde (mesure 2026-07-27), une reponse TRONQUEE se lisait comme un
        succes : l'objet racine n'etant pas referme, le scan tombait sur le premier
        element du tableau `themes` -- equilibre, lui -- et rendait
        {'theme','rationale','gap_type'}. `parsed.get('themes')` valait alors [] et
        la troncature passait pour un cycle sain. Un parseur permissif qui masque
        une famine de tokens est pire qu'un parseur strict qui la signale.
        """
        return isinstance(obj, dict) and (require_key is None or require_key in obj)

    txt = raw.strip()
    try:
        _p = json.loads(txt)  # cas nominal : JSON pur
        if _ok(_p):
            return _p
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", txt, re.DOTALL)
    if fence:
        _p = json.loads(fence.group(1))
        if _ok(_p):
            return _p
    # Premier objet equilibre (le modele peut parler avant ET apres).
    start = txt.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(txt)):
            c = txt[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        _p = json.loads(txt[start:i + 1])
                        if _ok(_p):
                            return _p
                    except json.JSONDecodeError:
                        pass
                    break
        start = txt.find("{", start + 1)
    raise json.JSONDecodeError("aucun objet JSON exploitable dans la reponse", txt[:200], 0)


# Themes de SOI par TEMPLATE — deterministe, zero token, zero reseau (owner 2026-07-27 :
# « si la ram sature, une methode moins gourmande est possible ? »). Un gap de regulation
# est deja une question formee : « l'organe X a N modules dont la mort est silencieuse »
# n'a pas besoin d'un LLM pour devenir une requete de recherche. La mesure etait deja
# deterministe (dense Qdrant + BM25 + rerank + manifold_error, cf coverage_dense) ; le
# cloud ne servait qu'a REDIGER. Ici on n'en a meme pas besoin -> la soif sur soi survit
# a une panne cloud, a un quota epuise et a une RAM saturee.
# MESURE 2026-07-27, premiere veille reelle sur soi (wj_ea26989e95) : le theme
# « silent process death detection heartbeat supervision non classe » a ramene
# 80 chunks d'un survey arXiv sur les GAN de series temporelles + 2 papiers
# d'APOPTOSE. « process death » et « heartbeat » existent aussi en biologie, et
# sans ancrage logiciel le moteur choisit la mauvaise acception. Le refine a bien
# note les 3 candidats sous le seuil (garde-fou tenu), mais 82 chunks hors sujet
# etaient deja vectorises.
# DEUX REGLES QUI EN DECOULENT :
#   1. ANCRER le domaine (« software », « daemon », « service ») — un terme
#      polysemique sans contexte est une requete perdue ;
#   2. NE JAMAIS injecter le nom d'organe dans la requete : « non classe » ou
#      « SN vegetatif (autonome) » sont des libelles INTERNES, sans aucun sens
#      pour un moteur de recherche — du bruit qui dilue les termes utiles.
#      L'organe reste dans le `rationale`, ou il sert au lecteur, pas au moteur.
_SELF_THEME_TPL = {
    "silent_death": ("software daemon crash detection watchdog heartbeat "
                     "process supervision monitoring"),
    "dead_zone": ("dead code detection unused module static analysis "
                  "software observability instrumentation"),
}


def _self_gap_themes(gaps: list[dict]) -> list[dict]:
    """Themes deterministes pour les gaps du CORPS. Aucun appel externe.

    AGREGE PAR `kind`, pas par organe : huit organes qui souffrent du meme mal
    posent UNE question, pas huit. Le detail (quels organes, combien de modules)
    va dans le `rationale`, qui sert au lecteur ; la requete, elle, ne doit porter
    que des termes cherchables.
    """
    par_kind: dict[str, dict] = {}
    for g in gaps:
        if g.get("type") != "self_regulation_gap":
            continue
        kind = g.get("kind")
        theme = (_SELF_THEME_TPL.get(kind) or "").strip()
        if not (10 < len(theme) < 300):
            continue
        acc = par_kind.setdefault(kind, {"theme": theme, "n_modules": 0, "organes": [], "exemples": []})
        acc["n_modules"] += int(g.get("n") or 0)
        acc["organes"].append(str(g.get("organ", "?")))
        acc["exemples"].extend(g.get("modules", [])[:2])

    out = []
    for kind, acc in par_kind.items():
        out.append({
            "theme": acc["theme"],
            "rationale": (f"{acc['n_modules']} modules en {kind} repartis sur "
                          f"{len(acc['organes'])} organes ({', '.join(acc['organes'][:3])}...). "
                          f"Ex: {', '.join(acc['exemples'][:4])}. "
                          "Gap mesure par regulation_gaps, pas infere."),
            "gap_type": "self_regulation",
        })
    return out


def generate_themes_for_gaps(gaps: list[dict], n: int = GAP_THEME_BUDGET_PER_CYCLE) -> list[dict]:
    """Themes de SOI par template (deterministe) + themes de corpus via LLM."""
    if not gaps:
        return []

    # 1. Le corps d'abord, sans dependance externe. Si le cloud tombe, la soif sur soi
    #    continue de parler — c'est la partie qu'on ne veut JAMAIS perdre.
    self_themes = _self_gap_themes(gaps)[:n]
    if len(self_themes) >= n:
        return self_themes
    n = n - len(self_themes)
    try:
        from nokido_agent.app.forge_secrets import get_secret

        key = get_secret("CEREBRAS_API_KEY") or get_secret("GROQ_API_KEY")
    except Exception:
        return self_themes
    if not key:
        logger.warning("[curiosity] aucune cle cloud — seuls les themes de SOI (deterministes) sont produits")
        return self_themes

    # Summarize top gaps for prompt
    gap_lines = []
    for g in gaps[:20]:
        if g["type"] == "domain_under_represented":
            gap_lines.append(f"- DOMAIN gap: '{g['domain']}' has only {g['n_chunks']} chunks")
        elif g["type"] == "domain_stale":
            gap_lines.append(f"- STALE: '{g['domain']}' not updated {g['age_days']}d")
        elif g["type"] == "predicate_isolated":
            gap_lines.append(f"- ISOLATED PREDICATE: '{g['predicate']}' only {g['n_claims']} claims")
        elif g["type"] == "stack_version_gap":
            gap_lines.append(
                f"- STACK gap: Nokido runs '{g['brique']} {g['version']}' ({g.get('role', '')}) "
                f"but has no recent knowledge of its changelog / breaking changes. "
                f"Need what changed since {g['version']}, migration notes, new capabilities"
            )
        elif g["type"] == "self_regulation_gap":
            # Gap sur SOI : on demande de quoi mieux REGULER cet organe, pas un sujet
            # de veille generique. Sans cette ligne, ces gaps traversaient la fonction
            # sans produire une seule ligne de prompt (gap_lines vide = prompt muet).
            _quoi = ("modules whose death is SILENT (started without heartbeat)"
                     if g.get("kind") == "silent_death" else "unmonitored dead-zone modules")
            gap_lines.append(
                f"- SELF/BODY gap: organ '{g['organ']}' has {g['n']} {_quoi} "
                f"(e.g. {', '.join(g.get('modules', [])[:3])}) — need engineering knowledge "
                f"to detect and regulate this failure mode"
            )

    prompt = GENERATE_THEMES_PROMPT.format(
        gaps_summary="\n".join(gap_lines),
        n=n,
    )

    try:
        raw = _cerebras_call(prompt, key)
        parsed = _extract_json(raw, require_key="themes")
        themes = parsed.get("themes", [])
        # Validation
        valid = []
        for t in themes[:n]:
            theme_text = (t.get("theme") or "").strip()
            if 10 < len(theme_text) < 300:
                valid.append(
                    {
                        "theme": theme_text,
                        "rationale": (t.get("rationale") or "")[:200],
                        "gap_type": t.get("gap_type", "auto_curiosity"),
                    }
                )
        return self_themes + valid
    except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
        # BRUYANT A DESSEIN : un cycle qui detecte N gaps et rend 0 theme est une
        # soif eteinte, pas un cycle sain. Le warning d'origine etait invisible.
        logger.error(
            f"[curiosity] volet CORPUS eteint — {len(gaps)} gaps detectes, "
            f"({type(e).__name__}: {str(e)[:120]}). Reponse LLM non exploitable. "
            f"Themes de SOI conserves: {len(self_themes)}."
        )
        return self_themes


# --- 4. Push themes -> watch_jobs queue ---


def push_themes_to_queue(themes: list[dict], dry_run: bool = False) -> int:
    """Insert themes dans watch_jobs + create chain_nodes (mimicking forge_watch_agent.create_job).
    Idempotent : skip si theme exact deja existe."""
    if not themes:
        return 0

    c = _conn()
    n_pushed = 0
    try:
        for t in themes:
            theme = t["theme"]
            # Dedup check
            existing = c.execute("SELECT id FROM watch_jobs WHERE theme = ? LIMIT 1", (theme,)).fetchone()
            if existing:
                logger.debug(f"skip dup: {theme[:60]}")
                continue

            if dry_run:
                logger.info(f"  DRY would push: {theme[:80]}")
                n_pushed += 1
                continue

            # DELEGUE A L'ORIGINAL (2026-07-27). Ce bloc RECOPIAIT create_job
            # (« mimicking », disait la docstring) et la copie a DERIVE : le schema
            # a rendu `agent_chain_nodes.llm_preferred` NOT NULL, l'original l'a
            # suivi, pas la copie -> `IntegrityError: NOT NULL constraint failed`
            # a CHAQUE push. Mesure du jour : cycle reel en erreur, watch_jobs
            # inchange (84 avant, 84 apres), zero theme pousse. La soif produisait
            # ses questions et on les jetait sur la derniere marche.
            # La copie perdait aussi la transaction `BEGIN IMMEDIATE` de l'original
            # — une chaine a moitie creee est reprise comme valide par l'executor.
            # Deux raisons de ne pas rapiecer mais d'appeler : la dette de schema
            # ne se paie qu'une fois, et l'atomicite vient avec.
            from nokido_agent.app.forge_watch_agent import create_job as _create_job  # local : evite le cycle d'import

            jid = _create_job(theme, idea_id=t.get("gap_type", "auto"), agent="CURIOSITY_DRIVER")
            n_pushed += 1
            logger.info(f"  pushed {jid}: {theme[:60]}")

        if not dry_run:
            c.commit()
    finally:
        c.close()
    return n_pushed


# --- Schmidhuber compression progress (CP) metric ---


def _zstd_size(data: bytes) -> int:
    """Mesure taille compressee zstd niveau 3. Si zstandard absent, fallback zlib."""
    try:
        import zstandard as zstd

        return len(zstd.ZstdCompressor(level=3).compress(data))
    except ImportError:
        import zlib

        return len(zlib.compress(data, level=6))


def compression_progress(domain: str = None, sample_size: int = 200, baseline_days: int = 7) -> dict:
    """Calcule Schmidhuber compression progress (CP) entre baseline (chunks
    plus anciens que baseline_days) et recent (derniers chunks).

    CP > 0 = nouveaux chunks reduisent surprise (knowledge converge, peu de gain).
    CP < 0 = nouveaux chunks augmentent surprise (vraie nouveaute, gain info).

    Drives curiosity : si CP < threshold (peu de nouveaute) sur un domain,
    on TRIGGER nouvelle veille focus zones rares.

    Args:
        domain: filter par domain (None = all)
        sample_size: nb chunks par groupe (baseline + recent)
        baseline_days: age cutoff baseline vs recent

    Returns:
        {baseline_size_bytes, recent_size_bytes, compression_ratio_baseline,
         compression_ratio_recent, cp_score, interpretation}
    """
    c = _conn()
    try:
        from datetime import timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(days=baseline_days)).isoformat()

        where_dom = f"AND domain='{domain}'" if domain else ""

        # Baseline : chunks plus anciens
        rows_old = c.execute(
            f"""
        SELECT text FROM rag_chunks
        WHERE ingested_at < ? {where_dom}
        AND text IS NOT NULL AND length(text) > 50
        ORDER BY RANDOM() LIMIT ?
        """,
            (cutoff, sample_size),
        ).fetchall()

        # Recent : chunks recents
        rows_new = c.execute(
            f"""
        SELECT text FROM rag_chunks
        WHERE ingested_at >= ? {where_dom}
        AND text IS NOT NULL AND length(text) > 50
        ORDER BY RANDOM() LIMIT ?
        """,
            (cutoff, sample_size),
        ).fetchall()

        if not rows_old or not rows_new:
            return {"skip": "insufficient data", "n_baseline": len(rows_old), "n_recent": len(rows_new)}

        old_text = "\n".join(r["text"] for r in rows_old).encode("utf-8", errors="replace")
        new_text = "\n".join(r["text"] for r in rows_new).encode("utf-8", errors="replace")

        old_comp = _zstd_size(old_text)
        new_comp = _zstd_size(new_text)
        old_ratio = old_comp / len(old_text) if old_text else 1.0
        new_ratio = new_comp / len(new_text) if new_text else 1.0

        # CP = baseline_ratio - recent_ratio
        # Positive = recent compresse mieux (knowledge stabilizes = less novelty)
        # Negative = recent compresse moins bien (more novelty = exploration needed)
        cp = old_ratio - new_ratio

        if cp > 0.05:
            interp = "high_redundancy"
        elif cp > 0.0:
            interp = "stabilizing"
        elif cp > -0.05:
            interp = "novel_balanced"
        else:
            interp = "high_novelty"

        return {
            "domain": domain or "all",
            "n_baseline": len(rows_old),
            "n_recent": len(rows_new),
            "baseline_size_bytes": len(old_text),
            "recent_size_bytes": len(new_text),
            "compression_ratio_baseline": round(old_ratio, 4),
            "compression_ratio_recent": round(new_ratio, 4),
            "cp_score": round(cp, 4),
            "interpretation": interp,
        }
    finally:
        c.close()


def cp_driven_theme_priority(threshold: float = 0.05) -> list[str]:
    """Identifie domains avec compression_progress > threshold = trop redondants,
    suggest themes pour explorer zones moins couvertes.

    Returns list of domains needing novel content.
    """
    c = _conn()
    try:
        domains = [
            r["domain"] for r in c.execute("SELECT DISTINCT domain FROM rag_chunks WHERE domain IS NOT NULL").fetchall()
        ]
    finally:
        c.close()

    stagnant = []
    for d in domains[:20]:
        cp = compression_progress(domain=d, sample_size=100)
        if cp.get("cp_score", 0) > threshold:
            stagnant.append(d)
    return stagnant


# --- 5. Cycle complet ---


def capitalize_completed(max_jobs: int = 10) -> dict:
    """Transforme le savoir RETENU par une veille en LECON reutilisable (anchor_solution).

    Le chainon manquant de la boucle. `pat_curiosity_driver` ancrait deja quelque chose,
    mais il ancrait LE CYCLE (« 3 themes -> 1 push ») : ancrer « j'ai cherche » n'est pas
    ancrer « j'ai compris ». Sans cette etape le savoir reste des chunks passifs que
    personne ne relit — le sort exact des 29 morts silencieuses, mesurees depuis des
    semaines et jamais lues.

    Ancre du FACTUEL, pas une synthese LLM : le gap d'origine, les sources retenues,
    les modules en defaut. Deterministe, zero token, et directement actionnable — le
    prochain agent qui trouve `forge_comm_watch.py` mort en silence tombera sur la
    lecture correspondante au lieu de rejouer l'enquete.

    Ne capitalise QUE si la veille a effectivement retenu (`n_stored > 0`) : ancrer une
    recherche bredouille produirait une lecon creuse, que le memory_gate rejetterait de
    toute facon. Les jobs sans retenue sont marques comme vus, pour ne pas etre
    re-examines a chaque cycle.

    Idempotent via `sandbox/curiosity_capitalized.json`.
    """
    import sqlite3 as _sq

    etat_p = ROOT / "sandbox" / "curiosity_capitalized.json"
    try:
        deja = set(json.loads(etat_p.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        deja = set()

    out = {"examines": 0, "ancres": 0, "sans_retenue": 0, "lecons": []}
    try:
        from nokido_agent.app.forge_db_path import db_path

        con = _sq.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=15)
    except Exception:  # noqa: BLE001
        return out
    try:
        rows = con.execute(
            "SELECT id, theme, idea_id, status, n_ingested, n_stored, refined_json "
            "FROM watch_jobs WHERE agent='CURIOSITY_DRIVER' AND status LIKE 'completed%' "
            "ORDER BY rowid DESC LIMIT 50"
        ).fetchall()
    except Exception:  # noqa: BLE001
        rows = []
    finally:
        con.close()

    try:
        from nokido_agent.app.forge_self_correction import anchor_solution
    except Exception:  # noqa: BLE001
        return out

    vus = list(deja)
    for jid, theme, idea_id, status, n_ing, n_sto, refined in rows:
        if jid in deja or out["examines"] >= max_jobs:
            continue
        out["examines"] += 1
        vus.append(jid)
        # ASSOUPLISSEMENT AGY (2026-07-28) CONSERVE, avec une exclusion mesuree.
        # Sa remarque est juste : beaucoup de veilles enrichissent le RAG sans rien
        # promouvoir en biblio (rejet duplicate_hash), et exiger n_stored>0 les rendait
        # steriles A JAMAIS — le savoir restait passif, jamais capitalise.
        # MAIS `completed_empty` est le cas ou le systeme a LUI-MEME juge n'avoir rien
        # retenu de valable : mesure du jour, wj_ea26989e95 porte n_ingested=82 pour
        # 3 candidats tous sous le seuil — 82 chunks d'apoptose pour une question de
        # supervision de processus. En ancrer une lecon apprendrait une FAUSSE reponse
        # au prochain agent. On capitalise donc l'enrichissement reel, jamais l'echec
        # declare. (`completed_dedup` reste eligible : « on possede deja » est un savoir.)
        if (not n_sto and not n_ing) or str(status or "").startswith("completed_empty"):
            out["sans_retenue"] += 1
            continue

        # Sources effectivement retenues (les refuses portent leur motif dans `refus`).
        gardees = []
        try:
            d = json.loads(refined) if refined else {}
            refuses = {str(w.get("u")) for w in (d.get("refus") or [])}
            for c in (d.get("candidats") or []):
                if str(c.get("u")) not in refuses:
                    gardees.append(f"{str(c.get('t'))[:70]} <{c.get('u')}>")
        except Exception:  # noqa: BLE001
            pass

        res = anchor_solution(
            problem=f"Gap du corps '{idea_id}' : {str(theme)[:120]}",
            solution=(f"Veille {jid} : {n_sto} source(s) retenue(s) sur {n_ing} chunks ingeres. "
                      f"Sources : {' | '.join(gardees[:3]) if gardees else '(non listees)'}"),
            example=f"rag: source LIKE 'watch%' AND theme={str(theme)[:60]}",
            domain="autoregulation",
        )
        if res.get("ok"):
            out["ancres"] += 1
            out["lecons"].append({"job": jid, "chunk": res.get("chunk_id")})
        elif res.get("rejected"):
            # Rejet de FOND par le memory_gate : lecon jugee creuse. C'est son role,
            # on n'insiste pas et le job reste marque vu.
            out.setdefault("rejets", []).append({"job": jid, "raison": res.get("rejected")})
        else:
            # ECHEC TECHNIQUE (mesure 2026-07-28 : « database is locked », les 5 veilles
            # d'AGY ecrivant en parallele). Une ecriture SQLite perdue sous contention
            # l'est DEFINITIVEMENT si personne ne la reprend — et marquer le job « vu »
            # ici condamnait la lecon a ne jamais renaitre. On le RETIRE des vus pour
            # que le prochain cycle la retente. Un rejet de fond se retient, un verrou
            # se rejoue : ne pas confondre « juge sans valeur » et « pas pu ecrire ».
            if vus and vus[-1] == jid:
                vus.pop()
            out.setdefault("a_reprendre", []).append({"job": jid, "raison": res.get("error")})

    try:
        etat_p.parent.mkdir(parents=True, exist_ok=True)
        etat_p.write_text(json.dumps(sorted(set(vus))[-500:], ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return out


def curiosity_cycle(dry_run: bool = False, n_themes: int = GAP_THEME_BUDGET_PER_CYCLE) -> dict:
    """1 cycle complet : capitalise le precedent -> scan -> detect -> generate -> push."""
    # Etape 0 : capitaliser ce que le cycle PRECEDENT a rapporte. Le push est asynchrone
    # (le ChainExecutor traite plus tard), donc la recolte se fait forcement au tour d'apres.
    if not dry_run:
        try:
            _cap = capitalize_completed()
            if _cap.get("ancres"):
                logger.info(f"[curiosity] capitalisation : {_cap['ancres']} lecon(s) ancree(s)")
        except Exception as _e:  # noqa: BLE001
            logger.warning(f"[curiosity] capitalisation KO: {_e}")
    logger.info("[1/4] Scan distributions...")
    domain_dist = scan_domain_distribution()
    pred_dist = scan_predicate_distribution()
    logger.info(
        f"  domains={len(domain_dist)} predicates={len(pred_dist)} "
        f"H_domain={_entropy(domain_dist):.2f} H_pred={_entropy(pred_dist):.2f}"
    )

    logger.info("[2a/4] Schmidhuber compression progress (CP) scan...")
    cp_global = compression_progress(domain=None, sample_size=150, baseline_days=14)
    stagnant_domains = cp_driven_theme_priority(threshold=0.05) if cp_global.get("cp_score", 0) > 0 else []
    logger.info(f"  CP global: {cp_global.get('cp_score')} ({cp_global.get('interpretation')})")
    if stagnant_domains:
        logger.info(f"  stagnant domains (CP>0.05): {stagnant_domains[:5]}")

    logger.info("[2b/4] Detect knowledge gaps...")
    gaps = detect_knowledge_gaps()
    # Boost gaps des domains stagnants (CP) en tete de liste
    if stagnant_domains:
        gaps_stagnant = [g for g in gaps if g.get("domain") in stagnant_domains]
        gaps_other = [g for g in gaps if g.get("domain") not in stagnant_domains]
        gaps = gaps_stagnant + gaps_other
    logger.info(f"  detected {len(gaps)} gaps (top types: {Counter(g['type'] for g in gaps[:20]).most_common(3)})")

    logger.info(f"[3/4] Generate {n_themes} themes via Cerebras...")
    themes = generate_themes_for_gaps(gaps, n=n_themes)
    logger.info(f"  generated {len(themes)} themes")
    for t in themes:
        logger.info(f"    + {t['theme'][:70]}  ({t.get('gap_type', '?')})")

    logger.info(f"[4/4] Push to watch_jobs (dry_run={dry_run})...")
    n_pushed = push_themes_to_queue(themes, dry_run=dry_run)

    return {
        "dry_run": dry_run,
        "n_domains": len(domain_dist),
        "n_predicates": len(pred_dist),
        "entropy_domain": round(_entropy(domain_dist), 3),
        "entropy_predicate": round(_entropy(pred_dist), 3),
        "n_gaps_detected": len(gaps),
        "n_themes_generated": len(themes),
        "n_pushed": n_pushed,
        "themes": themes,
    }


# --- CLI ---


def main():
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--n-themes", type=int, default=GAP_THEME_BUDGET_PER_CYCLE)
    ap.add_argument("--scan-only", action="store_true", help="Just scan + detect gaps, no LLM call")
    args = ap.parse_args()

    if args.scan_only:
        gaps = detect_knowledge_gaps()
        print(json.dumps({"n_gaps": len(gaps), "top_10": gaps[:10]}, indent=2))
        return

    result = curiosity_cycle(dry_run=args.dry_run, n_themes=args.n_themes)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
