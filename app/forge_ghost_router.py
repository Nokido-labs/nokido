"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_ghost_router
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
import asyncio, gc, os, sys, time, threading
from pathlib import Path


def _gs(k: str) -> str:
    """Secure secret access — WCM > .env > os.environ."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret(k) or ""
    except Exception:
        import os as _os

        return _os.environ.get(k, "")


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
GGUF_DIR = ROOT / "models" / "gguf"

GGUF_CATALOG = {
    "default": {
        "file": "qwen3-0.6b-q4.gguf",
        "abs": os.environ.get(
            "GHOST_GGUF_ABS",
            str(
                Path.home()
                / ".cache/huggingface/hub/models--unsloth--Qwen3-0.6B-GGUF/snapshots/50968a4468ef4233ed78cd7c3de230dd1d61a56b/Qwen3-0.6B-Q4_0.gguf"
            ),
        ),
        "n_ctx": 4096,
        "n_gpu": 20,
        "max_tok": 512,  # turbo: ctx reduit, tokens limites
    },
    "complex_refactor": {
        "file": "qwen2.5-coder-7b-q4.gguf",
        "abs": None,
        "n_ctx": 16384,
        "n_gpu": 20,
        "max_tok": 4096,
    },
}

# State ID GHOST_CONTEXT_MAX_V1 — prompt_header obligatoire
# TURBO : prompts courts = temps inference reduit
_DOCSTRING_HEADER = "Docstring Google-style obligatoire sur chaque fonction. "

# FORGE_ENGLISH_CORE_V1 — High-Density system prompt (anglais technique)
_HD = (
    "You are a Python expert. Output ONLY the improved Python code.\n"
    "STRICT RULES:\n"
    "1. Return ONLY the function/class as given — do NOT add, remove or rename functions.\n"
    "2. No talk, no preamble. Start directly with the code.\n"
    "3. Python 3.9+ types (list/dict/tuple, not List/Dict). No quoted type refs.\n"
    "4. Every try MUST have except or finally. NEVER truncate the output."
)

HOT_PERSONAS = {
    "security_patch": _HD + "\nTASK: Fix security issues only. Keep all existing functions.",
    "import_clean": _HD + "\nTASK: Reformat imports one-per-line. Change nothing else.",
    "docstrings": _HD + "\nTASK: Add Google-style docstrings. Do NOT change logic or signatures.",
    "type_hints": _HD + "\nTASK: Add type hints. Do NOT change logic or function names.",
    "default": _HD + "\nTASK: Add type hints and docstrings where missing. Keep ALL existing functions unchanged.",
}

TASK_ROUTING = {
    "unit_tests": "openrouter_free",
    "complex_refactor": "openrouter_free",
    "security_patch": "openrouter_free",
    "import_clean": "openrouter_free",
    "docstrings": "openrouter_free",
    "type_hints": "openrouter_free",
    "default": "openrouter_free",
}

# Fallback si OpenRouter indispo
TASK_ROUTING_LOCAL = {
    "unit_tests": "groq_70b",
    "complex_refactor": "gemini",
    "security_patch": "phi3_npu",
    "import_clean": "gemini",
    "docstrings": "phi3_npu",
    "type_hints": "phi3_npu",
    "default": "phi3_npu",
}

# Context:


def detect_task(instruction: str, code: str = "") -> str:
    """Detect task.

    Args:
        instruction: Description.
        code: Description.

    Returns:
        Detected task type.

    Raises:
        TypeError: If instruction or code are not strings.
    """
    # Input validation
    if not isinstance(instruction, str):
        raise TypeError(f"instruction must be a string, got {type(instruction).__name__}")
    if not isinstance(code, str):
        raise TypeError(f"code must be a string, got {type(code).__name__}")

    keywords: dict[str, list[str]] = {
        "unit_tests": ["def test_", "pytest", "assert ", "unittest"],
        "security_patch": ["securit", "security", "xss", "csrf"],
        "import_clean": ["from __future__"],  # restreint  vite faux positifs
        "docstrings": ["docstring", "documentation"],
        "type_hints": ["type hint", "typing"],
        "complex_refactor": ["refactor", "restructure"],
    }

    # Prioritize explicit instruction
    instruction_lower = instruction.lower()
    for task, kws in keywords.items():
        if any(kw in instruction_lower for kw in kws):
            return task

    # Detection on code only if instruction is empty/whitespace
    if not instruction.strip():
        code_snippet = code[:200].lower()
        for task, kws in keywords.items():
            if any(kw in code_snippet for kw in kws):
                return task

    return "default"


class GhostRouter:
    """Hot-plug via system prompt. 1 modele persistant. Lock exclusif."""

    def __init__(self) -> None:
        """Init."""
        self._llm = None
        self._llm_path = ""
        self._lock = threading.Lock()
        self._call_count = 0

    def _find_gguf(self, task="default") -> object:
        """Find gguf.

        Args:
            task: Description.
        """
        cat = GGUF_CATALOG.get(task, GGUF_CATALOG["default"])
        p = GGUF_DIR / cat["file"]
        if p.exists():
            return str(p)
        fb = cat.get("abs")
        if fb and Path(fb).exists():
            return fb
        if task != "default":
            return self._find_gguf("default")
        return None

    def _load_if_needed(self, model_path, task="default") -> None:
        """Load if needed.

        Args:
            model_path: Description.
            task: Description.
        """
        if self._llm is not None and self._llm_path == model_path:
            return
        self._purge_internal()
        cat = GGUF_CATALOG.get(task, GGUF_CATALOG["default"])
        t0 = time.time()
        print(f"[GHOST] Load {Path(model_path).name}...")
        # TOTAL_SILICON_V1 : config thermique dynamique
        try:
            from nokido_agent.app.forge_hw_allocator import apply_silicon_config

            _sc = apply_silicon_config()
            _n_ctx = max(min(cat["n_ctx"], _sc["n_ctx"]), 8192)
            _n_gpu = _sc["n_gpu_layers"]
            _n_threads = _sc["n_threads"]
            print(f"[SILICON] {_sc['plan']} ctx={_n_ctx} GPU={_n_gpu}L threads={_n_threads} RAM={_sc['ram_used_pct']}%")
        except Exception:
            _n_ctx, _n_gpu, _n_threads = cat["n_ctx"], cat["n_gpu"], 16
        from llama_cpp import Llama

        self._llm = Llama(
            model_path=model_path,
            n_ctx=_n_ctx,
            n_gpu_layers=_n_gpu,
            n_threads=_n_threads,
            verbose=False,
            chat_format="chatml",
            offload_kqv=True,
            flash_attn=True,
        )
        self._llm_path = model_path
        self._call_count = 0
        print(f"[GHOST] Ready {int((time.time() - t0) * 1000)}ms")

    def _purge_internal(self) -> None:
        """Purge internal."""
        if self._llm is not None:
            try:
                del self._llm
            except Exception:
                pass
            self._llm = None
            self._llm_path = ""
            gc.collect()
            print("[GHOST] RAM purgee")

    def purge(self) -> None:
        """Purge."""
        with self._lock:
            self._purge_internal()

    def generate_local(self, prompt, task="default", system="") -> str:
        # /no_think desactive le mode raisonnement Qwen3 (evite <think> infini)
        """Generate local.

        Args:
            prompt: Description.
            task: Description.
            system: Description.
        """
        if not prompt.startswith("/no_think"):
            prompt = "/no_think\n" + prompt
        model_path = self._find_gguf(task)
        if not model_path:
            return "[ERR] Aucun GGUF"
        cat = GGUF_CATALOG.get(task, GGUF_CATALOG["default"])
        sys_msg = system or HOT_PERSONAS.get(task, HOT_PERSONAS["default"])
        t0 = time.time()
        with self._lock:
            try:
                self._load_if_needed(model_path, task)
                self._call_count += 1
                res = self._llm.create_chat_completion(
                    messages=[
                        {"role": "system", "content": sys_msg},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=cat["max_tok"],
                    temperature=0.3,
                    stop=["Human:", "User:"],
                )
                text = res["choices"][0]["message"]["content"].strip()
                print(f"[GHOST] #{self._call_count} {task} {int((time.time() - t0) * 1000)}ms {len(text)}c")
                return text
            except Exception as e:
                print(f"[GHOST] ERR: {e}")
                self._purge_internal()
                return f"[ERR] {e}"

    def generate_npu(self, prompt: str, task: str = "default", system: str = "") -> str:
        """
        Generation via env NPU dedie (ryzen-ai-1.7.0).
        VitisAI EP = vrai NPU XDNA visible dans Gestionnaire des taches.
        Fallback : DirectML iGPU -> llamacpp.
        """
        persona = HOT_PERSONAS.get(task, HOT_PERSONAS["default"])
        sys_msg = system or persona
        # Essai 1 : env NPU dedie (VitisAI XDNA)
        try:
            from nokido_agent.app.forge_npu_env import run_phi3

            result = run_phi3(prompt, system=sys_msg)
            if result and not result.startswith("[ERR]"):
                print(f"[NPU] VitisAI XDNA OK {len(result)}c")
                return result
        except Exception as e:
            print(f"[NPU] env dedie err: {e}")
        # Essai 2 : DirectML iGPU (env actuel)
        try:
            from nokido_agent.app.forge_phi3_npu import generate as phi3_gen, is_available

            if is_available():
                return phi3_gen(prompt, system=sys_msg)
        except Exception as e:
            print(f"[NPU] DirectML err: {e}")
        # Fallback DirectML direct (llamacpp absent dans env ryzen)
        print("[NPU] fallback DirectML direct")
        try:
            from nokido_agent.app.forge_phi3_npu import generate as _phi3_direct

            persona = HOT_PERSONAS.get(task, HOT_PERSONAS["default"])
            result = _phi3_direct(prompt, system=system or persona)
            if result and not result.startswith("[ERR]"):
                return result
        except Exception as _e3:
            print(f"[NPU] DirectML fallback err: {_e3}")
        return ""

    def generate_cloud(self, prompt, provider, system="", task: str = "default") -> str:
        """Generate cloud.

        Args:
            prompt: Description.
            provider: Description.
            system: Description.
        """
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        try:
            from nokido_agent.app.forge_swarm_team import _default_team, LeadOrchestrator

            team = _default_team()
            team.activate(provider)
            orc = LeadOrchestrator()
            loop = asyncio.new_event_loop()
            full = f"[SYSTEM] {system}\n\n{prompt}" if system else prompt
            try:
                from nokido_agent.app.forge_performance_tuner import get_timeout

                _tout = get_timeout(provider)
            except Exception:
                _tout = 30
            res = loop.run_until_complete(asyncio.wait_for(orc.run(full, team), timeout=_tout))
            loop.close()
            turns = res.get("results", [])
            return str(turns[0].get("response", "")) if turns else ""
        except asyncio.TimeoutError:
            return f"[ERR] timeout {provider}"
        except Exception as e:
            err_str = str(e)
            if "403" in err_str or "402" in err_str or "401" in err_str or "shutdown" in err_str:
                # ERROR_TRANSLATION_V1 : signal de bascule local
                print(f"[ROUTER] Signal bascule locale — {err_str[:40]}")
                return self.generate_npu(prompt, task, system)
            if "429" in err_str or "quota" in err_str.lower() or len(str(e)) < 30:
                import time as _t2

                print(f"[ROUTER] {provider} rate limit — retry 3s")
                _t2.sleep(3)
                try:
                    res2 = loop.run_until_complete(asyncio.wait_for(orc.run(full, team), timeout=_tout))
                    turns2 = res2.get("results", [])
                    txt2 = str(turns2[0].get("response", "")) if turns2 else ""
                    if txt2 and len(txt2) > 20:
                        return txt2
                except Exception:
                    pass
                return self.generate_npu(prompt, task, system)
            return f"[ERR] cloud {provider}: {e}"

    def generate(self, prompt, instruction="", code="", system="", step: int = 0, total: int = 0) -> tuple:
        """Generate.

        Args:
            prompt: Description.
            instruction: Description.
            code: Description.
            system: Description.
            step: Description.
            total: Description.
        """
        task = detect_task(instruction or prompt, code)
        provider = TASK_ROUTING.get(task, "llamacpp_local")
        # CONTEXT_STEADINESS_V1 — injecter header STATUS_CHECK
        try:
            from nokido_agent.app.forge_context_steadiness import inject_header, update_state

            prompt = inject_header(prompt, task=task, step=step, total=total)
        except Exception:
            pass
        # OpenRouter free — priorité si clé dispo
        if provider == "openrouter_free":
            try:
                from nokido_agent.app.forge_openrouter import generate_code as _or_gen, _get_key as _or_key

                if _or_key():
                    _or_text = _or_gen(prompt, system=system)
                    if _or_text and not _or_text.startswith("[ERR]"):
                        return _or_text, "openrouter_free", task
                    print(f"[ROUTER] OpenRouter echec: {_or_text[:60]} — fallback local")
                else:
                    print("[ROUTER] OPENROUTER_API_KEY absent — fallback local")
            except Exception as _ore:
                print(f"[ROUTER] OpenRouter exception: {_ore} — fallback local")
            # Fallback local
            provider = TASK_ROUTING_LOCAL.get(task, "phi3_npu")

        # Gemini quota 20/jour free tier -> fallback phi3_npu direct
        if provider == "gemini":
            if not _gs("GEMINI_API_KEY"):
                provider = "phi3_npu"
            # else: tenter Gemini mais fallback sur 429
        if provider == "groq_70b" and not _gs("GROQ_API_KEY"):
            provider = "llamacpp_local"
        if provider == "phi3_npu":
            text = self.generate_npu(prompt, task, system)
        elif provider == "llamacpp_local":
            text = self.generate_local(prompt, task, system)
        else:
            text = self.generate_cloud(prompt, provider, system)
            if not text or text.startswith("[ERR]"):
                print(f"[GHOST] fallback local depuis {provider}")
                text = self.generate_local(prompt, task, system)
                provider = "llamacpp_local"
        # Ancrer le résultat dans le contexte
        try:
            from nokido_agent.app.forge_context_steadiness import update_state

            update_state(last_output=text[:150] if text else "empty")
        except Exception:
            pass
        return text, provider, task


# Charger les cles API depuis Windows Credential Manager
try:
    import win32cred as _wc
    import os as _os_cr

    _CRED_MAP = {
        "GROQ_API_KEY@LaForge": "GROQ_API_KEY",
        "DEEPSEEK_API_KEY@LaForge": "DEEPSEEK_API_KEY",
        "GEMINI_API_KEY@LaForge": "GEMINI_API_KEY",
        "HF_TOKEN@LaForge": "HF_TOKEN",
        "CODEBERG_TOKEN@LaForge": "CODEBERG_TOKEN",
    }
    for _cname, _envk in _CRED_MAP.items():
        if not _os_cr.environ.get(_envk):
            try:
                _c = _wc.CredRead(_cname, _wc.CRED_TYPE_GENERIC)
                _b = _c.get("CredentialBlob", b"")
                _v = _b.decode("utf-16-le", "replace").rstrip("\x00") if _b else ""
                if _v:
                    _os_cr.environ[_envk] = _v
            except Exception:
                pass
except Exception:
    pass

# Init performance au chargement du module
try:
    from nokido_agent.app.forge_performance_tuner import init_performance

    init_performance()
except Exception:
    pass

_router = None
_router_lock = threading.Lock()


def get_router() -> GhostRouter | None:
    """Get router."""
    global _router
    with _router_lock:
        if _router is None:
            _router = GhostRouter()
    return _router


def ghost_generate(prompt, instruction="", code="", system="") -> object:
    """Ghost generate.

    Args:
        prompt: Description.
        instruction: Description.
        code: Description.
        system: Description.
    """
    return get_router().generate(prompt, instruction, code, system)
