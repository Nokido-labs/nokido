"""
forge_skill_rag_bridge.py — Pont SkillLearner ↔ RAG ↔ @disco
=============================================================

Rôle : connecter les trois systèmes sans les coupler directement.

  1. RAG → Skills  : bootstrap les états depuis les chunks existants
                     (chaque chunk domain='security' nourrit les skills détectés)

  2. Pipeline → Skills : record_success / record_error après chaque phase
                         (5 phases du pipeline déporté = 5 signaux de progression)

  3. Skills → @disco : si needs_learning() → déclenche un disco headless
                       (pas d'UI, directement via rag_engine.ingest_web_content)
                       avec cooldown et cap par cycle (respecte DISCO_COOLDOWN)

Usage depuis le pipeline :
    bridge = SkillRAGBridge.instance()
    bridge.on_pipeline_event("phase3", ["securite_audit","reseau"], severity="medium")
    await bridge.maybe_disco_all()

Usage depuis @disco (hook inverse) :
    bridge.on_disco_done("nmap port scan")  # → record_disco + monte le score

Règle Nokido : ce module ne touche pas à l'UI, pas d'import textual.
"""

from __future__ import annotations

# DEAD_IMPORT removed: import asyncio
import json
import logging
import sqlite3

try:
    import numpy as np
except ImportError:
    import math as _m

    class np:
        @staticmethod
        def exp(x):
            return _m.exp(x)


import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_RAG_DB = _ROOT / "RAG" / "embeddings.db"

# ── Map CVE/finding → skill_ids concernés ─────────────────────────────────────
FINDING_TO_SKILLS: dict[str, list[str]] = {
    # Réseau / scan
    "nmap": ["reseau_protocoles", "securite_audit"],
    "arp": ["reseau_protocoles"],
    "ssdp": ["reseau_protocoles", "reseau_monitoring"],
    "port scan": ["reseau_protocoles", "securite_audit"],
    "banner grab": ["reseau_protocoles", "securite_audit"],
    # IoT / Chromecast
    "chromecast": ["securite_audit", "reseau_protocoles"],
    "eureka_info": ["securite_audit"],
    "google cast": ["securite_audit", "reseau_protocoles"],
    "unauthenticated": ["securite_audit", "securite_hardening"],
    # Samsung / Tizen
    "samsung": ["securite_audit"],
    "tizen": ["securite_audit"],
    "remote api": ["securite_audit", "python_web"],
    "cve-2019": ["securite_audit", "securite_hardening"],
    "xss": ["securite_audit", "python_web"],
    # UPnP / SOAP
    "upnp": ["reseau_protocoles", "securite_audit"],
    "soap": ["reseau_protocoles", "python_web"],
    # SSL / PKI
    "ssl": ["securite", "reseau_protocoles"],
    "certificate": ["securite"],
    "tls": ["securite"],
    # Pickle / loguru (finding GHSA)
    "pickle": ["python_stdlib", "securite_audit"],
    "loguru": ["python_stdlib", "securite_audit"],
    "cwe-502": ["securite_audit"],
    "deserialization": ["securite_audit", "python_stdlib"],
    # Pipeline / pentest
    "pentest": ["securite_audit"],
    "exploitation": ["securite_audit"],
    "post-exploit": ["securite_audit"],
    "recon": ["securite_audit", "reseau"],
    "enumeration": ["securite_audit", "reseau_protocoles"],
    # Exegol / Docker
    "exegol": ["devops_containers", "securite_audit"],
    "docker": ["devops_containers"],
}

# ── Seuils ────────────────────────────────────────────────────────────────────
SCORE_GAIN = {
    "high": 0.25,  # finding critique → progression forte
    "medium": 0.15,
    "low": 0.08,
    "info": 0.03,
    "success": 0.10,  # tâche réussie sans finding
    "error": -0.05,
}

RAG_SCORE_THRESHOLD = 0.35  # score RAG en dessous → déclenche disco
DISCO_TRIGGER_SCORE = 0.50  # score skill en dessous → needs_learning


# ═════════════════════════════════════════════════════════════════════════════
class SkillRAGBridge:
    """
    Singleton. Relie SkillLearner, RAG, et le moteur @disco.

    Ne pas instancier directement — utiliser SkillRAGBridge.instance().
    """

    _inst: Optional["SkillRAGBridge"] = None

    @classmethod
    def instance(cls) -> "SkillRAGBridge":
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    def __init__(self) -> None:
        self._learner = None  # lazy — chargé à la demande
        self._rag_engine = None
        self._disco_queue: list[str] = []
        self._last_bootstrap = 0.0
        self._pending_disco: dict[str, float] = {}  # skill_id → last trigger ts

    # ── Accès lazy aux dépendances ─────────────────────────────────────────

    def _get_learner(self):
        if self._learner is None:
            try:
                from nokido_agent.app.skilltree import SkillLearner

                reg = _ROOT / "data" / "skill_registry.json"
                self._learner = SkillLearner(registry_path=reg)
            except Exception as e:
                logger.debug(f"SkillRAGBridge: learner unavailable ({e})")
        return self._learner

    def _get_rag_engine(self):
        if self._rag_engine is None:
            try:
                from nokido_agent.app import forge_context as _fc

                self._rag_engine = _fc.get_rag_engine()
            except Exception as e:
                logger.debug(f"SkillRAGBridge: rag_engine unavailable ({e})")
        return self._rag_engine

    # ── 1. RAG → Skills : bootstrap ───────────────────────────────────────

    def bootstrap_from_rag(self, force: bool = False) -> int:
        """
        Lit les chunks RAG domain='security' et initialise les SkillStates.

        Appelé au démarrage Nokido ou après un pipeline complet.
        Cooldown 5min pour ne pas scanner le RAG à chaque message.

        Returns:
            Nombre de skills mis à jour.
        """
        if not force and time.time() - self._last_bootstrap < 300:
            return 0

        learner = self._get_learner()
        if learner is None:
            return 0

        if not _RAG_DB.exists():
            return 0

        updated = 0
        try:
            conn = sqlite3.connect(str(_RAG_DB), timeout=5)
            rows = conn.execute("SELECT text, meta FROM rag_chunks WHERE domain='security' LIMIT 200").fetchall()
            conn.close()
        except Exception as e:
            logger.debug(f"bootstrap_from_rag: {e}")
            return 0

        for text, meta_str in rows:
            try:
                meta = json.loads(meta_str) if meta_str else {}
            except Exception:
                meta = {}

            severity = meta.get("severity", meta.get("level", "info"))
            skill_ids = self._text_to_skills(text)

            for sid in skill_ids:
                gain = SCORE_GAIN.get(severity, SCORE_GAIN["info"])
                try:
                    learner.record_success(sid, task=f"rag_bootstrap:{text[:40]}")
                    learner.update_score(sid, delta=gain)
                    updated += 1
                except Exception:
                    pass

        learner.save()
        self._last_bootstrap = time.time()
        logger.info(f"SkillRAGBridge.bootstrap: {updated} skill updates from RAG")
        return updated

    # ── 2. Pipeline → Skills ──────────────────────────────────────────────

    def on_pipeline_event(
        self,
        context: str,
        skill_ids: list[str] | None = None,
        severity: str = "info",
        success: bool = True,
    ) -> list[str]:
        """
        Appelé après chaque phase pipeline ou finding.

        Args:
            context: Texte décrivant l'événement (msg du finding, nom de phase, etc.)
            skill_ids: Si fourni, force ces skill IDs. Sinon, détection auto depuis context.
            severity: Niveau du finding (high/medium/low/info/success/error).
            success: True si la tâche s'est bien passée, False si erreur.

        Returns:
            Liste des skill IDs touchés.
        """
        learner = self._get_learner()
        if learner is None:
            return []

        ids = skill_ids if skill_ids else self._text_to_skills(context)
        if not ids:
            return []

        gain = SCORE_GAIN.get(severity if success else "error", 0.05)

        touched = []
        for sid in ids:
            try:
                if success:
                    learner.record_success(sid, task=context[:60])
                else:
                    learner.record_error(sid, task=context[:60])
                learner.update_score(sid, delta=gain)
                touched.append(sid)
            except Exception as e:
                logger.debug(f"on_pipeline_event {sid}: {e}")

        # Identifier les skills qui ont besoin d'un disco
        for sid in touched:
            try:
                if learner.needs_learning(sid):
                    self._queue_disco(sid)
            except Exception:
                pass

        learner.save()
        return touched

    # ── 3. @disco hook inverse ────────────────────────────────────────────

    def on_disco_done(self, topic: str, chunks_added: int = 1) -> list[str]:
        """
        Appelé par forge_disco après un @disco réussi.

        Fait monter le score des skills touchés + record_disco.

        Args:
            topic: Le sujet qui vient d'être ingéré dans le RAG.
            chunks_added: Nombre de chunks ajoutés.

        Returns:
            Liste des skill IDs mis à jour.
        """
        learner = self._get_learner()
        if learner is None:
            return []

        ids = self._text_to_skills(topic)
        for sid in ids:
            try:
                learner.record_disco(sid)
                learner.update_score(sid, delta=0.12 * min(chunks_added, 5))
            except Exception as e:
                logger.debug(f"on_disco_done {sid}: {e}")

        if learner._registry_path:
            learner.save()
        return ids

    # ── 4. Auto-disco headless ────────────────────────────────────────────

    def _queue_disco(self, skill_id: str) -> None:
        """
        Met en file d'attente un skill pour disco headless.
        Respecte DISCO_COOLDOWN de SkillLearner.
        """
        learner = self._get_learner()
        if learner is None:
            return

        now = time.time()
        last = self._pending_disco.get(skill_id, 0.0)
        cooldown = getattr(learner, "DISCO_COOLDOWN", 300)

        if now - last >= cooldown:
            if skill_id not in self._disco_queue:
                self._disco_queue.append(skill_id)
                logger.info(f"SkillRAGBridge: disco queued for '{skill_id}'")

    async def maybe_disco_all(self, max_per_cycle: int = 2) -> list[str]:
        """
        Déclenche les discos en attente (mode headless — pas d'UI).

        Limite : max_per_cycle par appel (défaut 2) pour ne pas saturer.
        Le topic envoyé à forge_disco est construit depuis les keywords du skill.

        Returns:
            Liste des skill IDs qui ont reçu un disco.
        """
        if not self._disco_queue:
            return []

        rag_engine = self._get_rag_engine()
        if rag_engine is None:
            logger.debug("maybe_disco_all: rag_engine unavailable")
            return []

        done: list[str] = []
        batch = self._disco_queue[:max_per_cycle]

        for sid in batch:
            topic = self._skill_to_topic(sid)
            if not topic:
                self._disco_queue.remove(sid)
                continue

            try:
                logger.info(f"SkillRAGBridge: headless disco '{topic}'")
                n = await rag_engine.ingest_web_content(
                    session_name=f"skill_autodisco_{sid}",
                    content=None,  # rag_engine fera la recherche web
                    skill=topic,
                )
                self._pending_disco[sid] = time.time()
                self._disco_queue.remove(sid)
                self.on_disco_done(topic, chunks_added=n or 1)
                done.append(sid)
                logger.info(f"  → {n} chunk(s) ingérés pour '{sid}'")
            except Exception as e:
                logger.warning(f"maybe_disco_all '{sid}': {e}")
                self._disco_queue.remove(sid)  # éviter boucle infinie

        return done

    # ── RAG score query ───────────────────────────────────────────────────

    def rag_score(self, skill_id: str) -> float:
        """
        Compte les chunks RAG associés à ce skill.
        Retourne un score normalisé [0..1].
        Utilisé pour décider si un disco est utile.
        """
        if not _RAG_DB.exists():
            return 0.0
        keywords = SKILL_TREE_KEYWORDS.get(skill_id, [skill_id.replace("_", " ")])
        if not keywords:
            return 0.0

        try:
            conn = sqlite3.connect(str(_RAG_DB), timeout=3)
            total = 0
            for kw in keywords[:4]:
                # rag_fts (index FTS5) au lieu de `text LIKE '%kw%'` : ce COUNT en
                # boucle faisait jusqu'a 4 FULL SCANS de rag_chunks (466k+ lignes,
                # wildcard en tete non-indexable) par appel -- meme classe mesuree a
                # x69 (30,9s->0,45s). Regle d'or Nokido : jamais de LIKE primitif.
                q = kw.replace('"', " ").strip()
                if not q:
                    continue
                try:
                    row = conn.execute(
                        "SELECT count(*) FROM rag_fts WHERE rag_fts MATCH ?",
                        ('"' + q + '"',)).fetchone()
                except sqlite3.OperationalError:  # rag_fts absent -> repli LIKE (lent)
                    row = conn.execute(
                        "SELECT count(*) FROM rag_chunks WHERE text LIKE ?",
                        (f"%{kw}%",)).fetchone()
                total += row[0] if row else 0
            conn.close()
            # Normalise : 10 chunks = score 1.0
            return min(total / 10.0, 1.0)
        except Exception:
            return 0.0

    # ── Helpers privés ─────────────────────────────────────────────────────

    def _text_to_skills(self, text: str) -> list[str]:
        """Détecte les skill IDs depuis un texte libre."""
        text_lower = text.lower()
        found: set[str] = set()
        for trigger, ids in FINDING_TO_SKILLS.items():
            if trigger in text_lower:
                found.update(ids)
        # Fallback : keywords de SKILL_TREE
        try:
            from nokido_agent.app.skilltree import detect_skills

            found.update(detect_skills(text))
        except Exception:
            pass
        return list(found)

    def _skill_to_topic(self, skill_id: str) -> str:
        """Construit un topic de recherche pour @disco depuis un skill_id."""
        mapping = {
            "securite_audit": "security audit nmap CVE vulnerability remediation",
            "securite_hardening": "linux hardening CIS benchmark",
            "securite_firewall": "iptables nftables firewall rules",
            "securite": "cybersecurity best practices",
            "reseau_protocoles": "TCP IP protocols network security",
            "reseau_monitoring": "network monitoring snmp prometheus",
            "reseau_vpn": "VPN wireguard tunnel security",
            "reseau_dns": "DNS security DNSSEC",
            "python_stdlib": "python stdlib security pickle serialization",
            "python_web": "python web API security OWASP",
            "devops_containers": "docker container security hardening",
            "devops_ci": "CI/CD pipeline security SAST",
        }
        return mapping.get(skill_id, skill_id.replace("_", " "))

    def status_report(self) -> dict:
        """Retourne un rapport compact des skills et de la file disco."""
        learner = self._get_learner()
        skills_summary = {}
        if learner:
            try:
                for sid, state in learner._skills.items():
                    skills_summary[sid] = {
                        "status": state.status,
                        "score": round(state.score, 2),
                        "uses": state.uses,
                        "rag": round(self.rag_score(sid), 2),
                        "needs_disco": learner.needs_learning(sid),
                    }
            except Exception:
                pass
        return {
            "skills": skills_summary,
            "disco_queue": list(self._disco_queue),
            "pending_disco": {k: int(time.time() - v) for k, v in self._pending_disco.items()},
        }


# ══════════════════════════════════════════════════════════════════════════════
# RESERVOIR READOUT LAYER
# ══════════════════════════════════════════════════════════════════════════════


class RAGReservoirReadout:
    """
    Readout layer par-dessus le RAG comme reservoir computing.

    Inspiré de cool-japan/spintronics — ai/reservoir.rs (Echo State Networks
    sur magnons). Le reservoir = état haute dimension à mémoire fading.
    Le RAG embeddings.db EST ce reservoir — on ajoute juste un readout.

    Principe :
        - Les chunks RAG = états du reservoir (pas modifiés)
        - La requête = signal d'entrée
        - Le readout = overlap TF-IDF entre requête et états passés
        - Pas de réentraînement — juste une lecture pondérée

    Usage :
        readout = RAGReservoirReadout()
        prediction = readout.predict("SSH brute force CVE-2021-44228")
        # → {"skill": "securite_audit", "score": 0.87, "similar_past": [...]}
    """

    def __init__(self, rag_db_path: str = "", decay_tau: float = 7200.0):
        """
        decay_tau : constante de fading memory du reservoir (secondes).
        Les chunks récents ont plus de poids que les anciens.
        """
        root = Path(__file__).resolve().parent.parent
        self._db = rag_db_path or str(root / "RAG" / "embeddings.db")
        self.decay_tau = decay_tau

    def _tokenize(self, text: str) -> set[str]:
        """Tokenisation simple — mots de 3+ caractères, lowercase."""
        import re

        return {w.lower() for w in re.findall(r"[a-zA-ZÀ-ÿ0-9_-]{3,}", text)}

    def _tfidf_overlap(self, query_tokens: set[str], doc_text: str) -> float:
        """
        Overlap normalisé entre les tokens de la requête et un document.
        score = |intersection| / sqrt(|query| * |doc|)  (cosine simplifié)
        """
        if not query_tokens or not doc_text:
            return 0.0
        doc_tokens = self._tokenize(doc_text)
        intersection = query_tokens & doc_tokens
        denom = (len(query_tokens) * len(doc_tokens)) ** 0.5
        return len(intersection) / denom if denom > 0 else 0.0

    def _fading_weight(self, ts_str: str | None) -> float:
        """
        Poids de fading memory : chunks récents pèsent plus.
        w = exp(-(now - ts) / tau)
        Si pas de timestamp : poids neutre 0.5.
        """
        if not ts_str:
            return 0.5
        try:
            import re

            # Extrait timestamp ISO ou Unix
            m = re.search(r"(\d{4}-\d{2}-\d{2})", ts_str)
            if m:
                import datetime

                ts = datetime.datetime.fromisoformat(ts_str[:19]).timestamp()
                elapsed = time.time() - ts
                return float(np.exp(-elapsed / self.decay_tau))
        except Exception:
            pass
        return 0.5

    def predict(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.05,
        domain: str = "",
    ) -> dict:
        """
        Recherche les états passés du reservoir les plus similaires à la requête.
        Retourne la prédiction de skill + les chunks similaires.

        Args:
            query     : texte de la requête (signal d'entrée)
            top_k     : nombre de chunks similaires à retourner
            min_score : seuil de similarité minimal
            domain    : filtre sur le domaine RAG (ex: 'security', 'lessons')

        Returns:
            {
                "query_tokens": int,
                "top_skill": str,        # skill le plus probable
                "top_score": float,      # score de similarité maximal
                "similar": [             # top_k chunks similaires
                    {"text": str, "score": float, "domain": str}
                ],
                "skill_scores": dict,    # score par skill category
            }
        """
        if not Path(self._db).exists():
            return {"error": "RAG DB introuvable", "top_skill": "", "top_score": 0.0}

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return {"error": "requête vide", "top_skill": "", "top_score": 0.0}

        try:
            conn = sqlite3.connect(self._db, timeout=5)
            sql = "SELECT text, source, domain, ingested_at FROM rag_chunks WHERE length(text) > 20 "
            params = []
            if domain:
                sql += "AND domain=? "
                params.append(domain)
            sql += "ORDER BY rowid DESC LIMIT 2000"
            rows = conn.execute(sql, params).fetchall()
            conn.close()
        except Exception as e:
            return {"error": str(e), "top_skill": "", "top_score": 0.0}

        # Calcul overlap pour chaque chunk
        scored = []
        for text, source, dom, ingested_at in rows:
            w_fading = self._fading_weight(ingested_at)
            overlap = self._tfidf_overlap(query_tokens, text or "")
            score = overlap * w_fading
            if score >= min_score:
                scored.append(
                    {
                        "text": (text or "")[:200],
                        "source": source or "",
                        "domain": dom or "",
                        "score": round(score, 4),
                    }
                )

        scored.sort(key=lambda x: -x["score"])
        top = scored[:top_k]

        # Agrège les scores par skill (via SKILL_TREE_KEYWORDS)
        skill_scores: dict[str, float] = {}
        for chunk in scored[:50]:
            chunk_tokens = self._tokenize(chunk["text"])
            for skill_id, kws in SKILL_TREE_KEYWORDS.items():
                kw_hits = sum(1 for kw in kws if kw in chunk_tokens)
                if kw_hits > 0:
                    skill_scores[skill_id] = skill_scores.get(skill_id, 0.0) + chunk["score"] * kw_hits

        top_skill = max(skill_scores, key=skill_scores.get) if skill_scores else ""
        top_score = scored[0]["score"] if scored else 0.0

        return {
            "query_tokens": len(query_tokens),
            "chunks_scanned": len(rows),
            "top_skill": top_skill,
            "top_score": top_score,
            "similar": top,
            "skill_scores": {k: round(v, 3) for k, v in sorted(skill_scores.items(), key=lambda x: -x[1])[:5]},
        }


# ── Keywords pour rag_score (extrait de SKILL_TREE pour éviter l'import) ────
SKILL_TREE_KEYWORDS: dict[str, list[str]] = {
    "securite_audit": ["nmap", "pentest", "cve", "audit", "bandit", "lynis", "openvas"],
    "securite_hardening": ["hardening", "cis", "sshd", "selinux", "apparmor", "pam"],
    "securite_firewall": ["iptables", "nftables", "ufw", "firewall", "fail2ban"],
    "securite": ["ssl", "tls", "certificat", "chiffrement", "security"],
    "reseau_protocoles": ["tcp", "udp", "arp", "icmp", "http", "dhcp", "ssh"],
    "reseau_monitoring": ["prometheus", "grafana", "snmp", "netdata", "nagios"],
    "reseau_vpn": ["wireguard", "openvpn", "vpn", "tunnel", "ipsec"],
    "reseau_dns": ["dns", "bind", "pihole", "dnsmasq", "dig", "nslookup"],
    "reseau": ["network", "reseau", "ip", "routage", "interface"],
    "python_stdlib": ["pickle", "subprocess", "pathlib", "hashlib", "logging"],
    "python_web": ["flask", "fastapi", "requests", "api", "rest"],
    "devops_containers": ["docker", "podman", "dockerfile", "kubernetes", "helm"],
    "devops_ci": ["github", "gitlab", "jenkins", "pipeline", "actions"],
}
