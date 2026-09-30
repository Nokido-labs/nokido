"""
forge_hot_load_manager.py — Gestion keep-alive Ollama + tracking quotas Cloud
==============================================================================
Maintient les modèles locaux "chauds" en VRAM pour éliminer le cold-start (~5s)
et surveille les quotas Free Tier des APIs cloud (Groq/Gemini/OpenRouter).

Ce module NE falsifie PAS les métriques système — il les expose telles quelles
et laisse l'orchestrateur décider. Le lissage s'applique uniquement au
reporting vers des dashboards de monitoring, pas à la logique de décision.

Fonctionnalités :
  1. Keep-alive Ollama   : heartbeat toutes les N minutes pour éviter le déchargement
  2. Quota tracking      : fenêtre glissante RPM/TPM par provider
  3. Context optimizer   : ajuste num_ctx selon la taille du fichier et la VRAM dispo
  4. Failover indicator  : signale quand basculer local↔cloud

Usage :
    from tools.forge_hot_load_manager import ForgeHotLoadManager
    mgr = ForgeHotLoadManager()
    mgr.keep_warm("qwen2.5-coder:7b")
    ctx = mgr.optimal_context("app/forge_agents.py")
    quota = mgr.quota_headroom("groq")
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import psutil
import requests

# ── Configuration ──────────────────────────────────────────────────────────────
OLLAMA_API = "http://localhost:11434/api/chat"
KEEP_ALIVE_VAL = "60m"  # Modèle maintenu 1h sans requête
VRAM_TARGET_GB = 8.0  # VRAM allouée à l'iGPU 780M
HEARTBEAT_SECS = 270  # Heartbeat toutes les 4.5 min (< 5 min timeout Ollama)

# Limites Free Tier par provider (RPM = Requests Per Minute)
PROVIDER_LIMITS: dict[str, dict] = {
    "groq": {"rpm": 30, "tpm": 6_000, "rpd": 1_440},
    "gemini": {"rpm": 15, "tpm": 1_000_000, "rpd": 1_500},
    "openrouter": {"rpm": 20, "tpm": 200_000, "rpd": 0},  # 0 = illimité
    "ollama": {"rpm": 999, "tpm": 999_999, "rpd": 0},
}


class ProviderQuotaTracker:
    """Suit les appels par provider avec fenêtre glissante 60s."""

    def __init__(self, rpm_limit: int, tpm_limit: int) -> None:
        """Initialise le tracker de quota.

        Args:
            rpm_limit: Limite de requêtes par minute.
            tpm_limit: Limite de tokens par minute.
        """
        self.rpm_limit = rpm_limit
        self.tpm_limit = tpm_limit
        self._calls: deque[tuple[float, int]] = deque()  # (ts, tokens)

    def record(self, tokens: int = 0) -> None:
        """Enregistre un appel avec son nombre de tokens.

        Args:
            tokens: Tokens consommés pour cet appel.
        """
        now = time.time()
        self._calls.append((now, tokens))
        # Purger les appels > 60s
        while self._calls and now - self._calls[0][0] > 60:
            self._calls.popleft()

    @property
    def rpm_used(self) -> int:
        """Nombre de requêtes dans la dernière minute.

        Returns:
            Nombre d'appels récents.
        """
        now = time.time()
        return sum(1 for ts, _ in self._calls if now - ts <= 60)

    @property
    def tpm_used(self) -> int:
        """Tokens utilisés dans la dernière minute.

        Returns:
            Total de tokens récents.
        """
        now = time.time()
        return sum(t for ts, t in self._calls if now - ts <= 60)

    @property
    def rpm_headroom(self) -> int:
        """Requêtes restantes avant la limite RPM.

        Returns:
            Marge RPM disponible.
        """
        return max(0, self.rpm_limit - self.rpm_used)

    @property
    def tpm_headroom(self) -> int:
        """Tokens restants avant la limite TPM.

        Returns:
            Marge TPM disponible.
        """
        return max(0, self.tpm_limit - self.tpm_used)

    @property
    def is_throttled(self) -> bool:
        """True si le provider est en cooldown (< 2 RPM disponibles).

        Returns:
            True si throttled.
        """
        return self.rpm_headroom < 2

    def to_dict(self) -> dict:
        """Retourne l'état sous forme de dict.

        Returns:
            Dict avec rpm_used, rpm_headroom, tpm_used, throttled.
        """
        return {
            "rpm_used": self.rpm_used,
            "rpm_headroom": self.rpm_headroom,
            "tpm_used": self.tpm_used,
            "tpm_headroom": self.tpm_headroom,
            "throttled": self.is_throttled,
        }


class ForgeHotLoadManager:
    """Gère le keep-alive des modèles locaux et les quotas cloud."""

    def __init__(self) -> None:
        """Initialise le manager avec les trackers de quota."""
        self._trackers: dict[str, ProviderQuotaTracker] = {
            name: ProviderQuotaTracker(limits["rpm"], limits["tpm"])
            for name, limits in PROVIDER_LIMITS.items()
        }
        self._warm_models: dict[str, float] = {}  # model → last_heartbeat
        self._lock = threading.Lock()
        self._heartbeat_thread: threading.Thread | None = None

    # ── Keep-alive ────────────────────────────────────────────────────────────

    def keep_warm(self, model_name: str) -> bool:
        """Envoie un heartbeat Ollama pour maintenir le modèle en VRAM.

        Args:
            model_name: Nom du modèle Ollama (ex: 'qwen2.5-coder:7b').

        Returns:
            True si heartbeat envoyé avec succès.
        """
        if not model_name or "ollama" not in model_name.lower():
            # Extraire le nom si préfixé ollama/
            if not model_name.startswith("ollama/"):
                return False
            model_name = model_name.replace("ollama/", "")

        model_name = model_name.replace("ollama/", "")
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": ""}],
            "keep_alive": KEEP_ALIVE_VAL,
        }
        try:
            requests.post(OLLAMA_API, json=payload, timeout=0.5)
            with self._lock:
                self._warm_models[model_name] = time.time()
            return True
        except Exception:
            return False

    def start_heartbeat(self, models: list[str]) -> None:
        """Démarre un thread de heartbeat automatique.

        Args:
            models: Liste des modèles à maintenir chauds.
        """
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        def _loop() -> None:
            while True:
                for m in models:
                    self.keep_warm(m)
                time.sleep(HEARTBEAT_SECS)

        self._heartbeat_thread = threading.Thread(target=_loop, daemon=True, name="ForgeHeartbeat")
        self._heartbeat_thread.start()

    def is_warm(self, model_name: str, max_age_s: int = HEARTBEAT_SECS * 2) -> bool:
        """Vérifie si un modèle est probablement encore en VRAM.

        Args:
            model_name: Nom du modèle.
            max_age_s:  Âge maximum du dernier heartbeat.

        Returns:
            True si le modèle est probablement chaud.
        """
        model_name = model_name.replace("ollama/", "")
        last = self._warm_models.get(model_name, 0)
        return time.time() - last < max_age_s

    # ── Quota tracking ────────────────────────────────────────────────────────

    def record_call(self, provider: str, tokens: int = 0) -> None:
        """Enregistre un appel API pour le suivi de quota.

        Args:
            provider: Nom du provider (groq, gemini, openrouter...).
            tokens:   Tokens consommés.
        """
        name = self._normalize_provider(provider)
        if name in self._trackers:
            self._trackers[name].record(tokens)

    def quota_headroom(self, provider: str) -> dict:
        """Retourne la marge de quota disponible pour un provider.

        Args:
            provider: Nom du provider.

        Returns:
            Dict avec rpm_headroom, tpm_headroom, throttled.
        """
        name = self._normalize_provider(provider)
        tracker = self._trackers.get(name)
        if not tracker:
            return {"rpm_headroom": 999, "tpm_headroom": 999_999, "throttled": False}
        return tracker.to_dict()

    def best_available_provider(self, candidates: list[str]) -> str | None:
        """Retourne le meilleur provider disponible parmi les candidats.

        Choisit celui avec le plus de headroom RPM et non throttlé.

        Args:
            candidates: Liste de noms de providers.

        Returns:
            Nom du meilleur provider ou None si tous throttlés.
        """
        available = []
        for p in candidates:
            q = self.quota_headroom(p)
            if not q.get("throttled"):
                available.append((p, q.get("rpm_headroom", 0)))
        if not available:
            return None
        return max(available, key=lambda x: x[1])[0]

    def _normalize_provider(self, provider: str) -> str:
        """Normalise un nom de provider.

        Args:
            provider: Nom brut (ex: 'groq/llama-70b').

        Returns:
            Nom normalisé (ex: 'groq').
        """
        p = provider.lower().split("/")[0]
        if "groq" in p:
            return "groq"
        if "gemini" in p:
            return "gemini"
        if "ollama" in p:
            return "ollama"
        return p

    # ── Context optimizer ─────────────────────────────────────────────────────

    def optimal_context(self, file_path: str) -> int:
        """Calcule le num_ctx optimal selon la taille du fichier et la VRAM.

        Ne pas envoyer 32k tokens à un iGPU 8GB partagé — ça swapperait.

        Args:
            file_path: Chemin du fichier à muter.

        Returns:
            Taille de contexte recommandée (tokens).
        """
        try:
            size_kb = Path(file_path).stat().st_size / 1024
        except FileNotFoundError:
            return 8192

        ram_pct = psutil.virtual_memory().percent

        # Réduction si RAM sous pression
        pressure_factor = 0.5 if ram_pct > 80 else 1.0

        if size_kb > 100:
            ctx = 4096  # Gros fichier → contexte chirurgical
        elif size_kb > 30:
            ctx = 8192  # Fichier moyen
        else:
            ctx = 16384  # Petit fichier → contexte large

        return int(ctx * pressure_factor)

    # ── Métriques système (sans falsification) ────────────────────────────────

    def system_metrics(self) -> dict:
        """Retourne les métriques système réelles.

        Returns:
            Dict avec cpu_pct, ram_pct, vram_target_gb, warm_models.
        """
        vm = psutil.virtual_memory()
        return {
            "cpu_pct": psutil.cpu_percent(interval=0.1),
            "ram_pct": vm.percent,
            "ram_used_gb": round(vm.used / 1024**3, 1),
            "ram_total_gb": round(vm.total / 1024**3, 1),
            "vram_target_gb": VRAM_TARGET_GB,
            "warm_models": list(self._warm_models.keys()),
            "timestamp": datetime.now().isoformat(),
        }

    def all_quotas(self) -> dict:
        """Retourne l'état de tous les quotas.

        Returns:
            Dict provider → quota dict.
        """
        return {name: t.to_dict() for name, t in self._trackers.items()}

    def fetch_openrouter_limits(self, api_key: str | None = None) -> dict:
        """Récupère les limites réelles du compte OpenRouter via l'API.

        Met à jour le tracker openrouter avec les vraies valeurs RPM/TPM.
        Endpoint : https://openrouter.ai/api/v1/auth/key

        Args:
            api_key: Clé OpenRouter (lu dans Nokido.env si None).

        Returns:
            Dict avec rate_limit, usage, is_free_tier.
        """
        import httpx  # noqa: PLC0415

        if not api_key:
            try:
                env = (Path(__file__).parent.parent / "Nokido.env").read_text()
                api_key = next(
                    (
                        l.split("=", 1)[1].strip()
                        for l in env.splitlines()
                        if l.startswith("OPENROUTEUR_API_KEY=")
                        or l.startswith("OPENROUTER_API_KEY=")
                    ),
                    None,
                )
            except Exception:
                pass

        if not api_key:
            return {"error": "OPENROUTER_API_KEY absente dans Nokido.env"}

        try:
            r = httpx.get(
                "https://openrouter.ai/api/v1/auth/key",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=8,
            )
            data = r.json().get("data", {})
            limit = data.get("rate_limit", {})
            rpm = limit.get("requests", 20)
            # Mettre à jour le tracker openrouter dynamiquement
            if "openrouter" in self._trackers:
                self._trackers["openrouter"].rpm_limit = rpm
            return {
                "rpm_limit": rpm,
                "is_free_tier": data.get("is_free_tier", True),
                "usage": data.get("usage", 0),
                "label": data.get("label", ""),
            }
        except Exception as e:
            return {"error": str(e)}

    def fetch_all_model_contexts(self) -> dict[str, int]:
        """Récupère les context_length de tous les modèles OpenRouter free.

        Utile pour optimal_context() — connaître le vrai ctx max du modèle.

        Returns:
            Dict {model_id: context_length} pour les modèles :free.
        """
        import httpx  # noqa: PLC0415

        try:
            r = httpx.get("https://openrouter.ai/api/v1/models", timeout=10)
            models = r.json().get("data", [])
            return {
                m["id"]: m.get("context_length", 8192) for m in models if ":free" in m.get("id", "")
            }
        except Exception:
            return {}

    @property
    def stats(self) -> dict:
        """Retourne un résumé complet.

        Returns:
            Dict avec system_metrics + quotas.
        """
        return {
            "system": self.system_metrics(),
            "quotas": self.all_quotas(),
        }


# ── Singleton global ──────────────────────────────────────────────────────────
_manager: ForgeHotLoadManager | None = None


def get_hot_load_manager() -> ForgeHotLoadManager:
    """Retourne le manager global (singleton).

    Returns:
        Instance ForgeHotLoadManager.
    """
    global _manager
    if _manager is None:
        _manager = ForgeHotLoadManager()
    return _manager
