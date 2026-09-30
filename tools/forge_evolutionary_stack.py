"""
tools/forge_evolutionary_stack.py — Stacking Évolutif Nokido
=============================================================
Transforme chaque mutation validée en strate géologique réutilisable.

Architecture :
  GenomicVault     → archive physique NVMe (vault/)
  PatternStacker   → extrait patterns succès/échec du JSONL RAG
  StandardsWriter  → génère les règles auto-apprises (.rules)
  EvolutionaryStack → orchestre le cycle complet

Usage :
  python tools/forge_evolutionary_stack.py --file app/forge_routing.py
  python tools/forge_evolutionary_stack.py --report
  python tools/forge_evolutionary_stack.py --rollback app/forge_routing.py v_20260324_120848_nokido
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAULT_DIR = ROOT / "shadow_mutation" / "vault"
RAG_JSONL = ROOT / "shadow_mutation" / "rag_index" / "experience_memory.jsonl"
RULES_DIR = ROOT / "shadow_mutation" / "standards"


# ── GenomicVault ──────────────────────────────────────────────────────────────


class GenomicVault:
    """
    Archive physique NVMe — chaque Alpha validé est une strate immuable.
    Permet de remonter la lignée génétique si une génération régresse.
    """

    def __init__(self) -> None:
        """Initialise le vault."""
        VAULT_DIR.mkdir(parents=True, exist_ok=True)

    def archive(self, filepath: str, content: str, metadata: dict) -> str:
        """
        Archive une version validée avec son génome.
        Retourne le version_id (ex: v_20260324_120000_qwen32b).
        """
        ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        agent_slug = re.sub(r"[^a-z0-9]", "", metadata.get("agent", "?").lower())[:10]
        version_id = f"v_{ts}_{agent_slug}"
        stem = Path(filepath).stem

        arch = VAULT_DIR / stem / version_id
        arch.mkdir(parents=True, exist_ok=True)

        (arch / "code.py").write_text(content, encoding="utf-8")
        (arch / "genome.json").write_text(
            json.dumps(
                {
                    **metadata,
                    "filepath": filepath,
                    "version_id": version_id,
                    "archived_at": ts,
                    "lines": len(content.splitlines()),
                    "size_chars": len(content),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(
            f"[VAULT] {stem}/{version_id} archivé ({len(content)}c, score={metadata.get('score', 0)})"
        )
        return version_id

    def list_versions(self, filepath: str) -> list[dict]:
        """Liste les versions archivées triées par date."""
        stem = Path(filepath).stem
        base = VAULT_DIR / stem
        if not base.exists():
            return []
        versions = []
        for gf in sorted(base.glob("v_*/genome.json")):
            try:
                versions.append(json.loads(gf.read_text(encoding="utf-8")))
            except Exception:
                pass
        return sorted(versions, key=lambda x: x.get("archived_at", ""))

    def best_version(self, filepath: str) -> dict | None:
        """Retourne la version avec le meilleur fitness_score."""
        versions = self.list_versions(filepath)
        if not versions:
            return None
        return max(versions, key=lambda x: x.get("score", x.get("fitness_score", 0)))

    def rollback(self, filepath: str, version_id: str) -> bool:
        """Restaure une version archivée dans le projet."""
        stem = Path(filepath).stem
        code_src = VAULT_DIR / stem / version_id / "code.py"
        if not code_src.exists():
            print(f"[VAULT] Version introuvable: {version_id}")
            return False
        dest = ROOT / filepath
        shutil.copy(code_src, dest)
        print(f"[VAULT] Rollback {filepath} → {version_id}")
        return True


# ── PatternStacker ────────────────────────────────────────────────────────────


class PatternStacker:
    """
    Extrait les patterns succès/échec du JSONL pour enrichir les prompts.
    Le LLM du tour N+1 sait ce qui a marché et ce qui a échoué au tour N.
    """

    def get_stack_prompt(self, filepath: str, max_per_cat: int = 5) -> str:
        """
        Génère le bloc contexte évolutif pour un fichier.
        Injecté dans le prompt → le LLM ne répète pas les erreurs passées.
        """
        if not RAG_JSONL.exists():
            return ""

        successes: list[str] = []
        failures: list[str] = []
        best_agents: list[str] = []

        for line in RAG_JSONL.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("file") != filepath:
                continue

            fb = d.get("experience_feedback", d.get("feedback", {}))
            if not isinstance(fb, dict):
                continue

            if d.get("evolution_status") == "Success":
                successes.extend(fb.get("success_factors", []))
                successes.extend(fb.get("lessons_learned", []))
                if d.get("last_mutation_agent"):
                    best_agents.append(d["last_mutation_agent"])
            else:
                failures.extend(fb.get("failure_post_mortem", []))
                failures.extend(fb.get("lessons_learned", []))

        if not successes and not failures:
            return ""

        lines = ["--- MÉMOIRE ÉVOLUTIVE ---"]
        if successes:
            uniq = list(dict.fromkeys(successes))[:max_per_cat]
            lines.append("✅ CE QUI A MARCHÉ:")
            lines += [f"  - {s}" for s in uniq]
        if failures:
            uniq = list(dict.fromkeys(failures))[:max_per_cat]
            lines.append("❌ ÉCHECS À ÉVITER:")
            lines += [f"  - {f}" for f in uniq]
        if best_agents:
            from collections import Counter

            best = Counter(best_agents).most_common(1)[0][0]
            lines.append(f"🏆 Agent le plus fiable: {best}")
        lines.append("---")
        return chr(10).join(lines)

    def get_agent_ranking(self, filepath: str) -> list[tuple[str, float]]:
        """Retourne les agents classés par taux de succès sur ce fichier."""
        if not RAG_JSONL.exists():
            return []

        stats: dict[str, dict] = {}
        for line in RAG_JSONL.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("file") != filepath:
                continue
            agent = d.get("last_mutation_agent") or d.get("agent", "?")
            if agent not in stats:
                stats[agent] = {"ok": 0, "total": 0}
            stats[agent]["total"] += 1
            if d.get("evolution_status") == "Success":
                stats[agent]["ok"] += 1

        ranked = []
        for agent, s in stats.items():
            rate = s["ok"] / max(s["total"], 1)
            ranked.append((agent, round(rate, 2)))
        return sorted(ranked, key=lambda x: -x[1])


# ── StandardsWriter ───────────────────────────────────────────────────────────


class StandardsWriter:
    """
    Génère les règles auto-apprises depuis l'historique de mutations.
    Produit un fichier .rules qui sert de référence pour les prochains agents.
    """

    def __init__(self) -> None:
        """Initialise le writer."""
        RULES_DIR.mkdir(parents=True, exist_ok=True)

    def generate_rules(self, filepath: str) -> Path:
        """
        Génère shadow_mutation/standards/<stem>.rules depuis le JSONL.
        Format Markdown — injecté dans le system prompt des agents.
        """
        stacker = PatternStacker()
        vault = GenomicVault()
        stem = Path(filepath).stem
        versions = vault.list_versions(filepath)
        ranking = stacker.get_agent_ranking(filepath)
        stack = stacker.get_stack_prompt(filepath)

        lines = [
            f"# Standards Nokido — {stem}",
            f"_Généré le {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M')} UTC_",
            "",
        ]

        # Statistiques évolution
        if versions:
            best = max(versions, key=lambda x: x.get("score", 0))
            lines += [
                "## Historique",
                f"- Versions archivées: {len(versions)}",
                f"- Meilleur score: {best.get('score', 0)}/100 "
                f"(agent: {best.get('agent', '?')}, {best.get('archived_at', '?')[:10]})",
                "",
            ]

        # Classement agents
        if ranking:
            lines += ["## Agents recommandés"]
            for agent, rate in ranking[:5]:
                bar = "█" * int(rate * 10) + "░" * (10 - int(rate * 10))
                lines.append(f"- `{agent}` {bar} {rate:.0%}")
            lines.append("")

        # Patterns extraits
        if stack:
            lines += ["## Mémoire évolutive", stack, ""]

        # Règles structurelles
        lines += [
            "## Règles structurelles (non négociables)",
            "- Ne jamais tronquer le fichier — retourner le code COMPLET",
            "- Conserver TOUTES les classes et leurs corps intacts",
            "- Types Python 3.9+ builtins uniquement (pas de `from typing import`)",
            "- Chaque `try` doit avoir un `except` ou `finally`",
            "",
        ]

        rules_path = RULES_DIR / f"{stem}.rules"
        rules_path.write_text(chr(10).join(lines), encoding="utf-8")
        print(f"[STANDARDS] {rules_path.name} généré ({len(lines)} lignes)")
        return rules_path

    def load_rules(self, filepath: str) -> str:
        """Charge les règles pour injection dans un prompt."""
        rules_path = RULES_DIR / f"{Path(filepath).stem}.rules"
        if rules_path.exists():
            return rules_path.read_text(encoding="utf-8")
        return ""


# ── EvolutionaryStack ─────────────────────────────────────────────────────────


class EvolutionaryStack:
    """Orchestre le cycle complet : archive → patterns → standards."""

    def __init__(self) -> None:
        """Initialise le stack."""
        self.vault = GenomicVault()
        self.stacker = PatternStacker()
        self.writer = StandardsWriter()

    def on_success(
        self,
        filepath: str,
        content: str,
        score: int,
        agent: str,
        feedback: str = "",
    ) -> str:
        """
        Appelé après une mutation validée par Cerberus.
        Archive + met à jour les standards.
        """
        metadata = {
            "agent": agent,
            "score": score,
            "feedback": feedback,
        }
        version_id = self.vault.archive(filepath, content, metadata)
        self.writer.generate_rules(filepath)
        return version_id

    def get_context(self, filepath: str) -> str:
        """
        Retourne le contexte complet pour enrichir le prompt du prochain agent :
        stack évolutif + règles standards.
        """
        stack = self.stacker.get_stack_prompt(filepath)
        rules = self.writer.load_rules(filepath)
        parts = []
        if stack:
            parts.append(stack)
        if rules:
            parts.append(rules)
        return chr(10).join(parts)

    def report(self) -> None:
        """Affiche un rapport de toutes les évolutions archivées."""
        if not VAULT_DIR.exists():
            print("Vault vide — aucune mutation archivée")
            return

        print(f"\n{'=' * 60}\n  VAULT GÉNOMIQUE LaForge\n{'=' * 60}\n")
        for module_dir in sorted(VAULT_DIR.iterdir()):
            if not module_dir.is_dir():
                continue
            versions = sorted(module_dir.glob("v_*/genome.json"))
            if not versions:
                continue
            scores = []
            for gf in versions:
                try:
                    d = json.loads(gf.read_text(encoding="utf-8"))
                    scores.append(d.get("score", 0))
                except Exception:
                    pass
            best = max(scores) if scores else 0
            trend = "↑" if len(scores) >= 2 and scores[-1] >= scores[-2] else "→"
            print(
                f"  {module_dir.name:30s} {len(versions):3d} versions | best={best:3d}/100 {trend}"
            )
        print()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Nokido Evolutionary Stack")
    ap.add_argument("--file", default=None, help="Fichier à traiter")
    ap.add_argument("--report", action="store_true", help="Rapport vault")
    ap.add_argument(
        "--rollback", nargs=2, metavar=("FILE", "VERSION_ID"), help="Restaure une version"
    )
    ap.add_argument("--context", default=None, help="Affiche le contexte évolutif")
    args = ap.parse_args()

    stack = EvolutionaryStack()

    if args.report:
        stack.report()

    elif args.rollback:
        filepath, version_id = args.rollback
        ok = stack.vault.rollback(filepath, version_id)
        sys.exit(0 if ok else 1)

    elif args.context:
        ctx = stack.get_context(args.context)
        print(ctx or "(aucun contexte disponible)")

    elif args.file:
        # Simule un succès pour tester l'archivage
        filepath = args.file
        content = (ROOT / filepath).read_text(encoding="utf-8", errors="replace")
        vid = stack.on_success(filepath, content, score=85, agent="test", feedback="test archivage")
        print(f"Version archivée: {vid}")
        stack.report()

    else:
        ap.print_help()
