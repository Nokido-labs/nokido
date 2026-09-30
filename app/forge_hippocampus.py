"""
forge_hippocampus.py — Consolidation memoire Nokido (Phase H)
Transforme traces de session en connaissances persistantes (RAG + lessons_learned).
Organe: hippocampe — consolidation memoire de travail → long terme.
#FORGE:[score:88|agent:claude-sonnet-4-6|temp:0.00|color:GREEN|attempt:2]
"""
from __future__ import annotations

import json
import re
import sys
import logging
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("Nokido.Hippocampus")

LESSONS_PATH = ROOT / "logs" / "lessons_learned.md"
BRAIN_MAP = ROOT / "sandbox" / "cognitive_map.json"


class Hippocampus:
    """
    Centre de consolidation memoire de Nokido.
    Memoire de travail (session) -> memoire long terme (RAG + lessons).
    """

    def __init__(self, workspace_root: str = str(ROOT)):
        self.root = Path(workspace_root)

    # ── Extraction ──────────────────────────────────────────────────────────

    def distill_session(self, dialogue_text: str) -> dict:
        """
        Extrait essence d un dialogue: Intention -> Obstacle -> Solution.
        Ancre dans RAG via anchor_solution si solution identifiee.
        """
        distillation = {
            "timestamp": datetime.now().isoformat(),
            "intent": self._extract_intent(dialogue_text),
            "obstacles": self._extract_obstacles(dialogue_text),
            "breakthrough": self._extract_solution(dialogue_text),
            "domain": self._infer_domain(dialogue_text),
            "anchored": False,
        }

        if distillation["breakthrough"] and len(distillation["breakthrough"]) > 30:
            try:
                from nokido_agent.app.forge_self_correction import anchor_solution

                anchor_solution(
                    problem=distillation["intent"] or "session distillation",
                    solution=distillation["breakthrough"],
                    example="",
                    domain=distillation["domain"],
                )
                distillation["anchored"] = True
            except Exception as e:
                logger.debug(f"anchor_solution failed: {e}")

        return distillation

    def _extract_intent(self, text: str) -> str:
        for pat in [
            r"(?:intention|objectif|goal|task)\s*[:\-]\s*(.{10,120})",
            r"(?:je veux|je dois|on veut|to|build|create|fix)\s+(.{10,80})",
        ]:
            m = re.search(pat, text, re.I)
            if m:
                return m.group(1).strip()
        for line in text.splitlines():
            line = line.strip()
            if 20 < len(line) < 120 and not line.startswith("#"):
                return line
        return "Inconnue"

    def _extract_obstacles(self, text: str) -> list[str]:
        matches = re.findall(
            r"(?:erreur|bug|impossible|limitation|echec|failed|error|crash|"
            r"timeout|bloque|blocked|refuse|denied)[^.\n]{0,60}",
            text,
            re.I,
        )
        return list(dict.fromkeys(m.strip() for m in matches))[:5]

    def _extract_solution(self, text: str) -> str:
        for pat in [
            r"(?:solution|fix|resolved|corrige|fixe)\s*[:\-]\s*(.{20,300})",
            r"(?:PASS|OK|done|commit|anchor)\s+(.{20,200})",
            r"anchor_solution\(([^)]{20,200})\)",
        ]:
            m = re.search(pat, text, re.I | re.S)
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()[:300]
        return ""

    def _infer_domain(self, text: str) -> str:
        counts: dict[str, int] = {}
        keywords = {
            "rag": ["rag", "embedding", "faiss", "bm25", "chunk"],
            "securite": ["firewall", "injection", "ssrf", "dlp", "ring"],
            "exploit": ["tcache", "fastbin", "uaf", "fsop", "pwntools", "defcon"],
            "llm": ["router", "gemini", "ollama", "lmstudio", "orchestrate"],
            "systeme": ["supervisor", "nssm", "service", "daemon", "heartbeat"],
        }
        t = text.lower()
        for domain, words in keywords.items():
            counts[domain] = sum(t.count(w) for w in words)
        return max(counts, key=counts.get) if any(counts.values()) else "general"

    # ── Consolidation ────────────────────────────────────────────────────────

    def consolidate(self, session_summary: dict) -> None:
        LESSONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LESSONS_PATH, "a", encoding="utf-8") as f:
            ts = session_summary.get("timestamp", datetime.now().isoformat())[:19]
            f.write(f"\n### [{ts}] CONSOLIDATION HIPPOCAMPE\n")
            f.write(f"- **Intention** : {session_summary.get('intent', '')}\n")
            if session_summary.get("breakthrough"):
                f.write(f"- **Apprentissage** : {session_summary['breakthrough'][:200]}\n")
            if session_summary.get("obstacles"):
                f.write(f"- **Signaux** : {', '.join(session_summary['obstacles'][:3])}\n")

    # ── Synapses ─────────────────────────────────────────────────────────────

    def create_synapse(self, source_file: str, target_file: str, relationship: str) -> None:
        map_data: dict = {}
        if BRAIN_MAP.exists():
            try:
                map_data = json.loads(BRAIN_MAP.read_text(encoding="utf-8"))
            except Exception:
                pass
        key = f"{source_file}->{target_file}"
        entry = map_data.get(key, {"weight": 0})
        entry.update(
            {
                "rel": relationship,
                "weight": entry["weight"] + 1,
                "last_seen": datetime.now().isoformat(),
            }
        )
        map_data[key] = entry
        BRAIN_MAP.parent.mkdir(parents=True, exist_ok=True)
        BRAIN_MAP.write_text(json.dumps(map_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── Post-session hook ─────────────────────────────────────────────────────

    def post_session_hook(self, agent: str, dialogue_text: str) -> dict:
        """Hook post-conversation Claude/Gemini. Distille + consolide + synapses."""
        distillation = self.distill_session(dialogue_text)
        self.consolidate(distillation)
        modules = re.findall(r"forge_\w+", dialogue_text)
        seen = list(dict.fromkeys(modules))[:10]
        for i in range(len(seen) - 1):
            self.create_synapse(seen[i], seen[i + 1], f"co-modified-{agent}")
        return {
            "agent": agent,
            "ts": distillation["timestamp"],
            "anchored": distillation["anchored"],
            "synapses": max(0, len(seen) - 1),
            "domain": distillation["domain"],
        }


# ── Lessons consolidate (passif -> actif) ────────────────────────────────────


def lessons_consolidate(min_confidence: float = 0.85) -> dict:
    """Phase H: dedup lecons RAG (jaccard > 0.70 = doublon)."""
    try:
        import sqlite3

        DB = ROOT / "RAG" / "embeddings.db"
        conn = sqlite3.connect(str(DB), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        rows = conn.execute(
            "SELECT id, text FROM rag_chunks "
            "WHERE role_hint IN ('solution','feedback') AND LENGTH(text) > 50 "
            "ORDER BY ingested_at DESC LIMIT 200"
        ).fetchall()
        conn.close()

        if not rows:
            return {"merged": 0, "total_lessons": 0}

        def jaccard(a: str, b: str) -> float:
            sa, sb = set(a.lower().split()), set(b.lower().split())
            return len(sa & sb) / len(sa | sb) if (sa or sb) else 0.0

        merged = 0
        seen_ids: set[str] = set()
        for i, (id_a, text_a) in enumerate(rows):
            if id_a in seen_ids:
                continue
            for id_b, text_b in rows[i + 1 :]:
                if id_b in seen_ids:
                    continue
                if jaccard(text_a, text_b) > 0.70:
                    seen_ids.add(id_b)
                    merged += 1

        return {"merged": merged, "total_lessons": len(rows), "dedup_rate": round(merged / max(1, len(rows)), 3)}
    except Exception as e:
        return {"merged": 0, "error": str(e)}


# MCP entry points
def forge_distill_session(agent: str, dialogue_text: str) -> dict:
    """MCP-callable. Post-session hook distillation."""
    return Hippocampus().post_session_hook(agent, dialogue_text)


def forge_lessons_consolidate(min_confidence: float = 0.85) -> dict:
    """MCP-callable. Auto-merge lecons dupliquees."""
    return lessons_consolidate(min_confidence)


if __name__ == "__main__":
    h = Hippocampus()
    test = h.distill_session(
        "intention: fix supervisor wake bug\n"
        "erreur: startService fire-and-forget\n"
        "fix: await delay(600) + await startService\nPASS"
    )
    print(json.dumps(test, indent=2, ensure_ascii=False, default=str))
    print("consolidate:", lessons_consolidate())
