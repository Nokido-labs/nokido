"""Step 4 epistemic: classifier is_technical vs is_normative pour claims.

Mode hybride :
  1. Bootstrap KEYWORD : regles deterministes (score > 0.6 = technique)
  2. Upgrade MLP : BGE-M3 embedding + reseau 2 couches PyTorch
                   (active si data/claim_classifier.pt existe)

Inference < 5ms en mode keyword, < 50ms en mode MLP (ZMQ vers brain_worker).

API :
    is_technical(claim_text, predicates=None) -> (bool, confidence)
"""

from __future__ import annotations
import logging
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MLP_WEIGHTS = ROOT / "data" / "claim_classifier.pt"

logger = logging.getLogger("claim_classifier")


# --- Bootstrap keyword-based heuristic ---

TECHNICAL_KEYWORDS = frozenset(
    {
        # measurable/testable
        "detectable",
        "undetectable",
        "vulnerable",
        "exploit",
        "exploitable",
        "complexity",
        "latency",
        "throughput",
        "accuracy",
        "precision",
        "recall",
        "f1",
        "auc",
        "bleu",
        "rouge",
        "robust",
        "performance",
        "benchmark",
        "scalability",
        "concurrent",
        "parallel",
        "deterministic",
        # math/algo
        "hash",
        "signature",
        "polynomial",
        "np-hard",
        "convergence",
        "gradient",
        "entropy",
        "kl",
        "divergence",
        # security technical
        "cve",
        "rce",
        "xss",
        "sqli",
        "buffer overflow",
        "race condition",
        "sandbox",
        "isolation",
        "authentication",
        "authorization",
        "encryption",
        "decryption",
        "leak",
        "bypass",
        # systems
        "bandwidth",
        "memory",
        "cpu",
        "gpu",
        "ram",
        "cache",
        "p99",
        "p95",
        "rps",
        "tps",
        # ML/AI technical
        "loss",
        "tokens",
        "context window",
        "fine-tune",
        "fine-tuned",
        "rag",
        "embedding",
        "vectorize",
        "chunk",
        "retrieval",
        "rerank",
        # measurable outcomes
        "passes",
        "fails",
        "test",
        "score",
        "metric",
        "rate",
    }
)

NORMATIVE_KEYWORDS = frozenset(
    {
        # opinion/value
        "ethical",
        "ethics",
        "responsible",
        "fair",
        "fairness",
        "bias",
        "should",
        "ought",
        "recommended",
        "best practice",
        "must",
        "transparent",
        "accountable",
        "governance",
        "policy",
        "stakeholder",
        "compliance",
        "regulation",
        "law",
        # social
        "harm",
        "harmful",
        "benefit",
        "beneficial",
        "trust",
        "trustworthy",
        "consent",
        "privacy",
        "dignity",
        "values",
        "principles",
        # subjective
        "good",
        "bad",
        "better",
        "worse",
        "preferable",
        "acceptable",
        "controversial",
        "debate",
        "opinion",
        "perspective",
        # legal/regulatory
        "license",
        "agpl",
        "mit",
        "copyright",
        "patent",
        "ip",
        "intellectual",
        "gdpr",
        "hipaa",
        "soc2",
        "iso27001",
    }
)

# Patterns regex
RE_QUANTITATIVE = re.compile(
    r"\b\d+(\.\d+)?\s*(%|ms|s|min|h|tok|token|chars?|byte|kb|mb|gb|tb)\b|\b(\d+x|10\^)\b", re.IGNORECASE
)
RE_NORMATIVE_MODAL = re.compile(r"\b(should|ought|must|ought to|recommended|advisable)\b", re.IGNORECASE)


def _keyword_score(text: str, predicates: list[str] | None = None) -> tuple[float, float]:
    """Retourne (technical_score, normative_score) entre 0 et 1."""
    haystack = text.lower()
    if predicates:
        haystack += " " + " ".join(predicates).lower()

    tech_hits = sum(1 for kw in TECHNICAL_KEYWORDS if kw in haystack)
    norm_hits = sum(1 for kw in NORMATIVE_KEYWORDS if kw in haystack)

    # Bonus quantitatif
    if RE_QUANTITATIVE.search(text):
        tech_hits += 2
    # Bonus modal normatif
    if RE_NORMATIVE_MODAL.search(text):
        norm_hits += 2

    total = tech_hits + norm_hits
    if total == 0:
        return 0.5, 0.5  # ambigu : prior technique
    return tech_hits / total, norm_hits / total


def is_technical_keyword(
    claim_text: str, predicates: list[str] | None = None, threshold: float = 0.6
) -> tuple[bool, float]:
    """Heuristique keyword-based. Retourne (is_technical, confidence)."""
    tech, _ = _keyword_score(claim_text, predicates)
    return tech >= threshold, tech


# --- MLP upgrade (when trained) ---

_mlp_model = None


def _load_mlp():
    """Lazy load MLP si poids disponibles."""
    global _mlp_model
    if _mlp_model is not None:
        return _mlp_model
    if not MLP_WEIGHTS.exists():
        return None
    try:
        import torch
        import torch.nn as nn

        class ClaimMLP(nn.Module):
            def __init__(self, dim_in=1024, dim_hidden=128):
                super().__init__()
                self.net = nn.Sequential(
                    nn.Linear(dim_in, dim_hidden),
                    nn.ReLU(),
                    nn.Dropout(0.2),
                    nn.Linear(dim_hidden, 2),
                )

            def forward(self, x):
                return self.net(x)

        m = ClaimMLP()
        m.load_state_dict(torch.load(MLP_WEIGHTS, map_location="cpu"))
        m.eval()
        _mlp_model = m
        logger.info(f"Loaded MLP from {MLP_WEIGHTS}")
        return m
    except Exception as e:
        logger.debug(f"MLP load failed: {e}")
        return None


def _embed_via_brain_worker(text: str) -> list[float] | None:
    """Get BGE-M3 embedding via ZMQ brain_worker :5557. Retourne None si KO."""
    try:
        import zmq
        import msgpack

        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.RCVTIMEO, 5000)
        sock.connect("tcp://localhost:5557")
        sock.send(msgpack.packb({"cmd": "submit", "type": "embed", "texts": [text]}, use_bin_type=True))
        rep = msgpack.unpackb(sock.recv(), raw=False)
        task_id = rep.get("task_id")
        if not task_id:
            return None
        # Poll
        import time

        for _ in range(20):
            sock.send(msgpack.packb({"cmd": "check", "task_id": task_id}, use_bin_type=True))
            r = msgpack.unpackb(sock.recv(), raw=False)
            if r.get("status") == "completed":
                data = r.get("data")
                vecs = data.get("vecs", []) if isinstance(data, dict) else data
                return vecs[0] if vecs else None
            time.sleep(0.3)
        return None
    except Exception as e:
        logger.debug(f"embed failed: {e}")
        return None
    finally:
        try:
            sock.close()
        except Exception:
            pass


def is_technical_mlp(claim_text: str) -> tuple[bool, float] | None:
    """MLP-based si modele present. Retourne None si pas dispo."""
    model = _load_mlp()
    if model is None:
        return None
    emb = _embed_via_brain_worker(claim_text)
    if emb is None:
        return None
    try:
        import torch

        with torch.no_grad():
            logits = model(torch.tensor(emb).float().unsqueeze(0))
            probs = torch.softmax(logits, dim=-1)[0]
            tech_prob = float(probs[1])
            return tech_prob >= 0.5, tech_prob
    except Exception as e:
        logger.debug(f"MLP inference failed: {e}")
        return None


# --- API publique ---


@lru_cache(maxsize=1024)
def _cached_classify(text: str, predicates_key: str) -> tuple[bool, float]:
    preds = predicates_key.split("|") if predicates_key else []
    # Try MLP first if available
    mlp = is_technical_mlp(text)
    if mlp is not None:
        return mlp
    # Fallback keyword
    return is_technical_keyword(text, preds)


def is_technical(claim_text: str, predicates: list[str] | None = None) -> tuple[bool, float]:
    """API publique. Retourne (is_technical, confidence).
    Cache LRU 1024 entries pour eviter recompute sur extracteur batch."""
    pkey = "|".join(predicates or [])
    return _cached_classify(claim_text, pkey)


# --- CLI test ---


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", help="Claim to classify (or read examples)")
    args = ap.parse_args()

    examples = [
        ("LSB steganography in JPEG is undetectable by SVM-based steganalysis", ["lsb", "jpeg", "undetectable", "svm"]),
        ("AI systems should respect user privacy and consent", ["privacy", "consent", "ethical"]),
        ("BGE-M3 achieves 90.5% accuracy on MTEB benchmark", ["bge-m3", "accuracy", "benchmark"]),
        ("Open source models are more transparent than proprietary ones", ["transparent", "open source"]),
        ("Cerebras inference latency p99 is 380ms for llama-3.3-70b", ["latency", "cerebras", "llama"]),
        ("Researchers ought to follow ethical guidelines in dual-use research", ["ethical", "dual-use"]),
    ]

    if args.text:
        is_tech, conf = is_technical(args.text)
        print(f"text: {args.text}")
        print(f"is_technical={is_tech} confidence={conf:.3f}")
    else:
        print(f"{'TECHNICAL':>10} | {'conf':>5} | text")
        print("-" * 80)
        for text, preds in examples:
            is_tech, conf = is_technical(text, preds)
            marker = "TECH" if is_tech else "NORM"
            print(f"{marker:>10} | {conf:.3f} | {text[:60]}")


if __name__ == "__main__":
    main()
