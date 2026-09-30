"""
forge_semantic_routes.py — embedding route-matcher with threshold optimization.

Mined from aurelio-labs/semantic-router: a superfast decision layer that routes
an utterance to a named route by EMBEDDING similarity (0 LLM call), with per-route
similarity thresholds TUNED from labeled data (the project's key idea). Reuses the
sovereign embedder via forge_embed_router.embed (BGE-M3 :8099) -> no new backend.

Net-new in Nokido: the existing routers (forge_nlu FastClassifier, forge_byte_router,
forge_cognitive_router, forge_orchestration_gate) decide by keywords / complexity /
LLM. This adds a declarative, embedding-threshold route layer usable as a fast
pre-classifier / guardrail, with data-driven threshold tuning.

API:
    sr = SemanticRouter()
    sr.add_route("politics", ["who won the election", "tax policy", ...])
    sr.add_route("chitchat", ["how are you", "nice weather", ...])
    sr.fit()                       # embed utterances
    sr.route("what about the senate vote?")          -> "politics" | None
    sr.optimize_thresholds(labeled)                  # tune per-route cutoffs
    sr.save(path) / SemanticRouter.load(path)
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "metabolisme/cognitive_router : route-matcher par embedding avec seuil"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import math

try:
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None

DEFAULT_THRESHOLD = 0.5


def _embed(text):
    from nokido_agent.app.forge_embed_router import embed
    return embed(text)


def _cosine(a, b):
    if _np is not None:
        va, vb = _np.asarray(a, dtype=float), _np.asarray(b, dtype=float)
        na, nb = float(_np.linalg.norm(va)), float(_np.linalg.norm(vb))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return float(va.dot(vb) / (na * nb))
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class Route:
    def __init__(self, name, utterances, threshold=DEFAULT_THRESHOLD, vectors=None):
        self.name = name
        self.utterances = list(utterances)
        self.threshold = float(threshold)
        self.vectors = vectors or []  # list[list[float]]


class SemanticRouter:
    """Embedding route layer. fit() embeds utterances; route() returns the best
    route whose max-utterance similarity clears its threshold, else None."""

    def __init__(self, embed_fn=None):
        self._routes = {}
        self._embed = embed_fn or _embed

    def add_route(self, name, utterances, threshold=DEFAULT_THRESHOLD):
        self._routes[name] = Route(name, utterances, threshold)
        return self

    def fit(self):
        """Embed all utterances. Skips ones the embedder can't encode."""
        for r in self._routes.values():
            r.vectors = []
            for u in r.utterances:
                v = self._embed(u)
                if v and len(v) >= 256:
                    r.vectors.append(list(v))
        return self

    def _scores(self, query):
        """Return {route_name: max_similarity} for an embedded query."""
        qv = self._embed(query)
        if not qv:
            return {}, None
        out = {}
        for name, r in self._routes.items():
            out[name] = max((_cosine(qv, v) for v in r.vectors), default=0.0)
        return out, qv

    def route(self, query):
        """Best route clearing its threshold, else None. Returns (name, score)."""
        scores, _ = self._scores(query)
        best, best_s = None, -1.0
        for name, s in scores.items():
            if s >= self._routes[name].threshold and s > best_s:
                best, best_s = name, s
        return (best, best_s) if best else (None, best_s if best_s >= 0 else 0.0)

    def optimize_thresholds(self, labeled, grid=None):
        """Tune each route threshold to maximize F1 on labeled = list of
        (text, route_name_or_None). semantic-router's core idea: data-driven
        cutoffs instead of a fixed 0.5."""
        grid = grid or [i / 100.0 for i in range(20, 96, 5)]
        sims = []  # (scores_dict, gold)
        for text, gold in labeled:
            s, _ = self._scores(text)
            sims.append((s, gold))
        for name, r in self._routes.items():
            best_t, best_f1 = r.threshold, -1.0
            for t in grid:
                tp = fp = fn = 0
                for s, gold in sims:
                    pred = name if s.get(name, 0.0) >= t else None
                    # 1-vs-rest at this route's cutoff
                    if gold == name and pred == name:
                        tp += 1
                    elif gold != name and pred == name:
                        fp += 1
                    elif gold == name and pred != name:
                        fn += 1
                prec = tp / (tp + fp) if (tp + fp) else 0.0
                rec = tp / (tp + fn) if (tp + fn) else 0.0
                f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
                if f1 > best_f1:
                    best_f1, best_t = f1, t
            r.threshold = best_t
        return {n: r.threshold for n, r in self._routes.items()}

    def to_dict(self):
        return {"routes": [{"name": r.name, "utterances": r.utterances,
                            "threshold": r.threshold, "vectors": r.vectors}
                           for r in self._routes.values()]}

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f)

    @classmethod
    def load(cls, path, embed_fn=None):
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        sr = cls(embed_fn=embed_fn)
        for r in d.get("routes", []):
            sr._routes[r["name"]] = Route(r["name"], r["utterances"],
                                          r.get("threshold", DEFAULT_THRESHOLD),
                                          r.get("vectors"))
        return sr


_INTENT_ROUTER = None


def intent_router():
    """Cached SemanticRouter pre-fit on Nokido NLU intents (chat/action/rag).
    Consumed by forge_nlu.hybrid_classify (opt-in LAFORGE_NLU_SEMANTIC=1) as an
    embedding fallback when the predictive NaiveBayes router isn't confident.
    Debate verdict 2026-06-21: wire into NLU (natural fit, low hot-path risk),
    NOT the orchestration gate (lane decided by cost, not topic)."""
    global _INTENT_ROUTER
    if _INTENT_ROUTER is None:
        sr = SemanticRouter()
        sr.add_route("chat", ["hello how are you", "tell me a joke", "what's up",
                              "thanks a lot", "good morning", "let us chat a bit"])
        sr.add_route("action", ["run the tests", "deploy the service", "edit the file",
                                "restart the server", "create a script", "fix the bug now"])
        sr.add_route("rag", ["what do the docs say about this", "search the codebase",
                             "find information about the module", "explain how the system works",
                             "look up the reference documentation"])
        sr.fit()
        _INTENT_ROUTER = sr
    return _INTENT_ROUTER


def _selftest():
    """Live test against the sovereign embedder. SKIPs (rc=0) if embedder down."""
    probe = _embed("connectivity probe sentence")
    if not probe:
        print(json.dumps({"skip": "embedder unavailable (:8099 down)"}))
        return 0
    sr = SemanticRouter()
    sr.add_route("politics", ["who won the election", "the senate passed a bill",
                              "tax policy reform", "the president vetoed the law"])
    sr.add_route("chitchat", ["how are you today", "nice weather we are having",
                              "what is your favorite food", "did you sleep well"])
    sr.fit()
    name, score = sr.route("what about the latest vote in congress?")
    routed_ok = name == "politics"
    labeled = [("the governor signed the budget", "politics"),
               ("lovely sunny morning", "chitchat"),
               ("how's it going", "chitchat"),
               ("parliament debate on the new law", "politics")]
    thresholds = sr.optimize_thresholds(labeled)
    print(json.dumps({"routed": name, "score": round(score, 3),
                      "routed_ok": routed_ok, "thresholds": thresholds,
                      "pass": routed_ok}, ensure_ascii=False))
    return 0 if routed_ok else 1


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
