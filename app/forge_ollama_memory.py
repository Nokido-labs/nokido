"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_ollama_memory
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
forge_ollama_memory.py — extrait automatiquement depuis Nokido.py
Généré par shredder.py
"""

import aiohttp

logger = __import__("logging").getLogger(__name__)


class OllamaMemoryManager:
    """
    Gestion dynamique de la RAM/VRAM consommée par Ollama.
    - Détecte la quantification des modèles chargés (Q4, Q8, F16)
    - Configure le KV cache quantifié automatiquement si RAM faible
    - Stratégies d'éviction adaptatives basées sur la RAM disponible
    - Les modules (RAG, LLM, PTY) communiquent via ce manager
    """

    KNOWN_GiB: dict = {
        "deepseek-coder-v2": 8.9,
        "starcoder2:15b": 9.1,
        "glm-4.7-flash": 19.0,
        "qwen2.5-coder:latest": 4.7,
        "qwen2.5-coder:1.5b": 1.0,
        "mistral:7b": 4.4,
        "mistral:latest": 4.4,
        "qwen3:8b": 5.2,
        "qwen2:7b": 4.4,
        "tinyllama:1.1b": 0.6,
        "starcoder2:latest": 1.7,
        "bge-m3:latest": 1.2,
        "nomic-embed-text:latest": 0.3,
        "erukude/multiagent-orchestrator:1b": 1.4,
        "gpt-oss:120b-cloud": 0.0,
        "deepseek-v3.1:671b-cloud": 0.0,
        "deepseek-v3": 0.0,
        "qwen3-coder:480b-cloud": 0.0,
    }
    EVICT_SCORE: dict = {
        "embed": 0,
        "bge": 0,
        "nomic": 0,
        "1.1b": 1,
        "1.5b": 2,
        "3b": 3,
        "7b": 4,
    }
    # Seuils RAM en Mo pour les stratégies adaptatives
    RAM_CRITICAL = 1500  # > 1.5 Go → éviction agressive
    RAM_WARNING = 1000  # > 1 Go → éviction smart
    RAM_OK = 600  # < 600 Mo → tout va bien

    def __init__(self, base_url: str) -> None:
        """Init.

        Args:
            base_url: Description.
        """
        base = base_url.split("/api/")[0].rstrip("/")
        self._ps = base + "/api/ps"
        self._gen = base + "/api/generate"
        self._show = base + "/api/show"
        self._base = base
        self._model_info_cache: dict = {}  # cache info modèle (quant, params)
        self._kv_quant_enabled = False

    def estimate_gib(self, model: str) -> float:
        """Estimate gib.

        Args:
            model: Description.
        """
        low = model.lower()
        for k, v in self.KNOWN_GiB.items():
            if k in low:
                return v
        for tag, g in [("70b", 40.0), ("34b", 20.0), ("13b", 8.0), ("7b", 4.5), ("3b", 2.0), ("1b", 0.8)]:
            if tag in low:
                return g
        return 3.0

    async def loaded(self) -> list:
        """Loaded."""
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(self._ps, timeout=aiohttp.ClientTimeout(total=5)) as r:
                    if r.status == 200:
                        return (await r.json()).get("models", [])
        except Exception:
            pass
        return []

    async def model_info(self, model: str) -> dict:
        """Récupère les infos d'un modèle : quantification, taille, famille."""
        if model in self._model_info_cache:
            return self._model_info_cache[model]
        info = {"name": model, "quant": "unknown", "params": "?", "family": "?"}
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(self._show, json={"name": model}, timeout=aiohttp.ClientTimeout(total=5)) as r:
                    if r.status == 200:
                        data = await r.json()
                        details = data.get("details", {})
                        info["quant"] = details.get("quantization_level", "unknown")
                        info["params"] = details.get("parameter_size", "?")
                        info["family"] = details.get("family", "?")
                        info["format"] = details.get("format", "?")
        except Exception:
            pass
        self._model_info_cache[model] = info
        return info

    async def detect_quantization(self) -> list:
        """Détecte la quantification de tous les modèles chargés."""
        models = await self.loaded()
        results = []
        for m in models:
            name = m.get("name", "")
            if not name:
                continue
            info = await self.model_info(name)
            gib = m.get("size_vram", m.get("size", 0)) / (1024**3)
            results.append(
                {
                    "name": name,
                    "quant": info["quant"],
                    "params": info["params"],
                    "family": info["family"],
                    "vram_gb": round(gib, 1),
                }
            )
        return results

    async def unload(self, model: str) -> float:
        """Unload.

        Args:
            model: Description.
        """
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    self._gen, json={"model": model, "keep_alive": 0}, timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    if r.status in (200, 204):
                        g = self.estimate_gib(model)
                        logger.debug(f"[MemMgr] unload {model} ~{g:.1f}G")
                        return g
        except Exception as e:
            logger.debug(f"[MemMgr] unload {model}: {e}")
        return 0.0

    async def set_kv_quant(self, model: str, enable: bool = True) -> bool:
        """Configure le KV cache quantifié pour un modèle (via num_ctx + flash_attn)."""
        try:
            # Ollama supporte flash attention et KV cache quantifié via les options
            opts = {"num_ctx": 4096}  # contexte réduit = moins de KV cache
            if enable:
                opts["num_ctx"] = 2048  # contexte court → KV cache minimal
                opts["num_batch"] = 256  # batch réduit
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    self._gen,
                    json={"model": model, "keep_alive": "5m", "options": opts},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    if r.status == 200:
                        self._kv_quant_enabled = enable
                        logger.info(
                            f"[MemMgr] KV quant {'ON' if enable else 'OFF'} pour {model} (ctx={opts['num_ctx']})"
                        )
                        return True
        except Exception as e:
            logger.debug(f"[MemMgr] set_kv_quant: {e}")
        return False

    async def status_lines(self) -> tuple:
        """Status lines."""
        models = await self.loaded()
        lines, total = [], 0.0
        for m in models:
            name = m.get("name", "?")
            gib = m.get("size_vram", m.get("size", 0)) / (1024**3)
            total += gib
            info = await self.model_info(name)
            quant = info.get("quant", "?")
            exp = m.get("expires_at", "")[:16].replace("T", " ")
            lines.append(f"  {name:<35} {quant:<6} {gib:>5.1f} GiB  exp {exp}")
        lines.append(f"  {'TOTAL':<35} {'':6} {total:>5.1f} GiB")
        return lines, total

    async def free(self, strategy: str = "embed", target: str = "") -> dict:
        """Free.

        Args:
            strategy: Description.
            target: Description.
        """
        models = await self.loaded()
        evicted = []
        freed = 0.0
        if strategy == "all":
            for m in models:
                name = m.get("name", "")
                if name and name != target:
                    g = await self.unload(name)
                    evicted.append(name)
                    freed += g
        elif strategy == "embed":
            for m in models:
                name = m.get("name", "")
                if any(k in name.lower() for k in ("embed", "bge", "nomic")):
                    g = await self.unload(name)
                    evicted.append(name)
                    freed += g
        elif strategy == "smart":

            def score(m) -> object:
                """Score.

                Args:
                    m: Description.
                """
                low = m.get("name", "").lower()
                for k, v in OllamaMemoryManager.EVICT_SCORE.items():
                    if k in low:
                        return v
                return 5

            need = self.estimate_gib(target) * 0.4
            for m in sorted(models, key=score):
                name = m.get("name", "")
                if name == target:
                    continue
                g = await self.unload(name)
                evicted.append(name)
                freed += g
                if freed >= need:
                    break
        return {"evicted": evicted, "freed_gib": freed}

    async def adaptive_manage(self, current_ram_mb: float = 0, target_model: str = "") -> object:
        """
        Stratégie adaptive — appelée automatiquement par le watchdog mémoire.
        Les modules ne s'appellent pas entre eux — ils passent tous par ici.
        """
        actions = []
        if current_ram_mb > self.RAM_CRITICAL:
            # Critique → tout décharger sauf le modèle cible
            r = await self.free("all", target=target_model)
            actions.append(f"critical: evicted {r['evicted']}")
            # Activer KV quant sur le modèle actif
            if target_model:
                await self.set_kv_quant(target_model, enable=True)
                actions.append(f"kv_quant ON for {target_model}")
        elif current_ram_mb > self.RAM_WARNING:
            # Warning → éviction smart
            r = await self.free("smart", target=target_model)
            if r["evicted"]:
                actions.append(f"smart: evicted {r['evicted']}")
        else:
            # OK → désactiver KV quant si activé
            if self._kv_quant_enabled and target_model:
                await self.set_kv_quant(target_model, enable=False)
                actions.append("kv_quant OFF (RAM OK)")
        if actions:
            logger.info(f"[MemMgr] adaptive: {', '.join(actions)}")
        return actions


def get_mem_mgr() -> "OllamaMemoryManager":
    """Get mem mgr."""
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    _mem_mgr = _ac.mem_mgr
    return _mem_mgr
