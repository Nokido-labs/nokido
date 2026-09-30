"""
forge_llm_router_dt.py - Routeur LLM par DecisionTree sklearn
=============================================================
Couche additionnelle AU-DESSUS de forge_task_router.
Prédit le provider optimal depuis les features textuelles du payload
SANS remplacer le routing statique existant.

Architecture :
  Payload texte
    → TextFeatureExtractor (FEATURE_DIM dims, cf. FEATURE_NAMES)
    → DecisionTreeClassifier(max_depth=5)
    → provider_name
    → fallback : forge_task_router.select_provider(task_type)

Features (FEATURE_DIM = 35 dims, cf. FEATURE_NAMES) :

⚠ PAS compatibles avec CTFSpikeRouter(input_dim=31) : ce SNN consomme des
ChallengeFeatures CTF, un espace de representation SANS RAPPORT avec ces
features textuelles. Un vecteur d'ici n'est pas interpretable la-bas.
  Complexité      : n_words, n_sentences, avg_word_len, has_code, n_code_blocks
  Intention       : is_analysis, is_generation, is_classification, is_search,
                    is_synthesis, is_review, is_translation
  Domaine         : domain_code, domain_rag, domain_watch, domain_arch,
                    domain_security, domain_ops, domain_data, domain_doc
  Urgence         : is_urgent, is_error, is_debug
  Contexte        : has_url, has_path, has_json, has_number, has_list
  Provider hint   : hint_local, hint_fast, hint_large_ctx, hint_free

Données d'entraînement : bootstrap synthétique + MAJ live via log_decision()
Modèle : models/llm_router_dt.joblib (sauvegardé après chaque entraînement)
"""

from __future__ import annotations
import json
import re
import time
import logging
from pathlib import Path
from typing import Optional

import numpy as np

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("Nokido.LLMRouterDT")

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "models" / "llm_router_dt.joblib"
DATA_PATH = ROOT / "shadow_mutation" / "rag_index" / "router_decisions.jsonl"
DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

# Providers reconnus (ordre = label encoding)
PROVIDERS = [
    "groq",
    "ollama",
    "gemini",
    "llamacpp",
    "gpt4o_github",
    "openrouter_free",
    "deepseek",
    "kimi",
    "kimi_think",
    "glm5",
    "claude",
]
P2I = {p: i for i, p in enumerate(PROVIDERS)}
I2P = {i: p for i, p in enumerate(PROVIDERS)}

FEATURE_DIM = 36
FEATURE_NAMES = [
    # Complexité (5)
    "n_words_norm",
    "n_sentences_norm",
    "avg_word_len_norm",
    "has_code",
    "n_code_blocks_norm",
    # Intention (7)
    "is_analysis",
    "is_generation",
    "is_classification",
    "is_search",
    "is_synthesis",
    "is_review",
    "is_translation",
    # Domaine (8)
    "domain_code",
    "domain_rag",
    "domain_watch",
    "domain_arch",
    "domain_security",
    "domain_ops",
    "domain_data",
    "domain_doc",
    # Urgence (3)
    "is_urgent",
    "is_error",
    "is_debug",
    # Contexte (5)
    "has_url",
    "has_path",
    "has_json",
    "has_number",
    "has_list",
    # Provider hint (3)
    "hint_local",
    "hint_fast",
    "hint_large_ctx",
    # F3 (3)
    "n_chars_norm",
    "is_question",
    "agent_load_norm",
    # F35 — provider health (1)
    "prov_fail_rate",
    "provider_health",
]
assert len(FEATURE_NAMES) == FEATURE_DIM


# ── Feature Extractor ─────────────────────────────────────────────────────────


class TextFeatureExtractor:
    """
    Extrait FEATURE_DIM (35) features binaires/normalisées depuis un prompt.
    Espace propre au routage LLM — voir l'avertissement d'en-tête du module.
    """

    _ANALYSIS_KW = {
        "analyse",
        "analyze",
        "compare",
        "évalue",
        "evaluate",
        "examine",
        "diagnose",
        "inspect",
        "review",
        "audit",
        "check",
    }
    _GENERATION_KW = {
        "écris",
        "write",
        "génère",
        "generate",
        "crée",
        "create",
        "rédige",
        "draft",
        "produce",
        "build",
        "make",
        "implement",
    }
    _CLASSIF_KW = {
        "classify",
        "classifie",
        "catégorise",
        "categorize",
        "label",
        "tag",
        "triage",
        "route",
        "detect",
        "identify",
    }
    _SEARCH_KW = {"search", "cherche", "find", "trouve", "lookup", "query", "fetch", "get", "retrieve", "list"}
    _SYNTHESIS_KW = {
        "synthèse",
        "synthesize",
        "résume",
        "summarize",
        "summary",
        "condense",
        "merge",
        "combine",
        "aggregate",
    }
    _REVIEW_KW = {"review", "relis", "reread", "validate", "verify", "confirm", "check", "proofread", "correct"}
    _TRANSLATION_KW = {"traduis", "translate", "translates", "traduction", "translation"}

    _CODE_DOM = {
        "python",
        "javascript",
        "typescript",
        "rust",
        "go",
        "java",
        "c++",
        "function",
        "class",
        "def ",
        "import ",
        "async",
        "await",
        "pip",
        "npm",
    }
    _RAG_DOM = {"rag", "embedding", "vectoris", "chunk", "retriev", "semantic", "similarity", "cosine", "bm25"}
    _WATCH_DOM = {"watch", "veille", "alert", "release", "pypi", "github", "arxiv", "monitor", "notify"}
    _ARCH_DOM = {
        "architecture",
        "design",
        "pattern",
        "refactor",
        "structure",
        "module",
        "dependency",
        "coupling",
        "solid",
    }
    _SECURITY_DOM = {
        "security",
        "securite",
        "vulnerability",
        "exploit",
        "cve",
        "auth",
        "token",
        "secret",
        "permission",
        "sandbox",
    }
    _OPS_DOM = {"ops", "deploy", "docker", "kubernetes", "service", "process", "systemctl", "nssm", "restart", "daemon"}
    _DATA_DOM = {"data", "dataset", "csv", "json", "sql", "sqlite", "db", "table", "schema", "query", "analyse data"}
    _DOC_DOM = {"doc", "documentation", "readme", "docstring", "comment", "explain", "describe", "manual", "guide"}

    _URGENT_KW = {
        "urgent",
        "critique",
        "critical",
        "error",
        "erreur",
        "fix",
        "bug",
        "broken",
        "fail",
        "crash",
        "emergency",
    }
    _ERROR_KW = {"error", "exception", "traceback", "stacktrace", "failed", "crash", "invalid", "illegal", "forbidden"}
    _DEBUG_KW = {"debug", "trace", "log", "verbose", "inspect", "breakpoint", "step"}

    def _get_prov_fail_rate(self) -> float:
        """Fraction of recent decisions that failed (last 20). 0=healthy, 1=all failing."""
        try:
            data_path = ROOT / "shadow_mutation" / "rag_index" / "router_decisions.jsonl"
            if not data_path.exists():
                return 0.0
            lines = data_path.read_bytes().decode("utf-8", "replace").splitlines()
            recent = lines[-20:] if len(lines) >= 20 else lines
            if not recent:
                return 0.0
            fails = sum(1 for l in recent if not json.loads(l).get("ok", True))
            return round(fails / len(recent), 3)
        except Exception:
            return 0.0

    def _get_agent_load(self) -> float:
        """Heuristique de charge système (normalized 0-1)."""
        try:
            import sqlite3

            db_path = ROOT / "RAG" / "embeddings.db"
            conn = sqlite3.connect(str(db_path), timeout=1)
            # On prend la latence moyenne des providers actifs
            avg_ttft = conn.execute("SELECT AVG(ttft_ms) FROM provider_scores WHERE last_status='ok'").fetchone()[0]
            conn.close()
            if not avg_ttft:
                return 0.2
            return min(float(avg_ttft) / 2000.0, 1.0)
        except Exception:
            return 0.3

    def extract(self, text: str, task_type: str = "") -> np.ndarray:
        """Retourne un vecteur float32 de FEATURE_DIM dimensions."""
        t = text.lower()
        tl = t.split()
        sents = re.split(r"[.!?\n]+", t)
        sents = [s for s in sents if s.strip()]

        # Complexité
        n_words = min(len(tl) / 500.0, 1.0)
        n_sents = min(len(sents) / 20.0, 1.0)
        avg_wl = min(np.mean([len(w) for w in tl]) / 15.0, 1.0) if tl else 0.0
        code_blocks = len(re.findall(r"```", text)) // 2
        has_code = float(bool(code_blocks) or "```" in text or "def " in text or "import " in text)
        n_code_b = min(code_blocks / 5.0, 1.0)

        tset = set(tl)

        def _hit(kw_set):
            return float(bool(tset & kw_set))

        # Intention
        is_analysis = _hit(self._ANALYSIS_KW)
        is_generation = _hit(self._GENERATION_KW)
        is_classif = _hit(self._CLASSIF_KW)
        is_search = _hit(self._SEARCH_KW)
        is_synthesis = _hit(self._SYNTHESIS_KW)
        is_review = _hit(self._REVIEW_KW)
        is_translation = _hit(self._TRANSLATION_KW)

        # Domaine
        dom_code = float(any(kw in t for kw in self._CODE_DOM))
        dom_rag = float(any(kw in t for kw in self._RAG_DOM))
        dom_watch = float(any(kw in t for kw in self._WATCH_DOM))
        dom_arch = float(any(kw in t for kw in self._ARCH_DOM))
        dom_sec = float(any(kw in t for kw in self._SECURITY_DOM))
        dom_ops = float(any(kw in t for kw in self._OPS_DOM))
        dom_data = float(any(kw in t for kw in self._DATA_DOM))
        dom_doc = float(any(kw in t for kw in self._DOC_DOM))

        # Urgence
        is_urgent = float(any(kw in t for kw in self._URGENT_KW))
        is_error = float(any(kw in t for kw in self._ERROR_KW))
        is_debug = float(any(kw in t for kw in self._DEBUG_KW))

        # Contexte
        has_url = float(bool(re.search(r"https?://", text)))
        has_path = float(bool(re.search(r"[/\\][\w./\\]+", text)))
        has_json = float("{" in text and "}" in text)
        has_num = float(bool(re.search(r"\b\d+\b", text)))
        has_list = float(bool(re.search(r"^\s*[-*•]\s", text, re.M)))

        # Provider hints (depuis task_type)
        tt = task_type.lower()
        hint_local = float(tt in {"vectorize", "py_compile", "rag_search", "analyze_code"})
        hint_fast = float(
            tt in {"classify_domain", "filter_results", "synthesize_short", "summarize_log", "generate_queries"}
        )
        hint_large_ctx = float(tt in {"analyze_large", "summarize_long", "write_report"})

        # F3 (length, intent, agent_load)
        n_chars_norm = min(len(text) / 5000.0, 1.0)
        is_question = float(
            "?" in text or t.startswith(("how", "why", "what", "who", "when", "where", "est-ce", "peux-tu", "pouvons"))
        )
        agent_load = self._get_agent_load()

        prov_fail = self._get_prov_fail_rate()

        try:
            from nokido_agent.app.forge_ping_monitor import get_provider_health
            # Ping a few representative providers or all
            ph = get_provider_health(["groq", "ollama", "gemini", "claude"])
            provider_health_score = float(sum(ph.values()) / len(ph)) if ph else 1.0
        except Exception:
            provider_health_score = 1.0

        vec = np.array(
            [
                n_words,
                n_sents,
                avg_wl,
                has_code,
                n_code_b,
                is_analysis,
                is_generation,
                is_classif,
                is_search,
                is_synthesis,
                is_review,
                is_translation,
                dom_code,
                dom_rag,
                dom_watch,
                dom_arch,
                dom_sec,
                dom_ops,
                dom_data,
                dom_doc,
                is_urgent,
                is_error,
                is_debug,
                has_url,
                has_path,
                has_json,
                has_num,
                has_list,
                hint_local,
                hint_fast,
                hint_large_ctx,
                n_chars_norm,
                is_question,
                agent_load,
                prov_fail,
                provider_health_score,
            ],
            dtype=np.float32,
        )
        assert len(vec) == FEATURE_DIM
        return vec


# ── Dataset bootstrap ─────────────────────────────────────────────────────────

_BOOTSTRAP = [
    # (prompt_keywords, task_type, provider)
    ("python def class import refactor", "analyze_code", "llamacpp"),
    ("vectorise embed chunk rag search", "vectorize", "ollama"),
    ("résume log erreur crash service", "summarize_log", "groq"),
    ("génère queries recherche filtre", "generate_queries", "groq"),
    ("architecture design pattern solid decision", "architecture", "claude"),
    ("security audit vulnerability cve", "security_audit", "claude"),
    ("analyse large fichier entier ctx", "analyze_large", "gemini"),
    ("write docs docstring readme guide", "write_docs", "gemini"),
    ("code review pull request check", "code_review", "gpt4o_github"),
    ("synthèse résultats rapport final", "synthesize_short", "groq"),
    ("watch veille github pypi release", "research", "groq"),
    ("translate traduction english french", "classify_domain", "groq"),
    ("filter classify label tag triage", "filter_results", "groq"),
    ("benchmark eval compare report", "benchmark_eval", "gemini"),
    ("urgent error crash fix bug broken", "summarize_log", "groq"),
    ("kimi analyse architecture decision critique", "architecture", "kimi_think"),
    ("glm analyse code python", "analyze_code", "glm5"),
    ("deepseek code generate implement", "write_tests", "deepseek"),
    ("web search fact current events", "web_search_agent", "groq"),
    ("data sql sqlite query schema", "analyze_code", "ollama"),
    ("debug trace log inspect verbose", "summarize_log", "groq"),
    ("docker kubernetes deploy service", "analyze_code", "groq"),
    ("write report changelog docs", "write_report", "gemini"),
    ("classify domain route task type", "classify_domain", "groq"),
    ("rag ingest embed chunk pipeline", "vectorize", "ollama"),
    ("security sandbox guard token auth", "security_audit", "claude"),
    ("analyze code local fast compile", "py_compile", "llamacpp"),
    ("critical architecture design", "design_decision", "claude"),
    ("generate tests write code implement", "write_tests", "ollama"),
    ("summarize long file large context", "summarize_long", "gemini"),
    # Exemples contrastés providers rares -- correction erreurs DT
    ("kimi reasoning architecture critique structure", "architecture", "kimi_think"),
    ("kimi evaluate design decision critique archi", "design_decision", "kimi_think"),
    ("kimi think analyse decision system component", "analyze_code", "kimi_think"),
    ("glm analyse code python function module", "analyze_code", "glm5"),
    ("glm generate text classify label task", "classify_domain", "glm5"),
    ("deepseek code implement generate function py", "write_tests", "deepseek"),
    ("deepseek write implement python code module", "analyze_code", "deepseek"),
    ("security audit cve vulnerability pentest auth", "security_audit", "claude"),
    ("docker kubernetes deploy ops service restart", "classify_domain", "groq"),
    ("write docs docstring readme explain guide api", "write_docs", "gemini"),
    ("code review pr check quality review pull", "code_review", "gpt4o_github"),
    ("sql sqlite schema query local data analyze", "analyze_code", "ollama"),
    ("embed local pipeline rag index vectorize", "vectorize", "ollama"),
    ("fast classify filter synthesize short quick", "filter_results", "groq"),
    ("large analyze million tokens context long ctx", "analyze_large", "gemini"),
]


def _make_dataset():
    """Construit X,y depuis bootstrap + données live."""
    ext = TextFeatureExtractor()
    X, y = [], []
    _skipped_lines: list[str] = []

    for prompt, task_type, provider in _BOOTSTRAP:
        if provider not in P2I:
            continue
        vec = ext.extract(prompt, task_type)
        X.append(vec)
        y.append(P2I[provider])

    # Données live
    if DATA_PATH.exists():
        for line in DATA_PATH.read_bytes().decode("utf-8", "replace").splitlines():
            try:
                d = json.loads(line)
                vec = np.array(d["features"], dtype=np.float32)
                label = P2I.get(d.get("provider", ""))
                if vec.shape[0] == FEATURE_DIM and label is not None:
                    X.append(vec)
                    y.append(label)
            except Exception as e:
                # Sans trace, un dataset a moitie corrompu s'entraine sur une
                # poignee d'exemples en annoncant le succes.
                _skipped_lines.append(str(e)[:120])
        if _skipped_lines:
            logger.warning(
                f"[DTRouter] dataset: {len(_skipped_lines)} ligne(s) illisible(s) ecartee(s), "
                f"1re cause: {_skipped_lines[0]}"
            )

    return np.array(X, dtype=np.float32), np.array(y, dtype=np.int32)


# ── Modèle ────────────────────────────────────────────────────────────────────

_MODEL = None


def _load_or_train():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    from sklearn.tree import DecisionTreeClassifier
    import joblib

    if MODEL_PATH.exists():
        try:
            _MODEL = joblib.load(str(MODEL_PATH))
            logger.info(f"[DTRouter] modèle chargé ({MODEL_PATH.stat().st_size // 1024}KB)")
            return _MODEL
        except Exception as e:
            logger.warning(f"[DTRouter] chargement échoué: {e} — réentraînement")

    X, y = _make_dataset()
    clf = DecisionTreeClassifier(max_depth=5, min_samples_leaf=2, random_state=42)
    clf.fit(X, y)
    acc = clf.score(X, y)
    logger.info(f"[DTRouter] entraîné sur {len(X)} exemples, acc={acc:.1%}")
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    import joblib

    joblib.dump(clf, str(MODEL_PATH))
    _MODEL = clf
    return _MODEL


# Règles dures : overrides DT pour cas critiques (sécurité, architecture)
# Le DT apprend ces cas avec le temps via log_decision()
HARD_RULES: list[tuple[list[str], str]] = [
    # task_type match → provider forcé
    (["security_audit", "design_decision"], "claude"),
    (["architecture"], "claude"),
    (["analyze_large", "summarize_long"], "gemini"),
    (["vectorize", "rag_search", "py_compile"], "local"),
]


def _apply_hard_rules(task_type: str) -> str:
    """Retourne provider forcé si le task_type est dans HARD_RULES, sinon ''."""
    for task_types, provider in HARD_RULES:
        if task_type in task_types:
            return provider
    return ""


def predict(prompt: str, task_type: str = "", confidence_threshold: float = 0.6) -> tuple[str, float]:
    """
    Prédit le provider optimal.
    Retourne (provider_name, confidence).
    Si confidence < threshold → retourne ("", 0.0) pour fallback sur router statique.
    """
    try:
        clf = _load_or_train()
        ext = TextFeatureExtractor()
        vec = ext.extract(prompt, task_type).reshape(1, -1)
        proba = clf.predict_proba(vec)[0]
        idx = int(np.argmax(proba))
        conf = float(proba[idx])
        if conf < confidence_threshold:
            return "", conf
        return I2P.get(idx, "groq"), conf
    except Exception as e:
        logger.debug(f"[DTRouter] predict error: {e}")
        return "", 0.0


def log_decision(prompt: str, task_type: str, provider: str, latency_ms: float, ok: bool) -> None:
    """
    Enregistre une décision réelle pour améliorer le modèle.
    Appelé après chaque route() réussie.
    Auto-train trigger : accuracy < 0.85 ou n_samples > 1000.
    """
    try:
        ext = TextFeatureExtractor()
        vec = ext.extract(prompt, task_type)
        entry = {
            "ts": time.time(),
            "task_type": task_type,
            "provider": provider,
            "latency_ms": latency_ms,
            "ok": ok,
            "features": vec.tolist(),
        }
        with DATA_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        update_provider_health(provider, latency_ms, ok)

        # Auto-train logic
        # On lit les dernières lignes pour estimer l'accuracy (simplifié ici)
        # On déclenche si fichier > 1000 lignes ou périodiquement
        # Pour faire simple, on compte les lignes.
        try:
            line_count = 0
            with DATA_PATH.open("r", encoding="utf-8") as f:
                for _ in f:
                    line_count += 1

            if line_count > 1000:
                logger.info(f"[DTRouter] Trigger auto-train (n={line_count})")
                retrain()
            elif line_count > 0 and line_count % 100 == 0:
                # Check accuracy périodique sur les 100 derniers
                res = retrain()  # retrain() calcule l'accuracy sur tout le set
                if res.get("accuracy", 1.0) < 0.85:
                    logger.info(f"[DTRouter] Accuracy faible ({res['accuracy']}), modèle mis à jour.")
        except Exception as e:
            logger.warning(f"[DTRouter] auto-train impossible: {e}")

    except Exception as e:
        logger.debug(f"[DTRouter] log_decision: {e}")


def update_provider_health(provider: str, latency_ms: float, ok: bool) -> None:
    """UPSERT dans provider_scores avec EMA sur ttft_ms (alpha=0.3)."""
    try:
        import sqlite3
        from datetime import datetime

        db_path = ROOT / "RAG" / "embeddings.db"
        conn = sqlite3.connect(str(db_path), timeout=2)
        conn.execute("PRAGMA journal_mode=WAL")
        row = conn.execute("SELECT ttft_ms FROM provider_scores WHERE provider=?", (provider,)).fetchone()
        if row:
            new_ttft = int(0.3 * latency_ms + 0.7 * (row[0] or latency_ms))
        else:
            new_ttft = int(latency_ms)
        grade = "A" if new_ttft < 500 else "B" if new_ttft < 1500 else "C"
        conn.execute(
            "INSERT OR REPLACE INTO provider_scores (provider, ttft_ms, grade, status, measured_at) VALUES (?,?,?,?,?)",
            (provider, new_ttft, grade, "ok" if ok else "fail", datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"[DTRouter] update_provider_health: {e}")


def retrain() -> dict:
    """Réentraîne le modèle sur toutes les données disponibles."""
    global _MODEL
    from sklearn.tree import DecisionTreeClassifier
    import joblib

    X, y = _make_dataset()
    if len(X) < 10:
        return {"ok": False, "error": f"Pas assez de données ({len(X)}<10)"}

    clf = DecisionTreeClassifier(max_depth=5, min_samples_leaf=2, random_state=42)
    clf.fit(X, y)
    acc = clf.score(X, y)
    joblib.dump(clf, str(MODEL_PATH))
    _MODEL = clf

    # Résumé feature importance
    importance = sorted(zip(FEATURE_NAMES, clf.feature_importances_), key=lambda x: -x[1])[:5]

    return {
        "ok": True,
        "samples": len(X),
        "accuracy": round(acc, 3),
        "top_features": [(n, round(v, 3)) for n, v in importance],
    }


_SNN_ROUTER = None
_SNN_ETAT = None  # None = pas encore tente ; sinon raison de l'indisponibilite


def _snn_router():
    """Etage L1 : instance unique, modele PRE-ENTRAINE charge depuis le disque.

    Jamais d'entrainement dans le hot path : un routeur qui apprend au premier
    appel transforme une decision sub-ms en plusieurs secondes. Modele absent
    -> etage inactif, le DT prend la main (voir `--train` du module).
    """
    global _SNN_ROUTER, _SNN_ETAT
    if _SNN_ROUTER is not None or _SNN_ETAT is not None:
        return _SNN_ROUTER
    try:
        from nokido_agent.app.forge_snn_router import SNNRouter

        r = SNNRouter()
        if not r.load():
            # Pas une erreur : l'etage est simplement non provisionne.
            _SNN_ETAT = "modele absent (lancer forge_snn_router.py --train)"
            logger.info(f"[DTRouter] etage SNN inactif : {_SNN_ETAT}")
            return None
        _SNN_ROUTER = r
        logger.info("[DTRouter] etage SNN actif")
    except Exception as e:  # noqa: BLE001 - torch/dill peuvent manquer
        # Loggue UNE fois : sans cela, un etage mort reste invisible.
        _SNN_ETAT = str(e)[:160]
        logger.info(f"[DTRouter] etage SNN indisponible : {_SNN_ETAT}")
    return _SNN_ROUTER


# NOTE — la branche "spike" a ete RETIREE de route_with_dt le 2026-08-20.
# Elle appelait forge_spike_router.SpikeRouter, dont route() rappelle
# route_with_dt : une RECURSION que seul un garde threading.local rendait
# finie, et qui redescendait invariablement au DT ci-dessous. Le SNN
# CTFSpikeRouter n'y etait JAMAIS appele (il consomme des ChallengeFeatures
# CTF, espace etranger aux 35 features texte). Cout net : un aller-retour,
# un _load_or_train() par requete, et un provider fantome ("orchestrator",
# l'etiquette de systeme) propage a la place de la vraie decision.
# Pour brancher un vrai routeur SNN : le poser ICI, en priorite 2, en
# exigeant qu'il rende un provider de PROVIDERS — pas une etiquette.


def route_with_dt(task_type: str, prompt: str, fallback_fn=None) -> tuple[str, float, str]:
    """
    Route principale : hard rules → SNN (L1) → DT → fallback statique.
    Retourne (provider, confidence, source).
    source = "hard" | "snn" | "dt" | "static"
    """
    # Priorité 1 : règles dures non-négociables (sécurité, archi)
    hard = _apply_hard_rules(task_type)
    if hard and hard != "local":
        logger.debug(f"[DTRouter] HARD → {hard} (task={task_type})")
        return hard, 1.0, "hard"

    # Priorité 2 : etage SNN (L1). Il s'abstient des qu'il doute, et rend alors
    # la main au DT ci-dessous : c'est sa valeur, pas un defaut.
    _snn = _snn_router()
    if _snn is not None:
        try:
            d = _snn.predict(prompt, task_type)
            if d.route == "provider" and d.provider in PROVIDERS:
                logger.debug(
                    f"[DTRouter] SNN → {d.provider} conf={d.confidence:.2f} "
                    f"unc={d.uncertainty:.2f}"
                )
                return d.provider, d.confidence, "snn"
            if d.route == "provider":
                # Un etage qui rend un provider inconnu est casse, pas incertain.
                logger.warning(f"[DTRouter] SNN provider inconnu '{d.provider}' → DT")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[DTRouter] etage SNN en echec, repli DT : {e}")

    # Priorité 3 : DT
    provider, conf = predict(prompt, task_type)
    if provider:
        logger.debug(f"[DTRouter] DT → {provider} conf={conf:.2f}")
        return provider, conf, "dt"

    # Priorité 4 : fallback statique
    if fallback_fn:
        p = fallback_fn(task_type)
    else:
        from nokido_agent.app.forge_task_router import select_provider

        p = select_provider(task_type)
    return p, 1.0, "static"


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # Entraîner + afficher stats
    result = retrain()
    print(f"\nEntraînement: {result}")

    # Tests
    tests = [
        ("analyse large document complet", "analyze_large"),
        ("génère tests python def class", "write_tests"),
        ("urgent crash error service broken", "summarize_log"),
        ("architecture design pattern critique", "architecture"),
        ("résume log filtre résultats rapide", "synthesize_short"),
        ("vectorise embed chunk rag pipeline", "vectorize"),
        ("security audit vulnerability cve", "security_audit"),
        ("kimi analyse architecture decision", "architecture"),
    ]
    print("\nPrédictions:")
    for prompt, task_type in tests:
        p, conf, src = route_with_dt(task_type, prompt)
        print(f"  [{src:6s}] {task_type:22s} → {p:15s} conf={conf:.2f}  '{prompt[:40]}'")
