"""
forge_bfcl_runner.py — Berkeley Function Call Leaderboard v4 runner pour Nokido.

Évalue la capacité des LLMs à choisir le bon outil avec les bons arguments.

Dataset: gorilla/berkeley-function-call-leaderboard (v4 JSONL)
Catégories: simple, multiple, parallel

Usage:
    python tools/forge_bfcl_runner.py --provider mistral [--max 200] [--category simple]
    python tools/forge_bfcl_runner.py --provider mistral --category multiple --max 100
    python tools/forge_bfcl_runner.py --provider mistral --category parallel --max 50
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
BFCL_DIR = ROOT / "RAG" / "bfcl"
BFCL_DIR.mkdir(exist_ok=True)

_GH_BASE = "https://raw.githubusercontent.com/ShishirPatil/gorilla/main/berkeley-function-call-leaderboard/bfcl_eval/data"

_CATEGORY_URLS = {
    "simple": (
        f"{_GH_BASE}/BFCL_v4_simple_python.json",
        f"{_GH_BASE}/possible_answer/BFCL_v4_simple_python.json",
    ),
    "multiple": (
        f"{_GH_BASE}/BFCL_v4_multiple.json",
        f"{_GH_BASE}/possible_answer/BFCL_v4_multiple.json",
    ),
    "parallel": (
        f"{_GH_BASE}/BFCL_v4_parallel.json",
        f"{_GH_BASE}/possible_answer/BFCL_v4_parallel.json",
    ),
    "parallel_multiple": (
        f"{_GH_BASE}/BFCL_v4_parallel_multiple.json",
        f"{_GH_BASE}/possible_answer/BFCL_v4_parallel_multiple.json",
    ),
}


# ── Dataset download ──────────────────────────────────────────────────────────


def _fetch(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read()
    except Exception:
        return None


def _parse_jsonl(raw: bytes) -> list:
    """Parse JSONL (one JSON object per line) or fallback to JSON array."""
    text = raw.decode("utf-8")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # JSONL
    if lines and lines[0].startswith("{"):
        return [json.loads(l) for l in lines]
    # JSON array fallback
    data = json.loads(text)
    return data if isinstance(data, list) else []


def ensure_dataset(dataset_path: Path | None = None, category: str = "simple") -> tuple[list, dict]:
    """Return (questions, answers_by_id). Download/cache per category."""
    if dataset_path and Path(dataset_path).exists():
        qs = _parse_jsonl(Path(dataset_path).read_bytes())
        return qs, {}

    cached_q = BFCL_DIR / f"{category}_questions.jsonl"
    cached_a = BFCL_DIR / f"{category}_answers.jsonl"

    if cached_q.exists():
        print(f"[bfcl] Using cached {category}: {cached_q}")
        qs = _parse_jsonl(cached_q.read_bytes())
        ans_by_id = {}
        if cached_a.exists():
            for a in _parse_jsonl(cached_a.read_bytes()):
                ans_by_id[a["id"]] = a
        return qs, ans_by_id

    if category not in _CATEGORY_URLS:
        print(f"[bfcl] Unknown category '{category}'. Valid: {list(_CATEGORY_URLS)}")
        sys.exit(1)

    url_q, url_a = _CATEGORY_URLS[category]
    print(f"[bfcl] Downloading {category}...")
    raw_q = _fetch(url_q)
    if not raw_q:
        print(f"[bfcl] ERROR: could not download {url_q}")
        sys.exit(1)

    qs = _parse_jsonl(raw_q)
    print(f"[bfcl] Downloaded {category}: {len(qs)} questions")
    cached_q.write_bytes(raw_q)

    ans_by_id = {}
    raw_a = _fetch(url_a)
    if raw_a:
        try:
            for a in _parse_jsonl(raw_a):
                ans_by_id[a["id"]] = a
            cached_a.write_bytes(raw_a)
        except Exception:
            pass

    return qs, ans_by_id


# ── Format prompt ─────────────────────────────────────────────────────────────


def _build_prompt(entry: dict, category: str = "simple") -> str:
    """Build LLM prompt from BFCL entry."""
    question = entry.get("question", [{}])
    functions = entry.get("function", entry.get("functions", []))

    if isinstance(question, list):
        # v4: question = [[{role, content}]] (list of turns, each turn is a list)
        user_msg = ""
        for turn in question:
            if isinstance(turn, list):
                for m in turn:
                    if isinstance(m, dict) and m.get("role") == "user":
                        user_msg += m.get("content", "") + " "
            elif isinstance(turn, dict) and turn.get("role") == "user":
                user_msg += turn.get("content", "") + " "
        user_msg = user_msg.strip()
    else:
        user_msg = str(question)

    if not functions:
        user_msg = entry.get("instruction", user_msg)
        fn_raw = entry.get("function", "")
        functions = [fn_raw] if fn_raw else []

    fn_text = json.dumps(functions, ensure_ascii=False, indent=2)

    # Hints de format (BFCL = function-calling Python ; le GT exige la syntaxe Python).
    # Cf. simple_python_13 GT function=["x**2",...] : '^' est rejeté. Mistral échouait aussi ces cas.
    syntax_hint = (
        "RULES for argument VALUES:\n"
        "- Math/function expressions: use ** for power (NEVER ^), e.g. x**2 not x^2. "
        "Keep coefficients ATTACHED: 3x**2 (not 3*x**2).\n"
        "- Echo strings EXACTLY as the user phrased them (no abbreviation/expansion, "
        "e.g. 'human hemoglobin A1c' not 'human HbA1c').\n"
        "- Numbers as numbers (10 not '10'). Include every REQUIRED argument.\n"
    )

    if category == "parallel":
        return (
            "You are a function-calling assistant. The user request may require calling "
            "MULTIPLE functions. Respond with a JSON array of function calls.\n\n"
            f"AVAILABLE FUNCTIONS:\n{fn_text}\n\n"
            f"USER REQUEST: {user_msg}\n\n"
            f"{syntax_hint}"
            "- PARALLEL: if the request concerns N distinct items/entities, emit a SEPARATE "
            "call object PER item. NEVER merge several items into one call's list argument.\n\n"
            "Respond with ONLY a JSON array: "
            '[{"name": "<fn>", "arguments": {...}}, ...]\n'
            "No explanation, no markdown, only the JSON array."
        )
    return (
        "You are a function-calling assistant. Pick the correct function and arguments.\n\n"
        f"AVAILABLE FUNCTIONS:\n{fn_text}\n\n"
        f"USER REQUEST: {user_msg}\n\n"
        f"{syntax_hint}\n"
        "Respond with ONLY valid JSON: "
        '{"name": "<function_name>", "arguments": {<arg_key>: <arg_value>, ...}}\n'
        "No explanation, no markdown, only the JSON object."
    )


# ── LLM backends (direct, sans passer par le daemon) ─────────────────────────


def _read_env(key: str, default: str = "") -> str:
    # VAULT D'ABORD (politique owner 2026-08-19) — un runner qui ignore le
    # coffre rend un faux 0 % silencieux (mesure 21/08, runner HumanEval).
    try:
        import sys as _sys
        _app = str(ROOT / "app")
        if _app not in _sys.path:
            _sys.path.insert(0, _app)
        from nokido_agent.app.forge_secrets import get_secret as _gs
        v = _gs(key)
        if v:
            return v
    except Exception:  # muet-ok : fallback env/Nokido.env ci-dessous
        pass
    val = __import__("os").environ.get(key, "")
    if val:
        return val
    env_file = ROOT / "Nokido.env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip()
    return default


def _http_post(url: str, body: dict, headers: dict | None = None, timeout: int = 30) -> dict:
    from nokido_agent.tools.forge_bench_http import http_post  # source unique (cliquet clones 21/08)
    return http_post(url, body, headers=headers, timeout=timeout)


def _retry_post(
    url: str, body: dict, headers: dict, timeout: int = 30, max_retries: int = 4
) -> dict:
    """POST with exponential backoff on 429."""
    import urllib.error

    delay = 2.0
    for attempt in range(max_retries):
        try:
            return _http_post(url, body, headers, timeout)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise


_ROUTER_SLOTS = ["openrouter_gpt_oss", "hf_llama"]  # gpt-oss-120b fort ; hf fallback (clés vault)


def _router_call(prompt: str, max_tokens: int = 512) -> str:
    """Génère via forge_llm_router._call_slot sur slots cloud forts (clé vault auto).
    BFCL = schémas publics bénins → pas de firewall. Retry backoff sur 429."""
    import sys as _sys
    import time as _t
    from pathlib import Path as _P

    _app = str(_P(__file__).resolve().parent.parent / "app")
    if _app not in _sys.path:
        _sys.path.insert(0, _app)
    from nokido_agent.app.forge_llm_router import get_router

    r = get_router()
    last = "no slot"
    for name in _ROUTER_SLOTS:
        slot = r._slots.get(name)
        if not slot:
            continue
        for attempt in range(3):
            res = r._call_slot(slot, prompt[:12000], "", max_tokens, 0.0, 60, "tool_call")
            if res.get("ok") and res.get("text"):
                return res["text"].strip()
            last = f"{name}: {res.get('error')}"
            e = (res.get("error") or "").lower()
            if ("ratelimit" in e or "429" in e) and attempt < 2:
                _t.sleep(2.0 * (attempt + 1))
                continue
            break
    return f"[ERR] router cloud KO ({last})"


def call_llm(prompt: str, provider: str = "groq") -> str:
    """Call LLM directly (no daemon) for structured output tasks."""
    if provider == "router":
        return _router_call(prompt)

    if provider == "groq":
        key = _read_env("GROQ_API_KEY")
        if not key:
            return "[ERR] GROQ_API_KEY absent"
        d = _http_post(
            "https://api.groq.com/openai/v1/chat/completions",
            {
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt[:6000]}],
                # 512 : un array parallel de N appels deborde 256
                "max_tokens": 512,
                "temperature": 0.0,
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        return d["choices"][0]["message"]["content"].strip()

    if provider == "mistral":
        key = _read_env("MISTRAL_API_KEY")
        if not key:
            return "[ERR] MISTRAL_API_KEY absent"
        d = _retry_post(
            "https://api.mistral.ai/v1/chat/completions",
            {
                "model": "mistral-small-latest",
                "messages": [{"role": "user", "content": prompt[:4000]}],
                "max_tokens": 512,
                "temperature": 0.0,
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        return d["choices"][0]["message"]["content"].strip()

    if provider == "ollama":
        model = _read_env("OLLAMA_MODEL", "qwen2.5-coder:7b")
        d = _http_post(
            "http://127.0.0.1:11434/api/generate",
            {"model": model, "prompt": prompt[:6000], "stream": False},
        )
        return d.get("response", "").strip()

    if provider == "cerebras":
        key = _read_env("CEREBRAS_API_KEY")
        if not key:
            return "[ERR] CEREBRAS_API_KEY absent"
        d = _http_post(
            "https://api.cerebras.ai/v1/chat/completions",
            {
                "model": "llama3.1-70b",
                "messages": [{"role": "user", "content": prompt[:4000]}],
                "max_tokens": 512,
                "temperature": 0.0,
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        return d["choices"][0]["message"]["content"].strip()

    if provider == "nvidia":
        # NVIDIA NIM (cle vault, free tier). kimi-k3 = famille moonshot, la
        # cascade varie la FAMILLE. Latence mesuree ~76 s -> escalade seulement,
        # timeout 180.
        key = _read_env("NVIDIA_API_KEY")
        if not key:
            return "[ERR] NVIDIA_API_KEY absent"
        d = _retry_post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            {
                "model": "moonshotai/kimi-k3",
                "messages": [{"role": "user", "content": prompt[:6000]}],
                "max_tokens": 1024,
                "temperature": 0.0,
            },
            headers={"Authorization": f"Bearer {key}"},
            timeout=180,
        )
        return d["choices"][0]["message"]["content"].strip()

    return f"[ERR] Unknown provider: {provider}"


# ── Scoring ───────────────────────────────────────────────────────────────────


def _parse_call(text: str) -> list | dict | None:
    """Extract JSON function call(s) from LLM response. Returns list for parallel, dict for single."""
    text = text.strip()
    # Strip markdown fence
    if "```" in text:
        for p in text.split("```"):
            p = p.lstrip("json").strip()
            if p.startswith(("{", "[")):
                text = p
                break
    # Try whole string first (catches clean array or object)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, (list, dict)):
            return parsed
    except Exception:
        pass
    # Find JSON array
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    # Find JSON object
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def _spec_eq(pred, spec) -> bool:
    """
    Compare pred to a CONCRETE spec value (not an alternatives container).
    Handles nested dicts where each value IS an alternatives list.
    For all other types: direct equality with numeric tolerance.
    """
    if isinstance(spec, dict) and isinstance(pred, dict):
        for k, v_spec in spec.items():
            if k not in pred:
                if isinstance(v_spec, list) and "" in v_spec:
                    continue  # optional
                return False
            if not _value_in_accepted(pred[k], v_spec):
                return False
        return True
    if pred == spec:
        return True
    try:
        if float(pred) == float(spec):
            return True
    except (ValueError, TypeError):
        pass
    return False


def _value_in_accepted(val, accepted: list) -> bool:
    """
    Check val is in the BFCL accepted-values list.
    accepted = [val1, val2, ...] where "" means optional.
    _spec_eq handles nested dicts; direct equality handles lists/primitives.
    """
    non_empty = [a for a in accepted if a != ""]
    if not non_empty:
        return True  # fully optional
    return any(_spec_eq(val, acc) for acc in non_empty)


def _score_call(predicted: dict | None, ground_truth, strict: bool = True) -> tuple[bool, str]:
    """
    Strict (default) or loose AST match. Returns (passed, fail_reason).

    Strict rules (3 non-négociables):
      1. Exact function name — case-sensitive, no substring
      2. Each arg value must be in accepted_values (type-tolerant numeric)
      3. No hallucinated args — pred_keys must be subset of gt_keys
    """
    if predicted is None:
        return False, "no_parse"

    if isinstance(ground_truth, list):
        reasons = []
        for gt in ground_truth:
            ok, r = _score_call(predicted, gt, strict)
            if ok:
                return True, "ok"
            reasons.append(r)
        return False, "|".join(dict.fromkeys(reasons))

    if isinstance(ground_truth, dict):
        # v4: {func_name: {arg: [accepted_values]}}
        if "name" not in ground_truth and "function_name" not in ground_truth:
            for func_name, args_spec in ground_truth.items():
                pred_name = predicted.get("name", "")
                args_spec = args_spec or {}

                # Rule 1 — exact name
                if strict:
                    if pred_name != func_name:
                        return False, f"name:{pred_name!r}!={func_name!r}"
                else:
                    if pred_name.lower() not in (func_name.lower(),):
                        if func_name.lower() not in pred_name.lower():
                            return False, f"name_loose:{pred_name}"

                pred_args = predicted.get("arguments", predicted.get("parameters", {}))
                gt_keys = set(args_spec)
                pred_keys = set(pred_args)

                if strict:
                    # Rule 3 — no hallucinated args
                    extra = pred_keys - gt_keys
                    if extra:
                        return False, f"hallucinated:{extra}"

                    # Rule 2 — value validation
                    for key, accepted in args_spec.items():
                        is_optional = "" in accepted
                        if key not in pred_args:
                            if not is_optional:
                                return False, f"missing:{key}"
                        else:
                            if not _value_in_accepted(pred_args[key], accepted):
                                return False, f"wrong_val:{key}={pred_args[key]!r}"
                else:
                    required = {k for k, v in args_spec.items() if "" not in v}
                    if not all(k in pred_args for k in required):
                        return False, "missing_required"

                return True, "ok"
            return False, "no_candidate"

        # v3 dict: {name, arguments}
        gt_name = ground_truth.get("name") or ground_truth.get("function_name", "")
        gt_keys = set(ground_truth.get("arguments", ground_truth.get("parameters", {})).keys())
        pred_name = predicted.get("name", "")
        pred_args = predicted.get("arguments", predicted.get("parameters", {}))
        if strict:
            if pred_name != gt_name:
                return False, f"name:{pred_name!r}!={gt_name!r}"
            extra = set(pred_args) - gt_keys
            if extra:
                return False, f"hallucinated:{extra}"
            return (True, "ok") if all(k in pred_args for k in gt_keys) else (False, "missing")
        else:
            ok = (
                pred_name.lower() == gt_name.lower()
                or gt_name.lower() in pred_name.lower()
                or pred_name.lower() in gt_name.lower()
            )
            return (ok and all(k in pred_args for k in gt_keys), "loose")

    if isinstance(ground_truth, str):
        m = re.match(r"(\w+)\((.*)\)", ground_truth.strip(), re.DOTALL)
        if m:
            gt_name = m.group(1)
            gt_keys = set(re.findall(r"(\w+)\s*=", m.group(2)))
            pred_name = predicted.get("name", "")
            pred_args = predicted.get("arguments", predicted.get("parameters", {}))
            if strict:
                if pred_name != gt_name:
                    return False, f"name:{pred_name!r}!={gt_name!r}"
                extra = set(pred_args) - gt_keys
                if extra:
                    return False, f"hallucinated:{extra}"
                return (True, "ok") if all(k in pred_args for k in gt_keys) else (False, "missing")
        try:
            return _score_call(predicted, json.loads(ground_truth), strict)
        except Exception:
            return False, "parse_gt_failed"

    return False, "unknown_gt"


def _score_parallel(
    predicted: list | dict | None, ground_truth: list, strict: bool = True
) -> tuple[bool, str]:
    """Parallel: ALL required calls must appear in predicted (order-independent)."""
    if predicted is None:
        return False, "no_parse"
    preds = predicted if isinstance(predicted, list) else [predicted]
    for required in ground_truth:
        if not any(_score_call(p, [required], strict)[0] for p in preds):
            _, r = _score_call(preds[0] if preds else None, [required], strict)
            return (
                False,
                f"missing_call:{list(required.keys())[0] if isinstance(required, dict) else required}:{r}",
            )
    return True, "ok"


def _get_ground_truth(entry: dict, answers_by_id: dict) -> list | dict | str | None:
    """Get ground truth from answers dict or entry itself."""
    entry_id = entry.get("id", "")
    if entry_id and entry_id in answers_by_id:
        a = answers_by_id[entry_id]
        return a.get("ground_truth") or a.get("answer") or a.get("output")
    return (
        entry.get("ground_truth")
        or entry.get("answer")
        or entry.get("expected_output")
        or entry.get("output")
    )


# ── Oracle de schéma : validation DÉTERMINISTE (jamais le GT) ───────────────────


def _available_functions(entry: dict) -> list:
    fns = entry.get("function", entry.get("functions", []))
    if isinstance(fns, dict):
        fns = [fns]
    return fns if isinstance(fns, list) else []


def _schema_validate(predicted, entry: dict) -> tuple[bool, str]:
    """Oracle schéma : parse OK + nom de fonction valide + args REQUIS présents + aucun arg
    halluciné. NE JUGE JAMAIS la valeur (wrong_val = pas de signal sans GT). Retourne (ok, feedback)."""
    if predicted is None:
        return False, "Your output was not parseable JSON. Output ONLY the JSON call, nothing else."
    by_name: dict[str, tuple] = {}
    for s in _available_functions(entry):
        if isinstance(s, dict) and s.get("name"):
            params = s.get("parameters", {}) or {}
            by_name[s["name"]] = (
                set((params.get("properties") or {}).keys()),
                list(params.get("required") or []),
            )
    if not by_name:
        return True, ""  # pas de schéma exploitable → on ne bloque pas
    calls = predicted if isinstance(predicted, list) else [predicted]
    for c in calls:
        if not isinstance(c, dict) or "name" not in c:
            return False, 'Each call must be {"name": "<fn>", "arguments": {...}}.'
        name = c.get("name", "")
        args = c.get("arguments", {}) or {}
        if name not in by_name:
            return False, f"Function '{name}' is NOT available. Use EXACTLY one of: {list(by_name)}."
        allowed, required = by_name[name]
        missing = [r for r in required if r not in args]
        if missing:
            return False, f"Missing REQUIRED argument(s) for '{name}': {missing}. Add them."
        extra = [k for k in args if allowed and k not in allowed]
        if extra:
            return False, f"Argument(s) {extra} are NOT in the schema of '{name}'. Remove them."
    return True, ""


# ── Runner ────────────────────────────────────────────────────────────────────


def run(
    provider: str = "groq",
    max_entries: int = 50,
    dataset_path: Path | None = None,
    category: str = "simple",
    strict: bool = True,
    repair: int = 0,
    escalate: str = "",
    tag: str = "",
) -> dict:
    questions, answers_by_id = ensure_dataset(dataset_path, category)
    subset = questions[:max_entries]
    mode = "STRICT" if strict else "LOOSE"
    print(f"[bfcl] {len(subset)} entries | provider={provider} | category={category} | {mode}")

    results = []
    fail_reasons: dict[str, int] = {}
    t0 = time.time()
    errors = 0

    # Barre de progression live (dashboard /api/vital/jobs_progress) : best-effort.
    _emit = None
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_job_progress import emit as _emit  # noqa: PLC0415
    except Exception:  # muet-ok : enrichissement, jamais bloquant
        pass
    _jid = __import__("os").environ.get("LAFORGE_JOB_ID") or f"bfcl_{provider}_{category}"

    for i, entry in enumerate(subset):
        if _emit:
            try:
                _emit(_jid, i, len(subset))
            except Exception:  # muet-ok : idem
                pass
        prompt = _build_prompt(entry, category)
        gt = _get_ground_truth(entry, answers_by_id)

        t_call = time.time()
        attempts = 0
        try:
            response = call_llm(prompt, provider)
        except Exception as e:
            response = f"[ERR] {e}"
            errors += 1
        predicted = _parse_call(response)
        # repair-loop validé-par-SCHÉMA (oracle déterministe, 0 GT) : régénère sur violation
        while repair and attempts < repair and not response.startswith("[ERR]"):
            ok_s, fb = _schema_validate(predicted, entry)
            if ok_s:
                break
            attempts += 1
            rp = f"{prompt}\n\n# YOUR PREVIOUS OUTPUT WAS INVALID: {fb}\n# Output ONLY the corrected JSON."
            try:
                response = call_llm(rp, provider)
            except Exception:
                break
            predicted = _parse_call(response)
        # ESCALADE multi-modeles validee-par-SCHEMA (jamais le GT) : si le
        # schema reste viole apres le budget, re-tenter chaque provider de la
        # cascade (CSV). Adoption UNIQUEMENT sur schema valide ; erreurs
        # COLLECTEES (l'escalade muette du 21/08 = fausse conclusion).
        escalated_to = None
        escalade_errs = []
        if repair and escalate and not response.startswith("[ERR]"):
            ok_s, fb = _schema_validate(predicted, entry)
            if not ok_s:
                for esc_prov in [p.strip() for p in escalate.split(",") if p.strip() and p.strip() != provider]:
                    rp = f"{prompt}\n\n# A PREVIOUS OUTPUT WAS INVALID: {fb}\n# Output ONLY the corrected JSON."
                    try:
                        resp2 = call_llm(rp, esc_prov)
                    except Exception as e:
                        escalade_errs.append(f"{esc_prov}: {type(e).__name__} {str(e)[:60]}")
                        continue
                    if resp2.startswith("[ERR]"):
                        escalade_errs.append(f"{esc_prov}: {resp2[:80]}")
                        continue
                    cand = _parse_call(resp2)
                    ok2, fb2 = _schema_validate(cand, entry)
                    attempts += 1
                    if ok2:
                        predicted, escalated_to = cand, esc_prov
                        break
                    escalade_errs.append(f"{esc_prov}: schema {fb2[:60]}")
        elapsed = round(time.time() - t_call, 2)
        reason = ""
        if gt is None:
            passed = None
        elif category == "parallel":
            passed, reason = _score_parallel(
                predicted, gt if isinstance(gt, list) else [gt], strict
            )
        else:
            passed, reason = _score_call(predicted, gt, strict)

        if not passed and reason:
            # Track only the top-level reason code (before first colon)
            key = reason.split(":")[0]
            fail_reasons[key] = fail_reasons.get(key, 0) + 1

        status = "PASS" if passed else ("SKIP" if gt is None else "FAIL")
        detail = f" [{reason}]" if (not passed and reason) else ""
        print(f"  [{i + 1}/{len(subset)}] {status} {elapsed}s{detail} | pred={str(predicted)[:80]}")

        results.append(
            {
                "idx": i,
                "pass": passed,
                "elapsed_s": elapsed,
                "repairs": attempts,
                "predicted": predicted,
                "escalated_to": escalated_to,
                "escalade_errs": escalade_errs or None,
                "gt": str(gt)[:200] if gt else None,
                "response": response[:300],
            }
        )
        time.sleep(0.8)  # rate limit (mistral-small ~1 req/s safe)

    # Frame FINAL : la boucle emet AVANT chaque entree -> jamais total/total
    # (les watchers concluent « fige » sur un run termine — mesure 21/08).
    if _emit:
        try:
            _emit(_jid, len(subset), len(subset))
        except Exception:  # muet-ok
            pass
    elapsed_total = round(time.time() - t0, 1)
    scored = [r for r in results if r["pass"] is not None]
    passed_n = sum(1 for r in scored if r["pass"])
    pass_rate = round(passed_n / len(scored) * 100, 1) if scored else 0.0

    repaired_fixed = sum(1 for r in scored if r["pass"] and r.get("repairs", 0) > 0)
    summary = {
        "provider": provider,
        "category": category,
        "strict": strict,
        "n_total": len(subset),
        "n_scored": len(scored),
        "passed": passed_n,
        "pass_rate": pass_rate,
        "repair_budget": repair,
        "repaired_fixed": repaired_fixed,
        "errors": errors,
        "elapsed_s": elapsed_total,
        "fail_reasons": fail_reasons,
        "results": results,
    }

    # Nom UNIQUE par run : un run relance avec le meme nom ECRASE la preuve
    # (mesure 21/08 : le JSON HumanEval du 91,5 % publie a ete reecrit).
    stamp = tag or time.strftime("%Y%m%d-%H%M")
    out = BFCL_DIR / f"bfcl_{provider}_{category}_{len(subset)}{'_r' + str(repair) if repair else ''}_{stamp}.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print(f"\n{'=' * 50}")
    print(
        f"BFCL PASS RATE : {pass_rate}%  ({passed_n}/{len(scored)} scored, {len(subset)} total) [{mode}]"
    )
    if repair:
        print(f"Schema-repair  : +{repaired_fixed} corrigés (budget {repair})")
    print(f"Errors         : {errors}")
    print(f"Avg latency    : {round(sum(r['elapsed_s'] for r in results) / len(results), 2)}s")
    if fail_reasons:
        print(f"Fail breakdown : {dict(sorted(fail_reasons.items(), key=lambda x: -x[1]))}")
    print(f"Saved -> {out}")

    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_self_correction import anchor_solution

        anchor_solution(
            problem=f"BFCL {category} benchmark — {len(scored)} entries scored",
            solution=f"pass_rate={pass_rate}% provider={provider} category={category} errors={errors}",
            example=f"python tools/forge_bfcl_runner.py --provider {provider} --category {category} --max {len(subset)}",
            domain="systeme",
        )
    except Exception:
        pass

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--provider", default="mistral",
        choices=["groq", "mistral", "ollama", "cerebras", "router", "nvidia"],
        help="router = gpt-oss-120b cloud via forge_llm_router (clé vault)",
    )
    parser.add_argument("--max", type=int, default=50)
    parser.add_argument("--category", default="simple", choices=["simple", "multiple", "parallel"])
    parser.add_argument("--dataset", default=None, help="Path to local BFCL JSON file")
    parser.add_argument("--loose", action="store_true", help="Use loose AST match (not strict)")
    parser.add_argument("--repair", type=int, default=0, help="budget repair-loop validé-par-schéma (0=off)")
    parser.add_argument("--escalate", default="",
                        help="providers de secours CSV (ex: nvidia,router) sur violation de schéma après budget — cascade honnête")
    parser.add_argument("--tag", default="",
                        help="suffixe du JSON de sortie (défaut: horodatage — jamais écraser un résultat)")
    args = parser.parse_args()
    run(
        provider=args.provider,
        max_entries=args.max,
        category=args.category,
        repair=args.repair,
        escalate=args.escalate,
        tag=args.tag,
        dataset_path=Path(args.dataset) if args.dataset else None,
        strict=not args.loose,
    )
