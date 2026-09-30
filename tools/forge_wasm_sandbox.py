#!/usr/bin/env python3
"""forge_wasm_sandbox.py — tier d'exécution WASM RÉEL (« tend enfin vers le wasm »).

ÉTAT (mesuré) : `run sandbox=wasm` est aujourd'hui NATIF-labellé (forge_sandbox_exec n'a aucun backend
wasm). MAIS le substrat wasm RÉEL existe déjà (forge_wasm_cervelet) : wasmtime-py (isolation locale) +
Deno wasm `:7401/api/wasm/run` + wasmedge Docker (WSL). Il sert l'embedder cervelet, PAS l'isolation
d'exécution. Ici on l'EXPOSE comme un VRAI tier sandbox — on n'écrit pas un interpréteur, on câble l'existant.

ROADMAP (« tend vers ») :
  - Phase A (NOW)     : exécuter des MODULES .wasm compilés en VRAIE isolation (wasmtime-py local,
                        fallback Deno :7401). Pour des kernels de calcul (pas du Python source).
  - Phase B (roadmap) : Pyodide (CPython-wasm) pour exécuter du CODE PYTHON agent/généré en wasm
                        (isolation dure du code non-fiable de l'essaim) — le vrai but exécution-sandbox.
  - Phase C (roadmap) : wire comme backend `sandbox=wasm` de forge_sandbox_exec + componentize-py pour
                        les kernels 4096D EDGE (encode-4096D portable wasm à l'edge) → rejoint
                        hub_concurrency_plan P3 (vision edge + essaim).

Anti-dup : réutilise forge_wasm_cervelet. Gouverné (passe par le sandbox tier, pas open exec brut).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

DENO_WASM_URL = "http://127.0.0.1:7401/api/wasm/run"


def readiness() -> dict:
    """Substrat wasm disponible ? (le pré-requis du tier réel).

    Mesure 2026-07-28 : la 1re version testait `import wasmtime` (le BINDING PYTHON,
    absent) et rapportait « pas de wasm » alors que le RUNTIME NATIF `wasmtime.exe`
    (45.0.2) et wasmedge/WSL sont bel et bien installes — un capteur qui regarde la
    mauvaise chose et conclut a l'absence. On delegue desormais a forge_wasm_cervelet,
    qui teste le binaire NATIF (voie hub-direct, cache=n = zero ecriture disque) puis
    le pont WSL — le substrat REEL, pas un binding optionnel.
    """
    out = {}
    # 1. Runtime wasm NATIF (wasmtime.exe) + fallback WSL — via le cervelet existant.
    try:
        from nokido_agent.app.forge_wasm_cervelet import health_wasmtime
        hw = health_wasmtime()
        out["wasmtime_native"] = hw.get("version") if hw.get("ok") else hw.get("error", "?")
        out["wasmtime_ok"] = bool(hw.get("ok"))
    except Exception as e:  # noqa: BLE001
        out["wasmtime_native"] = f"cervelet indisponible ({type(e).__name__})"
        out["wasmtime_ok"] = False
    # 2. binding python (optionnel, souvent absent — pas bloquant)
    try:
        import wasmtime  # type: ignore
        out["wasmtime_py"] = getattr(wasmtime, "__version__", True)
    except Exception:
        out["wasmtime_py"] = "absent (optionnel — le natif suffit)"
    # 3. Deno wasm runner :7401
    try:
        r = urllib.request.urlopen(DENO_WASM_URL.replace("/api/wasm/run", "/health"), timeout=3)
        out["deno_7401"] = r.status == 200
    except Exception as e:  # noqa: BLE001
        out["deno_7401"] = f"down ({type(e).__name__})"
    # 4. Pyodide (Python-in-wasm) — Phase B
    try:
        import pyodide  # type: ignore  # noqa: F401
        out["pyodide"] = True
    except Exception:
        out["pyodide"] = "absent (Phase B : à installer pour Python-in-wasm)"
    out["verdict"] = (
        "wasm NATIF OK -> Phase A active (modules .wasm isolés, cache=n = zéro disque)"
        if out.get("wasmtime_ok") or out.get("deno_7401") is True
        else "aucun runtime wasm joignable -> vérifier wasmtime.exe / deno :7401 / WSL"
    )
    return out


def run_wasm_module(wasm_b64: str | None = None, wasm_url: str | None = None,
                    func: str = "run", args: list | None = None) -> dict:
    """Exécute un MODULE .wasm en isolation (Phase A). wasmtime-py local, fallback Deno.
    PAS du Python source (= Phase B Pyodide). Retourne {ok, backend, result|error}."""
    args = args or []
    # backend 1 : wasmtime.exe NATIF (voie hub-direct, cache=n = ZERO ecriture disque
    # de codegen). Le cervelet localise le binaire (present : 45.0.2) et l'invoque ;
    # fallback WSL/wasmedge integre. wasmtime.exe prend un CHEMIN -> on materialise les
    # bytes SOUS LE REPO (sandbox/wasm_cache), JAMAIS dans C:/tmp (exigence owner
    # 2026-07-28). Le module .wasm est un ASSET, pas un temp jetable : on le garde en
    # cache par hash, donc une seule ecriture bornee, reutilisee ensuite.
    try:
        from nokido_agent.app.forge_wasm_cervelet import run_wasm  # natif + fallback WSL
        import base64, hashlib

        if wasm_b64:
            wbytes = base64.b64decode(wasm_b64)
        elif wasm_url:
            wbytes = urllib.request.urlopen(wasm_url, timeout=10).read()
        else:
            return {"ok": False, "error": "wasm_b64 ou wasm_url requis"}
        cache = ROOT / "sandbox" / "wasm_cache"
        cache.mkdir(parents=True, exist_ok=True)
        wpath = cache / (hashlib.sha256(wbytes).hexdigest()[:16] + ".wasm")
        if not wpath.exists():
            wpath.write_bytes(wbytes)
        res = run_wasm(str(wpath), func=func, args=args)
        res.setdefault("backend", "wasmtime-native")
        return res
    except Exception as e:  # noqa: BLE001
        _native_err = str(e)[:150]
    # backend 2 : Deno wasm runner :7401 (si l'endpoint est expose)
    try:
        from nokido_agent.app.forge_wasm_cervelet import run_wasm_deno  # type: ignore
        res = run_wasm_deno(wasm_b64=wasm_b64, wasm_url=wasm_url, func=func, args=args)
        if res.get("ok"):
            return {"ok": True, "backend": "deno:7401", "result": res}
        return {"ok": False, "backend": "deno:7401", "error": res.get("error"),
                "native_error": _native_err}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "backend": "none",
                "error": f"aucun runtime wasm: natif={_native_err} deno={str(e)[:80]}"}


def run_python(code: str, timeout: int = 30) -> dict:
    """Execute du CODE PYTHON en WASM via le serveur Pyodide autonome (Phase B).

    C'est le but roadmap : le code de diagnostic genere par le CLI tourne EN MEMOIRE
    dans la sandbox WASM Pyodide, SANS ecrire de fichier sur le disque hote. Prouve
    faisable le 2026-07-28 (2+3=5, dist locale components/pyodide_dist).

    Le serveur (proxy_deno/organs/pyexec_server.ts, port 7402) est lance par le
    superviseur (il a le deno du profil owner). Retourne {ok, stdout, result|error}.
    Si le serveur est absent -> {ok:False, error:...} (fail clair, on n'invente rien).
    """
    port = os.environ.get("LAFORGE_PYEXEC_PORT", "7402")
    body = json.dumps({"code": code}).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:%s/pyexec" % port, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "serveur pyexec :%s injoignable (%s) — lance "
                "NokidoPyExec" % (port, type(e).__name__)}


def pyexec_ready() -> dict:
    """Le serveur Pyodide repond-il ?"""
    port = os.environ.get("LAFORGE_PYEXEC_PORT", "7402")
    try:
        r = urllib.request.urlopen("http://127.0.0.1:%s/health" % port, timeout=3)
        return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "%s" % type(e).__name__}


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "readiness"
    if cmd == "readiness":
        print(json.dumps(readiness(), ensure_ascii=False, indent=1))
    elif cmd == "run":
        # forge_wasm_sandbox.py run <wasm_url> [func]
        url = argv[1] if len(argv) > 1 else None
        fn = argv[2] if len(argv) > 2 else "run"
        print(json.dumps(run_wasm_module(wasm_url=url, func=fn), ensure_ascii=False, indent=1))
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
