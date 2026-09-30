"""
predictif.py — Moteur NLU adaptatif pour OctoDevOps
=====================================================
OctoDevOps v5

Principe :
  Le NLU statique (regex) classe correctement ~80 % des entrées.
  Pour les 20 % restants (formulations naturelles ambiguës, accents,
  fautes de frappe, phrases mixtes), ce moteur apprend des corrections
  utilisateur et affine le routage en temps réel.

Architecture :
  FastClassifier (< 1 ms, zéro I/O)
    → features extraites du texte brut
    → score bayésien chat/action/rag par feature
    → confiance >= seuil  → décision immédiate
    → sinon : fallback NLU statique (regex Nokido)

  AdaptiveLearner
    → enregistre (texte, intent_prédit, intent_corrigé)
    → met à jour les scores bayésiens
    → persistance JSON  (léger, sans dépendances)

Usage dans Nokido :
    from predictif import load_router, hybrid_classify

    router = load_router()
    intent_str, cmd, conf = hybrid_classify(text, static_fn, router)
    router.feedback(text, predicted="action", correct="chat")

Commandes TUI :
    @nlu stats               rapport du modele
    @nlu test <phrase>       prediction detaillee
    @nlu chat   <phrase>     enseigne : cette phrase = conversation
    @nlu action <phrase>     enseigne : cette phrase = terminal
    @nlu rag    <phrase>     enseigne : cette phrase = docs
"""

from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

INTENTS = ("chat", "action", "rag")


# =============================================================================
# RESULTAT DE PREDICTION
# =============================================================================


@dataclass
class IntentVote:
    intent: str
    confidence: float
    confident: bool
    scores: Dict[str, float] = field(default_factory=dict)
    features: List[str] = field(default_factory=list)
    source: str = "predictif"


# =============================================================================
# EXTRACTION DE FEATURES  (O(n), sans reseau)
# =============================================================================


class FeatureExtractor:
    import re as _re

    _ACT = frozenset(
        {
            "redémarre",
            "restart",
            "arrête",
            "stop",
            "start",
            "stoppe",
            "démarre",
            "lance",
            "installe",
            "désinstalle",
            "upgrade",
            "update",
            "reload",
            "enable",
            "disable",
            "purge",
            "reboot",
            "shutdown",
            "active",
            "désactive",
            "supprime",
            "efface",
            "copie",
            "déplace",
            "monte",
            "démonte",
            "connecte",
            "déconnecte",
            "formate",
            "kill",
            "killall",
            "chmod",
            "chown",
            "mv",
            "cp",
            "rm",
        }
    )
    _CHAT = frozenset(
        {
            "pourquoi",
            "quand",
            "combien",
            "lequel",
            "laquelle",
            "lesquels",
            "merci",
            "bonjour",
            "salut",
            "bonsoir",
            "svp",
            "stp",
            "expliquer",
            "comprendre",
            "différence",
            "avantage",
            "inconvénient",
        }
    )
    _RAG = frozenset(
        {
            "documentation",
            "manuel",
            "guide",
            "procédure",
            "runbook",
            "référence",
            "fiche",
            "memo",
            "tutoriel",
            "howto",
        }
    )

    import re as _re2

    _PATH = _re2.compile(r"(/[\w./\-]+|~[\w./\-]+|\.{1,2}/[\w./\-]+)")
    _IP = _re2.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
    _FLAG = _re2.compile(r"\s-{1,2}[\w-]+")
    _URL = _re2.compile(r"https?://\S+")

    def extract(self, text: str) -> List[str]:
        feats: List[str] = []
        lower = text.lower().strip()
        words = lower.split()
        if not words:
            return ["EMPTY"]

        first = words[0]
        feats.append(f"W0_{first[:5]}")

        for i in range(min(3, len(words) - 1)):
            feats.append(f"BG_{words[i]}_{words[i + 1]}")

        tail = text.rstrip()
        if tail.endswith("?"):
            feats.append("END_Q")
        if tail.endswith("."):
            feats.append("END_DOT")
        if tail.endswith("!"):
            feats.append("END_EXCL")

        ws = set(words)
        for w in ws & self._ACT:
            feats.append(f"ACT_{w}")
        if ws & self._CHAT:
            feats.append("CHAT_MARKER")
        if ws & self._RAG:
            feats.append("RAG_MARKER")

        if self._PATH.search(text):
            feats.append("HAS_PATH")
        if self._IP.search(text):
            feats.append("HAS_IP")
        if self._FLAG.search(text):
            feats.append("HAS_FLAG")
        if self._URL.search(text):
            feats.append("HAS_URL")

        if first in ("tu", "peux-tu", "pourrais-tu", "peux"):
            feats.append("ADDR_TU")
        if first in ("je", "j"):
            feats.append("SUBJ_JE")

        n = len(words)
        feats.append("LEN_TINY" if n <= 2 else "LEN_SHORT" if n <= 5 else "LEN_MED" if n <= 12 else "LEN_LONG")

        FR = {
            "le",
            "la",
            "les",
            "de",
            "du",
            "des",
            "un",
            "une",
            "et",
            "ou",
            "est",
            "pour",
            "sur",
            "avec",
            "dans",
            "que",
            "qui",
            "son",
            "sa",
            "ses",
        }
        if ws & FR:
            feats.append("LANG_FR")

        return feats


# =============================================================================
# CLASSIFICATEUR BAYESIEN NAIF
# =============================================================================


class NaiveBayesRouter:
    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha
        self.feature_counts: Dict[str, Dict[str, float]] = {i: defaultdict(float) for i in INTENTS}
        self.intent_counts: Dict[str, float] = {i: 0.0 for i in INTENTS}
        self.feature_totals: Dict[str, float] = {i: 0.0 for i in INTENTS}
        self.vocab: set = set()
        self.total: float = 0.0

    def train(self, features: List[str], intent: str, weight: float = 1.0):
        if intent not in INTENTS:
            return
        self.intent_counts[intent] += weight
        self.total += weight
        for f in features:
            self.feature_counts[intent][f] += weight
            self.feature_totals[intent] += weight
            self.vocab.add(f)

    def predict(self, features: List[str]) -> Dict[str, float]:
        if self.total < 1:
            return {i: 1.0 / len(INTENTS) for i in INTENTS}
        V = max(len(self.vocab), 1)
        sc: Dict[str, float] = {}
        for intent in INTENTS:
            ci = self.intent_counts[intent]
            lp = math.log((ci + self.alpha) / (self.total + self.alpha * len(INTENTS)))
            tf = self.feature_totals[intent]
            ll = 0.0
            for f in features:
                fc = self.feature_counts[intent].get(f, 0.0)
                ll += math.log((fc + self.alpha) / (tf + self.alpha * V + 1e-9))
            sc[intent] = lp + ll
        mx = max(sc.values())
        exp = {i: math.exp(s - mx) for i, s in sc.items()}
        tot = sum(exp.values()) + 1e-9
        return {i: v / tot for i, v in exp.items()}

    def to_dict(self) -> dict:
        return {
            "alpha": self.alpha,
            "feature_counts": {i: dict(v) for i, v in self.feature_counts.items()},
            "intent_counts": dict(self.intent_counts),
            "feature_totals": dict(self.feature_totals),
            "vocab": list(self.vocab),
            "total": self.total,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NaiveBayesRouter":
        obj = cls(alpha=d.get("alpha", 1.0))
        obj.intent_counts = {k: float(v) for k, v in d.get("intent_counts", {}).items()}
        obj.feature_totals = {k: float(v) for k, v in d.get("feature_totals", {}).items()}
        obj.vocab = set(d.get("vocab", []))
        obj.total = float(d.get("total", 0.0))
        for intent, counts in d.get("feature_counts", {}).items():
            obj.feature_counts[intent] = defaultdict(float, {k: float(v) for k, v in counts.items()})
        for i in INTENTS:
            obj.intent_counts.setdefault(i, 0.0)
            obj.feature_totals.setdefault(i, 0.0)
            obj.feature_counts.setdefault(i, defaultdict(float))
        return obj


# =============================================================================
# HISTORIQUE DE CORRECTIONS
# =============================================================================


@dataclass
class CorrectionEntry:
    text: str
    predicted: str
    correct: str
    ts: float
    features: List[str]


class CorrectionHistory:
    def __init__(self, maxlen: int = 200):
        self._entries: List[CorrectionEntry] = []
        self._maxlen = maxlen

    def add(self, text: str, predicted: str, correct: str, features: List[str]):
        self._entries.append(CorrectionEntry(text[:200], predicted, correct, time.time(), features))
        if len(self._entries) > self._maxlen:
            self._entries.pop(0)

    @property
    def entries(self) -> List[CorrectionEntry]:
        return self._entries

    def to_list(self) -> list:
        return [
            {"text": e.text, "predicted": e.predicted, "correct": e.correct, "ts": e.ts, "features": e.features}
            for e in self._entries
        ]

    @classmethod
    def from_list(cls, data: list) -> "CorrectionHistory":
        obj = cls()
        for d in data:
            obj._entries.append(
                CorrectionEntry(
                    text=d["text"],
                    predicted=d["predicted"],
                    correct=d["correct"],
                    ts=float(d["ts"]),
                    features=d.get("features", []),
                )
            )
        return obj


# =============================================================================
# DONNEES DE BOOTSTRAP (cas reels des logs)
# =============================================================================

BOOTSTRAP_EXAMPLES: List[Tuple[str, str]] = [
    # CHAT
    ("quel jour sommes nous", "chat"),
    ("quel jour sommes nous ?", "chat"),
    ("quelle heure est il", "chat"),
    ("sur quel modele es tu", "chat"),
    ("sur quel modele es-tu ?", "chat"),
    ("peux tu agir sur l hote", "chat"),
    ("peux tu agir sur le poste", "chat"),
    ("tu peux faire quoi", "chat"),
    ("c est quoi docker", "chat"),
    ("explique moi nginx", "chat"),
    ("comment fonctionne ssh", "chat"),
    ("quelle est la difference entre apt et apt-get", "chat"),
    ("merci ca marche", "chat"),
    ("ok super", "chat"),
    ("je veux savoir si tu peux", "chat"),
    ("tu es sur quel port", "chat"),
    ("dis moi ce que tu sais de fail2ban", "chat"),
    ("raconte moi l histoire de linux", "chat"),
    ("bonjour comment vas tu", "chat"),
    ("pourquoi mon service crash", "chat"),
    ("qu est ce que systemd", "chat"),
    ("tu connais prometheus", "chat"),
    ("c est quoi un cron job", "chat"),
    ("j ai besoin d explications sur wireguard", "chat"),
    ("analyse le poste pour voir si tu trouves des erreurs", "chat"),
    ("1", "chat"),
    ("peux tu agir sur l hote egalement", "chat"),
    # ACTION
    ("ls -la /etc", "action"),
    ("ls -la", "action"),
    ("cat /etc/hosts", "action"),
    ("systemctl restart nginx", "action"),
    ("docker ps -a", "action"),
    ("docker ps", "action"),
    ("ps aux", "action"),
    ("df -h", "action"),
    ("free -m", "action"),
    ("top", "action"),
    ("htop", "action"),
    ("redémarre nginx", "action"),
    ("arrete le service apache2", "action"),
    ("installe htop", "action"),
    ("donne moi les logs nginx", "action"),
    ("affiche le journal systeme", "action"),
    ("verifie le statut de pihole", "action"),
    ("montre moi la config adguard sur le serveur", "action"),
    ("je veux le contenu de adguard.conf", "action"),
    ("lance la commande top", "action"),
    ("check le serveur", "action"),
    ("passe la commande df -h", "action"),
    ("ip a", "action"),
    ("ss -tlnp", "action"),
    ("ping 8.8.8.8", "action"),
    ("grep error /var/log/syslog", "action"),
    ("tail -f /var/log/auth.log", "action"),
    ("donne moi la configuration d adguard sur le serveur", "action"),
    ("donne moi la conf adguard", "action"),
    ("je veux le contenu d adguard.conf", "action"),
    # RAG
    ("donne moi la documentation de nginx", "rag"),
    ("cherche des infos sur fail2ban", "rag"),
    ("trouve moi des articles sur wireguard", "rag"),
    ("documentation officielle de kubernetes", "rag"),
    ("guide de configuration de pihole", "rag"),
    ("comment configurer adguard home", "rag"),
    ("tutoriel pour installer docker", "rag"),
    ("manuel de systemd", "rag"),
    ("runbook de deploiement", "rag"),
]


# =============================================================================
# ROUTEUR PREDICTIF PRINCIPAL
# =============================================================================


class PredictiveRouter:
    DEFAULT_PATH = Path("nlu_history.json")
    THRESH_HIGH = 0.72
    THRESH_LOW = 0.52

    def __init__(
        self,
        model: NaiveBayesRouter,
        extractor: FeatureExtractor,
        history: CorrectionHistory,
        path: Path = DEFAULT_PATH,
    ):
        self.model = model
        self.extractor = extractor
        self.history = history
        self.path = path
        self._dirty = 0

    def predict(self, text: str) -> IntentVote:
        feats = self.extractor.extract(text)
        scores = self.model.predict(feats)
        best = max(scores, key=scores.get)
        conf = scores[best]
        return IntentVote(
            intent=best,
            confidence=conf,
            confident=conf >= self.THRESH_HIGH,
            scores=scores,
            features=feats,
        )

    def feedback(self, text: str, predicted: str, correct: str, weight: float = 1.0):
        if correct not in INTENTS:
            return
        feats = self.extractor.extract(text)
        if predicted != correct:
            self.model.train(feats, correct, weight=weight * 2.0)
            self.history.add(text, predicted, correct, feats)
        else:
            self.model.train(feats, correct, weight=weight * 0.4)
        self._dirty += 1
        if self._dirty >= 10:
            self.save()
            self._dirty = 0

    def train_batch(self, examples: List[Tuple[str, str]]):
        for text, intent in examples:
            self.model.train(self.extractor.extract(text), intent)

    def save(self):
        data = {
            "version": 2,
            "model": self.model.to_dict(),
            "history": self.history.to_list(),
            "saved_at": time.time(),
        }
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
            tmp.replace(self.path)
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(f"PredictiveRouter.save: {e}")

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "PredictiveRouter":
        extractor = FeatureExtractor()
        history = CorrectionHistory()
        if path.exists():
            try:
                data = json.loads(path.read_text("utf-8"))
                model = NaiveBayesRouter.from_dict(data["model"])
                history = CorrectionHistory.from_list(data.get("history", []))
                router = cls(model, extractor, history, path)
                for e in history.entries:
                    if e.predicted != e.correct:
                        model.train(e.features, e.correct, weight=1.5)
                return router
            except Exception as exc:
                import logging

                logging.getLogger(__name__).warning(f"PredictiveRouter.load failed ({exc}), rebuilding")
        model = NaiveBayesRouter(alpha=1.0)
        router = cls(model, extractor, history, path)
        router.train_batch(BOOTSTRAP_EXAMPLES)
        router.save()
        return router

    def report(self) -> str:
        total = self.model.total
        lines = [
            f"**Moteur NLU predictif**  "
            f"({int(total)} exemples, {len(self.model.vocab)} features, "
            f"seuil {self.THRESH_HIGH:.0%})\n"
        ]
        for intent in INTENTS:
            n = int(self.model.intent_counts.get(intent, 0))
            pct = (n / total * 100) if total > 0 else 0
            bar = "block" * min(20, int(pct / 5))
            lines.append(f"  `{intent:6}` {n:4} ex  {pct:4.0f}%")
        corrections = [e for e in self.history.entries if e.predicted != e.correct]
        if corrections:
            lines.append(f"\n**Corrections recentes ({len(corrections)}) :**")
            for e in corrections[-5:]:
                lines.append(f"  `{e.predicted}` -> `{e.correct}`  _{e.text[:55]}_")
        return "\n".join(lines)

    def test_sentence(self, text: str) -> str:
        vote = self.predict(text)
        lines = [
            f"**Texte** : _{text[:80]}_",
            f"**Prediction** : `{vote.intent}`  "
            f"(confiance {vote.confidence:.0%}  "
            f"{'OK decision directe' if vote.confident else 'fallback regex'})\n",
            "**Scores :**",
        ]
        for intent, s in sorted(vote.scores.items(), key=lambda x: -x[1]):
            bar = "#" * int(s * 24)
            lines.append(f"  `{intent:6}` {s:.3f}  {bar}")
        lines.append(
            f"\n**Features** ({len(vote.features)}) : "
            + ", ".join(f"`{f}`" for f in vote.features[:10])
            + ("..." if len(vote.features) > 10 else "")
        )
        return "\n".join(lines)


# =============================================================================
# SINGLETON GLOBAL
# =============================================================================

_singleton: Optional[PredictiveRouter] = None


def load_router(path: Optional[Path] = None) -> PredictiveRouter:
    global _singleton
    if _singleton is None:
        _singleton = PredictiveRouter.load(path or PredictiveRouter.DEFAULT_PATH)
    return _singleton


def get_router_if_ready() -> Optional[PredictiveRouter]:
    return _singleton


# =============================================================================
# INTEGRATION NOKIDO — classification hybride
# =============================================================================


def hybrid_classify(
    text: str,
    static_fn: Callable,
    router: Optional[PredictiveRouter] = None,
    log_fn: Optional[Callable] = None,
) -> Tuple[str, Optional[str], float]:
    """
    Classe un texte : predictif d'abord, regex en fallback.
    Retourne (intent_str, cmd_extracted, confidence).
    intent_str in {"chat", "action", "rag"}
    """
    r = router or get_router_if_ready()

    if r is not None:
        vote = r.predict(text)
        if vote.confident:
            if log_fn:
                log_fn(
                    "ROUTE",
                    "hybrid_classify",
                    "PREDICTIF confident",
                    {"intent": vote.intent, "conf": round(vote.confidence, 3), "text": text[:60]},
                )
            return vote.intent, None, vote.confidence
    else:
        vote = None

    # Fallback regex
    agent_type, cmd = static_fn(text)
    intent_str = agent_type.value

    if log_fn:
        log_fn(
            "ROUTE",
            "hybrid_classify",
            "STATIC fallback",
            {"intent": intent_str, "pred_conf": round(vote.confidence if vote else 0.0, 3), "text": text[:60]},
        )

    # Auto-feedback silencieux : aligne le predictif sur le statique
    if r is not None and vote is not None and vote.intent != intent_str:
        r.feedback(text, predicted=vote.intent, correct=intent_str, weight=0.3)

    return intent_str, cmd, 0.60
