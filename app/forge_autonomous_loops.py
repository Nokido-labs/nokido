"""
forge_autonomous_loops.py — Boucle évolutive autonome Nokido.

Orchestrateur de patterns récurrents qui font évoluer Nokido sans
intervention humaine. **Coût zéro cloud** : utilise UNIQUEMENT les
LLMs locaux (llamacpp :8080 + ollama :11434).

Patterns enregistrés (registry extensible) :
  1. health_check        (5min)  — services NSSM up, alerte si down
  2. git_hygiene         (1h)    — détecte uncommitted, suggère commits
  3. rag_warmup_delta    (6h)    — index nouveaux fichiers depuis last_run
  4. tool_effectiveness  (24h)   — stats usage tools, cleanup unused
  5. forge_missing_tool  (24h)   — détecte gaps dispatch → propose forge
  6. lessons_consolidate (48h)   — merge similar anchors RAG via local LLM

Cycle Singularité Faire-Savoir : chaque action anchore son résultat dans
RAG (`anchor_solution(domain="autonomous")`).

Lancement :
    LAFORGE_PYTHON app/forge_autonomous_loops.py --daemon
ou
    NSSM service NokidoAutonomousLoops auto-start

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `pat_evolution_triage` — Consomme les PENDING_CANDIDATE non encore tries, les regroupe par dossier.
- `pat_proposal_applier` — Le maillon qui manquait (mesure 2026-09-24) : branche `forge_proposal_applier`.
- `verifier_chaine_evolution` — Recalcule la chaine du registre d'evolution ; nomme la PREMIERE rupture (numero de ligne, 1-based).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from logging.handlers import RotatingFileHandler
import sqlite3
import subprocess
import sys
import time
import urllib.request

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[role:autonomous_loops|phase:G+|color:GREEN|lobe:frontal]"

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
from nokido_agent.app.forge_db_path import m2m_path  # noqa: E402  # scission M2M : agent_messages suit l'interrupteur sandbox/m2m.switch ; DB reste pour les autres tables
LOG_FILE = ROOT / "sandbox" / "autonomous_loops.log"
LLAMACPP_URL = "http://127.0.0.1:8080/v1/chat/completions"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"

# ── Logging ──────────────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler(LOG_FILE, encoding="utf-8", maxBytes=10485760, backupCount=5),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("autonomous_loops")


# ══════════════════════════════════════════════════════════════════════
# SCHEMA persistence
# ══════════════════════════════════════════════════════════════════════
_SCHEMA = """
CREATE TABLE IF NOT EXISTS autonomous_loop_state (
    pattern TEXT PRIMARY KEY,
    last_run REAL DEFAULT 0,
    last_status TEXT,
    last_outcome TEXT,
    runs_total INTEGER DEFAULT 0,
    runs_success INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS autonomous_loop_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    ts REAL NOT NULL,
    status TEXT,
    outcome TEXT,
    details TEXT
);
CREATE INDEX IF NOT EXISTS idx_autoloop_audit_ts ON autonomous_loop_audit(ts);
"""


def _ensure_schema():
    conn = sqlite3.connect(str(DB))
    for stmt in _SCHEMA.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════════════════
# REGISTRY
# ══════════════════════════════════════════════════════════════════════
@dataclass
class Pattern:
    name: str
    fn: Callable[[], dict]
    interval_sec: int
    description: str = ""
    requires_local_llm: bool = False
    enabled: bool = True
    # Circadian : fenêtre horaire préférée (24h format).
    # None = always-on. (start, end) inclusif. Si end<start, traverse minuit.
    preferred_window: tuple[int, int] | None = None


PATTERNS: dict[str, Pattern] = {}


def register_pattern(
    name: str,
    interval_sec: int,
    description: str = "",
    requires_local_llm: bool = False,
    preferred_window: tuple[int, int] | None = None,
):
    """Decorator pour enregistrer une routine."""

    def deco(fn):
        PATTERNS[name] = Pattern(
            name=name,
            fn=fn,
            interval_sec=interval_sec,
            description=description,
            requires_local_llm=requires_local_llm,
            preferred_window=preferred_window,
        )
        return fn

    return deco


def _in_preferred_window(window: tuple[int, int] | None) -> bool:
    """True si heure courante dans fenêtre. None = toujours OK."""
    if window is None:
        return True
    import datetime as _dt

    h = _dt.datetime.now().hour
    start, end = window
    if start <= end:
        return start <= h <= end
    # Traverse minuit (ex: 23-6)
    return h >= start or h <= end


@register_pattern(
    "eval_fitness", interval_sec=7200,
    description="Surveille scores benchmark (HumanEval/BFCL/SWE), proposal si régression >5%.",
    preferred_window=None,
)
def pat_eval_fitness() -> dict:
    """Eval-driven : LIT les derniers scores (ne lance PAS les benchs), détecte
    une régression vs dernier relevé, écrit une proposal pour self_patcher (gated).
    Anti-régression : surveiller, ne rien dégrader."""
    import json as _j
    import time as _t
    from pathlib import Path as _P
    try:
        from nokido_agent.app.forge_benchmark_adapter import latest_scores, detect_regression
    except Exception as e:
        return {"skip": f"adapter: {e}"}
    cur = latest_scores()
    if not cur:
        return {"scores": {}, "note": "aucun JSON benchmark"}
    sbx = _P(__file__).resolve().parent.parent / "sandbox"
    sf = sbx / "eval_fitness_state.json"
    prev = {}
    try:
        if sf.exists():
            prev = _j.loads(sf.read_text(encoding="utf-8")).get("scores", {})
    except Exception as e:
        log.warning(f"[eval_fitness] état précédent illisible ({e}) — baseline vide, régression indétectable ce tour")
    regr = detect_regression(prev, cur)
    if regr:
        ts = int(_t.time())
        try:
            (sbx / f"evolution_proposal_eval_{ts}.md").write_text(
                "# Eval fitness — régression détectée\n\n"
                + "\n".join(f"- **{r}**" for r in regr)
                + "\n\n## Actions suggérées\n"
                "- `git log --oneline -10` : identifier le commit suspect\n"
                "- inspecter le benchmark régressé ; self_patcher (gated) tentera un fix déterministe\n",
                encoding="utf-8",
            )
        except Exception as e:
            log.warning(f"[eval_fitness] écriture proposal échouée ({e}) — régression non transmise au self_patcher")
        log.warning(f"[eval_fitness] régression: {regr}")
        try:
            exp = record_evolution_experience({
                "kind": "regression_hypothesis", "status": "PENDING_CANDIDATE",
                "baseline": prev, "current": cur, "regressions": regr,
                "hypothesis": "régression benchmark — candidat attendu (self_patcher "
                              "ou owner) via submit_candidate_to_judge",
            })
            log.warning(f"[eval_fitness] expérience d'évolution ouverte: {exp}")
        except Exception as e:
            log.warning(f"[eval_fitness] ledger évolution non écrit ({e})")
    try:
        sbx.mkdir(parents=True, exist_ok=True)
        sf.write_text(_j.dumps({"scores": cur, "ts": _t.time()}, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log.warning(f"[eval_fitness] baseline non écrite ({e}) — prochaine détection de régression faussée")
    return {"scores": cur, "regressions": regr}


# ══════════════════════════════════════════════════════════════════════
# LOCAL LLM helpers (FREE only)
# ══════════════════════════════════════════════════════════════════════
def _llamacpp_chat(prompt: str, max_tokens: int = 200, timeout: int = 30) -> str:
    """Call llamacpp_native :8080 OpenAI-compat. Returns text or empty."""
    try:
        body = json.dumps(
            {
                "model": "qwen2.5-coder",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.2,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            LLAMACPP_URL, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
        d = json.loads(resp)
        return d.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        log.warning(f"llamacpp call failed: {e}")
        return ""


# MESURE 2026-08-26 : sur cette machine, tout 7B demande a ollama laisse un runner
# llama-server de 4,7-4,8 Go qui ne FINIT JAMAIS de charger (/api/ps vide, timeouts), et
# tant qu'il vit PLUS RIEN ne charge, meme un 1.5b qui repondait en 4 s — quatre wedges
# dans la journee, chacun tue a la main par l'owner. Le defaut etait ce 7B : chaque
# pattern qui « parle » (relais de debat, consolidation des lecons) re-coincait le corps
# toutes les cinq minutes. Regle du 2026-06-30 confirmee : <= 4B ici.
OLLAMA_MODELE_LOCAL = os.environ.get("LAFORGE_LOOPS_OLLAMA_MODEL", "qwen2.5-coder:1.5b")


def _ollama_call(
    prompt: str, model: str = OLLAMA_MODELE_LOCAL, max_tokens: int = 200, timeout: int = 60
) -> str:
    """Call ollama :11434. Returns text or empty."""
    try:
        body = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": max_tokens, "temperature": 0.2},
            }
        ).encode("utf-8")
        req = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
        resp = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
        d = json.loads(resp)
        return d.get("response", "")
    except Exception as e:
        log.warning(f"ollama call failed: {e}")
        return ""


def _local_llm_available() -> bool:
    """Quick health check at least 1 local LLM up."""
    import socket

    for port in (8080, 11434):
        try:
            s = socket.socket()
            s.settimeout(0.5)
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except Exception:  # muet-ok: port fermé = résultat normal du probe
            continue
    return False


# ══════════════════════════════════════════════════════════════════════
# AUDIT trail
# ══════════════════════════════════════════════════════════════════════
def _log_run(pattern: str, status: str, outcome: str, details: dict | None = None,
             programme: bool = True):
    """Trace une execution. `programme=False` NE DEPLACE PAS l'echeance.

    MESURE 2026-08-31 : un `--run veille_github_head` lance a la main a repousse
    le passage suivant du daemon de 36 minutes, parce que `_log_run` ecrivait
    `last_run = maintenant` et que `run_due_patterns` lit cette colonne pour
    juger l'eligibilite. Une action de DIAGNOSTIC deplacait donc le calendrier de
    PRODUCTION — et la preuve autonome qu'on attendait avec.

    Ce qui est conserve dans les deux cas : la ligne d'audit complete (pattern,
    horodatage, statut, sortie, details), enrichie de `declencheur`. On ne
    supprime pas la trace ; on l'empeche seulement de valoir « dernier passage
    programme ».

    `last_run` est alors relu depuis la ligne existante via COALESCE — pas remis
    a zero : ecraser par 0 rendrait le pattern eligible IMMEDIATEMENT, ce qui
    serait l'erreur inverse et tout aussi fausse.
    """
    try:
        conn = sqlite3.connect(str(DB))
        _det = dict(details or {})
        _det["declencheur"] = "programme" if programme else "manuel"
        conn.execute(
            "INSERT INTO autonomous_loop_audit (pattern, ts, status, outcome, details) VALUES (?,?,?,?,?)",
            (pattern, time.time(), status, outcome[:500], json.dumps(_det, ensure_ascii=False)),
        )
        # Seule la SOURCE de `last_run` change : l'instant present quand le
        # daemon passe, la valeur deja en base quand c'est une main humaine.
        _lr = "?" if programme else \
            "COALESCE((SELECT last_run FROM autonomous_loop_state WHERE pattern=?), 0)"
        conn.execute(
            "INSERT OR REPLACE INTO autonomous_loop_state "
            "(pattern, last_run, last_status, last_outcome, runs_total, runs_success, enabled) "
            "VALUES (?, " + _lr + ", ?, ?, "
            "  COALESCE((SELECT runs_total+1 FROM autonomous_loop_state WHERE pattern=?), 1), "
            "  COALESCE((SELECT runs_success FROM autonomous_loop_state WHERE pattern=?) "
            "    + CASE WHEN ? = 'ok' THEN 1 ELSE 0 END, "
            "    CASE WHEN ? = 'ok' THEN 1 ELSE 0 END), "
            "  1)",
            (pattern, time.time() if programme else pattern, status, outcome[:500],
             pattern, pattern, status, status),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"audit log fail: {e}")


def _last_run(pattern: str) -> float:
    try:
        conn = sqlite3.connect(str(DB))
        row = conn.execute("SELECT last_run FROM autonomous_loop_state WHERE pattern=?", (pattern,)).fetchone()
        conn.close()
        return float(row[0]) if row else 0.0
    except Exception:
        return 0.0


def _anchor(problem: str, solution: str, example: str = ""):
    """Anchor RAG (Faire-Savoir cycle)."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_self_correction import anchor_solution

        anchor_solution(problem=problem, solution=solution, example=example, domain="autonomous")
    except Exception as e:
        log.warning(f"anchor fail: {e}")


def _ram_gate(needed_gb: float = 2.0, pattern_name: str = "") -> bool:
    """True if enough free RAM; tries eviction first. Never raises.

    Ressource indéterminée = INDECIDABLE = refus : resource_manager → psutil → False.
    « Je ne sais pas si j'ai les ressources » ne vaut jamais « vas-y ».
    """
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_resource_manager import request_resources

        result = request_resources(needed_ram_gb=needed_gb, allow_evict=True)
        if not result.get("ok"):
            log.warning(
                f"[{pattern_name}] RAM gate blocked: need {needed_gb}GB free, "
                f"missing {result.get('missing_gb', '?')}GB — skipped."
            )
            return False
        return True
    except Exception as e:
        try:
            import psutil

            free_gb = psutil.virtual_memory().available / (1024 ** 3)
            if free_gb >= needed_gb:
                log.warning(
                    f"[{pattern_name}] RAM gate degraded to psutil ({e}): "
                    f"{free_gb:.1f}GB free >= {needed_gb}GB — proceeding."
                )
                return True
            log.warning(
                f"[{pattern_name}] RAM gate degraded to psutil ({e}): "
                f"{free_gb:.1f}GB < {needed_gb}GB — INDECIDABLE, skipped."
            )
            return False
        except Exception as e2:
            log.warning(
                f"[{pattern_name}] RAM gate INDECIDABLE ({e}; psutil: {e2}) — skipped."
            )
            return False


# ── CÂBLE ÉVOLUTION (22/08) — carte anatomique (autopoïèse sous inhibition corticale)
#
# La boucle d'auto-amélioration n'est PAS un moteur posé sur l'organisme : chaque
# étage est un organe existant, dans la grille CLAUDE.md §10 :
#   capteurs de déficit (health_check, trace_mining, eval_fitness,
#     _regression_capacitive, _proposer)      = NOCICEPTION (SN végétatif — cet hôte)
#   evolution_experiences.jsonl               = MÉMOIRE IMMUNITAIRE (même ganglion que
#                                               experience_memory du predictor)
#   forge_mutation_judge                      = THYMUS / sélection clonale (apoptose
#                                               WASM ; périmètre immuable = lignée
#                                               germinale, jamais auto-mutable)
#   quarantaine auto-tests                    = ANERGIE documentée (anticorps qui
#                                               disait « sain » à tort)
#   candidates/<sha>.py                       = génothèque (candidat intégral)
#   promotion = commit owner                  = INHIBITION CORTICALE : le végétatif
#                                               propose, le cortex décide.
# Extension future = même règle : organe existant d'abord, jamais d'organe étranger.
# Zone PARTAGÉE writable : sandbox/ = LaForgeSandboxUsers (M) + daemon, alors que
# shadow_mutation/rag_index = (R) pour les comptes sandbox (mesuré 22/08 : la moelle
# en run_job ne pouvait pas y écrire ses verdicts -> boucle cassée). Le ledger doit
# être écrivable par TOUS les organes qui produisent une expérience, pas seulement
# le daemon privilégié. sandbox/ racine persiste (jobs/ y survivent au restart).
_EVOLUTION_DIR = ROOT / "sandbox" / "evolution"
_EVOLUTION_LEDGER = _EVOLUTION_DIR / "evolution_experiences.jsonl"
_EVOLUTION_CANDIDATES = _EVOLUTION_DIR / "candidates"
_EVOLUTION_LEDGER_LEGACY = ROOT / "shadow_mutation" / "rag_index" / "evolution_experiences.jsonl"


def _ensure_ledger_migrated() -> None:
    """Migre l'ancien ledger (shadow_mutation, R-only sandbox) vers la zone partagée.

    Idempotent : ne copie que si le nouveau n'existe pas encore. Le legacy reste
    lisible (R) donc la copie marche depuis tout compte.
    """
    try:
        _EVOLUTION_DIR.mkdir(parents=True, exist_ok=True)
        if _EVOLUTION_LEDGER.exists():
            return
        if _EVOLUTION_LEDGER_LEGACY.exists():
            import shutil
            shutil.copy2(_EVOLUTION_LEDGER_LEGACY, _EVOLUTION_LEDGER)
    except Exception as e:  # noqa: BLE001
        log.warning(f"[evolution] migration ledger échouée ({e}) — nouveau ledger repart de zéro")


def _chainon(prev: str, rec: dict) -> str:
    """Patron de tools/forge_memory_ledger._append : sha256(prev + contenu canonique)."""
    import hashlib
    import json

    corps = {k: v for k, v in rec.items() if k != "chain_hash"}
    return hashlib.sha256((prev + json.dumps(corps, sort_keys=True, ensure_ascii=False)).encode("utf-8")).hexdigest()


def _dernier_chainon() -> str:
    """Tete de chaine : chain_hash de la derniere entree chainee ; sinon empreinte de la derniere ligne
    HERITEE (anterieure au 26/09, jamais reecrite) ; sinon GENESE."""
    import hashlib
    import json

    try:
        lignes = [l for l in Path(_EVOLUTION_LEDGER).read_text(encoding="utf-8", errors="replace").splitlines()
                  if l.strip()]
    except FileNotFoundError:
        return "GENESE"
    if not lignes:
        return "GENESE"
    try:
        tete = json.loads(lignes[-1]).get("chain_hash")
    except ValueError:
        tete = None
    return tete or hashlib.sha256(lignes[-1].encode("utf-8")).hexdigest()


def verifier_chaine_evolution() -> dict:
    """Recalcule la chaine du registre d'evolution ; nomme la PREMIERE rupture (numero de ligne, 1-based).

    Veille RSI 26/09 (P7) : tout evolue SAUF l'historique de preuve. Une entree reecrite, supprimee ou
    inseree apres le debut de la chaine se detecte. Les lignes HERITEES (avant la chaine) sont comptees,
    jamais reecrites : la premiere entree chainee s'ancre sur l'empreinte de la derniere d'entre elles."""
    import hashlib
    import json

    try:
        lignes = [l for l in Path(_EVOLUTION_LEDGER).read_text(encoding="utf-8", errors="replace").splitlines()
                  if l.strip()]
    except FileNotFoundError:
        return {"ok": True, "chainees": 0, "heritees": 0, "rupture": None, "note": "registre absent"}
    heritees = chainees = 0
    precedent, brut_precedent = None, None
    for i, ligne in enumerate(lignes, 1):
        try:
            e = json.loads(ligne)
        except ValueError:
            e = {}
        if "chain_hash" not in e:
            if chainees:
                return {"ok": False, "chainees": chainees, "heritees": heritees, "rupture": i,
                        "pourquoi": "ligne non chainee APRES le debut de la chaine (insertion ou reecriture)"}
            heritees += 1
            brut_precedent = ligne
            continue
        attendu = precedent if chainees else (
            hashlib.sha256(brut_precedent.encode("utf-8")).hexdigest() if brut_precedent is not None else "GENESE")
        if e.get("prev_hash") != attendu or e.get("chain_hash") != _chainon(e.get("prev_hash", ""), e):
            return {"ok": False, "chainees": chainees, "heritees": heritees, "rupture": i,
                    "pourquoi": "maillon rompu (entree alteree, supprimee ou deplacee)"}
        chainees += 1
        precedent = e["chain_hash"]
    return {"ok": True, "chainees": chainees, "heritees": heritees, "rupture": None}


def record_evolution_experience(rec: dict) -> str:
    """Append une expérience d'évolution au ledger — jamais d'écrasement.

    parent_commit et ts sont posés ici, exp_id dérivé du contenu. Un échec
    d'écriture REMONTE à l'appelant : une généalogie perdue en silence vaut
    pire qu'une exception.
    """
    import hashlib
    import json
    import subprocess
    import time as _time

    rec = dict(rec)
    rec.setdefault("ts", _time.strftime("%Y-%m-%dT%H:%M:%S"))
    if "parent_commit" not in rec:
        try:
            r = subprocess.run(
                ["git", "-C", str(ROOT), "rev-parse", "--short=8", "HEAD"],
                capture_output=True, text=True, errors="replace", timeout=10)
            rec["parent_commit"] = r.stdout.strip() or f"inconnu ({r.stderr.strip()[:50]})"
        except Exception as e:
            rec["parent_commit"] = f"inconnu ({e})"
    rec["exp_id"] = hashlib.sha256(
        json.dumps(rec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    _ensure_ledger_migrated()
    # Historique de preuve CHAINE (veille RSI 26/09, P7) : chaque entree scelle la precedente.
    rec["prev_hash"] = _dernier_chainon()
    rec["chain_hash"] = _chainon(rec["prev_hash"], rec)
    with open(_EVOLUTION_LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec["exp_id"]


def submit_candidate_to_judge(ref_exp: str, rel: str, nouveau: str,
                              tests: list | None = None) -> dict:
    """Soumet UN candidat au juge de référence et journalise le verdict.

    juger_module porte déjà verrou, périmètre immuable, patron sain, récidive,
    import réel, tests ciblés, et RESTAURE sur échec. SURVIT laisse le working
    tree modifié : la promotion est le COMMIT, décision owner (P5). Le candidat
    INTÉGRAL est archivé avant jugement — jamais de troncature d'un artefact
    adoptable.
    """
    import hashlib
    import sys as _sys

    _sys.path.insert(0, str(ROOT / "app"))
    from nokido_agent.app import forge_mutation_judge as juge

    # PORTE DE L'EVOLUTION (2026-10-01) : armement owner, frein evolution.halt, verrou
    # humain -- verifiee AVANT toute ecriture (juger_module ecrit dans l'arbre vivant).
    # Le refus est CONSIGNE au registre : une soumission arretee n'est pas une soumission
    # qui n'a jamais eu lieu.
    porte = juge.evolution_autorisee()
    if not porte["autorisee"]:
        exp_id = record_evolution_experience({
            "kind": "candidate_verdict", "ref_exp": ref_exp, "target": rel,
            "verdict": "HALTED", "status": "HALTED", "porte": porte,
        })
        log.warning(f"[evolution] {rel}: HALTED ({porte['etat']} : {porte['motif']}) exp={exp_id}")
        return {"exp_id": exp_id, "status": "HALTED", "verdict": "HALTED", "porte": porte}

    sha = hashlib.sha256(nouveau.encode("utf-8")).hexdigest()[:16]
    _EVOLUTION_CANDIDATES.mkdir(parents=True, exist_ok=True)
    (_EVOLUTION_CANDIDATES / f"{sha}.py").write_text(nouveau, encoding="utf-8")

    # CHEMIN FERME (raccorde le 2026-09-08, demande owner). Avant : `juger_module`,
    # qui prouve la SURVIE et ne dit RIEN du gain — une mutation qui passe les tests
    # et DEGRADE etait conservee. Le juge a gain existait, il etait cable, et sa
    # docstring designait deja cette boucle comme son appelant.
    #
    # Le juge ne peut pas inventer ce qu'est une amelioration : sans tests a jouer il
    # rend GAIN_INDECIDABLE. On complete donc le perimetre quand l'appelant n'en
    # fournit pas — des tests EXPLICITES priment toujours.
    if not tests:
        try:
            tests = juge.perimetre_mesure(rel)
        except Exception as e:  # noqa: BLE001 — perimetre indisponible : on le DIT
            log.warning("[evolution] perimetre de mesure indisponible pour %s (%s) — "
                        "le gain sera INDECIDABLE", rel, type(e).__name__)
            tests = []
    verdict = juge.juger_module_avec_gain(rel, nouveau, tests)
    # Liste BLANCHE : n'attend la decision owner que ce qui est PROUVE meilleur.
    # GAIN_INDECIDABLE est TERMINAL pour cette decision — ni promotion, ni echec :
    # il DESIGNE l'instrument manquant, et devient une file de travail.
    status = {"AMELIORE": "AWAITING_OWNER_COMMIT",
              "GAIN_INDECIDABLE": "PERIMETRE_MANQUANT",
              "SURVIT_SANS_GAIN": "REJECTED",
              "MEURT": "REJECTED",
              "REFUSE": "BLOCKED"}.get(verdict.get("verdict"), "INDECIDABLE")
    exp_id = record_evolution_experience({
        "kind": "candidate_verdict", "ref_exp": ref_exp, "target": rel,
        "candidate_sha": sha, "tests": tests or [],
        "verdict": verdict.get("verdict"), "judge": verdict, "status": status,
    })
    log.warning(f"[evolution] {rel}: verdict={verdict.get('verdict')} status={status} exp={exp_id}")
    return {"exp_id": exp_id, "status": status, **verdict}


_DOCS_HISTORIQUES = ("/archive/", "/wiki/", "/launch/")
_DEPORTE_CACHE: dict = {"set": frozenset(), "ts": 0.0}


def _docs_deportes() -> frozenset:
    """Docs marques `export-ignore` -- DEPORTES du produit public (memorise 60 s, minuscules).

    AUTORITE UNIQUE : les decisions `export-ignore` de `.gitattributes` (owner). Un doc
    deporte du produit public n'est pas une intention NON TENUE de ce produit -- et son
    lexique n'a rien a faire dans le registre d'evolution ni le RAG. Mesure 2026-09-30 :
    l'audit doc<->code scannait des plans internes deportes et ramenait leur vocabulaire en
    contexte, ce qui re-declenchait un classifieur. On REUTILISE la separation existante
    (anti-dup), jamais une 2e liste.

    `git` indisponible -> ensemble VIDE : best-effort, on ne sur-exclut pas (la protection
    PUBLIQUE, elle, tient par `git archive` qui honore export-ignore, independamment d'ici)."""
    import subprocess as _sp

    if time.time() - _DEPORTE_CACHE["ts"] < 60:
        return _DEPORTE_CACHE["set"]
    # -c safe.directory=* : le service tourne sous un autre compte que le proprietaire du
    # depot -> sans lui, git rend « dubious ownership » (rc 128) et l'ensemble serait vide.
    _g = ["git", "-c", "safe.directory=*", "-C", str(ROOT)]
    depo: set = set()
    try:
        ls = _sp.run([*_g, "ls-files", "-z", "*.md"], capture_output=True, timeout=15)
        mds = [p for p in ls.stdout.decode("utf-8", "replace").split("\0") if p]
        if mds:
            ca = _sp.run([*_g, "check-attr", "export-ignore", "-z", "--stdin"],
                         input="\0".join(mds).encode(), capture_output=True, timeout=20)
            toks = ca.stdout.decode("utf-8", "replace").split("\0")
            for i in range(0, len(toks) - 2, 3):     # -z : path \0 attr \0 value
                if toks[i + 2] == "set":
                    depo.add(toks[i].replace("\\", "/").lower())
    except Exception as e:  # noqa: BLE001 - git muet => aucun doc exclu, on le DIT
        log.warning("[unmet_intention] export-ignore illisible (%s) : aucun doc deporte exclu",
                    type(e).__name__)
    _DEPORTE_CACHE.update(ts=time.time(), set=frozenset(depo))
    return _DEPORTE_CACHE["set"]


def _est_doc_d_intention(rel: str) -> bool:
    """Liste BLANCHE des docs d'intention (doctrine owner 22/08) : MANIFESTO, specs/, le MOT roadmap
    ou plan dans le nom. Tout le reste est une MENTION, pas une intention.

    Mesure 2026-09-25 : l'ancienne liste noire (tout .md sauf archive/wiki/launch) faisait sortir 105
    « ecarts » de 53 sources -- journal de conversation archive, liste de candidats IP, SKILL.md,
    notes `memory/` (qui s'appellent aussi `roadmap_*` : notes de SESSION, pas des docs d'intention).
    Le MOT : `CLAUDE_PLANNING_MODE` ou `..._PLANNER_...` ne sont pas des plans.
    """
    import re as _re

    rel = "/" + rel.replace("\\", "/").lower().lstrip("/")
    if not rel.endswith(".md") or rel.startswith("/memory/"):
        return False
    if any(h in rel for h in _DOCS_HISTORIQUES) or "passation" in rel or "session-" in rel:
        return False
    # Doc DEPORTE du produit public (export-ignore) : ni une intention de ce produit, ni un
    # lexique a ramener en contexte/RAG. Consulte l'autorite existante, jamais une 2e liste.
    if rel.lstrip("/") in _docs_deportes():
        return False
    nom = rel.rsplit("/", 1)[-1][:-3]
    mots = set(_re.split(r"[^a-z0-9]+", nom))
    return nom == "manifesto" or "/specs/" in rel or bool(mots & {"roadmap", "plan"})


def _modules_absents_des_docs() -> list[dict]:
    """Modules forge_* cités dans les docs mais ABSENTS du code = intentions non tenues.

    Doctrine owner 22/08 : un doc d'intention (MANIFESTO, specs/, roadmap_*, *_PLAN)
    décrit une CIBLE ; un module cité absent n'est pas une erreur du doc, c'est du
    code pas encore écrit. On NE réécrit PAS le doc, on ouvre une expérience pour
    tendre le code vers l'intention. Purement mécanique : le scan par nom peut se
    tromper (module sous un autre nom), d'où statut PENDING_CANDIDATE, jamais un verdict.
    """
    import os
    import re as _re

    skip = {".git", "node_modules", ".venv", "venv", "__pycache__",
            "archaeology_clones", "sandbox", "RAG_plain_bak", "RAG"}
    present = set()
    for dp, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            present.add(f)
    rx_mod = _re.compile(r'`?((?:app/|tools/)?forge_\w+\.py)`?')
    ecarter = {"forge_pii_detector.py"}  # exemple de module SUPPRIMÉ (CLAUDE.md §3)
    trouve: dict[str, str] = {}
    # Exclure les docs HISTORIQUES : archive/wiki/launch décrivent le passé ou des
    # concepts déjà réalisés sous d'autres noms — ce ne sont PAS des intentions
    # actives (mesuré 22/08 : 6/7 du lot neuro venaient d'un audit archivé et
    # étaient déjà implémentés ailleurs). Le scan par nom ment ; ne scanner que
    # les docs d'intention vivants.
    # Liste BLANCHE depuis le 2026-09-25 (cf. _est_doc_d_intention) ; l'ecarte est COMPTE et dit.
    vus = lus = 0
    for dp, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if not f.endswith(".md"):
                continue
            vus += 1
            fp = os.path.join(dp, f)
            if not _est_doc_d_intention(os.path.relpath(fp, ROOT)):
                continue
            lus += 1
            try:
                txt = open(fp, encoding="utf-8", errors="replace").read()
            except Exception:  # muet-ok: .md illisible, on scanne le suivant
                continue
            for m in rx_mod.findall(txt):
                b = os.path.basename(m)
                if b in present or b in ecarter or b in trouve:
                    continue
                trouve[b] = os.path.relpath(fp, ROOT).replace("\\", "/")
    log.info(f"[unmet_intention] {lus} doc(s) d'intention lus sur {vus} .md vus -- {vus - lus} ecarte(s) "
             f"par la liste blanche (MANIFESTO, specs/, mot roadmap|plan ; memory/ et historiques exclus)")
    return [{"module": b, "source_doc": src} for b, src in sorted(trouve.items())]


def _intentions_deja_ouvertes() -> set:
    """target_module déjà présents dans le ledger (dédup inter-cycles)."""
    import os

    deja = set()
    _ensure_ledger_migrated()
    try:
        for line in open(_EVOLUTION_LEDGER, encoding="utf-8", errors="replace"):
            try:
                rec = json.loads(line)
                if rec.get("kind") == "unmet_intention" and rec.get("target_module"):
                    deja.add(os.path.basename(rec["target_module"]))
            except Exception:  # muet-ok: ligne ledger malformée, ignorée
                continue
    except FileNotFoundError:  # muet-ok: ledger pas encore créé
        pass
    return deja


@register_pattern(
    "unmet_intention_docs",
    interval_sec=604800,  # 7j — les docs d'intention bougent lentement
    description="Scanne les docs d'intention, ouvre une expérience pour chaque module forge_* décrit mais absent.",
    preferred_window=None,
)
def pat_unmet_intention_docs() -> dict:
    """Câble les intentions non tenues au ledger (routeur d'intention). Dédup inter-cycles."""
    absents = _modules_absents_des_docs()
    deja = _intentions_deja_ouvertes()
    ouverts = []
    for it in absents:
        if it["module"] in deja:
            continue
        try:
            exp = record_evolution_experience({
                "kind": "unmet_intention", "status": "PENDING_CANDIDATE",
                "organ": "intention_doc", "target_module": it["module"],
                "source_doc": it["source_doc"],
                "hypothesis": f"module {it['module']} décrit dans {it['source_doc']} mais "
                              f"absent du code — tendre le code vers l'intention (ne pas réécrire le doc)",
            })
            ouverts.append({"module": it["module"], "exp_id": exp})
        except Exception as e:
            log.warning(f"[unmet_intention] {it['module']} non câblé ({e})")
    if ouverts:
        log.warning(f"[unmet_intention] {len(ouverts)} intention(s) câblée(s) au routeur: "
                    f"{[o['module'] for o in ouverts]}")
    return {"absents_total": len(absents), "deja_ouvertes": len(deja), "nouvelles": len(ouverts),
            "ouverts": ouverts}


# ══════════════════════════════════════════════════════════════════════
# PATTERNS
# ══════════════════════════════════════════════════════════════════════


# Anti-bruit health_check : un down isolé est souvent transitoire (fenêtre de
# boot, restart de service). On exige N checks consécutifs avant de considérer
# un service réellement down, et on NE l'ancre JAMAIS dans les leçons/RAG : ce
# canal est réservé aux solutions VALIDÉES, l'ancrage répété d'un "investigate
# manually" générique poisonne le retrieval (185x observé 2026-05-30).
_HEALTH_DOWN_THRESHOLD = 3  # 3 x interval_sec(300) = ~15 min de down soutenu
_health_down_streak: dict = {}

# Sentinelle liveness du writer de traces. La régression 2026-05-24 a gelé
# execution_traces.db pendant 6.6j SANS alerte : rien ne surveillait « les
# traces coulent-elles encore ? ». Signature du gel = log d'audit FRAIS
# (activité réelle) mais traces VIEILLES. Si les deux sont vieux = idle
# légitime (pas d'appels) -> pas d'alarme. Détecte précisément un sidecar mort.
_TRACE_STALE_S = 1800  # 30 min sans nouvelle trace
_AUDIT_FRESH_S = 300  # log d'audit écrit il y a < 5 min = système actif


def _trace_writer_stale() -> dict:
    """Détecte un writer de traces gelé (audit actif mais execution_traces figé)."""
    import sqlite3 as _sql

    out: dict = {"stale": False, "trace_age_s": None, "audit_age_s": None}
    try:
        al = ROOT / "logs" / "mcp_audit.log"
        if al.exists():
            out["audit_age_s"] = round(time.time() - al.stat().st_mtime, 1)
        db = ROOT / "RAG" / "execution_traces.db"
        if db.exists():
            con = _sql.connect(str(db))
            mx = con.execute("SELECT MAX(ts) FROM traces").fetchone()[0]
            con.close()
            if mx:
                out["trace_age_s"] = round(time.time() - mx, 1)
        au, tr = out["audit_age_s"], out["trace_age_s"]
        if au is not None and tr is not None and au < _AUDIT_FRESH_S and tr > _TRACE_STALE_S:
            out["stale"] = True
    except Exception as e:
        out["error"] = str(e)[:120]
    return out


# ---------------------------------------------------------------------------
# POLITIQUE AVANT PANNE (2026-09-20). `health_check` portait une table de ports
# CODEE EN DUR et traitait tout port ferme comme un organe mort. Mesure sur le
# ledger d'evolution : 584 signalements sur 633 (92 %) visaient des organes
# ETEINTS PAR CHOIX — brain_worker:5557 (3 services declares, tous disabled),
# graph:7474 (disabled), 8080 (NokidoSearxng, disabled et on-demand). Envoyer
# reparer un CHOIX, c'est `DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE`, la
# troisieme ligne de la constitution semantique — et le bruit NOYAIT les 28
# signalements qui correspondaient a de vraies pannes (webhub:7400, hub:8766).
#
# La politique se DEMANDE a l'organe qui la porte (`services.toml`), elle ne se
# devine pas depuis un port ferme. Et elle se lit avec trois etats : un fichier
# illisible ne vaut pas « tout est actif ».
SERVICES_TOML_POLITIQUE = ROOT / "proxy_deno" / "core" / "services.toml"
_POLITIQUE_TTL_S = 300.0
_politique_cache: dict = {"ts": 0.0, "val": None, "src": None}


def _politique_des_ports(toml_path=None) -> dict:
    """Etat DECLARE de chaque port : {"etat", "raison", "par_port"}.

    `etat` vaut "ok" ou "INDETERMINE". Jamais de repli silencieux sur « actif » :
    sans politique lisible on ne peut affirmer NI qu'un organe est attendu actif,
    NI qu'il est eteint par choix.
    """
    chemin = Path(toml_path or SERVICES_TOML_POLITIQUE)
    maintenant = time.time()
    if (_politique_cache["val"] is not None
            and _politique_cache["src"] == str(chemin)
            and maintenant - _politique_cache["ts"] < _POLITIQUE_TTL_S):
        return _politique_cache["val"]
    try:
        import tomllib
        with open(chemin, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        res = {"etat": "INDETERMINE",
               "raison": "politique illisible (%s: %s)" % (type(e).__name__, str(e)[:80]),
               "par_port": {}}
        _politique_cache.update(ts=maintenant, val=res, src=str(chemin))
        return res
    par_port: dict = {}
    for s in data.get("service", []) or []:
        port = s.get("port")
        if not port:
            continue
        e = par_port.setdefault(int(port), {"noms": [], "actifs": [], "eteints": []})
        nom = s.get("name") or "?"
        e["noms"].append(nom)
        if s.get("disabled") is True:
            e["eteints"].append(nom)
        else:
            e["actifs"].append(nom)
    res = {"etat": "ok", "raison": None, "par_port": par_port}
    _politique_cache.update(ts=maintenant, val=res, src=str(chemin))
    return res


def _classer_ports_fermes(fermes, politique) -> tuple:
    """(down, disabled_by_policy, declaration_inconnue) — classement par liste BLANCHE.

    N'est une PANNE que ce qui est declare actif. Un port qui porte encore UN
    service actif reste un down meme si d'autres y sont eteints : le cout des
    deux erreurs n'est pas symetrique, et taire une vraie panne coute plus cher
    qu'un signalement de trop.
    """
    down, choix, inconnus = [], [], []
    lisible = (politique or {}).get("etat") == "ok"
    par_port = (politique or {}).get("par_port") or {}
    for item in fermes:
        try:
            port = int(str(item).rsplit(":", 1)[1])
        except (IndexError, ValueError):
            inconnus.append("%s (port illisible)" % item)
            continue
        if not lisible:
            inconnus.append("%s (%s)" % (
                item, (politique or {}).get("raison") or "politique INDETERMINEE"))
            continue
        e = par_port.get(port)
        if not e:
            inconnus.append("%s (aucun service declare sur ce port)" % item)
        elif not e["actifs"]:
            choix.append("%s (%s - disabled)" % (item, ", ".join(e["eteints"])))
        else:
            down.append(item)
    return down, choix, inconnus


_ENDPOINTS_ETAT = ROOT / "sandbox" / "endpoint_health_last.json"
_ENDPOINTS_PERIODE_S = 900     # GET /models : léger, mais 8 endpoints -> 4x/heure
# Budget TOTAL de la sonde, distinct du timeout PAR REQUETE (12 s dans le
# moniteur). Sans lui, `health_check` a tenu le tick 699 s le 2026-08-31.
_ENDPOINTS_BUDGET_S = 30.0


def _sante_endpoints() -> dict:
    """Supervise les chemins vers les modèles cloud, comme le keeper supervise
    Docker.

    `tools/forge_endpoint_monitor.py` existait déjà — il sonde `GET /models`
    (bon marché, ne brûle aucun quota d'inférence) et appelle `mark_http`, ce qui
    alimente la SANTÉ du pool de clés (`forge_key_rotation`). Mais il n'était
    déclaré NULLE PART : ni dans services.toml, ni dans un pattern, aucun
    heartbeat. Un superviseur écrit et jamais lancé.

    Consequence mesurée le 2026-08-14 : cinq providers en santé `unknown` (jamais
    testés), et une panne découverte seulement quand un appel échoue — en plein
    débat. `groq` est tombé en http403 entre deux runs : 18 tours, 3 réussis,
    tout le reste en « réponse vide ». Une clé morte doit être connue AVANT
    qu'on compose un panel, pas pendant.

    Ne remplace pas la rotation : il la NOURRIT. `forge_key_rotation` sait déjà
    écarter et réhabiliter (TTL 6 h) — encore faut-il que quelqu'un lui dise
    ce que rendent les endpoints.
    """
    import json as _json
    import sys as _sys

    try:
        try:
            _etat = _json.loads(_ENDPOINTS_ETAT.read_text(encoding="utf-8"))
            dernier = float(_etat.get("ts") or 0)
        except Exception:  # noqa: BLE001 - pas d'etat = premiere passe
            dernier = 0.0
        if time.time() - dernier < _ENDPOINTS_PERIODE_S:
            return {"skipped": "throttle_15min"}

        if str(ROOT / "tools") not in _sys.path:
            _sys.path.insert(0, str(ROOT / "tools"))
        from nokido_agent.tools.forge_endpoint_monitor import monitor

        # BUDGET TOTAL. Mesure : chaque requete est bornee a 12 s et il y a 8
        # fournisseurs, donc 96 s dans le pire cas legitime — deja plus qu'un
        # tick de 60 s. La mort instrumentee du 2026-08-31 a dure 699 s, preuve
        # que la borne par requete ne borne pas l'ensemble. 30 s couvre le cas
        # courant (des fournisseurs sains repondent en moins d'une seconde) et
        # coupe le cas pathologique. Valeur a re-mesurer, pas gravee.
        res, _depasse = _borner(monitor, _ENDPOINTS_BUDGET_S, defaut=[])
        if _depasse:
            # On n'ecrit PAS de releve partiel : le dernier releve valide vaut
            # mieux qu'un instantane tronque, que les lecteurs prendraient pour
            # une mesure. Le throttle n'avance pas non plus — la sonde sera
            # retentee, pour 30 s bornees, au prochain passage.
            log.warning("[health_check] sonde d'endpoints ABANDONNEE au budget "
                        "(%.0f s) — releve precedent conserve", _ENDPOINTS_BUDGET_S)
            return {"skipped": "budget_depasse", "budget_s": _ENDPOINTS_BUDGET_S}
        res = res or []
        par_statut: dict = {}
        for r in res:
            par_statut.setdefault(str(r.get("status") or "?"), []).append(r.get("provider"))
        _ENDPOINTS_ETAT.parent.mkdir(parents=True, exist_ok=True)
        _ENDPOINTS_ETAT.write_text(
            _json.dumps({"ts": time.time(), "par_statut": par_statut}), encoding="utf-8")

        # SAIN = 200 ou "ok", TOUT LE RESTE est casse. Premiere version : je
        # filtrais sur les libelles ("bad_key", "quota") alors que le moniteur
        # rend le CODE HTTP BRUT -> premiere passe reelle : `{403: 3, 200: 4}` et
        # `casses: []`. Trois endpoints morts, zero alerte. C'est le faux negatif
        # exact que ce garde est cense empecher ; on liste donc par exclusion,
        # jamais par enumeration des formes d'echec (on ne les connait pas toutes).
        _SAINS = {"200", "201", "ok"}
        casses = [p for s, ps in par_statut.items()
                  for p in ps if str(s).strip().lower() not in _SAINS and str(s).strip() != "-"]
        if casses:
            log.warning("[health_check] chemins LLM casses : %s", ", ".join(map(str, casses)))
            _anchor(
                problem="Providers LLM injoignables : {}".format(", ".join(map(str, casses))),
                solution=("Cle ecartee ou quota atteint. La rotation les reprendra a "
                          "l'expiration du TTL ; une SECONDE cle dans le pool "
                          "(SUFFIXE _2) supprimerait la coupure — les pools n'ont "
                          "qu'un seul slot rempli sur cinq possibles."),
                example="forge_key_rotation.pool_status('GROQ_API_KEY') / set_key(base, valeur, slot=2)",
            )
        return {"par_statut": {k: len(v) for k, v in par_statut.items()},
                "casses": casses}
    except Exception as e:  # noqa: BLE001
        log.warning("[health_check] moniteur d'endpoints INDISPONIBLE (%s: %s) | "
                    "consequence: la sante des cles n'est plus alimentee, une cle "
                    "morte ne sera vue qu'au prochain appel qui echoue",
                    type(e).__name__, str(e)[:90])
        return {"error": "{}: {}".format(type(e).__name__, str(e)[:80])}


@register_pattern(
    "health_check", interval_sec=300, description="Vérifie services NSSM up, alerte si down.", preferred_window=None
)  # 24/7 — surveillance vitale
def pat_health_check() -> dict:
    """Scan tous services Nokido + ports critiques."""
    import socket

    services_ports = {
        "hub_mcp": 8766,
        "webhub": 7400,
        "deno_proxy": 8000,
        "deno_webhub": 7401,
        "deno_hub_mcp": 8769,
        "graph": 7474,
        "ollama": 11434,
        "llamacpp": 8080,
        "brain_worker": 5557,
        "netcfg_mcp": 8767,
    }
    fermes = []
    for name, port in services_ports.items():
        try:
            s = socket.socket()
            s.settimeout(0.5)
            s.connect(("127.0.0.1", port))
            s.close()
        except Exception:
            fermes.append(f"{name}:{port}")

    # La politique est consultee AVANT de parler de panne : un organe eteint par
    # choix n'ouvre aucune experience et n'alimente aucun streak.
    politique = _politique_des_ports()
    down, choix_politique, sans_declaration = _classer_ports_fermes(fermes, politique)
    if choix_politique:
        log.info("[health_check] %d organe(s) DISABLED_BY_POLICY (ignores) : %s",
                 len(choix_politique), choix_politique)
    if sans_declaration:
        log.warning("[health_check] %d port(s) ferme(s) SANS declaration exploitable "
                    "- ni sain ni en panne : %s",
                    len(sans_declaration), sans_declaration)

    # Streak par service : un service qui remonte est absent du nouveau dict → reset 0.
    global _health_down_streak
    new_streak: dict = {}
    confirmed = []
    fresh_down = []
    for svc in down:
        streak = _health_down_streak.get(svc, 0) + 1
        new_streak[svc] = streak
        if streak >= _HEALTH_DOWN_THRESHOLD:
            confirmed.append(svc)
            if streak == _HEALTH_DOWN_THRESHOLD:
                fresh_down.append(svc)  # transition seulement : 1 expérience par épisode
    _health_down_streak = new_streak

    if fresh_down:
        try:
            exp = record_evolution_experience({
                "kind": "organ_down", "status": "PENDING_CANDIDATE",
                "organ": "services", "targets": fresh_down,
                "hypothesis": "organe down soutenu (>=%d checks) — remède attendu "
                              "(remediation ou owner)" % _HEALTH_DOWN_THRESHOLD,
            })
            log.warning(f"[health_check] expérience d'évolution ouverte: {exp} ({fresh_down})")
        except Exception as e:
            log.warning(f"[health_check] ledger évolution non écrit ({e})")
    if confirmed:
        # Down soutenu : on LOG (le runner _log_run trace déjà l'outcome), on
        # n'ancre PAS de fausse "solution". Le monitoring consomme le retour.
        log.warning(
            f"[health_check] {len(confirmed)} services DOWN ≥{_HEALTH_DOWN_THRESHOLD} checks: {confirmed}"
        )
    elif down:
        log.info(
            f"[health_check] {len(down)} transient-down (streak<{_HEALTH_DOWN_THRESHOLD}): {down}"
        )

    # Liveness writer de traces (sentinelle anti-gel-silencieux)
    trace_health = _trace_writer_stale()
    if trace_health.get("stale"):
        log.warning(
            f"[health_check] TRACE WRITER GELÉ: traces {trace_health['trace_age_s'] / 60:.0f}min "
            f"mais audit actif ({trace_health['audit_age_s']:.0f}s) -> sidecar mort ?"
        )
        try:
            import sys as _sys

            _sys.path.insert(0, str(ROOT / "app"))
            from nokido_agent.app.forge_critical_events import persist as _ce

            _ce("trace_writer_stale", "warning", trace_health)
        except Exception as e:
            log.warning(f"[trace_watch] critical_event trace_writer_stale non persisté ({e})")

    return {
        "down": down,
        "confirmed_down": confirmed,
        "disabled_by_policy": choix_politique,
        "declaration_inconnue": sans_declaration,
        "politique": politique.get("etat"),
        "total": len(services_ports),
        # `all_up` ne ment plus par omission : n'est sain que ce qui est PROUVE
        # sain. Un port ferme sans declaration exploitable n'est pas un succes —
        # le ranger du cote sain serait la liste NOIRE qu'on s'interdit.
        "all_up": not down and not sans_declaration,
        "trace_writer": trace_health,
        "endpoints_llm": _sante_endpoints(),
    }


_SENTINELLE_ETAT = ROOT / "sandbox" / "fix_sentinel_last.json"
_SENTINELLE_PERIODE_S = 6 * 3600     # coûteux (git show par commit) -> 4x/jour


def _sentinelle_correctifs() -> dict:
    """Un correctif commité puis ANNULÉ ne casse aucun test : il ramène le
    symptôme des semaines plus tard.

    Mesuré le 2026-08-14 : `43dbf555` et `fe9f323d` (deux gardes anti-sawtooth
    Docker) emportés par `3aec1500`, un revert qui a annulé plus que son objet ;
    le kill-switch WSL revenu à "1" malgré `0a880f22`. Symptôme côté owner :
    « Docker démarre et crash, ENCORE ». Les tests passaient, le lint passait :
    le défaut n'était pas dans le code présent, mais dans ce qui avait disparu.

    Branché ICI plutôt qu'en outil à lancer à la main : une sentinelle que
    personne n'exécute ne protège rien. Throttle 6 h — la passe fait un
    `git show` par commit, trop coûteux pour chaque tick.
    """
    import json as _json
    import sys as _sys

    try:
        try:
            _etat = _json.loads(_SENTINELLE_ETAT.read_text(encoding="utf-8"))
            dernier = float(_etat.get("ts") or 0)
        except Exception:  # noqa: BLE001 - pas d'etat = premiere passe
            dernier = 0.0
        if time.time() - dernier < _SENTINELLE_PERIODE_S:
            return {"skipped": "throttle_6h"}

        if str(ROOT / "tools") not in _sys.path:
            _sys.path.insert(0, str(ROOT / "tools"))
        from nokido_agent.tools.forge_fix_sentinel import scanner

        res = scanner(limit=60)
        _SENTINELLE_ETAT.parent.mkdir(parents=True, exist_ok=True)
        _SENTINELLE_ETAT.write_text(_json.dumps({"ts": time.time()}), encoding="utf-8")
        for p in res.get("perdus", [])[:5]:
            log.warning("[git_hygiene] CORRECTIF PERDU %s dans %s (commit %s)",
                        p["ancre"], p["fichier"], p["sha"])
            _anchor(
                problem="Correctif perdu : {} absent de {}".format(p["ancre"], p["fichier"]),
                solution=("Introduit par {} ({}) puis disparu sans revert qui le "
                          "nomme. Verifier avec git show, puis restaurer A "
                          "L IDENTIQUE ou documenter le retrait.").format(
                              p["sha"], p["sujet"]),
                example="git -c safe.directory=* log --oneline -S <ancre> -- <fichier>",
            )
        # On rend AUSSI le nombre d'ecartes : un detecteur qui ne montre que ses
        # trouvailles cache son taux de faux positifs (mesure : 60 % en v1).
        return {"n_perdus": res.get("n_perdus", 0),
                "n_remplacees_assumees": res.get("n_remplacees", 0),
                "ancres_suivies": res.get("ancres_suivies", 0)}
    except Exception as e:  # noqa: BLE001
        log.warning("[git_hygiene] sentinelle des correctifs INDISPONIBLE (%s: %s) "
                    "| consequence: un fix annule par un revert large repasse "
                    "inapercu jusqu'au retour du symptome",
                    type(e).__name__, str(e)[:90])
        return {"error": "{}: {}".format(type(e).__name__, str(e)[:80])}


@register_pattern(
    "git_hygiene",
    interval_sec=3600,
    description="Détecte uncommitted, suggère commits si volume élevé.",
    preferred_window=(8, 22),
)  # éveillé : pendant journée seulement
def pat_git_hygiene() -> dict:
    """Check git status + last commit age."""
    try:
        # Uncommitted count
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        # Last commit timestamp
        r2 = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
        last_ct = int(r2.stdout.strip()) if r2.stdout.strip() else 0
        age_h = (time.time() - last_ct) / 3600 if last_ct else 0
        info = {
            "uncommitted_files": len(lines),
            "last_commit_age_hours": round(age_h, 1),
            "samples": lines[:5],
        }
        if len(lines) > 50:
            log.warning(f"[git_hygiene] HIGH uncommitted: {len(lines)} files")
            _anchor(
                problem=f"Uncommitted volume élevé : {len(lines)} files",
                solution="Considérer commit groupé par theme. git status pour détails.",
                example="git add <pattern> && git commit -m '...'",
            )
        info["correctifs_perdus"] = _sentinelle_correctifs()
        return info
    except Exception as e:
        return {"error": str(e)}


@register_pattern(
    "reflex_adoption",
    interval_sec=86400,
    description="Mesure l'adoption du verbe introspect et la reutilisation des "
                "procedures connues, contre le point zero du 2026-08-31.",
    preferred_window=None,
)
def pat_reflex_adoption() -> dict:
    """Un indicateur qu'il faut penser a relancer n'est jamais relance.

    Toute la chaine reflexes repose sur une promesse verifiable : « la
    reutilisation va monter ». Sans emetteur, cette promesse resterait une
    intention — exactement ce que ce chantier corrige ailleurs. Le bilan est
    donc produit tout seul, une fois par jour, et son verdict est journalise.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_introspect import bilan
    except ImportError as e:  # noqa: BLE001
        return {"error": "introspect indisponible: %s" % type(e).__name__}
    try:
        b = bilan()
    except Exception as e:  # noqa: BLE001
        return {"error": "%s: %s" % (type(e).__name__, str(e)[:120])}
    log.info("[reflex_adoption] verdict=%s | consultations=%s | reutilisation=%s%%",
             b.get("verdict"), (b.get("adoption_live") or {}).get("consultations"),
             (b.get("reutilisation") or {}).get("taux_pct"))
    return b


@register_pattern(
    "success_promotion",
    interval_sec=21600,
    description="Fait passer les corrections de CONSTATE a PROUVE (test vert) "
                "ou INFIRME (le symptome est revenu).",
    preferred_window=None,
)
def pat_success_promotion() -> dict:
    """L'etat epistemique des corrections ne bouge que si quelqu'un le mesure.

    `forge_success_oplog` ecrit CONSTATE a chaque commit de correction, et les
    trois etats existaient depuis le 2026-08-31 sans qu'aucun emetteur ne
    remplisse PROUVE : une colonne declaree et vide. C'est le motif « garde
    branche sur un signal que personne n'emet », deja paye deux fois ici.

    Ce pattern est cet emetteur. Il est BORNE (15 entrees examinees, 3
    executions de tests par passe) parce qu'il execute reellement du pytest :
    une boucle autonome qui lance des suites sans plafond devient un pompage.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_success_oplog import evaluer
    except ImportError as e:  # noqa: BLE001 - le dire, pas rendre un dict vide
        return {"error": "oplog indisponible: %s" % type(e).__name__}
    try:
        bilan = evaluer()
    except Exception as e:  # noqa: BLE001
        return {"error": "%s: %s" % (type(e).__name__, str(e)[:120])}
    if bilan.get("prouvees") or bilan.get("infirmees"):
        log.info("[success_promotion] +%d PROUVE, +%d INFIRME (reste %d)",
                 bilan["prouvees"], bilan["infirmees"],
                 bilan.get("candidates_restantes", 0))
    return bilan


@register_pattern(
    "veille_gap_recover",
    interval_sec=3600,
    description="Rattrape le contenu des URLs de veille absentes du RAG (detache).",
    preferred_window=None,
)
def pat_veille_gap_recover() -> dict:
    """Lance UNE campagne de rattrapage de veille, en DETACHE.

    Le retard se resorbe par paliers : le domaine qui porte 96 % du reste
    (huggingface.co) sert ~100 pages puis impose un repos de plusieurs minutes.
    Rien d'urgent la-dedans, donc une campagne par heure suffit — mais elle dure
    des dizaines de minutes et ne doit JAMAIS bloquer le tick de 60 s du daemon,
    d'ou le detachement (meme motif que l'arene de debat plus bas).

    Anti-empilement : la lane `veille_gap` reste tenue tant qu'une campagne
    tourne. On ne lance rien dans ce cas, plutot que de faire courir deux crawls
    concurrents sur la meme base — deux ecrivains simultanes sur `embeddings.db`
    (WAL) se soldent par des `database is locked` et une passe entiere perdue.
    """
    try:
        from nokido_agent.app.forge_lane_admission import current as _lane_current

        tenue = _lane_current("veille_gap")
        if tenue:
            return {"skipped": "lane veille_gap deja tenue", "holder": str(tenue)[:80]}
    except Exception as exc:  # noqa: BLE001 - lane illisible : on le DIT, on ne suppose pas
        log.warning("[veille_gap_recover] admission illisible : %s", exc)

    script = ROOT / "tools" / "forge_veille_gap_run.py"
    if not script.exists():
        return {"error": "script absent : %s" % script}
    proc = subprocess.Popen(
        # -u : sans lui la sortie reste dans le tampon et le job PARAIT fige.
        [sys.executable, "-u", str(script)],
        cwd=str(ROOT),
        creationflags=_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log.info("[veille_gap_recover] campagne detachee, pid=%s", proc.pid)
    return {"lance": "detache", "pid": proc.pid}


@register_pattern(
    "rag_warmup_delta",
    interval_sec=21600,
    description="Index nouveaux .py/.md depuis last_run dans RAG.",
    preferred_window=(2, 6),
)  # nuit profonde : consolidation mémoire (REM)
def pat_rag_warmup_delta() -> dict:
    """Re-warmup RAG sur fichiers modifiés depuis last_run."""
    if not _ram_gate(1.5, "rag_warmup_delta"):
        return {"skipped": "ram_gate"}
    last = _last_run("rag_warmup_delta")
    cutoff = last if last > 0 else time.time() - 86400
    # List modified .py and .md
    new_files = []
    for ext in ("*.py", "*.md"):
        for f in (ROOT / "app").rglob(ext):
            try:
                if f.stat().st_mtime > cutoff and f.stat().st_size < 200_000:
                    new_files.append(str(f.relative_to(ROOT)))
            except Exception:  # muet-ok: fichier disparu entre listing et stat
                pass
        for f in (ROOT / "docs").rglob(ext):
            try:
                if f.stat().st_mtime > cutoff and f.stat().st_size < 200_000:
                    new_files.append(str(f.relative_to(ROOT)))
            except Exception:  # muet-ok: fichier disparu entre listing et stat
                pass
    if not new_files:
        return {"new_files": 0, "skipped": True}
    # Indexation directe sqlite : chunk size 1500 chars, sha256 id
    import hashlib

    cap = new_files[:30]  # cap 30/run pour éviter charge
    indexed = 0
    errors = 0
    try:
        conn = sqlite3.connect(str(DB), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        for rel_path in cap:
            try:
                full = ROOT / rel_path
                text = full.read_text(encoding="utf-8", errors="replace")
                # Chunks de 1500 chars
                for i in range(0, len(text), 1500):
                    chunk = text[i : i + 1500]
                    if not chunk.strip():
                        continue
                    cid = hashlib.sha256(f"{rel_path}#{i}#{chunk}".encode("utf-8")).hexdigest()[:16]
                    domain = "nokido_code" if rel_path.startswith("app/") else "nokido_doc"
                    conn.execute(
                        "INSERT OR REPLACE INTO rag_chunks(id, source, text, domain) VALUES (?, ?, ?, ?)",
                        (cid, rel_path, chunk, domain),
                    )
                indexed += 1
            except Exception as ie:
                errors += 1
                log.warning(f"[rag_warmup_delta] {rel_path}: {ie}")
        conn.commit()
        conn.close()
        log.info(f"[rag_warmup_delta] indexed {indexed}/{len(cap)} files ({errors} err)")
        return {"new_files": len(new_files), "indexed": indexed, "errors": errors, "method": "direct_sqlite_chunk"}
    except Exception as e:
        return {"new_files": len(new_files), "indexed": indexed, "error": str(e)}


def _regression_capacitive() -> dict:
    """« Nokido oublie ses capacites » : une capacite livree cesse d'exister et
    RIEN ne crie.

    `tools/forge_regression_matrix.py` traite exactement ce probleme — derive de
    CAPACITE, pas derive de sortie — a partir des 217 163 lignes de `network_log`.
    Il existait, il etait bon, et il n'etait CABLE NULLE PART : sa sortie
    `sandbox/regression_matrix.json` datait du 2026-08-12 14:48 et aucune boucle,
    aucun gate CI, aucun service ne la revoyait. Troisieme capteur du jour dans ce
    cas (moniteur d'endpoints, sentinelle des correctifs, celui-ci) : chez Nokido,
    ce ne sont pas les capteurs qui manquent, c'est leur cablage.

    On respecte SON contrat de sortie, qui distingue deja trois etats — la meme
    discipline que le CI local : 0 = capacites intactes, 1 = capacite PERDUE,
    2 = INDETERMINE (la sonde n'a pas pu observer ; un rc!=0 prouve le refus,
    jamais l'absence).
    """
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "forge_regression_matrix.py"), "--check"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=180,
            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
        )
        etat = {0: "capacites_intactes", 1: "CAPACITE_PERDUE",
                2: "INDETERMINE"}.get(r.returncode, f"rc={r.returncode}")
        extrait = (r.stdout or r.stderr or "").strip().splitlines()
        if r.returncode == 1:
            log.error("[capacite] CAPACITE PERDUE — %s", " | ".join(extrait[-3:]))
            _anchor(
                problem="Regression CAPACITIVE detectee (matrice sur network_log)",
                solution=("Une capacite livree n'est plus appelable. Comparer "
                          "sandbox/regression_matrix.json a l'historique et "
                          "restaurer, ou documenter le retrait."),
                example="LAFORGE_PYTHON tools/forge_regression_matrix.py --check",
            )
            try:
                exp = record_evolution_experience({
                    "kind": "capability_lost", "status": "PENDING_CANDIDATE",
                    "organ": "capacites", "detail": extrait[-3:],
                    "hypothesis": "capacité livrée disparue (matrice network_log) — "
                                  "restaurer ou documenter le retrait",
                })
                log.warning(f"[capacite] expérience d'évolution ouverte: {exp}")
            except Exception as e:
                log.warning(f"[capacite] ledger évolution non écrit ({e})")
        elif r.returncode == 2:
            # INDETERMINE n'est pas un succes : on le NOMME, sinon il se confond
            # avec un vert (faux-vert institutionnalise corrige le 2026-08-14).
            log.warning("[capacite] INDETERMINE — la sonde n'a pas pu observer : %s",
                        " | ".join(extrait[-2:]))
        return {"etat": etat, "rc": r.returncode}
    except Exception as e:  # noqa: BLE001
        log.warning("[capacite] matrice INDISPONIBLE (%s: %s) | consequence: une "
                    "capacite qui disparait ne fera crier personne",
                    type(e).__name__, str(e)[:90])
        return {"etat": "INDETERMINE", "erreur": f"{type(e).__name__}"}


@register_pattern(
    "tool_effectiveness",
    interval_sec=86400,
    description="Stats usage tools dispatch, identifie unused/over-used.",
    preferred_window=(7, 9),
)  # matin : revue quotidienne avant journée
def pat_tool_effectiveness() -> dict:
    """Query agent_messages last 7d, group par tool, identifie unused/popular."""
    try:
        cutoff = time.time() - 7 * 86400
        conn = sqlite3.connect(m2m_path())
        rows = conn.execute(
            "SELECT method, COUNT(*) FROM agent_messages "
            "WHERE created_at > datetime(?, 'unixepoch') "
            "GROUP BY method ORDER BY COUNT(*) DESC",
            (cutoff,),
        ).fetchall()
        conn.close()
        stats = {m or "unknown": c for m, c in rows}
        log.info(f"[tool_effectiveness] 7d usage: {stats}")
        capacite = _regression_capacitive()
        if stats:
            top3 = list(stats.items())[:3]
            _anchor(
                problem="Stats usage tools 7 derniers jours",
                solution=f"Top 3: {top3}. Total methods: {len(stats)}.",
                example=str(stats),
            )
        return {"period_days": 7, "method_stats": stats, "total_methods": len(stats),
                "regression_capacitive": capacite}
    except Exception as e:
        return {"error": str(e)}


_TRACE_MIN_SAMPLES = 30  # min échantillons pour juger un tool
_TRACE_SUCCESS_FLOOR = 0.70  # < 70% succès = tool à problème
_TRACE_COST_CEIL = 0.02  # cost delta moyen > 0.02 = action régressive
# Une ligne `status=CALL` est une EMISSION (la requete est partie), pas une ISSUE. Mesure 2026-09-25 :
# groq 227 / mistral 56 lignes en 7 j, TOUTES CALL success=0 -- le sidecar ne trace que les lignes
# OUT, et pour le canal CLOUD la ligne OUT est la requete ; la reponse (IN) n'atteint jamais la table.
# Le taux de succes ne se calcule que sur les issues ; un outil qui n'a QUE des emissions est dit
# « issue non tracee » -- ni en echec, ni sain (UNKNOWN n'est pas NO).
# Meme regle pour INCONNU : le sidecar pose ce statut quand il ne lit pas celui de l'audit (avant le
# 2026-09-25 il posait « OK » par defaut -- un echec `ERR:401` se lisait en succes).
_TRACE_ISSUE_SQL = "COALESCE(json_extract(action_json,'$.status'),'') NOT IN ('CALL', 'INCONNU')"


@register_pattern(
    "trace_mining",
    interval_sec=21600,  # 6h — analyse, pas temps réel
    description="Mine execution_traces : tools faible succès, actions cost-positives, angles morts.",
    preferred_window=None,
)
def pat_trace_mining() -> dict:
    """Surface les signaux exploitables des traces AMI pour la méta-boucle.

    Comble le trou : execution_traces alimentait offline_trainer (nets) mais pas
    l'auto-évolution. On remonte les tools peu fiables + les actions qui
    AUGMENTENT le cost (régressent vers l'instabilité), persisté en
    critical_events (PAS en leçons -> pas de pollution RAG). Reporte aussi la
    profondeur de flow (corrélation cross-call) = feedback live de la qualité
    des trace_id.
    """
    import sqlite3 as _sql

    db = ROOT / "RAG" / "execution_traces.db"
    if not db.exists():
        return {"skipped": "no traces db"}
    try:
        cutoff = time.time() - 7 * 86400
        con = _sql.connect(str(db))
        rows = con.execute(
            "SELECT json_extract(action_json,'$.tool') t, COUNT(*) c, "
            f"SUM(CASE WHEN {_TRACE_ISSUE_SQL} THEN 1 ELSE 0 END) ci, "
            f"AVG(CASE WHEN {_TRACE_ISSUE_SQL} THEN success END) s, "
            "AVG(cost_after - cost_before) d "
            "FROM traces WHERE ts > ? GROUP BY t HAVING c >= ?",
            (cutoff, _TRACE_MIN_SAMPLES),
        ).fetchall()
        depth = con.execute(
            "SELECT AVG(c) FROM (SELECT COUNT(*) c FROM traces WHERE ts > ? "
            "AND trace_id IS NOT NULL AND trace_id != 'system' GROUP BY trace_id)",
            (cutoff,),
        ).fetchone()[0]
        con.close()

        low_success, cost_regress, non_tracee = [], [], []
        for t, c, ci, s, d in rows:
            tool = t or "None/untyped"
            if not ci:
                non_tracee.append({"tool": tool, "appels_emis": c})
            elif ci >= _TRACE_MIN_SAMPLES and s is not None and s < _TRACE_SUCCESS_FLOOR:
                low_success.append({"tool": tool, "n": ci, "success_pct": round(100 * s)})
            if d is not None and d > _TRACE_COST_CEIL:
                cost_regress.append({"tool": tool, "n": c, "cost_delta": round(d, 3)})

        findings = {
            "low_success": low_success,
            "cost_regress": cost_regress,
            "issue_non_tracee": non_tracee,
            "avg_flow_depth": round(depth, 2) if depth else None,
        }
        n_issues = len(low_success) + len(cost_regress)
        log.info(
            f"[trace_mining] {len(rows)} tools, {n_issues} signaux, {len(non_tracee)} sans issue "
            f"tracee (emissions seules : ni echec ni succes), flow_depth={findings['avg_flow_depth']}"
        )
        if n_issues:  # persiste seulement si signal NOTABLE (anti-pollution)
            try:
                import sys as _sys

                _sys.path.insert(0, str(ROOT / "app"))
                from nokido_agent.app.forge_critical_events import persist as _ce

                _ce("trace_mining_findings", "info", findings)
            except Exception as e:
                log.debug(f"[trace_mining] critical_event findings non persisté ({e})")
            try:
                exp = record_evolution_experience({
                    "kind": "usage_findings", "status": "PENDING_CANDIDATE",
                    "organ": "tools", "issues": n_issues, "findings": findings,
                    "hypothesis": "tools à faible succès ou actions coûteuses "
                                  "(trace_mining) — candidats de réglage attendus",
                })
                log.debug(f"[trace_mining] expérience d'évolution ouverte: {exp}")
            except Exception as e:
                log.warning(f"[trace_mining] ledger évolution non écrit ({e})")
        return {"tools_analyzed": len(rows), "issues": n_issues, **findings}
    except Exception as e:
        return {"error": str(e)[:160]}


@register_pattern(
    "forge_missing_tool",
    interval_sec=86400,
    description="Détecte gaps dispatch (errors répétées) → propose forge.",
    requires_local_llm=True,
    preferred_window=(0, 4),
)  # nuit : créativité (rêve sémantique)
def pat_forge_missing_tool() -> dict:
    """Scan agent_messages errors, identifie patterns récurrents → propose tool."""
    if not _local_llm_available():
        return {"skipped": "local_llm_unavailable"}
    if not _ram_gate(2.0, "forge_missing_tool"):
        return {"skipped": "ram_gate"}
    try:
        cutoff = time.time() - 7 * 86400
        conn = sqlite3.connect(m2m_path())
        rows = conn.execute(
            "SELECT payload FROM agent_messages "
            "WHERE created_at > datetime(?, 'unixepoch') "
            "AND (status='error' OR result LIKE '%error%' OR result LIKE '%not found%') "
            "LIMIT 50",
            (cutoff,),
        ).fetchall()
        conn.close()
        if len(rows) < 3:
            return {"skipped": "insufficient_errors", "count": len(rows)}
        # Local LLM analyse patterns
        sample = "\n".join((r[0] or "")[:200] for r in rows[:20])
        prompt = (
            "Analyse ces erreurs/échecs récents d un agent autonome :\n\n"
            f"{sample}\n\n"
            "Liste 1-3 outils MCP qui auraient pu éviter ces erreurs. "
            'Format JSON strict : [{"name": "tool_name", "description": "...", '
            '"why": "..."}]'
        )
        suggestions = _llamacpp_chat(prompt, max_tokens=400)
        log.info(f"[forge_missing_tool] suggestions: {suggestions[:300]}")
        if suggestions:
            _anchor(
                problem=f"Erreurs répétées détectées (7d, {len(rows)} cas)",
                solution=f"Local LLM suggestions outils manquants: {suggestions[:300]}",
                example="POST /api/forge/tool {spec: ...} pour forger",
            )
        return {"errors_analyzed": len(rows), "suggestions": suggestions[:500]}
    except Exception as e:
        return {"error": str(e)}


@register_pattern(
    "git_evolution_tree",
    interval_sec=43200,
    description="Lit branches/commits git → identifie patterns évolution réussis pour inspirer prochaines forges.",
    requires_local_llm=False,
    preferred_window=(1, 3),
)  # nuit : analyse mémoire procédurale
def pat_git_evolution_tree() -> dict:
    """Analyse l arbre d évolution git (branches + commits taggés feat/fix)
    pour détecter patterns de migration/évolution réussis.

    User feedback : 'pendant les phases d évolution, inspire-toi des
    arbres d évolution possible avec git'.
    """
    try:
        # Branches actives
        r1 = subprocess.run(
            ["git", "branch", "-a", "--no-color"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
        branches = [b.strip().lstrip("* ") for b in r1.stdout.splitlines() if b.strip()]
        # Commits récents 30j par type
        cutoff = int(time.time() - 30 * 86400)
        # Format: SHA<TAB>UNIXTIMESTAMP<TAB>SUBJECT (subject last car peut contenir
        # n'importe quel char). TAB rare en commit subject → split(\t,2) safe.
        r2 = subprocess.run(
            ["git", "log", f"--since=@{cutoff}", "--pretty=format:%h%x09%ct%x09%s"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
        commits = []
        type_stats: dict[str, int] = {}
        for line in (r2.stdout or "").splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            sha, ct, subject = parts
            try:
                ct_int = int(ct.strip())
            except ValueError:  # muet-ok: ligne git non conforme, ignorée
                continue
            # Conventional commits prefix detection
            prefix = subject.split("(")[0].split(":")[0].strip().lower() if ":" in subject else "other"
            type_stats[prefix] = type_stats.get(prefix, 0) + 1
            commits.append({"sha": sha, "subject": subject[:80], "ts": ct_int})

        # Identify "evolution branches" : commits feat(phase, deno, forge, etc)
        evolution_keywords = ["phase", "deno", "forge", "tool_smith", "evolve", "kill_switch", "anatomy", "py314"]
        evolution_commits = [c for c in commits if any(k in c["subject"].lower() for k in evolution_keywords)]

        # Top commits by recency (last 10 evolution)
        top_evolution = evolution_commits[:10]

        info = {
            "branches_total": len(branches),
            "branches_active": [b for b in branches if not b.startswith("remotes/")][:5],
            "commits_30d": len(commits),
            "commit_type_stats": dict(sorted(type_stats.items(), key=lambda x: -x[1])[:10]),
            "evolution_commits_recent": [c["subject"] for c in top_evolution],
        }

        # Anchor : Nokido "lit son propre passé" pour inspirer futur
        if top_evolution:
            _anchor(
                problem="Lecture arbre évolution git (mémoire procédurale)",
                solution=f"30j: {len(commits)} commits, {len(evolution_commits)} evolution. "
                f"Top types: {list(info['commit_type_stats'].keys())[:5]}. "
                f"Pattern : feat(phase) + feat(forge) + chore(nssm) dominent.",
                example="; ".join([c["subject"][:50] for c in top_evolution[:3]]),
            )
        log.info(
            f"[git_evolution_tree] {len(commits)} commits 30d, "
            f"{len(evolution_commits)} evolution, types: {list(type_stats.keys())[:5]}"
        )
        return info
    except Exception as e:
        return {"error": str(e)}


@register_pattern(
    "lessons_consolidate",
    interval_sec=172800,
    description="Merge similar anchors RAG via local LLM (dedup).",
    requires_local_llm=True,
    preferred_window=(3, 5),
)  # nuit profonde : consolidation hippocampe
def pat_lessons_consolidate() -> dict:
    """Détecte anchors similaires, propose consolidation."""
    if not _local_llm_available():
        return {"skipped": "local_llm_unavailable"}
    if not _ram_gate(2.0, "lessons_consolidate"):
        return {"skipped": "ram_gate"}
    try:
        # Read recent anchors
        conn = sqlite3.connect(str(DB))
        rows = conn.execute(
            "SELECT id, source, substr(text, 1, 300) FROM rag_chunks "
            "WHERE source LIKE 'lesson%' OR source LIKE 'autonomous%' "
            "ORDER BY rowid DESC LIMIT 30"
        ).fetchall()
        conn.close()
        if len(rows) < 5:
            return {"skipped": "insufficient_anchors", "count": len(rows)}
        sample = "\n---\n".join(f"[{i + 1}] {r[2][:200]}" for i, r in enumerate(rows[:15]))
        prompt = (
            "Identifie clusters d anchors similaires (2-3 max) qui pourraient être "
            "consolidés en une leçon unique. Format JSON strict :\n"
            '[{"cluster": [1, 5, 8], "summary": "..."}]\n\n'
            f"Anchors récents :\n{sample}"
        )
        clusters = _llamacpp_chat(prompt, max_tokens=400)
        log.info(f"[lessons_consolidate] clusters: {clusters[:200]}")
        return {"anchors_analyzed": len(rows), "clusters": clusters[:500]}
    except Exception as e:
        return {"error": str(e)}


_GITINGEST_DIR = ROOT / "data" / "gitingest"
_GITINGEST_PROCESSED = ROOT / "data" / "gitingest" / ".processed"


@register_pattern(
    "repo_ingestion",
    interval_sec=21600,
    description="Scan data/gitingest/ pour nouveaux dumps gitingest → AST+score → indexe RAG.",
    requires_local_llm=False,
    preferred_window=(1, 6),
)  # nuit : I/O lourd
def pat_repo_ingestion() -> dict:
    """Traite les dumps gitingest (.txt) non encore processés.

    Workflow :
      1. Lire manifest .processed (set de fichiers déjà traités)
      2. Scanner data/gitingest/*.txt pour trouver nouveaux
      3. Exécuter forge_ingestion_pipeline.run_ingestion_pipeline()
      4. Sauvegarder <name>_compressed.json
      5. Indexer core_modules dans RAG via anchor_solution
      6. Mettre à jour manifest
    """
    if not _ram_gate(3.0, "repo_ingestion"):
        return {"skipped": "ram_gate"}
    if not _GITINGEST_DIR.exists():
        _GITINGEST_DIR.mkdir(parents=True, exist_ok=True)
        return {"skipped": "data/gitingest/ directory created, no files yet"}

    processed: set[str] = set()
    if _GITINGEST_PROCESSED.exists():
        try:
            processed = set(_GITINGEST_PROCESSED.read_text(encoding="utf-8").splitlines())
        except Exception as e:  # noqa: BLE001
            log.warning(
                "[repo_ingestion] liste des depots deja traites ILLISIBLE (%s: %s) — "
                "repart d'un ensemble VIDE | consequence: tous les depots seront "
                "re-ingeres, et ce travail redondant passera pour du travail neuf",
                type(e).__name__, str(e)[:90])

    txt_files = [f for f in _GITINGEST_DIR.glob("*.txt") if f.name not in processed]
    if not txt_files:
        return {"processed": 0, "already_done": len(processed), "pending": 0}

    sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_ingestion_pipeline import run_ingestion_pipeline
    except ImportError as e:
        return {"error": f"forge_ingestion_pipeline import failed: {e}"}

    results = []
    for txt_path in txt_files[:5]:  # max 5 par run pour éviter OOM
        name = txt_path.stem
        try:
            compressed_json = run_ingestion_pipeline(str(txt_path), top_k=10)
            out_path = _GITINGEST_DIR / f"{name}_compressed.json"
            out_path.write_text(compressed_json, encoding="utf-8")

            data = json.loads(compressed_json)
            modules = data.get("core_modules", [])
            if modules:
                summary = ", ".join(m["name"] for m in modules[:5])
                _anchor(
                    problem=f"Repo externe analysé via gitingest : {name}",
                    solution=f"Top modules: {summary}. {len(modules)} core modules indexés.",
                    example=f"forge_ingestion_pipeline.run_ingestion_pipeline('{txt_path.name}')",
                )
            processed.add(txt_path.name)
            results.append({"file": txt_path.name, "modules": len(modules), "ok": True})
            log.info(f"[repo_ingestion] {name}: {len(modules)} modules → RAG")
        except Exception as e:
            results.append({"file": txt_path.name, "ok": False, "error": str(e)[:120]})
            log.warning(f"[repo_ingestion] {name} failed: {e}")

    try:
        _GITINGEST_PROCESSED.write_text("\n".join(sorted(processed)), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.error(
            "[repo_ingestion] liste des depots traites NON sauvegardee (%s: %s) — %d "
            "entree(s) | consequence: le travail de ce tour sera refait au prochain, "
            "indefiniment tant que l'ecriture echoue",
            type(e).__name__, str(e)[:90], len(processed))

    return {
        "processed": len([r for r in results if r["ok"]]),
        "failed": len([r for r in results if not r["ok"]]),
        "details": results,
    }


@register_pattern(
    "semantic_pressure",
    interval_sec=86400,  # 24h — migre l'ex-schtask LaForge-AutopoiesisDaily @03:00
    description="Autopoiese : mesure pression semantique + consolidation/curiosity si trigger.",
    requires_local_llm=False,
    preferred_window=(3, 5),
)
def pat_semantic_pressure() -> dict:
    """Migration LaForge-AutopoiesisDaily -> scheduler souverain."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_semantic_pressure import autopoiesis_cycle

        return autopoiesis_cycle(window_days=7, dry_run=False)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


@register_pattern(
    "curiosity_driver",
    interval_sec=604800,  # 7j — migre l'ex-schtask LaForge-CuriosityCPWeekly @dim 04:00
    description="Scan gaps RAG -> themes -> push watch_jobs (veille autonome).",
    requires_local_llm=False,
    preferred_window=(4, 5),
)
def pat_curiosity_driver() -> dict:
    """Migration LaForge-CuriosityCPWeekly -> scheduler souverain."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_curiosity_driver import curiosity_cycle

        res = curiosity_cycle(dry_run=False, n_themes=5)
        if res.get("themes"):
            _anchor(
                problem="Gaps RAG detectes (curiosity scan)",
                solution=f"{res.get('n_themes_generated', 0)} themes -> {res.get('n_pushed', 0)} push watch_jobs",
                example="; ".join(t["theme"][:40] for t in res["themes"][:3]),
            )
        return res
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


@register_pattern(
    "remediation_cycle",
    interval_sec=1800,  # 30 min
    description="Remédiation autonomique 8 dettes physiques (embed/lock/orphans/phantoms/cffi/oauth/402/stale).",
    requires_local_llm=False,
    preferred_window=(2, 6),  # nuit off-peak
)
def pat_remediation() -> dict:
    """Surveillance + remédiation des 8 dettes (signal-only via critical_events ;
    auto-fix orphans désactivé sur tick autonome — armer manuellement)."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_remediation import run_remediation_cycle

        return run_remediation_cycle(armed=False)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


# ══════════════════════════════════════════════════════════════════════
# RUN due patterns
# ══════════════════════════════════════════════════════════════════════
@register_pattern(
    "m2m_inbox_watch",
    interval_sec=900,
    description="Observabilite boucle M2M : compte les frames unread non draines par inbox (hors canaux morts/fantomes).",
    preferred_window=None,
)  # 24/7 - detecte silencieusement le travail inter-agent non recu
def pat_m2m_inbox_watch() -> dict:
    """Backlog M2M par destinataire : messages-frames status=unread jamais lus.

    Rend visible dans l'audit autonome (local, 0 LLM, 0 ecriture hub) tout
    message inter-agent qui stagne — signal de sante de la boucle collaborative.
    N'execute ni ne consomme rien (non destructif).
    """
    import sqlite3 as _sq

    _DEAD = {
        "agt_gemini", "agt_groq", "agt_cohere", "agt_gpt4o_github",
        "agt_gemini_flash", "agt_agy", "EVENTBUS_ARCHIVE", "local",
    }
    backlog = {}
    try:
        conn = _sq.connect(m2m_path(), timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        rows = conn.execute(
            "SELECT to_agent, COUNT(*), MAX(created_at) FROM agent_messages "
            "WHERE status='unread' AND id LIKE 'frm_%' GROUP BY to_agent"
        ).fetchall()
        conn.close()
    except Exception as e:
        return {"error": str(e)}
    for to_agent, n, last in rows:
        if not to_agent or to_agent in _DEAD or str(to_agent).startswith("agt_agt_"):
            continue
        backlog[to_agent] = {"unread": n, "last": last}
    return {"stale_m2m_backlog": backlog, "inboxes_with_backlog": len(backlog)}


# ── Actionneur M2M ───────────────────────────────────────────────────
# m2m_inbox_watch COMPTE le courrier qui stagne et ne le livre pas : un capteur
# sans actionneur laisse le debat inter-agent avancer au rythme des relances
# humaines. Ce pattern ferme la boucle. Il ne consomme AUCUN LLM tant que le
# pair n'a pas ecrit : le cout suit la conversation, pas l'horloge.
# ── VEILLE -> DIGEST : le chainon manquant ────────────────────────────────────
# MESURE 2026-08-31 : `findstr /s /m "forge_veille_digest"` sur app/ et tools/
# rend UN SEUL fichier -- lui-meme. Le digest n'avait aucun consommateur : une
# veille produisait de la matiere et personne ne la digerait, sauf un humain
# lancant le CLI. Les suggestions du 30/08 sont sorties comme ca, a la main.
#
# PAS de nouveau scheduler : la boucle autonome existe et porte deja 21 routines.
# PAS de nouvelle base : `backfill(since=...)` sait deja filtrer `biblio_raw` par
# date, et `veille_digest_suggestions` deduplique deja par md5(suggestion+organe).
_DIGEST_ETAT = ROOT / "sandbox" / "veille_digest_auto.json"
# SEULS verdicts qui peuvent porter de la matiere. `completed_empty` et
# `completed_dedup` n'en ont pas, `failed`/`indetermine`/`en_cours` ne prouvent
# rien. La liste est celle du verdict de chaine (cf. `forge_watch_agent`).
_DIGEST_VERDICTS = ("completed", "completed_partial")
_DIGEST_MEMOIRE = 200
# Une veille = un appel de digest. Sans cap, le premier tour reel rattrapait un
# MOIS d'arriere (31 veilles candidates le 2026-08-31) en une seule fois.
_DIGEST_MAX_PAR_TOUR = 5
# DISPONIBILITE DU FOURNISSEUR — capteur DEJA EXISTANT, produit par le pattern
# `endpoint_health` de cette meme boucle. Aucun systeme de sante nouveau : on lit
# l'instantane qu'un voisin ecrit deja, et qui classe en ce moment `ollama` dans
# `-` (injoignable).
#
# REGRESSION QUE CECI FERME (mesuree le 2026-08-31) : `veille_digest_auto` a
# appele le LLM local FIGE, 120 s par lot, et a monopolise le tick de 15:39 a
# 15:43+. `veille_github_head` n'a jamais obtenu son tour. Un pattern qui attend
# un fournisseur mort affame tous les suivants -- le tick est SERIEL.
_SANTE_ENDPOINTS = ROOT / "sandbox" / "endpoint_health_last.json"
_SANTE_TTL_S = 900.0


# `_fournisseur_digest` a ete RETIRE le 2026-08-31. Il pretendait nommer « le
# fournisseur que le digest va REELLEMENT appeler » ; depuis le contrat provider
# (Groq primaire / Ollama secondaire, `forge_veille_digest.choisir_provider`),
# cette phrase etait devenue fausse. Une fonction dont la docstring ment est pire
# qu'une fonction morte. L'autorite unique est desormais dans l'organe qui appelle
# le LLM. `_fournisseur_pret` reste : `epistemic_consolidation` s'en sert.
def _fournisseur_pret(nom: str, ttl: float = _SANTE_TTL_S) -> tuple:
    """(pret, raison) — TROIS etats : PRET / INDISPONIBLE / INCONNU.

    INCONNU (instantane absent, illisible ou perime) vaut ABSTENTION, et c'est
    un choix asymetrique assume : tenter sur un etat inconnu risque de rejouer
    exactement la panne — un tick affame pendant des minutes — alors que
    s'abstenir ne coute qu'un cycle differe, la matiere restant intacte. Et
    l'abstention est auto-reparatrice : en rendant la main vite, elle laisse
    `endpoint_health` tourner et rafraichir l'instantane.
    """
    import json as _j
    try:
        d = _j.loads(_SANTE_ENDPOINTS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False, "sante des fournisseurs INCONNUE (%s absent)" % _SANTE_ENDPOINTS.name
    except Exception as exc:  # noqa: BLE001
        return False, "sante des fournisseurs ILLISIBLE (%s)" % type(exc).__name__
    age = time.time() - float(d.get("ts") or 0)
    if age > ttl:
        return False, "sante des fournisseurs PERIMEE (%.0f min)" % (age / 60)
    par_statut = d.get("par_statut") or {}
    for statut, noms in par_statut.items():
        if nom in (noms or []):
            if str(statut) == "200":
                return True, "%s joignable (releve il y a %.0f min)" % (nom, age / 60)
            if str(statut).strip() == "-":
                # `-` = LA SONDE elle-meme a echoue (`probe` ne produit cette valeur
                # que depuis son `except` generique) : c'est une absence de mesure,
                # PAS un verdict de panne. L'ecrivain du meme fichier le sait deja
                # (L730 exclut "-" des `casses`) ; le lecteur, lui, comptait "-"
                # comme INDISPONIBLE -- d'ou SEPT abstentions consecutives le
                # 2026-08-31 sur un Ollama vivant, dont le seul tort etait de
                # n'avoir pas repondu a la sonde ce jour-la.
                return False, "%s NON SONDE (statut -, releve il y a %.0f min) — " \
                              "absence de mesure, pas une panne" % (nom, age / 60)
            return False, "%s INDISPONIBLE (statut %s, releve il y a %.0f min)" % (
                nom, statut, age / 60)
    return False, "%s absent du releve de sante" % nom


def _urls_du_job(refined_json) -> list:
    """Les URLs que CETTE veille a tracees. PURE.

    `watch_jobs.refined_json` porte deja `{"candidats": [{t, u, rel}], "refus": []}`
    — la trace compacte ajoutee pour rendre la provenance verifiable. Mesure
    2026-08-31 : exploitable sur 43 des 45 jobs, et sur les 31 candidats au
    digest. C'est donc une metadonnee EXISTANTE, pas une colonne a creer.

    Rend `[]` quand la trace manque ou ne se lit pas. `[]` veut dire « rien
    d'attribuable a cette veille », JAMAIS « toute la base » : c'est la
    difference entre attribuer et supposer.

    LIMITE ASSUMEE : la trace est plafonnee a 20 candidats. Une veille qui a
    stocke davantage est SOUS-attribuee — on digere moins, jamais la matiere
    d'une autre chaine.
    """
    try:
        d = json.loads(refined_json or "")
    except Exception:  # noqa: BLE001
        return []                 # muet-ok : trace illisible = rien d'attribuable
    if not isinstance(d, dict):
        return []
    return [str(x.get("u")) for x in (d.get("candidats") or []) if x.get("u")]


def _digest_a_faire(jobs, vus) -> list:
    """Les veilles qui meritent un digest. PURE, donc testable sans LLM ni base.

    DEUX conditions, jamais une seule. Le verdict dit que la chaine a bien
    travaille ; `n_stored > 0` dit qu'il en RESTE quelque chose. Deduire la
    matiere du seul statut est exactement l'erreur que H3/H4 viennent de fermer
    un cran plus haut : un worker sain ne prouve pas une veille utile, un verdict
    `completed` ne prouve pas une retention.
    """
    vus = set(vus or ())
    return [j for j in (jobs or [])
            if str(j.get("status") or "") in _DIGEST_VERDICTS
            and str(j.get("id") or "") not in vus
            and int(j.get("n_stored") or 0) > 0]


@register_pattern(
    "veille_digest_auto", interval_sec=3600,
    description="Digere la matiere des veilles terminees qui n'ont jamais ete digerees.",
    preferred_window=None,
)
def pat_veille_digest_auto(db=None, backfill=None) -> dict:
    """VEILLE -> verdict -> matiere neuve -> DIGEST -> suggestions persistees.

    IDEMPOTENCE a deux filets, parce qu'un seul ne survit pas a un restart :
      1. un filigrane `sandbox/veille_digest_auto.json` retient les `chain_id`
         deja digeres (200 derniers) -- meme idiome que `m2m_debate_relay.json` ;
      2. `veille_digest_suggestions` refuse deja un doublon par md5. Un second
         passage rend donc 0 suggestion nouvelle, jamais un doublon.

    ECHEC LLM : les jobs ne sont PAS marques vus. La veille reste terminee, le
    digest se declare `unavailable`, et la matiere sera reprise au prochain tour.
    Marquer vu un digest qui n'a rien pu faire fabriquerait un succes.
    """
    import json as _j
    import sqlite3 as _sq
    etat = {}
    try:
        etat = _j.loads(_DIGEST_ETAT.read_text(encoding="utf-8"))
    except FileNotFoundError:
        pass                      # muet-ok : premier tour, filigrane a creer
    except Exception as exc:      # noqa: BLE001
        # ILLISIBLE n'est pas VIDE : repartir d'un filigrane vide re-digererait
        # tout l'historique. On s'abstient, et on le DIT.
        return {"skip": "filigrane illisible (%s)" % type(exc).__name__,
                "digest": "non tente"}
    # CHEMIN COURT, AVANT toute lecture de base et tout appel LLM. C'est ici que
    # la boucle rend la main : aucun job n'est marque, la matiere reste entiere,
    # et le tour suivant la reprendra.
    #
    # La DECISION du fournisseur appartient a l'organe qui appelle le LLM
    # (`forge_veille_digest.choisir_provider`), pas au pattern : deux endroits qui
    # choisissent le meme fournisseur finissent par diverger, et c'est le pattern
    # qui avait raison contre le module — ou l'inverse — sans que rien ne tranche.
    try:
        from nokido_agent.app.forge_veille_digest import (  # noqa: PLC0415
            DIGEST_MODEL as _modele_local, choisir_provider as _choisir,
            sante_endpoints as _sante, sonde_ollama as _sonde,
            statut_abstention as _statut_abs)
    except Exception as exc:  # noqa: BLE001
        return {"digest": "unavailable", "statut": "SKIPPED_PROVIDER_UNAVAILABLE",
                "raison": "import: %s" % type(exc).__name__, "jobs_marques_vus": 0}
    # `_sonde` est passe SANS parenthese : la sonde locale n'est payee que si le
    # primaire distant a deja refuse.
    _releve, _motif_sante = _sante(avec_motif=True)
    _prov, _modele, _etat_prov, _essais = _choisir(_releve, _sonde,
                                                   modele_local=_modele_local)
    if not _prov:
        return {"digest": "unavailable", "statut": _statut_abs(_essais),
                "provider": "", "model": "", "provider_state": _etat_prov,
                "essais": _essais, "sante_motif": _motif_sante,
                "jobs_marques_vus": 0,
                "note": "abstention rapide : la matiere est conservee"}
    vus = list(etat.get("jobs_vus") or [])
    # TROISIEME liste, et pas un detail : une veille dont la matiere n'est pas
    # attribuable n'a pas ete digeree (elle ne va pas dans `jobs_vus`) mais ne
    # doit pas non plus etre retentee chaque heure pour rien.
    sans_matiere = list(etat.get("jobs_sans_matiere") or [])
    try:
        if db is None:
            from nokido_agent.app.forge_db_path import db_path as _dbp  # noqa: PLC0415
            db = _dbp()
        conn = _sq.connect("file:%s?mode=ro" % str(db).replace("\\", "/"), uri=True)
        conn.row_factory = _sq.Row
        jobs = [dict(r) for r in conn.execute(
            "SELECT id, status, n_stored, created_at, refined_json FROM watch_jobs "
            "ORDER BY created_at DESC LIMIT 100").fetchall()]
        candidats = _digest_a_faire(jobs, vus + sans_matiere)[:_DIGEST_MAX_PAR_TOUR]
        # La matiere d'une veille = les documents dont l'URL figure dans SA trace.
        matiere = {}
        for j in candidats:
            us = _urls_du_job(j.get("refined_json"))
            matiere[str(j["id"])] = [] if not us else [
                r[0] for r in conn.execute(
                    "SELECT id FROM biblio_raw WHERE url IN (%s)"
                    % ",".join("?" * len(us)), us).fetchall()]
        conn.close()
    except Exception as exc:  # noqa: BLE001
        return {"skip": "watch_jobs illisible (%s)" % type(exc).__name__,
                "digest": "non tente"}
    if not candidats:
        return {"digest": "rien a digerer", "jobs_vus": len(vus),
                "jobs_sans_matiere": len(sans_matiere), "jobs_examines": len(jobs)}
    if backfill is None:
        try:
            from nokido_agent.app.forge_veille_digest import backfill  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            return {"digest": "unavailable", "candidats": len(candidats),
                    "jobs_marques_vus": 0,
                    "raison": "import: %s" % type(exc).__name__}
    # UN APPEL PAR VEILLE. C'est ce qui permet de marquer chacune selon SON
    # propre resultat : un digest partiellement echoue ne doit pas faire passer
    # pour digeree la matiere qu'il n'a pas traitee.
    faits, echoues, sans, detail = [], [], [], []
    for j in candidats:
        cid = str(j["id"])
        ids = matiere.get(cid) or []
        if not ids:
            sans.append(cid)
            detail.append({"chain_id": cid, "etat": "sans matiere attribuable"})
            continue
        try:
            res = backfill(limit=400, ids=ids, provider=_prov, modele=_modele) or {}
        except Exception as exc:  # noqa: BLE001
            echoues.append(cid)
            detail.append({"chain_id": cid, "etat": "unavailable",
                           "raison": "%s: %s" % (type(exc).__name__, str(exc)[:80])})
            continue
        # Le VERDICT DU MODULE fait autorite : `DIGEST_FAILED` dit que tous les
        # lots ont echoue, et il le sait par lot, la ou le pattern ne voyait qu'un
        # compteur global. Un `SKIPPED_*` en cours de route (un provider tombe
        # entre deux veilles) n'est pas non plus un digest : la veille reste a
        # faire, elle ne va pas dans le filigrane.
        _st = str(res.get("statut") or "")
        _sugg = res.get("suggestions_generated", res.get("new_suggestions"))
        # Un `backfill` qui ne rend PAS de statut n'est pas pour autant un succes :
        # on retombe sur le signal historique (des lots traites, aucun retenu, des
        # echecs LLM). Le statut fait autorite quand il existe ; son absence ne
        # doit pas valoir acquittement.
        _echec = (_st.startswith("SKIPPED_") or _st == "DIGEST_FAILED"
                  or (not _st and int(res.get("llm_fails") or 0) > 0 and not _sugg))
        if _echec:
            echoues.append(cid)
            detail.append({"chain_id": cid, "etat": "unavailable", "statut": _st,
                           "llm_fails": res.get("llm_fails"),
                           "documents": res.get("documents"),
                           "provider_state": res.get("provider_state")})
            continue
        faits.append(cid)
        detail.append({"chain_id": cid, "etat": "digere", "statut": _st,
                       "documents": res.get("documents"),
                       "candidats_matiere": len(ids),
                       "lots_ok": res.get("success"), "lots_ko": res.get("failure"),
                       # PAS « connaissance nouvelle » : des LIGNES retenues apres
                       # dedup md5, qui ne voit pas une reformulation.
                       "suggestions_generated": res.get("suggestions_generated"),
                       "docs_marques": res.get("docs_marques")})
    filigrane = "ecrit"
    if faits or sans:
        try:
            _DIGEST_ETAT.parent.mkdir(parents=True, exist_ok=True)
            _DIGEST_ETAT.write_text(
                _j.dumps({"jobs_vus": (vus + faits)[-_DIGEST_MEMOIRE:],
                          "jobs_sans_matiere": (sans_matiere + sans)[-_DIGEST_MEMOIRE:],
                          "dernier_ts": time.time()}, ensure_ascii=False),
                encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            # Le digest a tourne ; c'est le filigrane qui n'a pas pu etre ecrit.
            # Le dire : au prochain tour la matiere sera representee, et seul le
            # dedup md5 empechera les doublons.
            filigrane = "NON ecrit (%s)" % type(exc).__name__
    return {"digest": "fait" if faits else ("unavailable" if echoues
                                            else "rien de digerable"),
            "provider": _prov, "model": _modele, "provider_state": _etat_prov,
            "essais": _essais,
            "filigrane": filigrane,
            "chain_ids_digeres": faits, "chain_ids_echoues": echoues,
            "chain_ids_sans_matiere": sans,
            "candidats": len(candidats),
            "jobs_marques_vus": len(faits) if filigrane == "ecrit" else 0,
            "detail": detail}


# ── H2 PHASE A : le CAPTEUR de changement de depot ────────────────────────────
# SEPARATION VOULUE. Detecter n'est pas rapatrier : un probleme du clone ne doit
# pas detruire la capacite du capteur. Ce pattern ne clone RIEN et n'ingere RIEN.
#
# CE QU'IL NE PEUT PAS FAIRE, et qui est dit plutot que masque : la recuperation
# reste `RECOVERY_UNAVAILABLE`. Mesure 2026-08-31 — le clone ECHOUE sous `run_job`
# meme en `online` (0 fichier en 19 min) et n'aboutit que sous `trusted`, et le
# compte de ce daemon n'est pas lisible depuis le bac a sable (`sc qc` rend
# « Acces refuse », `tasklist /v` rend « N/A » sur les 85 process). Tant que le
# chemin d'execution autorise n'est pas ETABLI, brancher le clone ici serait
# inventer une veille fonctionnelle.
_GH_ETAT = ROOT / "sandbox" / "veille_github_watch.json"
# Intention LONGUE limitee aux depots CRITIQUES (decision owner 2026-09-23). Le fichier
# porte la LISTE (`{"cibles": [nom_dump|slug|target_id, ...]}`) : hors d'elle, seule
# l'intention courte `veille_gh.wanted` (24 h) ouvre la re-recuperation.
_GH_INTENTION_CRITIQUES = ROOT / "sandbox" / "veille_gh_critiques.wanted"
_GH_TTL_CRITIQUES = 180 * 86400.0
_GH_REGISTRE = ROOT / "sandbox" / "veille_targets.json"
# Detection = UNE requete `ls-remote` par cible, sans clone. Le plafond protege
# le tour, pas le reseau : c'est la RECUPERATION qui coute, et elle n'est pas
# branchee. Il sera re-arbitre avec elle.
_GH_MAX_PAR_TOUR = 12
_GH_MEMOIRE = 400
# DEPOT PILOTE, pas « canari » : ce mot est DEJA pris dans Nokido, et avec un
# tout autre sens — `generate_canary` / `check_canary_leak` / `canary_leaked`
# designent un jeton-piege d'exfiltration (forge_commit_intel, forge_cost_module,
# forge_immune_adaptive). Le reutiliser ici rendrait un grep ambigu entre « petit
# depot de test » et « fuite detectee ».
# Choisi par la MESURE : 9,5 Ko de dump contre 69,9 Mo pour codex.
_GH_PILOTE = "systolicdemo"
# CAP DE RECUPERATION, distinct du cap d'EXAMEN. Examiner coute un `ls-remote` ;
# recuperer coute un clone. Mesure : le pilote fait 9,5 Ko et 7,2 s, `codex` fait
# 69,9 Mo. Ouvrir les 12 d'un coup ferait 12 clones dans un tick de 60 s.
_GH_MAX_RECUPERATIONS_PAR_TOUR = 1
# BUDGET aligne sur le defaut du hub (`timeout` de trusted_script, plafond 3600).
_GH_BUDGET_RECUPERATION_S = 120
# ORDRE FORCE — VIDE depuis le 2026-08-31, et sa raison est CONSOMMEE. `codex` y
# figurait parce qu'il etait le seul depot dont le capteur avait mesure un
# changement reel ; il a ete recupere (65,0 Mo, 5 875 fichiers, commit
# 32f48598a060) et porte desormais son manifeste.
#
# LE GARDER SERAIT UNE FAMINE STRUCTURELLE : la clef d'ordre le classait rang 0
# INCONDITIONNELLEMENT, donc a cap=1 il aurait pris le slot a CHAQUE tour tant
# qu'il reste UPDATED — et c'est le depot le plus actif des douze (quatre SHA
# differents dans la journee). Les onze autres n'auraient jamais eu leur tour.
_GH_PRIORITAIRES: tuple = ()


def _gh_ordre_recuperation(candidats: list, docs, etat=None) -> list:
    """Jamais tentes d'abord, puis la tentative la PLUS ANCIENNE, puis la taille.

    EQUITE. A cap=1, ordonner par taille seule laisse un petit depot tres actif
    reprendre le slot indefiniment. L'age depuis la derniere tentative garantit
    que CHAQUE cible suivie passe avant qu'aucune ne repasse — c'est la propriete
    « un depot tres vivant ne peut pas affamer les autres ».

    Aucun ordonnanceur nouveau : `last_recovery` est deja ecrit dans
    `veille_github_watch.json` a chaque tentative, succes ou echec. On lit ce que
    le corps note deja.
    """
    return sorted(candidats, key=lambda c: _gh_cle_recuperation(c, docs, etat))


def _gh_cle_recuperation(cible: dict, docs, etat=None) -> tuple:
    """(deja tente, horodatage de la derniere tentative, taille, nom).

    La taille reste le DERNIER critere : c'est une mesure du cout, utile pour
    departager, jamais pour decider seule qui passe.
    """
    cible = cible or {}
    nom = str(cible.get("nom_dump") or "")
    prio = (_GH_PRIORITAIRES.index(nom) if nom in _GH_PRIORITAIRES
            else len(_GH_PRIORITAIRES))
    tid = str(cible.get("target_id") or cible.get("repo") or "?")
    derniere = str(((etat or {}).get(tid) or {}).get("last_recovery") or "")
    try:
        taille = _gh_dump(docs, nom).stat().st_size
    except OSError:
        taille = float("inf")         # jamais dumpe : cout INCONNU, donc en dernier
    # `derniere` vide = jamais tentee : elle passe AVANT toute cible deja servie.
    return (prio, 1 if derniere else 0, derniere, taille, nom)
# Verdicts de la PHASE B. Ils ne se melangent JAMAIS a ceux de la phase A : le
# capteur peut savoir qu'un depot a avance (`last_head_seen`) pendant que
# l'actionneur echoue a suivre (`last_head_ingested` reste en arriere).
REC_SUCCESS, REC_FAILED = "SUCCESS", "FAILED"
REC_UNAVAILABLE, REC_OCCUPE = "RECOVERY_UNAVAILABLE", "OCCUPE"
# INTENTION, idiome DEJA en place dans l'organisme : `sandbox/<nom>.wanted`,
# pose par `forge_embed_router.declare_wanted`, lu par le regulateur et par le
# keeper (docker.wanted / llama.wanted / rerank.wanted / embed.wanted /
# snn.wanted). Aucun mecanisme nouveau.
#
# POURQUOI IL FALLAIT CA : `run_due_patterns` appelle les patterns SANS argument.
# Un opt-in exprime en parametre de fonction est donc inatteignable depuis le
# daemon -- exactement le motif « un garde branche sur un signal que personne
# n'emet », applique a mon propre code.
_GH_INTENTION = ROOT / "sandbox" / "veille_gh.wanted"
# TTL LONG, et c'est un choix motive : `docker.wanted` vaut 900 s parce qu'il dit
# « j'ai besoin de docker MAINTENANT ». Ici l'intention est « surveille ce
# depot », qui dure. A 900 s elle expirerait entre deux ticks horaires et ne
# serait jamais lue -- un drapeau qu'aucun lecteur n'atteint ne vaut rien.
_GH_TTL_INTENTION = 86400.0


def _gh_intention(ttl: float = _GH_TTL_INTENTION) -> tuple:
    """(voulu, raison) — la recuperation est-elle DEMANDEE, et depuis quand ?

    TROIS etats, jamais deux : posee et fraiche / posee mais PERIMEE / absente.
    Une intention perimee n'est pas une absence d'intention : elle dit que
    quelqu'un l'a voulue puis ne l'a pas renouvelee, et ce n'est pas la meme
    chose que personne ne l'a jamais demandee.
    """
    try:
        age = time.time() - _GH_INTENTION.stat().st_mtime
    except FileNotFoundError:
        return False, "aucune intention posee (%s absent)" % _GH_INTENTION.name
    except OSError as exc:
        return False, "intention illisible (%s)" % type(exc).__name__
    if age > ttl:
        return False, "intention PERIMEE (%.0f h > %.0f h)" % (age / 3600, ttl / 3600)
    return True, "intention posee il y a %.0f min" % (age / 60)


def _gh_intention_critiques(ttl: float = None) -> tuple:
    """(ensemble des depots critiques | None, raison). Trois etats, jamais deux."""
    ttl = _GH_TTL_CRITIQUES if ttl is None else ttl
    try:
        age = time.time() - _GH_INTENTION_CRITIQUES.stat().st_mtime
        liste = json.loads(_GH_INTENTION_CRITIQUES.read_text(encoding="utf-8")).get("cibles") or []
    except FileNotFoundError:
        return None, "aucune intention critique (%s absent)" % _GH_INTENTION_CRITIQUES.name
    except (OSError, ValueError, AttributeError) as exc:
        return None, "intention critique ILLISIBLE (%s)" % type(exc).__name__
    if age > ttl:
        return None, "intention critique PERIMEE (%.0f j > %.0f j)" % (age / 86400, ttl / 86400)
    return set(map(str, liste)), "intention critique posee il y a %.0f j (%d depot(s))" % (
        age / 86400, len(liste))


def _gh_recuperer(cible: dict, sha_attendu: str, docs, appel=None) -> dict:
    """PHASE B — DELEGUE au chemin de confiance existant. Ne clone RIEN ici.

    CHEMIN REUTILISE, aucune capacite privilegiee creee :
        pattern -> HubClient.tool("run", action="trusted_script")
                -> gate « committe + propre vs HEAD » (forge_mcp_registry)
                -> spawn_as_trusted, compte LaForgeTrusted
                -> tools/forge_veille_clone_ingest.py --dump-only
    `trusted_script` exige le ring DEV (forge_mcp_rbac), pas le ring owner : un
    agent legitime peut l'appeler. Le pattern est l'ORCHESTRATEUR, jamais un
    second cloneur — reimplementer le clone ici dupliquerait le pipeline de
    qualification (filtre d'intake, manifeste, FTS) que le module porte deja.

    LE MANIFESTE EST LA PREUVE, et il ne l'est qu'a une condition : son `commit`
    doit valoir le HEAD qu'on croyait recuperer. Un dump present ne prouve rien
    (il peut dater), un rc=0 non plus (mesure du 29/08 : un push rendait rc=1 en
    ayant reussi). On ne declare SUCCESS qu'apres avoir relu le manifeste.
    """
    import json as _j
    import os as _os
    tid = str(cible.get("target_id") or cible.get("repo") or "?")
    nom = cible.get("nom_dump")
    if not nom:
        return {"etat": REC_FAILED, "raison": "cible sans identite de dump"}
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_lane_admission import acquire, release  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return {"etat": REC_UNAVAILABLE,
                "raison": "verrou de lane indisponible (%s)" % type(exc).__name__}
    lane, holder = "veille_gh:%s" % tid, "loops:%d" % _os.getpid()
    if not acquire(lane, holder):
        # Deux tours simultanes : le second s'abstient. Il ne s'agit pas d'un
        # echec, et le compter comme tel accuserait a faux.
        return {"etat": REC_OCCUPE, "raison": "une recuperation tient deja %s" % lane}
    try:
        if appel is None:
            try:
                from nokido_agent.app.forge_hub_client import HubClient  # noqa: PLC0415
                # TIMEOUT EXPLICITE. Le defaut de HubClient est 5 s : un clone
                # plus long rendrait None cote client pendant que le travail
                # continue cote serveur, et l'on inscrirait UNAVAILABLE sur une
                # recuperation peut-etre reussie. On attend un peu PLUS que le
                # budget serveur, pour recevoir `timed_out=True` au lieu de
                # couper la ligne et confondre depassement et hub injoignable.
                # IDENTITE PROPRE. Le defaut de HubClient est SERVICES, resolu
                # ring 4 : `trusted_script` exige ring <= 2 et le refusait. Le
                # registre declare AUTONOMOUS_LOOPS au ring 2 depuis toujours ;
                # il ne lui manquait que SON jeton (mesure 2026-08-31 : la
                # resolution retombait sur FORGE_TOKEN_SERVICES, et un jeton non
                # apparie DEGRADE l'identite au lieu de l'etablir).
                #
                # PRIVILEGE ASSUME, et il n'est PAS limite a ce script : ring 2
                # ouvre `trusted_script`, donc l'execution de tout .py committe et
                # propre sous tools/ ou app/. Le modele RBAC n'a aucune
                # granularite par script — ne pas lire cette ligne comme une
                # permission etroite.
                appel = HubClient(agent="AUTONOMOUS_LOOPS",
                                  timeout=_GH_BUDGET_RECUPERATION_S + 15).tool
            except Exception as exc:  # noqa: BLE001
                return {"etat": REC_UNAVAILABLE,
                        "raison": "hub injoignable depuis ce daemon (%s)"
                                  % type(exc).__name__}
        # `path`, PAS `script` : mesure du 2026-08-31, le hub refuse
        # « trusted_script: 'path' requis (relatif au repo, sous tools/ ou app/) ».
        # La preuve live a attrape ce defaut que les tests, qui injectent l'appel,
        # ne pouvaient pas voir — un contrat d'API ne se devine pas.
        sortie = appel("run", {
            "action": "trusted_script",
            "path": "tools/forge_veille_clone_ingest.py",
            "args": "%s --force --dump-only" % nom,
            "timeout": _GH_BUDGET_RECUPERATION_S,
        })
        # Le hub represente un depassement dans son en-tete : `timed_out=True`.
        # Le lire evite de prendre un dump PRECEDENT pour le resultat du clone —
        # la comparaison de commit le refuserait de toute facon, mais la raison
        # serait fausse et enverrait chercher un defaut de manifeste.
        if isinstance(sortie, str) and "timed_out=True" in sortie:
            return {"etat": REC_FAILED,
                    "raison": "budget de %d s depasse cote hub ; dump precedent "
                              "conserve" % _GH_BUDGET_RECUPERATION_S}
        # UN REFUS DU HUB N'EST PAS UNE REPONSE. Mesure du 2026-08-31 : le hub a
        # rendu `GATE_DENIED: ring 4 <= requis 3`, mon code l'a pris pour une
        # sortie normale, a verifie le dump — inchange, forcement — et a rapporte
        # « dump sans manifeste : provenance inverifiable ». Une raison fausse
        # envoie la session suivante chercher un defaut de manifeste la ou il y a
        # un probleme d'identite.
        if isinstance(sortie, str) and any(
                sortie.lstrip().startswith(p)
                for p in ("GATE_DENIED", "ERR:", "[Hub] Erreur")):
            return {"etat": REC_UNAVAILABLE, "refus_hub": sortie.strip()[:160],
                    "raison": "le hub a REFUSE l'appel : %s" % sortie.strip()[:120]}
        if sortie is None:
            return {"etat": REC_UNAVAILABLE,
                    "raison": "le hub n'a rien rendu (trusted_script refuse ou hors "
                              "ligne) — aucun clone tente"}
        # VERIFICATION, dans l'ordre du plus grossier au plus precis.
        dump = _gh_dump(docs, nom)
        if not dump.exists():
            return {"etat": REC_FAILED, "raison": "aucun dump apres recuperation"}
        if dump.stat().st_size <= 0:
            return {"etat": REC_FAILED, "raison": "dump vide"}
        man = Path(str(dump) + ".manifest.json")
        try:
            m = _j.loads(man.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"etat": REC_FAILED,
                    "raison": "dump sans manifeste : provenance invérifiable"}
        except (OSError, ValueError) as exc:
            return {"etat": REC_FAILED,
                    "raison": "manifeste illisible (%s)" % type(exc).__name__}
        obtenu = str((m or {}).get("commit") or "").strip()
        if not obtenu or obtenu != str(sha_attendu or "").strip():
            return {"etat": REC_FAILED, "sha_manifeste": obtenu[:12] or None,
                    "raison": "manifeste au commit %s, HEAD attendu %s — on n'ecrit "
                              "JAMAIS un SHA suppose"
                              % (obtenu[:12] or "?", str(sha_attendu)[:12])}
        return {"etat": REC_SUCCESS, "sha_manifeste": obtenu,
                "octets": dump.stat().st_size,
                "raison": "manifeste au commit attendu"}
    finally:
        try:
            release(lane, holder)
        except Exception as exc:  # noqa: BLE001
            print("[gh] bail %s non relache (%s) : la prochaine tentative sera "
                  "refusee jusqu'au TTL" % (lane, type(exc).__name__))


def _gh_dossiers_dumps(docs=None) -> list:
    """Dossiers de dumps : `docs` injecte (tests), sinon le resolveur unique du
    registre (docs/ + `sandbox/veille_dumps.dir`, mesure 2026-09-23 : les dumps
    du registre peuvent vivre sur E:). Resolveur illisible -> docs/ seul, DIT."""
    if docs is not None:
        return [Path(docs)]
    try:
        from nokido_agent.tools.forge_veille_registre import dossiers_dumps  # noqa: PLC0415
        return dossiers_dumps(ROOT)
    except Exception as exc:  # noqa: BLE001
        print("[gh] resolveur de dumps ILLISIBLE (%s) : docs/ seul, les dumps hors "
              "depot se liront ABSENT" % type(exc).__name__)
        return [ROOT / "docs"]


def _gh_dump(docs, nom) -> Path:
    """Chemin du dump `nom` : la copie la plus RECENTE (meme regle que le
    registre, qu'on appelle au lieu de la recopier), sinon docs/."""
    dossiers = _gh_dossiers_dumps(docs)
    try:
        from nokido_agent.tools.forge_veille_registre import chemin_dump  # noqa: PLC0415
        trouve = chemin_dump(nom, dossiers)
    except Exception as exc:  # noqa: BLE001
        print("[gh] chemin_dump ILLISIBLE (%s) : repli sur le 1er dossier"
              % type(exc).__name__)
        trouve = None
    return trouve or Path(dossiers[0]) / ("gitingest_veille_%s.txt" % nom)


def _gh_cibles_suivies(doc, docs=None, dossiers=None) -> tuple:
    """(suivies, sans_identite). Une cible n'est SUIVIE que si un dump la nomme.

    2026-09-23 : l'identite se DEDUIT comme le fait le dumper (`charger_cibles` :
    `_NOM_HISTORIQUE` sinon le slug). Lire le seul `nom_dump` BRUT du registre ne
    suivait que 12 cibles sur 342 : llama.cpp, ollama, qdrant, dumpes le soir meme,
    etaient invisibles au capteur. Une cible est suivie si son nom est declare OU
    si le dump `docs/gitingest_veille_<nom>.txt` existe.

    Mesure 2026-08-31 : le registre porte 339 cibles et AUCUNE ne declare de
    `nom_dump`, alors que 12 dumps existent dans `docs/`. Le lien entre les deux
    n'existe pas encore. Surveiller les 339 reviendrait a declarer `UPDATED` tout
    ce que Nokido a cite un jour ; on surveille donc ce qui a une identite de
    dump, et on COMPTE le reste au lieu de le taire.
    """
    cibles = (doc or {}).get("cibles") or {}
    paires = list(cibles.items()) if isinstance(cibles, dict) else [
        (str((c or {}).get("target_id")), c) for c in cibles]
    dossiers = [Path(d) for d in dossiers] if dossiers else _gh_dossiers_dumps(docs)
    try:
        from nokido_agent.tools.forge_veille_clone_ingest import _NOM_HISTORIQUE  # noqa: PLC0415
    except Exception:  # noqa: BLE001  muet-ok: repli sur le slug, meme regle que le dumper
        _NOM_HISTORIQUE = {}
    suivies = []
    for slug, c in paires:
        if not isinstance(c, dict):
            continue
        nom = c.get("nom_dump") or _NOM_HISTORIQUE.get(str(c.get("url", "")).lower(), slug)
        if c.get("nom_dump") or any(
                (d / ("gitingest_veille_%s.txt" % nom)).exists() for d in dossiers):
            suivies.append({**c, "nom_dump": nom, "slug": slug})
    return suivies, len(paires) - len(suivies)


@register_pattern(
    "veille_github_head", interval_sec=3600,
    description="Capteur : les depots suivis ont-ils bouge ? Aucun clone, aucune ingestion.",
    preferred_window=None,
)
def pat_veille_github_head(cibles=None, tete=None, sha_local=None, docs=None,
                           recuperer=None, pilote=None, appel=None) -> dict:
    """PHASE A. HEAD distant -> NO_CHANGE / UPDATED / UNKNOWN, sans cloner.

    Le pattern MESURE SON PROPRE CONTEXTE et le rapporte (`compte`, `pid`) :
    c'est le seul endroit d'ou le compte du daemon est observable, le bac a sable
    ne le voyant pas. Un rapport qui ne dit pas d'ou il parle ne prouve rien.

    `UNKNOWN` ne devient JAMAIS `NO_CHANGE` : un HEAD illisible signifie « je ne
    sais pas si le depot a change ». Et l'etat par depot n'ecrase jamais un
    `last_head_seen` connu avec un echec — un echec ecrit `last_failure`, pas un
    HEAD vide, sinon une panne effacerait la memoire du capteur.
    """
    import getpass
    import json as _j
    import os as _os
    from datetime import datetime as _dt  # noqa: PLC0415
    from datetime import timezone as _tz  # noqa: PLC0415
    contexte = {"pid": _os.getpid()}
    try:
        contexte["compte"] = getpass.getuser()
    except Exception as exc:  # noqa: BLE001
        contexte["compte"] = "ILLISIBLE (%s)" % type(exc).__name__
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_veille_registre import (  # noqa: PLC0415
            NO_CHANGE, UNKNOWN, UPDATED, etat_cible, head_distant, sha_ingere)
    except Exception as exc:  # noqa: BLE001
        return {"skip": "registre indisponible (%s)" % type(exc).__name__, **contexte}
    tete = tete or head_distant
    sha_local = sha_local or sha_ingere
    # None = resolveur unique (docs/ + dossiers hors depot) ; un chemin = injecte.
    docs = Path(docs) if docs else None

    if cibles is None:
        try:
            doc = _j.loads(_GH_REGISTRE.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"skip": "registre illisible (%s)" % type(exc).__name__, **contexte}
        cibles, sans_identite = _gh_cibles_suivies(doc, docs=docs)
    else:
        sans_identite = 0
    try:
        etat = _j.loads(_GH_ETAT.read_text(encoding="utf-8"))
    except FileNotFoundError:
        etat = {}
    except Exception as exc:  # noqa: BLE001
        # ILLISIBLE n'est pas VIDE : repartir a zero perdrait `last_head_seen` de
        # tous les depots, donc la memoire meme du capteur.
        return {"skip": "etat de surveillance illisible (%s)" % type(exc).__name__,
                **contexte}

    # `None` = laisser l'INTENTION decider. Un booleen explicite reste prioritaire
    # (tests, appel manuel) et court-circuite le drapeau.
    critiques = None
    if recuperer is None:
        recuperer, raison_intention = _gh_intention()
        if not recuperer:
            critiques, raison_crit = _gh_intention_critiques()
            raison_intention = "%s ; %s" % (raison_intention, raison_crit)
    else:
        raison_intention = "force par l'appelant"
    a_faire, differees = cibles[:_GH_MAX_PAR_TOUR], max(0, len(cibles) - _GH_MAX_PAR_TOUR)
    candidats_rec: list = []
    compte_etats = {NO_CHANGE: 0, UPDATED: 0, UNKNOWN: 0}
    detail = []
    maintenant = _dt.now(_tz.utc).isoformat(timespec="seconds")
    for c in a_faire:
        tid = str(c.get("target_id") or c.get("repo") or "?")
        dump = _gh_dump(docs, c.get("nom_dump"))
        sha_vu, raison_tete = tete(c.get("url"))
        ingere = sha_local(dump)
        verdict, raison = etat_cible(sha_vu, ingere)
        compte_etats[verdict] = compte_etats.get(verdict, 0) + 1
        e = dict(etat.get(tid) or {})
        e["repo"] = c.get("repo")
        e["last_check"] = maintenant
        e["last_head_ingested"] = ingere        # miroir du MANIFESTE, pas une source
        if sha_vu:
            e["last_head_seen"] = sha_vu
            e["last_success"] = maintenant
        else:
            # On n'ecrase PAS `last_head_seen` : une panne ne doit pas effacer ce
            # que le capteur savait avant elle.
            e["last_failure"] = maintenant
            e["last_failure_raison"] = raison_tete
        ligne = {"repo": c.get("repo"), "etat": verdict, "raison": raison,
                 "sha_vu": (sha_vu or "")[:12] or None,
                 "sha_ingere": (ingere or "")[:12] or None}
        # PHASE B, sur le SEUL depot pilote et sur opt-in explicite. Le premier
        # tour des 12 provoquerait 12 UPDATED donc 12 clones : on mesure le cout
        # sur un depot de 9,5 Ko avant d'ouvrir.
        # PHASE B : on COLLECTE ici, on recupere APRES. Recuperer dans la boucle
        # de detection lierait l'ordre des clones a celui du registre, alors que
        # le cout, lui, se MESURE (taille du dump deja sur disque).
        autorise = recuperer or bool(critiques and (
            {str(c.get("nom_dump")), str(c.get("slug")), tid} & critiques))
        if autorise and verdict == UPDATED and (
                pilote is None or c.get("nom_dump") == pilote):
            candidats_rec.append({"cible": c, "sha": sha_vu, "tid": tid,
                                  "ligne": ligne})
        etat[tid] = e
        detail.append(ligne)

    # ── PHASE B, capee et ordonnee ──────────────────────────────────────────
    differees_rec = 0
    if candidats_rec:
        ordonnes = sorted(candidats_rec,
                          key=lambda x: _gh_cle_recuperation(x["cible"], docs, etat))
        differees_rec = max(0, len(ordonnes) - _GH_MAX_RECUPERATIONS_PAR_TOUR)
        # COMPTEUR DE FAMINE. Sans lui, « differee » ne dit pas depuis COMBIEN de
        # tours : une cible ecartee dix fois se lit comme une cible ecartee une
        # fois, et l'inequite reste invisible.
        for x in ordonnes[_GH_MAX_RECUPERATIONS_PAR_TOUR:]:
            e3 = etat.get(x["tid"]) or {}
            e3["deferred_count"] = int(e3.get("deferred_count") or 0) + 1
            etat[x["tid"]] = e3
        for x in ordonnes[:_GH_MAX_RECUPERATIONS_PAR_TOUR]:
            rec = _gh_recuperer(x["cible"], x["sha"], docs, appel=appel)
            x["ligne"]["recuperation"] = rec.get("etat")
            x["ligne"]["recuperation_raison"] = rec.get("raison")
            e2 = etat.get(x["tid"]) or {}
            e2["last_recovery"] = maintenant
            e2["last_recovery_etat"] = rec.get("etat")
            if rec.get("etat") == REC_SUCCESS:
                # SEUL endroit ou `last_head_ingested` avance, et seulement apres
                # que le manifeste a ete relu au bon commit.
                e2["last_head_ingested"] = rec.get("sha_manifeste")
                # TENTATIVE et SUCCES sont deux dates distinctes : une cible
                # tentee dix fois sans succes se lirait « servie recemment » si
                # l'on n'avait que la premiere.
                e2["last_recovery_success"] = maintenant
                e2["deferred_count"] = 0
            # Un echec de PHASE B ne touche NI `last_head_seen` NI
            # `last_head_ingested` : le capteur doit continuer de savoir que le
            # depot a avance meme quand l'actionneur n'a pas suivi. On ne declare
            # JAMAIS un depot a jour pour vider le backlog.
            etat[x["tid"]] = e2
    filigrane = "ecrit"
    if a_faire:
        try:
            _GH_ETAT.parent.mkdir(parents=True, exist_ok=True)
            _GH_ETAT.write_text(_j.dumps(dict(list(etat.items())[-_GH_MEMOIRE:]),
                                         ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            filigrane = "NON ecrit (%s)" % type(exc).__name__
    return {**contexte,
            "cibles_examinees": len(a_faire),
            "sans_identite_dump": sans_identite,
            "differees_par_cap": differees,
            "NO_CHANGE": compte_etats[NO_CHANGE],
            "UPDATED": compte_etats[UPDATED],
            "UNKNOWN": compte_etats[UNKNOWN],
            # PHASE B : ce qui a REELLEMENT ete tente. Un `UPDATED` ne dit rien
            # de la recuperation, et le taire ferait conclure que la matiere a
            # ete rapatriee.
            # « hors pilote » datait de l'epoque ou la recuperation etait gardee
            # par identite. Avec un cap, une cible non retenue est DIFFEREE ; une
            # cible qui n'a pas bouge est SANS OBJET. Confondre les deux ferait
            # lire un backlog la ou il n'y a rien a faire.
            "recuperation": ("non demandee" if not recuperer else
                             {d["repo"]: d.get("recuperation")
                              or ("differee" if d["etat"] == UPDATED else "sans objet")
                              for d in detail}),
            "pilote": pilote,
            "recuperations_differees": differees_rec,
            "cap_recuperations": _GH_MAX_RECUPERATIONS_PAR_TOUR,
            "intention": raison_intention,
            "etat_surveillance": filigrane,
            "detail": detail}


_M2M_ETAT = ROOT / "sandbox" / "m2m_debate_relay.json"
_M2M_PAIR = "ANTIGRAVITY"
# Cadence : garde anti-emballement, PAS un delai d'attente. Le rejeu d'un meme
# courrier est deja empeche par 'dernier_mail' ; cette borne ne protege donc que
# d'un pair bavard. Une heure rendait la boucle inerte alors qu'elle avait deja
# la reponse — 10 min suffisent a proteger le budget sans tuer la reactivite.
_M2M_CADENCE_S = 600
_M2M_BACKTEST_N = 20           # bornes explicites : jamais de coupe silencieuse


def _m2m_etat() -> dict:
    try:
        return json.loads(_M2M_ETAT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _m2m_ecrit_etat(d: dict) -> None:
    try:
        _M2M_ETAT.parent.mkdir(parents=True, exist_ok=True)
        _M2M_ETAT.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.warning(f"[m2m_debate_relay] etat non sauvegarde ({e}) — le meme courrier "
                    f"pourra relancer un tour au prochain tick")


def _frames_du_pair(wm: str) -> list:
    """Frames brutes du pair (table agent_messages), au-dela du watermark.

    Seul endroit ou l'on touche encore au SQL : c'est le POINT D'ENTREE d'un
    transport que le postal ne connait pas. Tout le reste du flux passe ensuite
    par le facteur et le secretaire.
    """
    base = ("SELECT id, payload, created_at FROM agent_messages WHERE "
            "upper(from_agent) LIKE '%ANTIGRAV%' AND lower(to_agent) IN "
            "('agt_claude','claude') ")
    try:
        c = sqlite3.connect(m2m_path(), timeout=5)
        if wm:
            r = c.execute(base + "AND datetime(created_at) > datetime(?) "
                                 "ORDER BY datetime(created_at)", (wm,)).fetchall()
        else:   # 1er passage : le dernier message, pas tout l'historique
            r = c.execute(base + "ORDER BY datetime(created_at) DESC LIMIT 1").fetchall()
        c.close()
        return r
    except Exception:  # noqa: BLE001
        return []


@register_pattern(
    "m2m_debate_relay",
    interval_sec=300,
    description="Actionneur M2M : livre le courrier en gare, releve l'inbox CLAUDE, "
                "et relance un tour de debat + backtest quand le pair a repondu.",
    preferred_window=None,
)  # 24/7 — la conversation ne dort pas plus que le pair
def pat_m2m_debate_relay() -> dict:
    """ACTIONNEUR, la ou m2m_inbox_watch n'est qu'un CAPTEUR.

    Trois gestes, chacun rendant compte de son echec :
      1. LIVRER   — facteur() sur chaque canal qui a du courrier en gare ;
      2. RELEVER  — secretaire() sur l'inbox CLAUDE ;
      3. RELANCER — si le pair a ecrit depuis le dernier tour : backtest local
         (0 LLM, chiffre) + arene detachee, puis on lui poste le resultat.

    Garde-fous : cadence bornee, et le dernier courrier traite est memorise —
    un meme message ne relance jamais deux tours.
    """
    sys.path.insert(0, str(ROOT))
    out: dict = {"livres": 0, "canaux": [], "reponses_pair": 0, "relance": None}
    try:
        from nokido_agent.app.forge_postal import channels_with_pending, facteur, post, secretaire
    except Exception as e:  # noqa: BLE001
        return {"error": f"postal indisponible: {e}"}

    for ch in (channels_with_pending() or []):
        try:
            n = len((facteur(ch) or {}).get("delivered") or [])
            out["livres"] += n
            out["canaux"].append({ch: n})
        except Exception as e:  # noqa: BLE001
            out.setdefault("echecs_livraison", []).append(f"{ch}: {str(e)[:80]}")

    # PONT FRAMES -> POSTAL. Le pair ecrit des FRAMES (frm_*, table agent_messages)
    # alors que le facteur et le secretaire ne connaissent que le COURRIER (mail_*).
    # Plutot que de lire deux files a la main, on VERSE chaque frame nouvelle dans le
    # postal (dedup_key = id de la frame -> INSERT OR IGNORE, donc idempotent) : le
    # SECRETAIRE redevient l'unique surface de lecture et le facteur le seul livreur.
    wm = _m2m_etat().get("dernier_frame_ts") or ""
    frames = _frames_du_pair(wm)
    out["watermark_lu"] = wm or "(premier passage)"
    out["frames_pair"] = len(frames)
    verses = 0
    for _fid, _payload, _cree in frames:
        try:
            _txt = json.loads(_payload).get("text") or _payload
        except Exception:  # noqa: BLE001
            _txt = str(_payload)
        try:
            _r = post(_M2M_PAIR, "CLAUDE", str(_txt)[:4000], dedup_key=_fid)
            facteur(_r.get("recipient_channel", ""))
            verses += 0 if _r.get("duplicate") else 1
        except Exception as e:  # noqa: BLE001
            out.setdefault("pont_erreurs", []).append(f"{_fid}: {str(e)[:80]}")
    out["frames_versees_au_postal"] = verses

    # LECTURE PAR LE SECRETAIRE — avec include_acked=True, ET NOTRE PROPRE WATERMARK.
    # Lecon apprise DEUX FOIS le meme jour : d'abord le hook d'inbox marquait les
    # frames 'read' avant nous, puis le hook d'auto-surface a marque le courrier
    # 'acked' avant nous. Tout etat PARTAGE (unread, acked) est vole par le premier
    # lecteur ; seul un curseur qui nous appartient survit a la concurrence. On ack
    # quand meme (courtoisie envers l'emetteur), mais on ne s'y FIE pas.
    postal_wm = float(_m2m_etat().get("dernier_postal_ts") or 0)
    boite = []
    for ident in ("CLAUDE", "agt_claude"):
        try:
            boite += secretaire(ident, ack=True, include_acked=True) or []
        except Exception as e:  # noqa: BLE001
            out.setdefault("inbox_error", []).append(f"{ident}: {str(e)[:80]}")
    boite = [m for m in boite if float(m.get("ts_delivered") or 0) > postal_wm]
    out["identites_relevees"] = ["CLAUDE", "agt_claude"]
    out["postal_watermark_lu"] = postal_wm

    def _exp(m: dict) -> str:
        return str(m.get("sender") or m.get("from_agent") or m.get("from") or "").upper()

    # ⚠️ Le WATERMARK reste la garde anti-rejeu : le hook d'inbox de session marque
    # les frames 'read' des qu'il les affiche, donc filtrer sur 'unread' ferait rater
    # tout message qu'un autre consommateur a vu avant nous (piege vecu le 13/08).
    du_pair = [m for m in boite if _M2M_PAIR in _exp(m)]
    out["reponses_pair"] = len(du_pair)
    if not du_pair:
        return out

    etat = _m2m_etat()
    dernier = str(du_pair[-1].get("id") or "")
    if dernier and dernier == etat.get("dernier_mail"):
        out["relance"] = "courrier deja traite"
        return out
    age = time.time() - float(etat.get("ts_relance") or 0)
    if age < _M2M_CADENCE_S:
        out["relance"] = f"cadence: prochain tour dans {int(_M2M_CADENCE_S - age)}s"
        return out

    # 3a. MESURE locale d'abord : elle ne depend d'aucun cloud et chiffre le debat.
    chiffres = {}
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools import forge_axis_backtest as B

        commits = B.commits_de_correction("2026-05-01", _M2M_BACKTEST_N)
        for axe in B.AXES:
            r = B.backtest(axe, commits)
            chiffres[axe] = {"rappel_pct": r["rappel_pct"],
                             "hors_cible_pct": r["bruit_hors_cible_pct"],
                             "juges": r["commits_juges"], "rates": len(r["RATES"])}
    except Exception as e:  # noqa: BLE001
        chiffres = {"erreur_backtest": str(e)[:140]}

    # 3b. ARENE detachee : un tour de debat ne doit jamais bloquer le tick.
    try:
        subprocess.Popen(
            [sys.executable, str(ROOT / "tools" / "forge_m2m_debate_antiregression.py"),
             "--rounds", "2"],
            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW)
        out["arene"] = "lancee"
    except Exception as e:  # noqa: BLE001
        out["arene"] = f"non lancee: {str(e)[:100]}"

    # 3c. On repond au pair : la mesure d'abord, la promesse ensuite.
    # Le postal est LIVRE mais PAS LU par ce pair (4 tours, 0 accuse de reception) :
    # la reponse part donc AUSSI sur le tableau noir, seul canal ou il a lu et repondu.
    try:
        from nokido_agent.app.forge_swarm_blackboard import apply_fact_sync

        # `get_blackboard` n'a jamais existe : ce relai finissait toujours en "echec".
        _r = apply_fact_sync(
            "discovered_facts",
            json.dumps({"de": "CLAUDE", "pour": _M2M_PAIR, "tour": "relai autonome",
                        "mesures": chiffres,
                        "note": "backtest relance a la reception de ton message ; "
                                "les commits RATE sont les regressions qu aucun axe ne voit"},
                       ensure_ascii=False),
            category="debat", trust=0.8,
            key=f"debat_relai_auto_{int(time.time())}", source="autonomous_loops", ring=2)
        out["blackboard"] = ("poste" if _r.get("ok") else "planifie (demande, pas atteint)"
                             if _r.get("planifie") else f"echec: {str(_r)[:90]}")
    except Exception as e:  # noqa: BLE001
        out["blackboard"] = f"echec: {str(e)[:90]}"
    try:
        r = post("CLAUDE", _M2M_PAIR,
                 "[RELAI AUTONOME] Ton message a ete relev. Mesure du tour, backtest sur "
                 f"{_M2M_BACKTEST_N} commits de correction (un axe ne compte que s'il pointait "
                 f"une ligne REPAREE par le fix) :\n{json.dumps(chiffres, ensure_ascii=False)}\n"
                 "Arene relancee en detache, 2 tours. Les commits listes RATE sont les "
                 "regressions qu'AUCUN axe ne voit : ce sont eux qui dictent les axes a creer.")
        facteur(r.get("recipient_channel", ""))
        out["relance"] = {"mail": r.get("id"), "chiffres": chiffres}
    except Exception as e:  # noqa: BLE001
        out["relance"] = f"reponse non postee: {str(e)[:120]}"

    # Les frames traitees sont marquees LUES : sans cela le meme courrier
    # relancerait un tour a chaque tick, et la cadence ne serait plus qu'un
    # pansement sur une boucle qui se re-declenche toute seule.
    if frames:
        try:
            _c = sqlite3.connect(m2m_path(), timeout=5)
            _c.execute("PRAGMA busy_timeout=5000")
            _c.executemany(
                "UPDATE agent_messages SET status='read', read_at=datetime('now') WHERE id=?",
                [(f[0],) for f in frames])
            _c.commit()
            _c.close()
            out["frames_acquittees"] = len(frames)
        except Exception as e:  # noqa: BLE001
            out["frames_acquittees"] = f"echec: {str(e)[:80]}"

    # COMPTE RENDU VERS LA SESSION. La boucle tourne sans Claude eveille — mais
    # l'owner, lui, devait DEMANDER « verifie ». On depose donc un digest dans la
    # boite de CLAUDE : le hook d'auto-surface l'injecte dans la session des le
    # prochain appel d'outil, sans polling ni monitor cote client.
    try:
        r2 = post("RELAI_M2M", "CLAUDE",
                  f"[RELAI AUTONOME] Message du pair traite sans intervention. "
                  f"Mesure du tour : {json.dumps(chiffres, ensure_ascii=False)[:600]}. "
                  f"Arene : {out.get('arene')}. Reponse envoyee : {out.get('relance')}.")
        facteur(r2.get("recipient_channel", ""))
        out["compte_rendu_session"] = r2.get("id")
    except Exception as e:  # noqa: BLE001
        out["compte_rendu_session"] = f"echec: {str(e)[:80]}"

    _m2m_ecrit_etat({"dernier_mail": dernier, "ts_relance": time.time(),
                     "chiffres": chiffres,
                     # les deux curseurs avancent meme si un autre lecteur a deja
                     # acquitte a notre place : ils nous appartiennent
                     "dernier_frame_ts": max((f[2] for f in frames), default=wm),
                     "dernier_postal_ts": max(
                         (float(m.get("ts_delivered") or 0) for m in du_pair),
                         default=postal_wm)})
    return out


@register_pattern(
    "epistemic_consolidation",
    interval_sec=3600,
    description=(
        "Consolidation epistemique (hippocampe) : extrait les assertions des chunks "
        "recents avec le LLM LOCAL, juge les contradictions, FERME les assertions "
        "remplacees (superseder) et PROMEUT les brouillons corrobores. Emetteur des "
        "primitives qui dormaient depuis leur ecriture (mesure 2026-08-26 : 0 claim, "
        "0 reevaluation, 0 appelant)."
    ),
    requires_local_llm=True,
    preferred_window=None,
)
def pat_epistemic_consolidation() -> dict:
    """Trois etats dans le compte-rendu : extrait / rien a extraire / LLM muet.
    Un LLM muet n'est jamais compte comme « aucune assertion »."""
    import os as _os

    if not _local_llm_available():
        return {"skipped": "no_local_llm"}
    if not _ram_gate(float(_os.environ.get("LAFORGE_EPISTEMIC_RAM_GB", "5")), "epistemic_consolidation"):
        return {"skipped": "ram_gate"}
    # LE PATTERN LE PLUS OBSERVE DANS LES MORTS DU DAEMON. Mesure du 2026-08-31 :
    # quatre des cinq morts instrumentees sont survenues ICI, bloquees de 921 a
    # 1669 s, et dans les cinq cas `gap_s == pattern_running_for_s` — l'instance
    # est entree dans le pattern, a battu une derniere fois, et n'en est jamais
    # ressortie.
    #
    # CAUSE STRUCTURELLE : `consolider` appelle Ollama en LOCAL (120 s par lot,
    # 20 lots) et son repli Cerebras est OPT-IN par contrat (regle owner « pas de
    # cloud »). Sur fournisseur mort il n'a donc AUCUNE issue : il attend.
    # S'abstenir ne prive ici d'aucun chemin de travail — c'est pourquoi ce n'est
    # pas un changement silencieux de fournisseur.
    # SERVICE_UP NE SUFFIT PAS ICI, et c'est une regression que j'ai OUVERTE le
    # 2026-08-31 en corrigeant `-` (non sonde) pour qu'il cesse de valoir « en
    # panne ». Cette correction est juste, mais elle a leve une abstention qui
    # PROTEGEAIT par accident : tant qu'ollama etait range en `-`, ce pattern
    # s'abstenait et le daemon survivait. Des qu'il est repasse a 200, le garde a
    # laisse passer -- et le daemon est mort en 65 s, sur ce pattern, exactement
    # comme les quatre morts instrumentees precedentes.
    #
    # Le releve de sante atteste que le PORT repond ; il ne dit RIEN du modele.
    # Mesure du meme jour : `_fournisseur_pret('ollama')` -> True pendant que
    # `/api/ps` rendait `{"models":[]}`. Le premier appel paie alors le
    # chargement a froid (>55 s pour un 7B) et monopolise un tick de 60 s.
    # On exige donc MODEL_READY, avec la meme primitive que le digest.
    try:
        from nokido_agent.app.forge_veille_digest import etat_provider as _etat_prov  # noqa: PLC0415
        from nokido_agent.app.forge_veille_digest import sonde_ollama as _sonde_ol  # noqa: PLC0415
        _tools = str(ROOT / "tools")
        if _tools not in sys.path:
            sys.path.insert(0, _tools)
        from nokido_agent.tools.forge_epistemic_extract_claims import MODELE_LOCAL as _mod_epi
        _etat, _, _raison = _etat_prov("ollama", None, sonde_locale=_sonde_ol(),
                                       modele_local=_mod_epi)
    except Exception as exc:  # noqa: BLE001
        # Ne pas conclure a « pret » sur une sonde qu'on n'a pas pu faire.
        _etat, _raison = "UNKNOWN", "sonde du modele local IMPOSSIBLE (%s)" % type(exc).__name__
    if _etat != "READY":
        return {"skipped": "fournisseur_indisponible", "etat_modele": _etat,
                "raison": _raison,
                "note": "aucun lot consomme, la matiere reste entiere"}
    try:
        tools_dir = str(ROOT / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        from nokido_agent.tools.forge_epistemic_extract_claims import consolider

        return consolider(limit=int(_os.environ.get("LAFORGE_EPISTEMIC_BATCH", "20")))
    except Exception as e:
        return {"error": str(e)[:300]}


def run_due_patterns(force: bool = False) -> list[dict]:
    """Scan + execute patterns dont interval écoulé ET dans fenêtre circadienne."""
    _ensure_schema()
    now = time.time()
    results = []
    skipped_circadian = 0
    for name, pat in PATTERNS.items():
        if not pat.enabled:
            continue
        last = _last_run(name)
        elapsed = now - last
        if not force and elapsed < pat.interval_sec:
            continue
        # Circadian gate : respecte fenêtre cognitive sauf si force
        if not force and not _in_preferred_window(pat.preferred_window):
            skipped_circadian += 1
            continue
        log.info(
            f"[run] {name} (interval {pat.interval_sec}s, last {int(elapsed)}s ago, window {pat.preferred_window})"
        )
        # AVANT l'appel : si l'instance meurt ici, le pouls porte deja le nom.
        _pouls_marquer(current_pattern=name,
                       pattern_started_at=_iso_maintenant())
        t0 = time.time()
        try:
            outcome = pat.fn()
            status = "ok"
            details = outcome
        except Exception as e:
            outcome = f"exception: {e}"
            status = "fail"
            details = {"error": str(e)}
        dt_ms = int((time.time() - t0) * 1000)
        # TERMINE, quel que soit le statut : une exception attrapee est un retour.
        # `current_pattern` repasse a None — sans quoi le prochain diagnostic
        # accuserait ce pattern d'une mort survenue bien plus tard.
        _pouls_marquer(current_pattern=None,
                       last_completed_pattern=name,
                       last_completed_at=_iso_maintenant(),
                       last_completed_duration_s=round(dt_ms / 1000.0, 1))
        _log_run(name, status, str(outcome)[:300], details)
        results.append({"pattern": name, "status": status, "duration_ms": dt_ms, "outcome": str(outcome)[:200]})
    return results


def status() -> dict:
    """État de tous les patterns."""
    _ensure_schema()
    out = {"patterns": [], "total": len(PATTERNS)}
    try:
        conn = sqlite3.connect(str(DB))
        for name, pat in PATTERNS.items():
            row = conn.execute(
                "SELECT last_run, last_status, runs_total, runs_success FROM autonomous_loop_state WHERE pattern=?",
                (name,),
            ).fetchone()
            entry = {
                "name": name,
                "interval_sec": pat.interval_sec,
                "description": pat.description,
                "requires_local_llm": pat.requires_local_llm,
                "preferred_window": list(pat.preferred_window) if pat.preferred_window else None,
                "in_window_now": _in_preferred_window(pat.preferred_window),
                "enabled": pat.enabled,
                "last_run": row[0] if row else 0,
                "last_status": row[1] if row else None,
                "runs_total": row[2] if row else 0,
                "runs_success": row[3] if row else 0,
            }
            if row and row[0]:
                entry["age_minutes"] = round((time.time() - row[0]) / 60, 1)
                entry["due_in_seconds"] = max(0, int(pat.interval_sec - (time.time() - row[0])))
            out["patterns"].append(entry)
        conn.close()
    except Exception as e:
        out["error"] = str(e)
    return out


# ══════════════════════════════════════════════════════════════════════
# Daemon mode
# ══════════════════════════════════════════════════════════════════════
# ── MESURER LES RESPAWNS ──────────────────────────────────────────────────────
# MESURE 2026-08-31 : ce daemon a demarre 34 fois dans la journee et 2 984 fois
# dans l'historique du journal, parfois a 3 secondes d'intervalle — pendant que
# le superviseur affichait `restarts: 0`. Ses morts ne laissent aucune ligne :
# 120 `Traceback` et 114 `shutdown` pour 2 984 demarrages.
#
# CE MODULE NE CORRIGE RIEN. Il rend la serie MESURABLE, ce qui est le prealable
# de tout correctif : sans denominateur, on ne saura jamais si une politique de
# redemarrage future ameliore quoi que ce soit.
_POULS_DAEMON = ROOT / "sandbox" / "autonomous_loops.heartbeat"
# Un pouls plus recent que ceci appartient vraisemblablement a une instance qui
# tourne ENCORE. Trois ticks de 60 s : assez pour couvrir un tick lent, assez peu
# pour ne pas crier au recouvrement sur un pouls d'il y a une heure.
_DEMARRAGE_FRAICHEUR_S = 180.0


# ── LE POULS PORTE LE TRAVAIL EN COURS ────────────────────────────────────────
# MESURE 2026-08-31 : sur 32 transitions naturelles, 27 restent sans cause. Le
# diagnostic de demarrage sait DEJA dire qui etait la avant ; il ne sait pas dire
# CE QU'ELLE FAISAIT. Ce trou-la, et lui seul, est comble ici.
#
# ORDRE D'ECRITURE, non negociable : `current_pattern` s'ecrit AVANT l'appel.
# L'ecrire apres laisserait le champ vide precisement dans le cas qui nous
# interesse — une mort PENDANT le pattern.
#
# DEUX CHAMPS DISTINCTS, jamais un seul : `current_pattern` (en cours, remis a
# None au retour) et `last_completed_pattern` (termine). Les confondre rendrait
# indiscernables « il est mort dedans » et « il l'avait fini il y a dix ticks ».
_POULS_ETAT: dict = {}


def _iso_maintenant() -> str:
    """Meme format que `forge_heartbeat` : un pouls qui melange deux formats
    d'horodatage devient illisible pour son propre lecteur."""
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _pouls_marquer(**champs) -> bool:
    """Enrichit et reecrit le pouls EXISTANT. Hors daemon, ne fait RIEN.

    Le garde `if not _POULS_ETAT` est deliberate : `run_due_patterns` est aussi
    appele par le CLI (`--run`) et par les tests, ou ecrire un pouls ferait
    croire le superviseur a un daemon vivant qui ne l'est pas.
    """
    if not _POULS_ETAT:
        return False
    _POULS_ETAT.update(champs)
    try:
        from nokido_agent.app.forge_heartbeat import beat_daemon  # noqa: PLC0415
        return bool(beat_daemon("autonomous_loops", **_POULS_ETAT))
    except Exception as exc:  # noqa: BLE001
        # muet-ok : un pouls qui casse son porteur serait pire que pas de pouls,
        # et l'echec est deja visible par le figement du fichier lui-meme.
        log.debug("pouls non ecrit (%s)", type(exc).__name__)
        return False


def _borner(fn, budget_s: float, defaut=None):
    """(valeur, depasse) — execute `fn` et REND LA MAIN au budget.

    POURQUOI un thread et pas un timeout d'appel : `forge_endpoint_monitor.monitor`
    n'expose aucun budget total. Ses requetes sont bornees a 12 s CHACUNE, ce qui
    ne borne rien globalement — la mort instrumentee de `health_check` a dure
    699 s. On ne reecrit pas le moniteur : on borne sa contribution au tick.

    Le thread survit au depassement (Python ne peut pas tuer un thread bloque en
    I/O) et il est demon : il ne retient pas l'interpreteur. Ce qui est garanti
    ici, c'est que LE TICK reprend, pas que l'appel s'arrete.
    """
    import threading  # noqa: PLC0415
    boite = {}

    def _cible():
        try:
            boite["v"] = fn()
        except Exception as exc:  # noqa: BLE001
            boite["e"] = exc

    th = threading.Thread(target=_cible, daemon=True, name="borne")
    th.start()
    th.join(budget_s)
    if th.is_alive():
        return defaut, True
    if "e" in boite:
        raise boite["e"]
    return boite.get("v", defaut), False


def _pid_vivant(pid):
    """True / False / None. `None` = on n'a PAS PU savoir, et ca compte.

    Sans cette troisieme valeur, un `psutil` absent ferait passer une instance
    vivante pour morte, donc un recouvrement pour une reprise propre.
    """
    try:
        import psutil  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    try:
        return psutil.pid_exists(int(pid))
    except Exception:  # noqa: BLE001
        return None


def diagnostic_demarrage(pouls, pid_courant: int, patterns: int, vivant=None,
                         maintenant=None, fraicheur: float = _DEMARRAGE_FRAICHEUR_S) -> dict:
    """Ce que le demarrage peut DIRE, et STRICTEMENT rien de plus.

    LA REGLE : on ne deduit JAMAIS la cause d'une mort de l'absence d'un pouls.
    Pas de pouls precedent ne veut pas dire « crash » — ca veut dire qu'on ne
    sait pas, et le motif est alors `NEW_START`.

    Motifs, tous adosses a une observation :
      NEW_START          aucun pouls precedent lisible, ou pouls sans pid
      SAME_PID           le pouls porte le pid courant (aucune transition)
      OVERLAP_SUSPECTED  le pouls vient d'un AUTRE pid qui est ENCORE VIVANT
      RECOVERY           le pouls vient d'un autre pid, mesure comme disparu
      INDETERMINE        autre pid, mais on n'a pas pu verifier s'il vit
    """
    now = time.time() if maintenant is None else float(maintenant)
    out = {"pid": int(pid_courant), "patterns": int(patterns),
           "previous_pid": None, "previous_pulse": None,
           "previous_patterns": None, "gap_s": None,
           "previous_current_pattern": None,
           "previous_pattern_started_at": None,
           "pattern_running_for_s": None}
    if not isinstance(pouls, dict):
        return {**out, "startup_reason": "NEW_START",
                "detail": "aucun pouls precedent lisible"}
    out["previous_pid"] = pouls.get("pid")
    out["previous_patterns"] = pouls.get("patterns")
    out["previous_pulse"] = pouls.get("ts")
    out["previous_current_pattern"] = pouls.get("current_pattern")
    out["previous_pattern_started_at"] = pouls.get("pattern_started_at")
    # Duree CALCULEE a la lecture, jamais persistee : une duree ecrite avant la
    # mort serait fausse de tout le temps ecoule depuis. `None` quand
    # l'horodatage est illisible ou qu'aucun pattern n'etait en cours.
    if out["previous_current_pattern"]:
        try:
            from datetime import datetime as _d2  # noqa: PLC0415
            out["pattern_running_for_s"] = round(
                now - _d2.fromisoformat(str(out["previous_pattern_started_at"])).timestamp(), 1)
        except Exception:  # noqa: BLE001
            out["pattern_running_for_s"] = None
    # L'horodatage peut etre illisible : le gap vaut alors None, JAMAIS zero.
    # Un gap a zero ferait croire a une transition instantanee.
    try:
        from datetime import datetime as _dt  # noqa: PLC0415
        out["gap_s"] = round(now - _dt.fromisoformat(str(pouls.get("ts"))).timestamp(), 1)
    except Exception:  # noqa: BLE001
        out["gap_s"] = None
    ppid = out["previous_pid"]
    if ppid is None:
        return {**out, "startup_reason": "NEW_START", "detail": "pouls sans pid"}
    if int(ppid) == int(pid_courant):
        return {**out, "startup_reason": "SAME_PID",
                "detail": "le pouls porte deja le pid courant"}
    etat = (vivant or _pid_vivant)(ppid)
    if etat is None:
        return {**out, "startup_reason": "INDETERMINE",
                "detail": "pid precedent %s : vitalite non verifiable" % ppid}
    if etat:
        recent = out["gap_s"] is None or out["gap_s"] <= fraicheur
        return {**out, "startup_reason": "OVERLAP_SUSPECTED",
                "detail": "pid precedent %s ENCORE VIVANT%s" % (
                    ppid, "" if recent else " (pouls ancien)")}
    return {**out, "startup_reason": "RECOVERY",
            "detail": "pid precedent %s disparu ; cause NON etablie" % ppid}


def _pouls_precedent(chemin=None):
    """Le pouls laisse par l'instance d'avant, ou None si illisible."""
    import json as _j
    try:
        return _j.loads(Path(chemin or _POULS_DAEMON).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None                # muet-ok : l'absence est un cas NOMME (NEW_START)


def daemon_loop(tick_sec: int = 60):
    """Boucle infinie : scan patterns toutes les `tick_sec` secondes."""
    log.info(
        f"🔁 [autonomous_loops] daemon start, tick={tick_sec}s, patterns={len(PATTERNS)}, free_local_llms_only=True"
    )
    # Le pouls precedent est lu AVANT que le notre ne l'ecrase : c'est la seule
    # fenetre ou l'on sait encore ce que l'instance d'avant faisait.
    _diag = diagnostic_demarrage(_pouls_precedent(), os.getpid(), len(PATTERNS))
    log.info("[autonomous_loops] startup_reason=%s pid=%s previous_pid=%s "
             "previous_pulse=%s previous_patterns=%s gap_s=%s "
             "last_known_pattern=%s pattern_running_for_s=%s — %s",
             _diag["startup_reason"], _diag["pid"], _diag["previous_pid"],
             _diag["previous_pulse"], _diag["previous_patterns"],
             _diag["gap_s"], _diag["previous_current_pattern"],
             _diag["pattern_running_for_s"], _diag["detail"])
    _POULS_ETAT.update({"patterns": len(PATTERNS), "interval_s": tick_sec})
    _anchor(
        problem="Boucle évolutive autonome démarrée",
        solution=f"daemon tick={tick_sec}s patterns={list(PATTERNS.keys())}",
        example="Nokido auto-orchestre tools/knowledge/code via patterns récurrents",
    )
    # `services.toml` declare heartbeat = "sandbox/autonomous_loops.heartbeat" et le
    # superviseur le scrute — mais AUCUN module n'ecrivait ce fichier. Mesure 2026-08-02 :
    # pouls fige a 12:10:47, soit AVANT le redemarrage de la machine, pendant que le
    # service tournait depuis 7 min et etait declare `running`. Capteur declare, garde
    # arme, zero emetteur : la mort de ce daemon etait silencieuse par construction.
    from nokido_agent.app.forge_heartbeat import beat_daemon  # UN seul chemin (39 reimplementations recensees)

    while True:
        try:
            results = run_due_patterns()
            if results:
                log.info(f"[tick] {len(results)} patterns ran")
            # APRES le cycle, jamais au demarrage : le pouls atteste du TRAVAIL et non de
            # l'existence (contrat de beat_daemon). Un tour qui echoue laisse donc le pouls
            # geler et le superviseur releve le daemon — c'est voulu, pas un effet de bord.
            # Passe par `_pouls_marquer` pour ne pas EFFACER `last_completed_*` :
            # un beat qui n'ecrirait que patterns/interval_s perdrait a chaque
            # tick la trace du travail, donc l'information qu'on vient d'ajouter.
            _pouls_marquer(current_pattern=None)
        except KeyboardInterrupt:
            log.info("interrupted")
            break
        except Exception as e:
            log.error(f"[tick] error: {e}")
        time.sleep(tick_sec)


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════

@register_pattern(
    "self_improvement_watch",
    interval_sec=3600,
    description=(
        "Consomme les diagnostics que PERSONNE ne lisait : faits self_care du demon "
        "epistemique, effecteurs qui POMPENT, ecart a la direction voulue."
    ),
    preferred_window=None,
)  # 24/7 - local, 0 LLM, non destructif
def pat_self_improvement() -> dict:
    """Ferme la boucle d'auto-amelioration : DIAGNOSTIC -> CONSOMMATION.

    Mesure 2026-07-30, et c'est la raison d'etre de ce pattern : le corps produisait
    trois diagnostics que personne ne lisait.
      * `self_care` (« SOIN requis », RAM au seuil P1, services DOWN) : **1 ecrivain,
        0 lecteur**. Le demon epistemique diagnostiquait dans le vide.
      * `forge_regulation_efficacy` : verdicts POMPE, aucun consommateur hors le
        reclaimer qui n'en lit que la refractaire.
      * `forge_gap_direction` : **0 appelant**. Un outil lance a la main par un client
        n'est pas de l'auto-amelioration.
    Un diagnostic que rien ne consomme est un diagnostic qui n'existe pas -- symetrique
    exact du garde branche sur un signal sans emetteur (RULES_SHARED, 2026-07-30).

    Non destructif, local, 0 LLM : il CORRELE et rend visible. La correlation est le
    seul apport qu'aucune des trois sources ne peut produire seule -- un defaut
    `self_care` qui persiste PENDANT qu'un effecteur pompe sur le meme organe, c'est un
    symptome qu'on traite sans le soigner, et c'est precisement ce qui s'est passe avec
    llama-server:8091 (73 arrets, 312,94 Go, RAM toujours au seuil).

    Chaque source echoue INDEPENDAMMENT et le DIT : une source aveugle se nomme, sinon
    l'absence de signal se lirait comme l'absence de probleme.
    """
    import re as _re  # le module n'importe pas `re` au niveau global (mesure : NameError)

    out: dict = {"aveugle": []}

    # 1. Les diagnostics que le corps s'ecrit a lui-meme.
    soins: list[dict] = []
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_swarm_blackboard import read_zone

        for f in read_zone("discovered_facts", category="self_care", limit=60) or []:
            txt = str(f.get("value") or f.get("fact") or "")
            persist = 0
            m = _re.search(r"persistant (\d+) cycle", txt)
            if m:
                persist = int(m.group(1))
            soins.append({"cle": str(f.get("key") or "")[:60],
                          "persistance": persist, "texte": txt[:110]})
    except Exception as e:  # noqa: BLE001
        out["aveugle"].append("self_care(%s)" % type(e).__name__)
    out["soins_requis"] = len(soins)
    # Un defaut qui revient est un defaut que personne n'a soigne.
    out["soins_persistants"] = sorted(
        (s for s in soins if s["persistance"] >= 2),
        key=lambda s: -s["persistance"])[:5]

    # 2. Les effecteurs qui pompent (remede plus couteux que le mal).
    pompe: list[dict] = []
    _ev = None  # journal de cycle de vie, lu UNE fois et partage (chemin non chaud,
                # mais une relecture par effecteur serait une fuite d'I/O gratuite)
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_regulation_efficacy import journal as _lire_journal
        from nokido_agent.tools.forge_regulation_efficacy import verdicts

        _ev = _lire_journal()
        for v in verdicts(_ev):
            if v.get("verdict") in ("POMPE", "PROCHE DU POMPAGE"):
                pompe.append({"effecteur": "%s/%s" % (v["action"], v["cible"]),
                              "verdict": v["verdict"],
                              "rafale_h": v.get("debit_rafale_par_heure"),
                              "budget_h": v.get("budget_par_heure"),
                              "volume_go": v.get("volume_total_go")})
    except Exception as e:  # noqa: BLE001
        out["aveugle"].append("regulation_efficacy(%s)" % type(e).__name__)
    out["effecteurs_qui_pompent"] = pompe[:6]

    # 3. L'ecart a la direction voulue.
    try:
        from nokido_agent.tools.forge_gap_direction import point as gap_point

        g = gap_point()
        out["direction"] = {
            "alignes": len(g.get("alignes") or []),
            "hors_direction": len(g.get("hors_direction") or []),
            "sans_mesure": len(g.get("sans_mesure") or []),
            "silent_death": (g.get("totaux") or {}).get("silent_death_total"),
        }
        out["hors_direction_top"] = [
            {"module": h.get("module"), "organe": h.get("organe")}
            for h in (g.get("hors_direction") or [])[:5]
        ]
    except Exception as e:  # noqa: BLE001
        out["aveugle"].append("gap_direction(%s)" % type(e).__name__)

    # 4. CORRELATION -- l'apport propre du pattern.
    # Un soin qui persiste pendant qu'un effecteur pompe = symptome traite, cause intacte.
    # CRITERE DE FLUX (revue AGY, R2). L'ancienne regle appariait un etat symptomatique
    # STATIQUE (« RAM >= 85 % ») a TOUT effecteur qui pompait : faux couplage, et
    # mesure — sur 3 propositions produites, 1 seule etait solide. Le critere exige
    # desormais un RECOUVREMENT TEMPOREL (l'effecteur a tire pendant la persistance du
    # symptome) ET la MEME RESSOURCE (volume d'octets reellement deplace au journal,
    # pas un nom qui evoque la memoire). Les paires rejetees sont CONSERVEES avec leur
    # motif : un filtre qui ecarte en silence surestime sa propre justesse.
    croisements, rejets = [], []
    try:
        from nokido_agent.tools.forge_regulation_efficacy import cadence as _cadence
        from nokido_agent.tools.forge_regulation_efficacy import croisement_flux as _flux
    except Exception as e:  # noqa: BLE001
        out["aveugle"].append("critere_flux(%s)" % type(e).__name__)
        _flux = None
    if _flux:
        for s in out["soins_persistants"]:
            # Age du symptome : la persistance est comptee en cycles du demon
            # epistemique (~600 s), on la convertit plutot que d'inventer une duree.
            age_s = max(1, int(s["persistance"])) * 600.0
            for p in pompe:
                act, _, cib = p["effecteur"].partition("/")
                cad = _cadence(act, cib, evenements=_ev)
                v = _flux(cad, age_s, s["texte"])
                if v.get("lie"):
                    croisements.append({"soin": s["cle"], "cycles": s["persistance"],
                                        "effecteur": p["effecteur"],
                                        "preuve_flux": v["raison"],
                                        "lecture": "symptome traite, cause intacte"})
                else:
                    rejets.append({"effecteur": p["effecteur"], "motif": v["raison"]})
    out["symptomes_traites_sans_remede"] = croisements[:5]
    out["paires_ecartees"] = rejets[:6]
    out["paires_ecartees_total"] = len(rejets)

    # 5. PRODUIRE. Un diagnostic qui reste dans un journal n'ameliore rien : le journal
    # d'audit n'est lu que par la retention, qui SUPPRIME, et par une route d'affichage.
    # La table `orchestrator_recommendations` porte deja le vocabulaire complet d'une
    # proposition -- param, valeur courante, valeur suggeree, raison, confiance, preuve,
    # et un cycle applied_at / applied_by / rolled_back_at. Elle contenait 14 lignes,
    # TOUTES du 27 avril, 0 appliquee, `evidence` a NULL partout (mesure 2026-07-30) :
    # l'organe qui l'alimentait ne tourne plus. On l'alimente donc depuis la seule
    # boucle vivante, et on remplit la preuve, qui est ce qui rend une proposition
    # examinable au lieu d'opinable.
    # On ne s'APPLIQUE rien a soi-meme : `applied_by` reste a decider par un humain ou
    # un agent mandate. Produire une proposition n'est pas la meme chose que muter le
    # corps sans accord.
    out["propositions"] = 0
    for x in croisements:
        eff = x["effecteur"]
        p = next((q for q in pompe if q["effecteur"] == eff), None)
        if not p:
            continue
        # Confiance DERIVEE de la mesure, pas choisie : un verdict POMPE est un
        # depassement constate du budget, PROCHE DU POMPAGE ne l'est pas encore ;
        # et plus le soin persiste, plus la lecture « cause intacte » est solide.
        base = 0.75 if p["verdict"] == "POMPE" else 0.5
        conf = min(0.9, base + 0.05 * min(int(x["cycles"]), 3))
        if _proposer(
            param=eff,
            current_value="%s tirs/h en rafale contre un budget de %s/h ; %s Go deplaces"
                          % (p.get("rafale_h"), p.get("budget_h"), p.get("volume_go")),
            suggested_value="traiter la CAUSE du retour de la cible plutot que la reprendre : "
                            "verifier qui la recree, et que le reveilleur DECLARE son intention",
            reason="soin %s persistant depuis %s cycle(s) PENDANT que %s pompe : "
                   "symptome traite, cause intacte. Couplage par FLUX : %s"
                   % (x["soin"], x["cycles"], eff, x.get("preuve_flux", "n/d")),
            confidence=round(conf, 2),
            evidence={"effecteur": eff, "verdict": p["verdict"],
                      "rafale_par_heure": p.get("rafale_h"),
                      "budget_par_heure": p.get("budget_h"),
                      "volume_total_go": p.get("volume_go"),
                      "soin": x["soin"], "cycles_persistance": x["cycles"]},
        ):
            out["propositions"] += 1

    # 6. UNE proposition REFLEXE, quand elle est justifiee. Les propositions ci-dessus
    # sont DIAGNOSTIQUES par nature : « verifier qui recree la cible » est un changement
    # de code, donc cortical. Mesure : les 17 propositions en base ne portaient AUCUNE
    # action machine, si bien que l'applicateur n'avait rien a appliquer -- « 0 appliquee »
    # n'etait pas qu'un applicateur manquant, c'etait aussi zero proposition applicable.
    # Le seul cas reellement REFLEXE ici est la pression memoire avec des reclaimers
    # DECLARES : rendre un cache reconstructible est purement reversible (on perd du
    # temps de reconstruction, jamais de l'etat), ce qui est exactement le critere de
    # l'etage medullaire.
    # Les leviers se constatent au JOURNAL, pas au registre en memoire.
    # `reclaimers_declares()` est LOCAL AU PROCESS : l'enregistrement se fait dans le
    # hub (`_declarer_cache_reclamable`), donc depuis le demon autonome il rend
    # TOUJOURS une liste vide -- le pattern n'aurait jamais vu un seul levier. Mesure
    # 2026-07-30. Un reclaimer qui a DEJA rendu des Go est de surcroit un temoignage
    # plus fort qu'un nom enregistre : il prouve que le levier fonctionne.
    _rec = []
    if _ev:
        _vus = {}
        for _e in _ev:
            if _e.get("action") != "reclaim":
                continue
            _x = _e.get("extra") or {}
            _t = _x.get("target")
            if _t:
                _vus[_t] = _vus.get(_t, 0) + 1
        _rec = sorted(_vus, key=lambda k: -_vus[k])
    else:
        out["aveugle"].append("leviers(journal indisponible)")
    _soins_ram = [s for s in out["soins_persistants"]
                  if _re.search(r"\bRAM\b|memoire|mémoire", s["texte"], _re.I)]
    if _soins_ram and _rec:
        _pire = max(_soins_ram, key=lambda s: s["persistance"])
        # Confiance derivee : la persistance EST la mesure de realite du symptome.
        _c = min(0.9, 0.7 + 0.05 * min(int(_pire["persistance"]), 4))
        if _proposer(
            param="pression_memoire_soutenue",
            current_value="soin RAM persistant depuis %s cycle(s) ; %d reclaimer(s) declare(s) : %s"
                          % (_pire["persistance"], len(_rec), ", ".join(_rec[:4])),
            suggested_value="rendre la RAM reclamable (run_reclaimers) — reversible pur",
            reason="symptome memoire persistant ET leviers reversibles disponibles : "
                   "etage REFLEXE. %s" % _pire["texte"][:150],
            confidence=round(_c, 2),
            evidence={"soin": _pire["cle"], "cycles": _pire["persistance"],
                      "reclaimers": _rec,
                      # C'est CE bloc qui rend la proposition applicable. Sans lui,
                      # l'applicateur la classe DIAGNOSTIC et n'y touche pas.
                      "action": {"type": "reclaim_cache", "needed_gb": 0.0}},
        ):
            out["propositions"] += 1
            out["proposition_reflexe"] = True

    if out["aveugle"]:
        # Trois etats, jamais deux : une source illisible n'est pas une source vide.
        _log_run("self_improvement_watch", "partial",
                 "sources aveugles: %s" % ",".join(out["aveugle"]))
    return out


_PROPOSAL_DEDUP_S = 86400.0


def _proposer(param: str, current_value: str, suggested_value: str, reason: str,
              confidence: float, evidence: dict | None = None) -> bool:
    """Depose une proposition d'amelioration. Rend True si elle a ete ECRITE.

    Deduplique sur 24 h par `param` tant que la proposition n'est pas appliquee :
    sans cela un pattern horaire empilerait la meme proposition vingt-quatre fois par
    jour et noierait la table sous sa propre repetition. Une proposition DEJA
    appliquee n'empeche pas d'en reproposer une : si le defaut revient apres remede,
    c'est un fait nouveau et il doit se voir.
    """
    try:
        from nokido_agent.app.forge_db_path import write_retry

        def _corps(conn):
            recent = conn.execute(
                "SELECT id FROM orchestrator_recommendations "
                "WHERE param=? AND applied_at IS NULL "
                "AND created_at > datetime('now', ?) LIMIT 1",
                (param, "-%d seconds" % int(_PROPOSAL_DEDUP_S)),
            ).fetchone()
            if recent:
                return False
            conn.execute(
                "INSERT INTO orchestrator_recommendations "
                "(param, current_value, suggested_value, reason, confidence, "
                " source_module, evidence, pattern_code, created_at) "
                "VALUES (?,?,?,?,?,?,?,?, datetime('now'))",
                (param, current_value[:400], suggested_value[:400], reason[:400],
                 float(confidence), "forge_autonomous_loops.pat_self_improvement",
                 json.dumps(evidence or {}, ensure_ascii=False),
                 "self_improvement_watch"),
            )
            return True

        ecrite = bool(write_retry(_corps))
        if ecrite:
            try:
                exp = record_evolution_experience({
                    "kind": "parameter_proposal", "status": "PENDING_CANDIDATE",
                    "organ": "regulation", "param": param,
                    "current": current_value[:200], "suggested": suggested_value[:200],
                    "reason": reason[:300], "confidence": float(confidence),
                })
                log.info(f"[self_improvement] expérience d'évolution ouverte: {exp} ({param})")
            except Exception as exc:
                log.warning(f"[self_improvement] ledger évolution non écrit ({exc})")
        return ecrite
    except Exception as e:  # noqa: BLE001
        # Jamais muet : une proposition perdue est une amelioration qui n'a pas eu lieu,
        # et rien en aval ne pourrait s'en apercevoir.
        log.warning(f"proposition non deposee ({param}): {type(e).__name__}: {e}")
        return False



@register_pattern(
    "proposal_applier",
    interval_sec=3600,
    description=(
        "Ferme la chaine PROPOSER -> APPLIQUER : l'etage REFLEXE (reversible pur, confiance "
        ">= 0.75, sante lisible) des propositions de self_improvement_watch. Cortical, "
        "diagnostic et refuse ne sont JAMAIS executes. Sans LAFORGE_APPLIER_ARMED=1 : plan seul."
    ),
    preferred_window=None,
)
def pat_proposal_applier() -> dict:
    """Le maillon qui manquait (mesure 2026-09-24) : `forge_proposal_applier` etait complet,
    arme dans Nokido.env depuis le 27/08 -- et importe par PERSONNE. Des propositions etaient
    ecrites chaque heure, aucune n'etait jamais consideree pour application.

    Ce pattern ne decide rien lui-meme : il appelle `appliquer()`, qui porte les deux etages,
    la mesure avant/apres, le veto de sante et le marquage `applied_by`/`rolled_back_at`
    (tracabilite). L'etat d'armement est RENDU tel que le process le voit (son env), jamais
    suppose : arme dans un fichier != arme dans le process.
    """
    from nokido_agent.app import forge_proposal_applier as _ap

    r = _ap.appliquer()
    actes = r.get("actes") or []
    return {"ok": True, "arme": r.get("arme"), "dry_run": r.get("dry_run"),
            "reflexe": r.get("reflexe"), "cortical": r.get("cortical"),
            "diagnostic": r.get("diagnostic"), "refuse": r.get("refuse"),
            "actes": len(actes), "succes": sum(1 for a in actes if a.get("succes")),
            "annules": sum(1 for a in actes if a.get("fait") and not a.get("succes"))}


# ── TRI DES EXPERIENCES (P1, 2026-09-25) ─────────────────────────────────────────────────
# Mesure du jour : 658 experiences au registre, 652 PENDING_CANDIDATE -- six producteurs
# ci-dessus, AUCUN consommateur (les 6 requalifications presentes ont ete ecrites a la main).
# La variation existait, la selection (forge_mutation_judge) aussi ; le maillon entre les deux,
# CHOISIR LE TRAITEMENT SELON LE DIAGNOSTIC, n'existait pas. Meme geste que la soif le meme
# jour (un manque interne ne part pas en veille web) : le remede depend de la pathologie.
# Decision owner : A BLANC d'abord -- le tri ecrit sa decision, n'execute rien ; armement
# traitement par traitement ensuite ; la promotion d'un code reste le commit owner (P5).
_TRAITEMENTS = {
    "organ_down": ("RELANCE_OU_OWNER",
                   "organe declare actif et tombe (les choix de configuration sont filtres a la "
                   "production, 209295d21) : route gouvernee de service, sinon owner"),
    "usage_findings": ("ROUTEUR_A_VERIFIER",
                       "le routeur ecarte deja les fournisseurs qui echouent (dead_end persistant, "
                       "disjoncteur, 3 echecs, preference apprise) : verifier qu'il le fait AVANT "
                       "toute action ; a defaut, marquage dead_end reversible"),
    # CORRIGE le meme jour : classe d'abord « SOIF » d'apres le NOM du kind, sans lire son
    # producteur (pat_unmet_intention_docs) -- c'est un ecart DOC/CODE, pas un manque de savoir.
    "unmet_intention": ("ECART_DOC_CODE",
                        "module decrit dans un doc d'intention mais absent du code : l'owner tranche "
                        "-- construire le module (le producteur dit : tendre le code vers "
                        "l'intention) ou dater le doc"),
    "capability_lost": ("MUTATION_CODE_JUGEE",
                        "seul chemin qui touche au code : self_patcher, puis forge_mutation_judge "
                        "(gain mesure contre baseline), puis AWAITING_OWNER_COMMIT"),
    "regression_hypothesis": ("MUTATION_CODE_JUGEE",
                              "seul chemin qui touche au code : self_patcher, puis forge_mutation_judge "
                              "(gain mesure contre baseline), puis AWAITING_OWNER_COMMIT"),
    "parameter_proposal": ("APPLICATEUR_SI_ACTION_DECLAREE",
                           "forge_proposal_applier, etage reflexe seulement et seulement pour une "
                           "action machine declaree ; une proposition en prose reste un diagnostic owner"),
}


def _port_ouvert(port: int) -> bool:
    """La sonde MEME de pat_health_check (socket loopback, 0,5 s)."""
    import socket

    try:
        s = socket.socket()
        s.settimeout(0.5)
        s.connect(("127.0.0.1", int(port)))
        s.close()
        return True
    except OSError:  # muet-ok : un port qui refuse EST la mesure (fermé), pas une erreur
        return False


def _succes_recent_des_outils(outils) -> dict:
    """{outil: (n, succes_pct)} sur 7 jours -- la table, la fenetre ET le contrat de pat_trace_mining :
    seules les ISSUES comptent (une emission `CALL` n'en est pas une, cf. _TRACE_ISSUE_SQL).
    Un outil sans assez d'issues est ABSENT du resultat (le re-examen le dit INDETERMINE)."""
    import sqlite3 as _sql

    db = ROOT / "RAG" / "execution_traces.db"
    outils = [o for o in outils if o]
    if not outils or not db.exists():
        return {}
    con = _sql.connect("file:%s?mode=ro" % str(db).replace("\\", "/"), uri=True, timeout=10)
    try:
        marques = ",".join("?" * len(outils))
        rows = con.execute(
            "SELECT json_extract(action_json,'$.tool') t, COUNT(*) c, AVG(success) s FROM traces "
            "WHERE ts > ? AND json_extract(action_json,'$.tool') IN (%s) AND %s GROUP BY t HAVING c >= ?"
            % (marques, _TRACE_ISSUE_SQL),
            (time.time() - 7 * 86400, *outils, _TRACE_MIN_SAMPLES)).fetchall()
    finally:
        con.close()
    return {t: (c, round(100 * s)) for t, c, s in rows if s is not None}


_ABSENTS_CACHE: dict = {}


def _modules_absents_maintenant() -> set:
    """Instrument de pat_unmet_intention_docs, memorise 60 s : un cycle de tri le consulte pour
    ~140 dossiers, le re-scanner a chaque fois paierait 140 lectures des docs pour une reponse."""
    if time.time() - _ABSENTS_CACHE.get("ts", 0) > 60:
        _ABSENTS_CACHE["set"] = {os.path.basename(m["module"]) for m in _modules_absents_des_docs()}
        _ABSENTS_CACHE["ts"] = time.time()
    return _ABSENTS_CACHE["set"]


def _synthese(par_cible: dict, a_traiter: str) -> str:
    v = set(par_cible.values())
    if a_traiter in v:
        return "A_TRAITER"
    if "INDETERMINE" in v or not v:
        return "INDETERMINE"
    return "RESOLU"


def _reexaminer(kind: str, lot: list) -> dict:
    """Relit le manque d'un dossier MAINTENANT, avec l'instrument MEME qui l'a ouvert (decision
    owner 2026-09-25) : une experience ancienne est STALE, pas DEAD -- au 20/09, 92 % du registre
    etait faux. Lecture seule. Aucun instrument pour ce kind -> NON_REEXAMINE, dit tel quel."""
    if kind == "organ_down":
        cibles = list(dict.fromkeys(t for e in lot for t in (e.get("targets") or [])))
        par_cible, fermes = {}, []
        for c in cibles:
            try:
                ouvert = _port_ouvert(int(str(c).rsplit(":", 1)[1]))
            except (IndexError, ValueError):
                par_cible[c] = "INDETERMINE"
                continue
            if ouvert:
                par_cible[c] = "RESOLU"
            else:
                fermes.append(c)
        if fermes:
            down, choix, inconnus = _classer_ports_fermes(fermes, _politique_des_ports())
            for item in down:
                par_cible[item] = "FERME_A_L_INSTANT"
            for item in choix:
                par_cible[str(item).split(" (", 1)[0]] = "CHOIX_DE_CONFIGURATION"
            for item in inconnus:
                par_cible[str(item).split(" (", 1)[0]] = "INDETERMINE"
        return {"verdict": _synthese(par_cible, "FERME_A_L_INSTANT"), "par_cible": par_cible,
                "instrument": "sonde de port + politique services.toml (pat_health_check)"}
    if kind == "usage_findings":
        outils = list(dict.fromkeys(f.get("tool") for e in lot
                                    for f in ((e.get("findings") or {}).get("low_success") or [])))
        mesures = _succes_recent_des_outils(outils)
        par_cible = {}
        for o in outils:
            if o not in mesures:
                par_cible[o] = "INDETERMINE"
            elif mesures[o][1] < 100 * _TRACE_SUCCESS_FLOOR:
                par_cible[o] = "TOUJOURS_EN_ECHEC"
            else:
                par_cible[o] = "RESOLU"
        return {"verdict": _synthese(par_cible, "TOUJOURS_EN_ECHEC"), "par_cible": par_cible,
                "mesures": {o: {"n": n, "succes_pct": p} for o, (n, p) in mesures.items()},
                "instrument": "execution_traces 7 j (pat_trace_mining)"}
    if kind == "unmet_intention":
        absents = _modules_absents_maintenant()
        par_cible = {}
        for e in lot:
            mod = os.path.basename(str(e.get("target_module") or ""))
            doc = str(e.get("source_doc") or "")
            if "template" in doc.lower() or mod == "forge_X.py":
                par_cible[mod] = "FAUX_POSITIF_GABARIT"
            elif not _est_doc_d_intention(doc):
                # Nee de l'ancienne liste noire (avant le 2026-09-25) : une MENTION, jamais une
                # intention. RESOLU serait un faux calme -- rien n'a ete resolu.
                par_cible[mod] = "MENTION_HORS_INTENTION"
            elif mod not in absents:
                par_cible[mod] = "RESOLU"
            else:
                par_cible[mod] = "ECART_CONFIRME"
        v = set(par_cible.values())
        verdict = ("A_TRAITER" if "ECART_CONFIRME" in v else
                   "FAUX_POSITIF_GABARIT" if v == {"FAUX_POSITIF_GABARIT"} else
                   "MENTION_HORS_INTENTION" if "MENTION_HORS_INTENTION" in v and "RESOLU" not in v
                   else "RESOLU")
        return {"verdict": verdict, "par_cible": par_cible,
                "instrument": "modules absents des docs (pat_unmet_intention_docs)"}
    return {"verdict": "NON_REEXAMINE", "par_cible": {}, "instrument": None}


def _trier(exp: dict) -> tuple:
    """(traitement, motif) d'une experience. Liste BLANCHE : un kind inconnu est NOMME
    INDETERMINE, jamais ecarte ni range d'office dans un traitement."""
    t = _TRAITEMENTS.get(exp.get("kind"))
    if t is None:
        return ("INDETERMINE", "kind inconnu du tri : %r -- nomme, jamais ecarte" % exp.get("kind"))
    return t


# Version des INSTRUMENTS du tri. v3 (26/09) : capteurs du re-examen corriges (CALL n'est pas une
# issue ; unmet_intention en liste blanche, MENTION_HORS_INTENTION). Une decision rendue par une
# version anterieure ne couvre plus ses experiences : elles sont REJUGEES, en ajout (la plus recente
# fait foi). Mesure : le tri reel rendait 0 dossier decide, les 106 « A_TRAITER » de l'ancien capteur
# restaient figes. Monter ce numero a chaque correction d'un instrument de re-examen.
_TRI_VERSION = 3


@register_pattern(
    "evolution_triage",
    interval_sec=3600,
    description=(
        "TRI des experiences d'evolution PENDING_CANDIDATE : un dossier (kind, organe, hypothese) "
        "recoit UN traitement selon son diagnostic. A BLANC : ecrit la decision au registre, "
        "n'execute rien (armement par traitement = decision owner)."
    ),
    preferred_window=None,
)
def pat_evolution_triage() -> dict:
    """Consomme les PENDING_CANDIDATE non encore tries, les regroupe par dossier et ecrit une
    decision `kind=triage, status=TRIAGED_DRY_RUN` par dossier, qui cite les experiences
    couvertes. Idempotent : une experience deja couverte n'est plus retriee ; une experience
    nouvelle d'un dossier connu recoit sa propre decision."""
    import hashlib as _h

    try:
        lignes = Path(_EVOLUTION_LEDGER).read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return {"ok": True, "a_blanc": True, "dossiers_decides": 0, "experiences_couvertes": 0,
                "note": "registre absent : rien a trier (pas un succes, un vide)"}
    exps, couverts, illisibles = [], set(), 0
    for ligne in lignes:
        if not ligne.strip():
            continue
        try:
            e = json.loads(ligne)
        except ValueError:
            illisibles += 1
            continue
        # Seule une decision RE-EXAMINEE couvre ses experiences : celles du premier cycle (sans
        # re-examen, et SOIF a tort pour unmet_intention) sont redecidees -- en ajout, jamais en
        # ecrasement ; la plus recente fait foi.
        if (e.get("kind") == "triage" and e.get("reexamen")
                and int(e.get("version") or 0) >= _TRI_VERSION):
            couverts.update(e.get("experiences") or [])
        elif e.get("status") == "PENDING_CANDIDATE" and e.get("exp_id"):
            exps.append(e)
    dossiers: dict = {}
    for e in exps:
        if e["exp_id"] in couverts:
            continue
        cle = _h.sha256(("%s|%s|%s" % (e.get("kind"), e.get("organ"), str(e.get("hypothesis", ""))[:120])
                         ).encode()).hexdigest()[:12]
        dossiers.setdefault(cle, []).append(e)
    par_traitement: dict = {}
    par_verdict: dict = {}
    for cle, lot in dossiers.items():
        dernier = lot[-1]
        traitement, motif = _trier(dernier)
        try:
            reexamen = _reexaminer(dernier.get("kind"), lot)
        except Exception as ex:  # noqa: BLE001 - un instrument casse se DIT, il ne fait pas taire le tri
            reexamen = {"verdict": "INDETERMINE", "par_cible": {},
                        "erreur": ("%s: %s" % (type(ex).__name__, ex))[:160]}
        par_verdict[reexamen["verdict"]] = par_verdict.get(reexamen["verdict"], 0) + 1
        record_evolution_experience({
            "kind": "triage", "status": "TRIAGED_DRY_RUN", "version": _TRI_VERSION, "dossier": cle,
            "reexamen": reexamen,
            "source_kind": dernier.get("kind"), "organ": dernier.get("organ"),
            "hypothesis": str(dernier.get("hypothesis", ""))[:200],
            "treatment": traitement, "motif": motif,
            # la PLUS RECENTE valeur presente dans le dossier : une derniere experience sans
            # constats ne doit pas effacer la preuve portee par les precedentes
            "evidence": {k: v for k in ("findings", "issues", "organ")
                         for v in [next((x.get(k) for x in reversed(lot) if x.get(k) is not None), None)]
                         if v is not None},
            "experiences": [e["exp_id"] for e in lot], "n": len(lot),
        })
        par_traitement[traitement] = par_traitement.get(traitement, 0) + len(lot)
    return {"ok": True, "a_blanc": True, "dossiers_decides": len(dossiers),
            "experiences_couvertes": sum(len(v) for v in dossiers.values()),
            "par_traitement": par_traitement, "reexamen_par_verdict": par_verdict,
            "lignes_illisibles": illisibles}


# ── EFFECTEURS DU TRI (owner 2026-09-30 : « on arme 1 et 2 ») ─────────────────────────────────
# Le tri decidait A BLANC depuis le 25/09. Mesure du jour avant d'armer : les 3 decisions
# RELANCE_OU_OWNER forment UN dossier, deja RESOLU ou CHOIX_DE_CONFIGURATION ; les 23
# ROUTEUR_A_VERIFIER portent sur UN fournisseur, `mistral`, TOUJOURS_EN_ECHEC depuis le 27/09,
# sans AUCUNE ligne dans motivation_failures : le routeur ne l'a jamais ecarte.
# Deux effecteurs sont armes, les plus surs ; chacun agit sur un RE-EXAMEN du jour :
#   relance : organe DECLARE actif, port FERME A L'INSTANT, et service que le superviseur
#             rapporte ARRETE -- jamais `sleeping` (la regulation l'a endormi), jamais un pilier
#             du keeper (il les eteint quand ils ne servent plus) : relancer l'un ou l'autre
#             reproduirait l'anti-phase de la soif du 30/09. UNE demande par service et par
#             24 h ; toujours ferme au passage suivant -> OWNER_REQUIS, une fois.
#   routeur : LECTURE SEULE. Le fournisseur toujours en echec est-il ecarte par le routeur
#             (dead_end de forge_motivation, la ou le routeur le lit) ? Le verdict est ecrit au
#             registre ; aucun marquage : poser un dead_end reste une decision owner.
# Desarmement sans toucher au code : LAFORGE_EFFECTEUR_RELANCE=0 / LAFORGE_EFFECTEUR_ROUTEUR=0.
_EFFECTEUR_TTL_S = 24 * 3600
_STATUTS_ARRETES = frozenset({"stopped", "crashed", "failed", "exited", "dead"})


def _statuts_superviseur() -> dict:
    """{service: statut} lu au superviseur ; {} si illisible : on n'agit pas a l'aveugle."""
    import urllib.request as _u

    try:
        with _u.urlopen("http://127.0.0.1:8765/supervisor/status", timeout=8) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001 - statut inconnu => abstention, dite dans le resultat
        log.warning("[effecteurs] superviseur illisible : %s", type(e).__name__)
        return {}
    s = d.get("services") if isinstance(d, dict) else d
    if isinstance(s, dict):
        return {k: (v.get("status") if isinstance(v, dict) else v) for k, v in s.items()}
    return {x.get("name"): x.get("status") for x in (s or []) if isinstance(x, dict)}


def _piliers_du_keeper() -> set:
    try:
        from nokido_agent.tools.forge_llama_keeper import _PILIERS

        return {nom for nom, _port, _drapeau in _PILIERS}
    except Exception as e:  # noqa: BLE001 - repli sur les piliers CONNUS, jamais sur « aucun »
        log.warning("[effecteurs] piliers du keeper illisibles (%s) : repli", type(e).__name__)
        return {"NokidoLlamaEmbed", "NokidoLlamaReranker"}


def _registre_lu() -> tuple:
    """(experiences par exp_id, decisions de tri, actes d'effecteur) du registre."""
    exps, tri, actes = {}, [], []
    try:
        lignes = Path(_EVOLUTION_LEDGER).read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return exps, tri, actes
    for ligne in lignes:
        try:
            e = json.loads(ligne)
        except ValueError:
            continue    # muet-ok : le tri compte deja les lignes illisibles de ce registre
        if e.get("kind") == "triage":
            tri.append(e)
        elif e.get("kind") == "effecteur":
            actes.append(e)
        if e.get("exp_id"):
            exps[e["exp_id"]] = e
    return exps, tri, actes


def _acte_recent(actes, effecteur: str, cible: str):
    """Dernier acte de cet effecteur sur cette cible dans les 24 h, sinon None."""
    for a in reversed(actes):
        if a.get("effecteur") == effecteur and a.get("cible") == cible:
            try:
                t = time.mktime(time.strptime(str(a.get("ts"))[:19], "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                return a    # date illisible : tenue pour recente -> on s'abstient
            return a if time.time() - t < _EFFECTEUR_TTL_S else None
    return None


def _effecteur_relance(decision: dict, lot: list, actes: list) -> list:
    reex = _reexaminer("organ_down", lot)      # MAINTENANT, avec l'instrument du producteur
    fermes = [c for c, v in (reex.get("par_cible") or {}).items() if v == "FERME_A_L_INSTANT"]
    if not fermes:
        return []
    statuts = _statuts_superviseur()
    piliers = _piliers_du_keeper()
    par_port = _politique_des_ports().get("par_port") or {}
    faits = []
    for cible in fermes:
        try:
            port = int(str(cible).rsplit(":", 1)[1])
        except (IndexError, ValueError):
            faits.append({"cible": cible, "acte": "ABSTENTION", "motif": "port illisible"})
            continue
        for svc in (par_port.get(port) or {}).get("actifs") or []:
            statut = statuts.get(svc)
            if svc in piliers or statut not in _STATUTS_ARRETES:
                faits.append({"service": svc, "port": port, "acte": "ABSTENTION",
                              "motif": "pilier du keeper" if svc in piliers else "statut %r" % statut})
                continue
            deja = _acte_recent(actes, "relance", svc)
            if deja and deja.get("status") == "OWNER_REQUIS":
                continue    # deja remonte a l'owner dans les 24 h : ne pas le redire chaque heure
            if deja:
                acte, detail = "OWNER_REQUIS", "deja relance (%s) et toujours ferme" % deja.get("ts")
            else:
                try:
                    from nokido_agent.tools.forge_ensure_service import ensure

                    r = ensure(svc, "running")
                    ok = bool((r or {}).get("success")) if isinstance(r, dict) else bool(r)
                    acte, detail = ("RELANCE_DEMANDEE" if ok else "RELANCE_REFUSEE"), str(r)[:200]
                except Exception as e:  # noqa: BLE001 - l'echec est ecrit au registre
                    acte, detail = "RELANCE_ECHOUEE", ("%s: %s" % (type(e).__name__, e))[:200]
            record_evolution_experience({
                "kind": "effecteur", "effecteur": "relance", "cible": svc, "status": acte,
                "port": port, "statut_superviseur": statut,
                "dossier": decision.get("dossier"), "detail": detail})
            faits.append({"service": svc, "port": port, "acte": acte})
    return faits


def _effecteur_routeur(decision: dict, lot: list, actes: list) -> list:
    reex = _reexaminer("usage_findings", lot)
    faits = []
    for outil, v in (reex.get("par_cible") or {}).items():
        if v != "TOUJOURS_EN_ECHEC" or _acte_recent(actes, "routeur", outil):
            continue
        try:
            from nokido_agent.app import forge_motivation as _mot

            con = sqlite3.connect("file:%s?mode=ro" % _mot.DEFAULT_DB, uri=True, timeout=10)
            try:
                marques = con.execute(
                    "SELECT target, failure_count, dead_end FROM motivation_failures WHERE method=?",
                    ("llm_call:%s" % outil,)).fetchall()
            finally:
                con.close()
            ecarte = [t for t, _n, de in marques if de]
            verdict = "ECARTE_PAR_LE_ROUTEUR" if ecarte else "NON_ECARTE"
            detail = {"dead_end_sur": ecarte, "marques": len(marques)}
        except Exception as e:  # noqa: BLE001 - une lecture ratee est ILLISIBLE, jamais NON
            verdict, detail = "ILLISIBLE", {"erreur": ("%s: %s" % (type(e).__name__, e))[:160]}
        record_evolution_experience({
            "kind": "effecteur", "effecteur": "routeur", "cible": outil, "status": verdict,
            "dossier": decision.get("dossier"),
            "mesure": (reex.get("mesures") or {}).get(outil), "detail": detail})
        faits.append({"outil": outil, "verdict": verdict})
    return faits


@register_pattern(
    "evolution_effecteurs",
    interval_sec=3600,
    description=(
        "Effecteurs ARMES du tri (owner 2026-09-30) : relance d'un organe declare actif, ferme "
        "et ARRETE (jamais endormi par la regulation, jamais un pilier du keeper) ; verification "
        "LECTURE SEULE du routeur pour un fournisseur toujours en echec."
    ),
    preferred_window=None,
)
def pat_evolution_effecteurs() -> dict:
    from nokido_agent.app.forge_drapeau_env import actif

    exps, tri, actes = _registre_lu()
    dernieres: dict = {}
    for d in tri:
        if d.get("treatment") in ("RELANCE_OU_OWNER", "ROUTEUR_A_VERIFIER"):
            dernieres[d.get("dossier")] = d        # la decision la plus recente fait foi
    armes = {"relance": actif("LAFORGE_EFFECTEUR_RELANCE", True),
             "routeur": actif("LAFORGE_EFFECTEUR_ROUTEUR", True)}
    res = {"ok": True, "armes": armes, "relance": [], "routeur": []}
    for d in dernieres.values():
        lot = [exps[x] for x in (d.get("experiences") or []) if x in exps]
        if d["treatment"] == "RELANCE_OU_OWNER" and armes["relance"]:
            res["relance"] += _effecteur_relance(d, lot, actes)
        elif d["treatment"] == "ROUTEUR_A_VERIFIER" and armes["routeur"]:
            res["routeur"] += _effecteur_routeur(d, lot, actes)
    return res


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", action="store_true", help="lance boucle continue")
    ap.add_argument("--tick", type=int, default=60, help="tick daemon en secondes")
    ap.add_argument("--run", help="execute un pattern par nom (ou 'all')")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        print(
            json.dumps(
                [
                    {
                        "name": n,
                        "interval_sec": p.interval_sec,
                        "description": p.description,
                        "local_llm": p.requires_local_llm,
                    }
                    for n, p in PATTERNS.items()
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.status:
        print(json.dumps(status(), indent=2, ensure_ascii=False, default=str))
    elif args.run == "all":
        _ensure_schema()
        print(json.dumps(run_due_patterns(force=True), indent=2, ensure_ascii=False, default=str))
    elif args.run:
        _ensure_schema()
        if args.run not in PATTERNS:
            print(f"unknown pattern: {args.run}. Available: {list(PATTERNS.keys())}")
            sys.exit(1)
        t0 = time.time()
        try:
            outcome = PATTERNS[args.run].fn()
            # `programme=False` : on trace, on ne deplace PAS l'echeance daemon.
            _log_run(args.run, "ok", str(outcome)[:300], outcome, programme=False)
            print(json.dumps(outcome, indent=2, ensure_ascii=False, default=str))
        except Exception as e:
            _log_run(args.run, "fail", str(e), {"error": str(e)}, programme=False)
            print(f"ERR: {e}")
            sys.exit(1)
    elif args.daemon:
        daemon_loop(tick_sec=args.tick)
    else:
        ap.print_help()
