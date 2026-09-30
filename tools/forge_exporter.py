"""
ForgeProjectExporter — Pack de survie pour migration locale.

Compile l'état génomique du projet en un master_context.json
ingérable par Qwen 2.5 Coder ou Llama 3.3 sans connexion cloud.
"""

from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class ForgeProjectExporter:
    """Prépare une exportation haute densité du projet Nokido."""

    def __init__(self, root_path: str = ".") -> None:
        """Initialise l'exporteur.

        Args:
            root_path: Chemin racine du projet Nokido.
        """
        self.root = Path(root_path).resolve()
        self.export_dir = self.root / "exports"
        self.export_dir.mkdir(exist_ok=True)

        self.memory_path = self.root / "shadow_mutation" / "rag_index" / "experience_memory.jsonl"
        self.vault_path = self.root / "shadow_mutation" / "vault"

    def generate_master_context(self) -> Path:
        """Génère le master_context.json — savoir condensé de toutes les sessions.

        Contient :
        - Les 50 dernières interactions RAG (succès + échecs)
        - L'état génomique du vault (modules + scores)
        - Les contraintes techniques extraites des headers FORGE HD
        - La configuration hardware cible

        Returns:
            Path vers le fichier master_context.json exporté.
        """
        import re

        print("🔍 [EXPORT] Extraction du savoir accumulé...")

        ctx: dict = {
            "project": "Nokido",
            "state_id": "ALPHA-506-SWARM-READY-v3",
            "export_timestamp": datetime.now().isoformat(),
            "hardware_target": "Ryzen 8700G iGPU — 32GB RAM — NVMe PCIe 5.0",
            "local_model": "qwen2.5-coder:7b-instruct-q4_K_M (Ollama :11434)",
            # ── Savoir épisodique ─────────────────────────────────────────────
            "success_patterns": [],
            "failure_lessons": [],
            # ── Savoir génomique ──────────────────────────────────────────────
            "vault_modules": [],
            # ── Contraintes techniques extraites des headers FORGE HD ─────────
            "constraints": [],
            # ── Scores actuels ────────────────────────────────────────────────
            "scores": {},
        }

        # 1 — Épisodique : experience_memory.jsonl
        if self.memory_path.exists():
            lines = self.memory_path.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[-50:]:
                try:
                    entry = json.loads(line)
                    if entry.get("evolution_status") == "Success":
                        ctx["success_patterns"].append(
                            {
                                "module": entry.get("module", "?"),
                                "score": entry.get("fitness_score", 0),
                                "agent": entry.get("last_mutation_agent", "?"),
                                "factors": entry.get("experience_feedback", {}).get(
                                    "success_factors", []
                                ),
                            }
                        )
                    else:
                        lesson = entry.get("experience_feedback", {}).get(
                            "failure_post_mortem"
                        ) or [entry.get("feedback", "")]
                        ctx["failure_lessons"].extend(lesson[:2])
                except Exception:
                    pass

        # 2 — Génomique : vault/
        if self.vault_path.exists():
            for genome_file in sorted(
                self.vault_path.rglob("genome.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:20]:
                try:
                    g = json.loads(genome_file.read_text(encoding="utf-8"))
                    mod = genome_file.parent.parent.name
                    ctx["vault_modules"].append(
                        {
                            "module": mod,
                            "version": genome_file.parent.name,
                            "score": g.get("score", 0),
                            "agent": g.get("agent", "?")[:25],
                        }
                    )
                    ctx["scores"][mod] = g.get("score", 0)
                except Exception:
                    pass

        # 3 — Contraintes HD : lire __FORGE_TAGS__ + CONTRAINTES: dans les sources
        for fpath in sorted((self.root / "app").glob("*.py"))[:30]:
            try:
                src = fpath.read_text(encoding="utf-8", errors="replace")
                # Extraire le tag vector
                m = re.search(r"#FORGE:\[([^\]]+)\]", src)
                if not m:
                    continue
                tags = dict(pair.split(":", 1) for pair in m.group(1).split("|") if ":" in pair)
                # Extraire les contraintes textuelles
                cblock = re.search(r"CONTRAINTES?:(.*?)(?:LESSONS:|\"\"\")", src, re.DOTALL)
                if cblock:
                    for c in re.findall(r"! (.+)", cblock.group(1)):
                        ctx["constraints"].append(f"{fpath.name}: {c.strip()}")
            except Exception:
                pass

        # 4 — Déduplication
        ctx["failure_lessons"] = list(dict.fromkeys(str(l) for l in ctx["failure_lessons"] if l))[
            :30
        ]
        ctx["constraints"] = list(dict.fromkeys(ctx["constraints"]))[:20]

        ts = int(datetime.now().timestamp())
        out = self.export_dir / f"master_context_{ts}.json"
        out.write_text(json.dumps(ctx, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  📄 master_context.json — {len(json.dumps(ctx))} chars")
        print(
            f"     succès: {len(ctx['success_patterns'])} | échecs: {len(ctx['failure_lessons'])}"
        )
        print(
            f"     vault : {len(ctx['vault_modules'])} modules | contraintes: {len(ctx['constraints'])}"
        )
        return out

    def generate_prompt_passation(self, ctx_path: Path) -> Path:
        """Génère le prompt de passation pour le LLM local.

        Args:
            ctx_path: Chemin vers le master_context.json.

        Returns:
            Path vers le fichier prompt_passation.md exporté.
        """
        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))

        top_scores = sorted(ctx["scores"].items(), key=lambda x: -x[1])[:5]
        scores_str = "\n".join(f"  - {m}: {s}/100" for m, s in top_scores)

        constraints_str = (
            "\n".join(f"  - {c}" for c in ctx["constraints"][:8]) or "  (aucune critique)"
        )

        success_str = (
            "\n".join(
                f"  - {p['module']} score={p['score']} agent={p['agent']}"
                for p in ctx["success_patterns"][:5]
            )
            or "  (aucun)"
        )

        prompt = f"""# Nokido — Prompt de Passation Locale

Tu reprends le projet Nokido v17 là où Claude l'a laissé.
State ID actuel : **{ctx["state_id"]}**
Hardware cible  : {ctx["hardware_target"]}
Modèle local    : {ctx["local_model"]}

## Ce qui a été accompli

### Scores vault (top 5)
{scores_str}

### Succès récents
{success_str}

## Contraintes techniques critiques (NE PAS ignorer)
{constraints_str}

## Règles absolues héritées de Claude

1. Après chaque mutation, valider avec `python -m py_compile`
2. Tests : `python -m pytest tests/nr/ --ignore=tests/nr/test_import_all_nr.py`
3. Fichiers > 30KB → `--cerberus` uniquement (jamais `--intelligent`)
4. `get_remote_context` dans forge_handlers.py doit rester `async def`
5. Ne jamais supprimer les tombeaux CANARI de forge_handlers.py
6. `app/pyproject.toml` ignore E402/F401/F821 (préexistants intentionnels)
7. GPU Lock actif dans ParallelMutationWorker — ne pas lancer > 2 workers Ollama simultanés

## Comment continuer

```bash
# Run standard
python -X utf8 tools/evolutionary_engine.py \\
  --files app/<fichier>.py --intelligent --population 3 \\
  --task "..."

# Fichier > 30KB
python -X utf8 tools/evolutionary_engine.py \\
  --files app/<fichier>.py --cerberus --population 3 --generations 2 \\
  --task "..."

# Vérification santé
python -m pytest tests/nr/ --ignore=tests/nr/test_import_all_nr.py -q
python -m ruff check app/
```

Le fichier `shadow_mutation/rag_index/experience_memory.jsonl` contient
{len(ctx["failure_lessons"])} leçons d'échec — lis-le avant toute mutation.
"""
        ts = int(datetime.now().timestamp())
        out = self.export_dir / f"prompt_passation_{ts}.md"
        out.write_text(prompt, encoding="utf-8")
        print(f"  📝 prompt_passation.md — {len(prompt)} chars")
        return out

    def create_migration_package(self) -> Path:
        """Crée un ZIP contenant code + RAG + contexte.

        Returns:
            Path vers le fichier ZIP exporté.
        """
        ts = int(datetime.now().timestamp())
        zip_path = self.export_dir / f"nokido_migration_{ts}.zip"
        exclude = {
            ".venv",
            "__pycache__",
            ".git",
            "exports",
            "backups",
            "sandbox",
            "logs",
            "workspace",
        }

        print(f"📦 [EXPORT] Création du package : {zip_path.name}")
        total = 0
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(self.root):
                dirs[:] = [d for d in dirs if d not in exclude]
                for fname in files:
                    fp = Path(root) / fname
                    arc = fp.relative_to(self.root)
                    try:
                        zf.write(fp, arc)
                        total += 1
                    except Exception:
                        pass
        size_mb = zip_path.stat().st_size / 1024 / 1024
        print(f"  🎁 {total} fichiers | {size_mb:.1f} MB")
        return zip_path


if __name__ == "__main__":
    exporter = ForgeProjectExporter(root_path=str(ROOT))

    print("=" * 55)
    print("  Nokido — Export Pack de Survie")
    print("=" * 55)

    ctx_file = exporter.generate_master_context()
    prompt_file = exporter.generate_prompt_passation(ctx_file)

    ans = input("\nCréer le ZIP complet ? (o/N) : ").strip().lower()
    if ans == "o":
        pkg_file = exporter.create_migration_package()
        print(f"\n✨ Package prêt : {pkg_file.name}")
    else:
        print("\n✨ Contexte prêt :")
        print(f"  📄 {ctx_file.name}")
        print(f"  📝 {prompt_file.name}")
        print("\nFor Qwen local :")
        print("  ollama run qwen2.5-coder:7b")
        print("  → colle le contenu de prompt_passation.md")
