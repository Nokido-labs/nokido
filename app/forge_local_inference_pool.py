"""forge_local_inference_pool.py — pool d'inférence locale (ForgeSwarm M3).

Fournit l'`infer_fn` RÉEL injecté dans le worker (M2) / l'orchestrateur (M5).
Deux backends :
  - **llamacpp** (préféré) : `forge_llamacpp.llamacpp_call(schema=GBNF)`. Le
    parallélisme frugal vient des SLOTS du llama-server (lancer
    `--ctx-size 16384 --parallel 2 --cont-batching`) ; le `n_ctx` est une config
    serveur (LLAMACPP_N_CTX), pas un paramètre par-appel.
  - **ollama** (fallback) : HTTP direct `:11434/api/chat` pour pouvoir passer
    `options.num_ctx` DYNAMIQUE (forge_ollama.ollama_call ne l'expose pas).

Discipline mémoire : un Semaphore borne la concurrence à `OLLAMA_NUM_PARALLEL`
(défaut 2) — empile les sous-requêtes au lieu d'asphyxier la RAM unifiée.

Backends INJECTABLES → logique (ordre, fallback, n_ctx, sémaphore) testable sans LLM.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import time
import urllib.request
from pathlib import Path
from nokido_agent.app.forge_secrets import get_secret

_OLLAMA_RAW = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
# Ollama pose souvent OLLAMA_HOST="127.0.0.1:11434" SANS schéma → urllib lève
# "unknown url type". On normalise (sinon ollama raise → fallback poison).
OLLAMA_BASE = _OLLAMA_RAW if "://" in _OLLAMA_RAW else f"http://{_OLLAMA_RAW}"
_SWARM_OLLAMA_MODEL = os.environ.get("LAFORGE_SWARM_OLLAMA_MODEL", "qwen2.5-coder:7b-instruct-q4_K_M")


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)  # heuristique ~4 chars/token


def dynamic_n_ctx(prompt: str, *, floor: int = 2048, cap: int = 8192, factor: float = 1.3, out_budget: int = 512) -> int:
    """n_ctx dynamique : assez pour le contexte + la génération, capé (TTFT local)."""
    n = math.ceil(estimate_tokens(prompt) * factor) + out_budget
    return max(floor, min(cap, n))


def _ensure_app_path() -> None:
    p = str(Path(__file__).resolve().parent)
    if p not in sys.path:
        sys.path.insert(0, p)


def make_openrouter_free_backend(model: str | None = None):
    """Lane CLOUD quota-free (OpenRouter modèle :free) = repli RÉACTIF quand les lanes locales
    échouent/saturent. 0 crédit -> jamais 402. Clé via env ou forge_agent_proxy._load_api_key."""
    mdl = model or os.environ.get("LAFORGE_OPENROUTER_FREE_MODEL", "deepseek/deepseek-chat-v3-0324:free")

    async def _cloud(prompt: str, *, schema=None, n_ctx=None, timeout: float = 120.0, model=None) -> str:
        key = get_secret("OPENROUTER_API_KEY") or get_secret("OPENROUTEUR_API_KEY")
        if not key:
            try:
                from nokido_agent.app.forge_agent_proxy import _load_api_key
                key = _load_api_key("OPENROUTER_API_KEY") or _load_api_key("OPENROUTEUR_API_KEY")
            except Exception:  # noqa: BLE001
                key = None
        if not key:
            raise RuntimeError("cloud :free indisponible (OPENROUTER_API_KEY absente)")
        payload: dict = {"model": mdl, "messages": [{"role": "user", "content": prompt}], "max_tokens": 1200}
        if schema:
            payload["response_format"] = {"type": "json_schema",
                                          "json_schema": {"name": schema.get("title", "out"), "strict": True, "schema": schema}}
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions", data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "HTTP-Referer": "https://nokido.local", "X-Title": "Nokido"})

        def _call() -> str:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            ch = data.get("choices")
            if not ch:
                raise RuntimeError(f"cloud :free sans choices: {str(data)[:160]}")
            return ch[0]["message"]["content"]

        txt = (await asyncio.get_event_loop().run_in_executor(None, _call)) or ""
        t = txt.strip()
        if t.startswith("```"):
            t = t[3:]
            if t[:4].lower() == "json":
                t = t[4:]
            t = t.strip().removesuffix("```").strip()
        return t

    return _cloud


def _default_backends() -> dict:
    async def _llamacpp(prompt: str, *, schema=None, n_ctx=None, timeout=120.0, model=None) -> str:
        _ensure_app_path()
        from nokido_agent.app.forge_llamacpp import llamacpp_call

        # n_ctx = config serveur (LLAMACPP_N_CTX) ; on le suggère best-effort.
        # model = ignoré (llama-server sert un seul blob ; override modèle = ollama only).
        if n_ctx:
            os.environ.setdefault("LLAMACPP_N_CTX", str(n_ctx))
        return await llamacpp_call([{"role": "user", "content": prompt}], schema=schema)

    async def _ollama(prompt: str, *, schema=None, n_ctx=None, timeout=120.0, model=None) -> str:
        body = {
            "model": model or _SWARM_OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"num_ctx": n_ctx or 8192},
        }
        if schema:
            body["format"] = schema
        req = urllib.request.Request(
            OLLAMA_BASE + "/api/chat",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        def _call() -> str:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())["message"]["content"]

        return await asyncio.get_event_loop().run_in_executor(None, _call)

    backends = {"llamacpp": _llamacpp, "ollama": _ollama}
    # Repli cloud quota-free RÉACTIF (opt-in : besoin clé + réseau). Lane tentée EN DERNIER
    # (pas prefer, latence inconnue) -> seulement quand les lanes locales sont en cooldown/échec.
    if os.environ.get("LAFORGE_POOL_CLOUD_FALLBACK") == "1":
        try:
            backends["cloud_free"] = make_openrouter_free_backend()
        except Exception:  # noqa: BLE001
            pass
    return backends


# --- fiabilisation pool : fast-fail + circuit-breaker (anti-wedge, user 2026-06-15) ---
_BREAK_BASE = float(os.environ.get("LAFORGE_POOL_BREAK_BASE", "30"))   # cooldown initial backend en panne (s)
_BREAK_MAX = float(os.environ.get("LAFORGE_POOL_BREAK_MAX", "300"))    # cap cooldown (s)


async def warm_models(models: list[str], *, base: str | None = None, keep_alive: str = "30m",
                      timeout: float = 300.0) -> dict:
    """Préchargement du flux de travail : charge + garde au chaud (ollama keep_alive) les
    modèles AVANT le hot-path, pour éliminer les stalls de cold-load (ex. 7b ~60s -> chaud).
    Retourne {model: {ok, latency_ms|error}}. Best-effort, séquentiel (discipline VRAM)."""
    b = (base or OLLAMA_BASE).rstrip("/")
    out: dict[str, dict] = {}
    loop = asyncio.get_event_loop()
    for m in models:
        body = json.dumps({
            "model": m,
            "messages": [{"role": "user", "content": "ok"}],
            "stream": False,
            "keep_alive": keep_alive,
            "options": {"num_predict": 1},
        }).encode()
        req = urllib.request.Request(b + "/api/chat", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")

        def _call() -> None:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                r.read()

        t0 = time.monotonic()
        try:
            await loop.run_in_executor(None, _call)
            out[m] = {"ok": True, "latency_ms": round((time.monotonic() - t0) * 1000.0, 1)}
        except Exception as e:  # noqa: BLE001
            out[m] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return out


class LocalInferencePool:
    """Pool borné multi-backend. `infer()` essaie le backend préféré puis fallback."""

    def __init__(self, *, max_parallel: int | None = None, backends: dict | None = None, prefer: str = "llamacpp"):
        n = max_parallel if max_parallel is not None else int(os.environ.get("OLLAMA_NUM_PARALLEL", "2"))
        self._sem = asyncio.Semaphore(max(1, n))
        self.prefer = prefer
        self.backends = backends if backends is not None else _default_backends()
        self._fails: dict[str, tuple[int, float]] = {}  # name -> (fail_count, cooldown_until_monotonic)
        self._lat: dict[str, float] = {}  # name -> EWMA latence ms (équilibrage latency-aware)

    def _in_cooldown(self, name: str) -> bool:
        _c, until = self._fails.get(name, (0, 0.0))
        return time.monotonic() < until

    def _record_ok(self, name: str) -> None:
        self._fails.pop(name, None)

    def _record_fail(self, name: str) -> None:
        c, _u = self._fails.get(name, (0, 0.0))
        c += 1
        cooldown = min(_BREAK_MAX, _BREAK_BASE * (2 ** (c - 1)))
        self._fails[name] = (c, time.monotonic() + cooldown)

    def _record_latency(self, name: str, ms: float) -> None:
        prev = self._lat.get(name)
        self._lat[name] = ms if prev is None else (prev * 0.7 + ms * 0.3)  # EWMA

    def _order(self) -> list[str]:
        # Équilibrage health+latency-aware : cooldown en dernier ; sinon la lane la PLUS
        # RAPIDE mesurée d'abord (hot-swap). Lane non mesurée : préférée tentée tôt (pour
        # apprendre), non-préférée tentée en dernier.
        def keyf(k: str) -> tuple:
            cool = 1 if self._in_cooldown(k) else 0
            lat = self._lat.get(k)
            v = lat if lat is not None else (-1.0 if k == self.prefer else 1e12)
            return (cool, v)

        return sorted(self.backends, key=keyf)

    def monitor(self) -> dict:
        """Lecture d'état des lanes : santé / latence / charge (monitoring + contrôle)."""
        out: dict[str, dict] = {}
        for name in self.backends:
            c, _until = self._fails.get(name, (0, 0.0))
            out[name] = {
                "latency_ms": round(self._lat[name], 1) if name in self._lat else None,
                "cooldown": self._in_cooldown(name),
                "fails": c,
                "preferred": name == self.prefer,
            }
        return out

    async def probe_all(self, prompt: str = "ping", *, timeout: float = 30.0, n_ctx: int = 256) -> dict:
        """Sonde CHAQUE lane (latence + santé) — source de données pour _order + warm.
        Une lane qui échoue/timeout entre en cooldown (breaker) ; une lane OK est mesurée."""
        grace = float(os.environ.get("LAFORGE_POOL_WAIT_GRACE", "10"))
        for name in list(self.backends):
            t0 = time.monotonic()
            try:
                await asyncio.wait_for(
                    self.backends[name](prompt, schema=None, n_ctx=n_ctx, timeout=timeout, model=None),
                    timeout=timeout + grace,
                )
                self._record_latency(name, (time.monotonic() - t0) * 1000.0)
                self._record_ok(name)
            except Exception:  # noqa: BLE001
                self._record_fail(name)
        return self.monitor()

    async def infer(self, prompt: str, *, schema=None, n_ctx: int | None = None, timeout: float = 120.0,
                    model: str | None = None, tag: str | None = None) -> str:
        # `model` = override par-appel (ollama only). `tag` = absorbé (compat LensRoutedPool).
        if n_ctx is None:
            n_ctx = dynamic_n_ctx(prompt)
        grace = float(os.environ.get("LAFORGE_POOL_WAIT_GRACE", "10"))
        async with self._sem:  # discipline mémoire : empile au-delà de N slots
            last = None
            for name in self._order():
                try:
                    # plafond DUR : un backend wedgé (ex. llamacpp in-process bloqué sur iGPU)
                    # ne peut plus suspendre infer() indéfiniment -> on bascule sur le suivant.
                    t0 = time.monotonic()
                    out = await asyncio.wait_for(
                        self.backends[name](prompt, schema=schema, n_ctx=n_ctx, timeout=timeout, model=model),
                        timeout=timeout + grace,
                    )
                    self._record_latency(name, (time.monotonic() - t0) * 1000.0)
                    self._record_ok(name)
                    return out
                except asyncio.TimeoutError:
                    self._record_fail(name)
                    last = f"{name}: TimeoutError (>{timeout + grace:.0f}s, backend wedgé)"
                except Exception as e:  # noqa: BLE001
                    self._record_fail(name)
                    last = f"{name}: {type(e).__name__}: {e}"
            raise RuntimeError(f"tous les backends locaux ont échoué ({last})")

    def make_infer_fn(self, *, schema=None):
        """Retourne un `infer_fn(prompt) -> str` prêt pour run_worker / run_forge_swarm."""

        async def _f(prompt: str) -> str:
            return await self.infer(prompt, schema=schema)

        return _f


# ── Swarm souverain multi-modèle : routage / ensemble par lens ───────────────
# NB : 32b-q4 OOM la RAM unifiée de l'APU → hors route défaut. Strong = opt-in via
# LAFORGE_AUDIT_STRONG (ou tier DISTANT cerebras/groq via remote_fn). Défaut = modèles
# locaux RAPIDES qui tiennent en RAM, diversité de familles pour l'ensemble.
_FAST = os.environ.get("LAFORGE_AUDIT_FAST", "qwen2.5-coder:7b-instruct-q4_K_M")
_ALT = os.environ.get("LAFORGE_AUDIT_ALT", "deepseek-coder:6.7b")
_REASON = os.environ.get("LAFORGE_AUDIT_REASON", "qwen3:8b")
_STRONG = os.environ.get("LAFORGE_AUDIT_STRONG", _FAST)  # défaut = fast ; mettre 32b/cloud si voulu

# Map lens → modèle (str) OU liste de modèles (ensemble : union findings, dédup AST aval).
DEFAULT_LENS_ROUTE = {
    "security": [_FAST, _ALT],     # ensemble : 2 familles (qwen+deepseek) se croisent
    "correctness": _STRONG,        # bug fonctionnel → modèle fort (fast par défaut)
    "architecture": _REASON,       # raisonnement → qwen3
    "style": _FAST,                # cosmétique → rapide
}


class LensRoutedPool:
    """Pool souverain multi-modèle. Route chaque `tag` (= lens) vers un modèle local —
    ou une LISTE = ensemble (exécute tous, union des findings ; le reducer AST aval
    dédup + jette les hallucinations = vote implicite). Distant = seam `remote_fn`
    (à brancher sur forge_llm_router + SemanticFirewall ; inerte sans clé)."""

    def __init__(self, *, route=None, default=None, base: LocalInferencePool | None = None,
                 merge_key: str = "findings", remote_fn=None):
        self.route = dict(route or DEFAULT_LENS_ROUTE)
        self.default = default or _FAST
        self.base = base or LocalInferencePool(prefer="ollama")
        self.merge_key = merge_key
        self.remote_fn = remote_fn  # async (prompt, *, schema, tag) -> str | None

    def models_for(self, tag) -> list[str]:
        m = self.route.get(tag, self.default)
        return list(m) if isinstance(m, (list, tuple)) else [m]

    async def _one(self, m, prompt, *, schema, n_ctx, timeout):
        """Un modèle. Entrée 'cloud:<use_case>' → tier DISTANT via remote_fn (firewall intégré)."""
        if isinstance(m, str) and m.startswith("cloud:"):
            if not self.remote_fn:
                raise RuntimeError("route 'cloud:' demandée mais remote_fn non câblé")
            return await self.remote_fn(prompt, schema=schema, tag=m.split(":", 1)[1])
        return await self.base.infer(prompt, schema=schema, n_ctx=n_ctx, timeout=timeout, model=m)

    async def infer(self, prompt: str, *, schema=None, n_ctx=None, timeout=120.0,
                    model: str | None = None, tag: str | None = None) -> str:
        models = [model] if model else self.models_for(tag)
        if len(models) == 1:
            return await self._one(models[0], prompt, schema=schema, n_ctx=n_ctx, timeout=timeout)
        # ENSEMBLE : chaque modèle (local OU cloud) évalue, on UNIONne les findings (dédup AST aval).
        outs = await asyncio.gather(
            *[self._one(mm, prompt, schema=schema, n_ctx=n_ctx, timeout=timeout) for mm in models],
            return_exceptions=True,
        )
        merged: list = []
        for o in outs:
            if isinstance(o, Exception):
                continue
            try:
                merged.extend(json.loads(o).get(self.merge_key, []) or [])
            except Exception:
                pass
        return json.dumps({self.merge_key: merged})

    def make_infer_fn(self, *, schema=None, tag=None):
        async def _f(prompt: str) -> str:
            return await self.infer(prompt, schema=schema, tag=tag)

        return _f


# ── Tier DISTANT : route lens → cloud:<use_case> (cerebras/groq via forge_llm_router) ──
# call_cascade() exécute SemanticFirewall.pre_flight EN INTERNE (Règle d'or #4) + tire les
# clés du vault DPAPI (forge_secrets.get_secret). Aucune injection env requise.
CLOUD_LENS_ROUTE = {
    "security": "cloud:code",       # use_case code → chain groq/cerebras forts
    "correctness": "cloud:code",
    "architecture": "cloud:reasoning",
    "style": "cloud:speed",         # cosmétique → le + rapide
}

# Hybride : lens dure au cloud, reste en local (souverain + frugal).
HYBRID_LENS_ROUTE = {
    "security": "cloud:code",
    "correctness": _FAST,
    "architecture": _REASON,
    "style": _FAST,
}


# Slots cloud FORTS avec clé présente (ordre = préférence). call_cascade route
# local-first → inutile pour forcer la puissance ; on cible les slots directement.
# Free-tier = rate-limit agressif → on SÉRIALISE (sémaphore) + retry backoff sur 429.
_CLOUD_SLOTS = [
    s.strip() for s in os.environ.get(
        "LAFORGE_AUDIT_CLOUD_SLOTS",
        "openrouter_gpt_oss,hf_llama",  # gpt-oss-120b prouvé OK ; hf = filet dernier recours
    ).split(",") if s.strip()
]

_CLOUD_SEM = None  # bornage concurrence cloud (créé lazy dans la boucle d'événements)


def _cloud_sem():
    global _CLOUD_SEM
    if _CLOUD_SEM is None:
        _CLOUD_SEM = asyncio.Semaphore(int(os.environ.get("LAFORGE_AUDIT_CLOUD_PARALLEL", "1")))
    return _CLOUD_SEM


def _is_rate_limited(err: str) -> bool:
    e = (err or "").lower()
    return "ratelimit" in e or "rate limit" in e or "429" in e


def make_cloud_remote_fn(*, slots=None, max_tokens: int = 1400, temperature: float = 0.2,
                         timeout: int = 60, ring: int = 3, retries: int = 3, public: bool = False):
    """remote_fn(prompt, *, schema, tag) -> str. FORCE un slot cloud fort (pas la cascade
    local-first) + SemanticFirewall pre/post manuel (egress code = Règle d'or #4). Clé tirée
    du vault par ProviderSlot.api_key. SÉRIALISÉ (sémaphore) + retry backoff sur 429.

    public=True : code open-source → on SKIP la redaction DLP (faux-positifs type
    [BASE64_SUSPECT] qui dégradent le code) ; le véto injection/ring reste actif."""
    cands = list(slots or _CLOUD_SLOTS)

    async def _remote(prompt: str, *, schema=None, tag: str = "code") -> str:
        def _call() -> str:
            import time as _t
            _ensure_app_path()
            from nokido_agent.app.forge_llm_router import get_router
            from nokido_agent.app.forge_semantic_firewall import get_firewall

            router = get_router()
            fw = get_firewall()
            pf = fw.pre_flight(prompt, context="", ring=ring, provider="auto")
            # Hard-véto SEULEMENT sur injection / ring (vrai danger). Le DLP faux-positive
            # sur du code (ex [BASE64_SUSPECT]) → on RÉDIGE (original→placeholder) et on envoie
            # le rédigé (egress propre), puis restore en sortie. CLAUDE.md §5.
            if getattr(pf, "injection", False) or getattr(pf, "ring_blocked", False):
                raise RuntimeError(f"firewall véto (injection/ring): {pf.reason}")
            if public:
                mapping = {}          # code public → pas de redaction DLP (faux-positifs)
                safe = prompt         # code intact → meilleure détection
            else:
                mapping = pf.mapping or {}
                safe = pf.safe_task or ""
                if not safe:
                    safe = prompt
                    for _ph, _orig in mapping.items():
                        safe = safe.replace(str(_orig), str(_ph))
            last = "aucun slot"
            for name in cands:
                slot = router._slots.get(name)
                if not slot:
                    last = f"{name}: no slot"
                    continue
                for attempt in range(retries):
                    res = router._call_slot(slot, safe, "", max_tokens, temperature, timeout, tag or "code")
                    if res.get("ok") and res.get("text"):
                        txt = res["text"]
                        try:
                            pfr = fw.post_flight(txt, task=prompt, expected_fmt="json" if schema else "text")
                            txt = getattr(pfr, "response", None) or txt
                        except Exception:
                            pass
                        return fw.restore(txt, mapping)
                    last = f"{name}: {res.get('error')}"
                    if _is_rate_limited(res.get("error", "")) and attempt < retries - 1:
                        _t.sleep(2.0 * (attempt + 1))  # backoff puis retry MÊME slot
                        continue
                    break  # erreur non-429 → slot suivant
            raise RuntimeError(f"tous les slots cloud KO ({last})")

        async with _cloud_sem():  # discipline rate-limit : free-tier supporte mal le burst
            return await asyncio.get_event_loop().run_in_executor(None, _call)

    return _remote
