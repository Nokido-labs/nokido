"""
forge_thought_interceptor.py — Intercepteur CoT avec GPU Lock + densité cognitive
==================================================================================
Capture les balises <think>...</think> des modèles DeepSeek-R1/Qwen-R1 en streaming,
avec synchronisation iGPU (FileLock) et contrôle qualité de la réflexion.

Fonctionnalités :
  1. GPU Lock       : FileLock sur shadow_mutation/gpu_inference.lock
                      → évite la saturation de la VRAM partagée iGPU 780M
  2. Densité cognitive : réflexion < 50 chars → marquée LOW_DENSITY (suspicion d'hallucination)
  3. Streaming live  : affiche les points `.` pendant la réflexion, le code en clair
  4. Archive NVMe    : écriture groupée sur PCIe 5.0
  5. RAG épisodique  : injection dans experience_memory.jsonl

Usage :
    from tools.forge_thought_interceptor import ForgeThoughtInterceptor
    interceptor = ForgeThoughtInterceptor()
    result = interceptor.stream_with_thought_capture(
        model="deepseek-r1:7b",
        prompt="Optimise cette fonction Python...",
        task_id="opt_001",
    )
    if not result.get("density_ok"):
        print("⚠️ Réflexion trop courte — risque d'hallucination")
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from filelock import FileLock, Timeout

ROOT = Path(__file__).resolve().parent.parent
OLLAMA_URL = "http://localhost:11434/api/chat"
GPU_LOCK_PATH = ROOT / "shadow_mutation" / "gpu_inference.lock"
MIN_THOUGHT_CHARS = 50  # Seuil de densité cognitive


class ForgeThoughtInterceptor:
    """Intercepteur CoT avec synchronisation GPU et archivage RAG.

    Attributes:
        root:       Répertoire racine du projet.
        thought_dir: Dossier de stockage des traces de raisonnement.
        memory_path: Fichier JSONL de la mémoire épisodique.
    """

    def __init__(self, root_path: str | None = None) -> None:
        """Initialise l'intercepteur.

        Args:
            root_path: Répertoire racine (auto-détecté si None).
        """
        self.root = Path(root_path).resolve() if root_path else ROOT
        self.thought_dir = self.root / "shadow_mutation" / "thoughts"
        self.memory_path = self.root / "shadow_mutation" / "rag_index" / "experience_memory.jsonl"

        self.thought_dir.mkdir(parents=True, exist_ok=True)
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        GPU_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

    # ── Outils de sécurité [2026-03-22] ──────────────────────────────────────

    def _get_safety_tools(self) -> list[dict]:
        """Retourne les outils de validation injectés dans le payload Ollama.

        Conformité directive [2026-03-22] — injection systématique.

        Returns:
            Liste de définitions d'outils de validation AST.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "validate_mutation_integrity",
                    "description": "Vérifie l'intégrité AST de la mutation avant application.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Fichier cible"},
                            "code": {"type": "string", "description": "Code muté à valider"},
                        },
                        "required": ["file_path", "code"],
                    },
                },
            }
        ]

    # ── Streaming principal ───────────────────────────────────────────────────

    def stream_with_thought_capture(
        self,
        model: str,
        prompt: str,
        task_id: str = "evolution",
        temperature: float = 0.4,
        gpu_timeout: int = 300,
    ) -> dict:
        """Stream Ollama avec capture CoT, GPU Lock et contrôle de densité.

        Phase 1 : Acquisition du verrou GPU (FileLock) pour éviter
                  la saturation VRAM de l'iGPU Radeon 780M.
        Phase 2 : Streaming avec séparation <think>...</think>.
        Phase 3 : Archivage NVMe + RAG épisodique.

        Args:
            model:       Nom du modèle Ollama (ex: 'deepseek-r1:7b').
            prompt:      Prompt utilisateur.
            task_id:     Identifiant de la tâche pour l'archivage.
            temperature: Température d'inférence.
            gpu_timeout: Timeout d'attente GPU en secondes (défaut 5 min).

        Returns:
            Dict avec 'content', 'thought_trace', 'density_ok'.
            En cas d'erreur : {'error': str}.
        """
        import requests  # noqa: PLC0415

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "tools": self._get_safety_tools(),
            "options": {"temperature": temperature},
        }

        full_response = ""
        captured_thought = ""
        is_thinking = False

        # ── Phase 1 : GPU Lock ────────────────────────────────────────────────
        lock = FileLock(str(GPU_LOCK_PATH))
        print(f"🔒 [WAIT] {model} attend l'accès à l'iGPU 780M...")

        try:
            with lock.acquire(timeout=gpu_timeout):
                print(f"🧠 [INTERCEPTOR] Inférence démarrée — {model} (mission: {task_id})")

                try:
                    response = requests.post(OLLAMA_URL, json=payload, stream=True, timeout=180)
                    response.raise_for_status()

                    for line in response.iter_lines():
                        if not line:
                            continue

                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")

                        # ── Détection ouverture <think> ───────────────────
                        if "<think>" in content:
                            is_thinking = True
                            content = content.replace("<think>", "")
                            print("\n💭 [RÉFLEXION] ", end="", flush=True)

                        # ── Détection fermeture </think> ──────────────────
                        if "</think>" in content and is_thinking:
                            parts = content.split("</think>", 1)
                            captured_thought += parts[0]
                            is_thinking = False
                            content = parts[1] if len(parts) > 1 else ""
                            print(f" | ({len(captured_thought)} chars)")
                            print("🏁 [FIN RÉFLEXION] ---")
                            if not content:
                                continue

                        # ── Accumulation ──────────────────────────────────
                        if is_thinking:
                            captured_thought += content
                            print(".", end="", flush=True)
                        else:
                            full_response += content
                            print(content, end="", flush=True)

                except Exception as e:
                    return {"error": f"[THOUGHT ERR] streaming: {e}"}

        except Timeout:
            return {"error": f"[THOUGHT ERR] GPU timeout après {gpu_timeout}s"}

        print()  # newline final

        # ── Phase 2 : Contrôle densité cognitive ─────────────────────────────
        density_ok = len(captured_thought) >= MIN_THOUGHT_CHARS

        # ── Phase 3 : Archivage NVMe + RAG ───────────────────────────────────
        if captured_thought.strip():
            self._archive_reasoning(model, task_id, captured_thought, full_response, density_ok)
        elif not density_ok and captured_thought:
            print(
                f"⚠️  [COT] Réflexion trop courte ({len(captured_thought)} chars < {MIN_THOUGHT_CHARS})"
            )

        return {
            "content": full_response.strip(),
            "thought_trace": captured_thought,
            "density_ok": density_ok,
        }

    # ── Archivage ─────────────────────────────────────────────────────────────

    def _archive_reasoning(
        self,
        model: str,
        task_id: str,
        thought: str,
        result: str,
        quality_flag: bool,
    ) -> Path:
        """Archive la réflexion sur le NVMe et l'indexe dans le RAG épisodique.

        Args:
            model:        Nom du modèle.
            task_id:      ID de la tâche.
            thought:      Chaîne de pensée capturée.
            result:       Réponse finale du modèle.
            quality_flag: True si densité cognitive suffisante.

        Returns:
            Chemin du fichier de trace archivé.
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        status_tag = "VALID" if quality_flag else "LOW_DENSITY"
        log_file = self.thought_dir / f"trace_{task_id}_{ts}_{status_tag}.txt"

        header = (
            f"--- LOG DE RAISONNEMENT NOKIDO ---\n"
            f"DATE   : {datetime.now().isoformat()}\n"
            f"MODÈLE : {model} | STATUS : {status_tag}\n"
            f"TASK   : {task_id}\n"
            f"-----------------------------------\n\n"
        )

        try:
            # Écriture groupée — exploite la bande passante PCIe 5.0
            log_file.write_text(
                header + "CHAÎNE DE PENSÉE :\n" + thought + "\n\nSORTIE FINALE :\n" + result,
                encoding="utf-8",
            )

            # Injection RAG épisodique
            entry = {
                "timestamp": datetime.now().isoformat(),
                "type": "thought_trace",
                "task_id": task_id,
                "model": model,
                "density_ok": quality_flag,
                "thought_path": str(log_file),
                "thought_len": len(thought),
                "summary": thought[:150].strip().replace("\n", " ") + "...",
            }
            with self.memory_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            print(f"💾 [NVMe] Archivé : {log_file.name} ({len(thought)} chars | {status_tag})")

        except Exception as e:
            print(f"⚠️  [THOUGHT] Archivage échoué : {e}")

        return log_file

    # ── Utilitaires ───────────────────────────────────────────────────────────

    def list_thoughts(self, limit: int = 10) -> list[dict]:
        """Liste les réflexions archivées récentes.

        Args:
            limit: Nombre maximum de résultats.

        Returns:
            Liste de dicts {name, task_id, status, size, ts}.
        """
        files = sorted(
            self.thought_dir.glob("trace_*.txt"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]
        return [
            {
                "name": f.name,
                "task_id": f.name.split("_")[1] if "_" in f.name else "?",
                "status": "VALID" if "VALID" in f.name else "LOW_DENSITY",
                "size": f.stat().st_size,
                "ts": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            }
            for f in files
        ]

    def replay_thought(self, thought_file: str) -> str:
        """Relit une réflexion archivée.

        Args:
            thought_file: Nom ou chemin complet du fichier.

        Returns:
            Contenu de la trace de raisonnement.
        """
        p = Path(thought_file)
        if not p.is_absolute():
            p = self.thought_dir / p
        return p.read_text(encoding="utf-8") if p.exists() else f"[THOUGHT ERR] {p} introuvable"

    def get_stats(self) -> dict:
        """Retourne les statistiques des réflexions archivées.

        Returns:
            Dict avec total, valid, low_density, total_chars.
        """
        files = list(self.thought_dir.glob("trace_*.txt"))
        valid = sum(1 for f in files if "VALID" in f.name)
        low = sum(1 for f in files if "LOW_DENSITY" in f.name)
        total_b = sum(f.stat().st_size for f in files)
        return {
            "total": len(files),
            "valid": valid,
            "low_density": low,
            "total_kb": round(total_b / 1024, 1),
        }
