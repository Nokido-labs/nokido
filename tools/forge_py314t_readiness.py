"""tools/forge_py314t_readiness.py - Per-workload py314t readiness probe + auto-trigger.

Per Gemini Web 2026-05-29 + Acte 5 partial DEFER strategy.

Single-thread bench dit py314t = ~plat vs py314 GIL. Multi-thread bench (proof
livre 2026-05-29) dit py314t = 6.3x speedup pure-Python @ 8t, 2.5x AMI mix @ 4t.

Donc Acte 5 NE doit PAS flipper canon LAFORGE_PYTHON. Acte 5 = flip PARTIEL :
seulement workloads parallel-CPU vraiment paralleles sur py314t. Reste sur py314.

Cette tool :
1. Probe IMPORT de chaque module candidat sur les 3 envs (py312/py314/py314t)
2. Bench micro multi-thread spot-check sur py314t (run rapide, pas full bench)
3. Si BOTH OK -> flag service comme py314t_ready
4. Compare vs snapshot precedent. Notify CLAUDE via hub si nouveau service ready.

Wired dans schtasks LaForge-WheelProbe (deja mensuel).

Usage:
    LAFORGE_PYTHON tools/forge_py314t_readiness.py
    LAFORGE_PYTHON tools/forge_py314t_readiness.py --print
"""

from __future__ import annotations

import argparse
import ast
import datetime
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = ROOT / "sandbox" / "py314t_readiness_history"

TARGET_ENVS = {
    "py312": r"%USERPROFILE%/miniforge3/python.exe",
    "py314": r"%USERPROFILE%/miniforge3/envs/laforge_py314/python.exe",
    "py314t": r"%USERPROFILE%/miniforge3/envs/laforge_py314t/python.exe",
}

# Per-service candidate map. Each entry = (services.toml service name, module to probe,
# tier hint, parallel_workload True/False).
CANDIDATES = {
    "forge_handoff": {
        "module": "forge_handoff",
        "tier": "parallel_dispatch",
        "parallel": True,
        "rationale": "multi-agent LLM dispatch -- N-thread eval = real free-threading gain",
    },
    "forge_world_model_ami": {
        "module": "forge_world_model",
        "tier": "ami_batch",
        "parallel": True,
        "rationale": "AMI offline trainer JEPA batch -- 2.5x @ 4 threads measured",
    },
    "forge_chain_executor": {
        "module": "forge_chain_executor",
        "tier": "pipeline",
        "parallel": False,
        "rationale": "single-thread pipeline -- py314 GIL preferred (+8.2% bench)",
    },
    "forge_frugal_cascade": {
        "module": "forge_frugal_cascade",
        "tier": "pipeline",
        "parallel": False,
        "rationale": "cascade local->cloud serial -- py314 GIL fine",
    },
    "forge_lats_general": {
        "module": "forge_lats_general",
        "tier": "parallel_search",
        "parallel": True,
        "rationale": "MCTS rollouts parallel candidates -- py314t candidate",
    },
    "forge_tem_factorize": {
        "module": "forge_tem_factorize",
        "tier": "math",
        "parallel": True,
        "rationale": "numpy ops batch -- py314t scales via no-GIL numpy thread-pool",
    },
    "forge_semantic_pressure": {
        "module": "forge_semantic_pressure",
        "tier": "math",
        "parallel": True,
        "rationale": "cluster centroid + pressure compute batch -- py314t candidate",
    },
    "forge_curiosity_driver": {
        "module": "forge_curiosity_driver",
        "tier": "compute",
        "parallel": False,
        "rationale": "single-pass zstd compression heuristic -- py314 fine",
    },
    "forge_bge_m3_shared": {
        "module": "forge_bge_m3_shared",
        "tier": "embed",
        "parallel": True,
        "rationale": "in-process ONNX shared session multi-thread -- requires cp314t onnxruntime",
    },
}


def probe_module_import(python_exe: str, module: str) -> dict:
    """Test import of `module` on a given python.exe. Returns ok/error dict."""
    if not Path(python_exe).exists():
        return {"ok": False, "error": "python.exe not found"}
    code = (
        "import sys, json\n"
        f"sys.path.insert(0, r'{ROOT}/app')\n"
        f"try:\n"
        f"    __import__('{module}')\n"
        f"    print(json.dumps({{'ok': True}}))\n"
        f"except Exception as e:\n"
        f"    print(json.dumps({{'ok': False, 'error': f'{{type(e).__name__}}: {{e}}'[:200]}}))\n"
    )
    try:
        r = subprocess.run(
            [python_exe, "-c", code], capture_output=True, text=True, timeout=30
        , errors="replace")
        if r.returncode != 0:
            return {"ok": False, "error": f"rc={r.returncode} stderr={r.stderr[:200]}"}
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}


def hub_notify(message: str) -> bool:
    """Notify CLAUDE via hub MCP :8766."""
    try:
        import os
        import urllib.request

        token = os.environ.get("FORGE_MCP_TOKEN", "")
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "hub",
                    "arguments": {"action": "notify", "to": "CLAUDE", "message": message},
                },
            }
        ).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8766/mcp",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "X-Agent-Name": "PY314T_READINESS",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


_MODULES_PARALLELES = ("concurrent", "threading", "multiprocessing")

# Bibliotheques de TRAVAIL : celles sans lesquelles le module tourne en repli
# degrade au lieu d'echouer. La liste est une CATEGORIE (choix assume) ; ce qui est
# MESURE, c'est quels modules les importent reellement.
_DEPS_LOURDES = ("onnxruntime", "torch", "faiss", "sentence_transformers",
                 "snntorch", "jax", "lxml")


def parallelisme_mesure(module: str) -> dict:
    """Le module importe-t-il VRAIMENT de quoi tourner sur plusieurs threads ?

    POURQUOI CE CONTROLE (mesure 2026-08-30). `CANDIDATES` est une carte ecrite a
    la main : son champ `parallel` est une INTENTION, que rien ne confrontait au
    code. Resultat, quatre modules etaient affiches `READY+PARALLEL` sans importer
    ni `threading` ni `concurrent` -- `forge_semantic_pressure`, `forge_tem_factorize`,
    `forge_lats_general`, `forge_world_model`. Les basculer sur py314t aurait coute
    +13 % de RAM (18,1 -> 20,4 Mo a vide, mesure du jour) pour un gain NUL : le
    free-threaded leve le GIL, il ne parallelise pas le code a notre place.

    Trois etats, jamais deux : `oui` / `non` / `illisible`. Un module qu'on ne peut
    pas lire n'est pas un module sans threads.
    """
    chemin = ROOT / "app" / (module + ".py")
    if not chemin.exists():
        return {"etat": "illisible", "motif": "source introuvable: app/%s.py" % module}
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as exc:
        return {"etat": "illisible", "motif": "SyntaxError: %s" % exc.msg}
    vus = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.Import):
            for a in n.names:
                vus.add(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.module:
            vus.add(n.module.split(".")[0])
    trouves = sorted(m for m in _MODULES_PARALLELES if m in vus)
    return {"etat": "oui" if trouves else "non", "imports": trouves}


def deps_de_travail(module: str) -> list:
    """Bibliotheques lourdes que ce module importe (mesure AST, pas declaration)."""
    chemin = ROOT / "app" / (module + ".py")
    if not chemin.exists():
        return []
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    vus = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.Import):
            for a in n.names:
                vus.add(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.module:
            vus.add(n.module.split(".")[0])
    return sorted(d for d in _DEPS_LOURDES if d in vus)


def deps_absentes(exe: str, deps: list) -> list:
    """Celles de `deps` que l'interpreteur cible NE PEUT PAS importer.

    POURQUOI (mesure 2026-08-30). `probe_module_import` sonde le module, et un
    module dont les imports lourds sont proteges par try/except s'importe TRES
    BIEN sans eux : `forge_bge_m3_shared` passe la sonde sous py314t alors
    qu'`onnxruntime`, `torch` et `sentence_transformers` y sont absents. Il
    tournerait donc en repli, silencieusement -- le meme faux vert que le SNN,
    ou un repli correct masquait que le mode voulu n'avait jamais tourne.
    Un import qui reussit ne prouve pas qu'une capacite fonctionne.
    """
    if not deps:
        return []
    code = ("import importlib.util as u\n"
            "print(','.join(d for d in %r if u.find_spec(d) is None))" % (deps,))
    try:
        r = subprocess.run([exe, "-c", code], capture_output=True, text=True,
                           errors="replace", timeout=120)
    except Exception:  # noqa: BLE001
        return ["<sonde impossible>"]
    if r.returncode != 0:
        return ["<sonde rc=%d>" % r.returncode]
    return [d for d in r.stdout.strip().split(",") if d]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", help="Print snapshot to stdout")
    ap.add_argument("--notify", action="store_true", help="Force notify CLAUDE")
    args = ap.parse_args()

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    snapshot: dict = {
        "ts": datetime.datetime.now(datetime.UTC).isoformat(),
        "envs": list(TARGET_ENVS.keys()),
        "candidates": {},
    }

    print(f"[py314t_readiness] probing {len(CANDIDATES)} candidates x {len(TARGET_ENVS)} envs")

    for cname, cinfo in CANDIDATES.items():
        module = cinfo["module"]
        per_env = {}
        for env_name, exe in TARGET_ENVS.items():
            per_env[env_name] = probe_module_import(exe, module)
        py314t_ok = per_env.get("py314t", {}).get("ok", False)
        mes = parallelisme_mesure(module)
        besoins = deps_de_travail(module)
        manquantes = deps_absentes(TARGET_ENVS["py314t"], besoins) if py314t_ok else []
        # Trois conditions, pas une : le code doit THREADER, l'env doit importer le
        # module, ET ses dependances de travail doivent y etre. Sinon on bascule un
        # service vers un repli degrade en croyant l'accelerer.
        recommande = (py314t_ok and bool(cinfo["parallel"])
                      and mes["etat"] == "oui" and not manquantes)
        snapshot["candidates"][cname] = {
            "module": module,
            "tier": cinfo["tier"],
            "parallel_workload": cinfo["parallel"],          # ce que la carte DECLARE
            "parallel_mesure": mes,                          # ce que le CODE montre
            "deps_travail": besoins,                         # libs lourdes mesurees
            "deps_absentes_py314t": manquantes,              # ... et celles qui manquent
            "per_env_import": per_env,
            "py314t_ready": py314t_ok,
            "py314t_recommended": recommande,
            "rationale": cinfo["rationale"],
        }
        if recommande:
            status = "READY+PARALLEL"
        elif manquantes and mes["etat"] == "oui" and cinfo["parallel"]:
            status = "DEPS_MANQUANTES"
        elif cinfo["parallel"] and mes["etat"] == "non":
            status = "DECLARE_SANS_THREAD"
        elif mes["etat"] == "illisible":
            status = "PARALLELISME_ILLISIBLE"
        elif py314t_ok:
            status = "ready_serial"
        else:
            status = "blocked"
        suffixe = ""
        if status == "DECLARE_SANS_THREAD":
            suffixe = "  <- declare parallele, AUCUN thread dans le code : gain nul, RAM en plus"
        elif status == "PARALLELISME_ILLISIBLE":
            suffixe = "  <- %s" % mes.get("motif", "")
        elif status == "DEPS_MANQUANTES":
            suffixe = ("  <- threade, mais %s absent(es) de py314t : tournerait en REPLI"
                       % ", ".join(manquantes))
        print(f"  {cname:<32s} {status:<22s} {cinfo['tier']}{suffixe}")

    # Snapshot diff vs latest
    latest = HISTORY_DIR / "latest.json"
    new_ready: list = []
    if latest.exists():
        try:
            prev = json.loads(latest.read_text(encoding="utf-8"))
            prev_ready = {
                k for k, v in prev.get("candidates", {}).items() if v.get("py314t_recommended")
            }
            now_ready = {
                k for k, v in snapshot["candidates"].items() if v.get("py314t_recommended")
            }
            new_ready = sorted(now_ready - prev_ready)
        except Exception:
            pass

    # Archive snapshot
    out = HISTORY_DIR / f"py314t_readiness_{snapshot['ts'][:10]}.json"
    out.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    if args.print:
        print(json.dumps(snapshot, indent=2))

    # Summary
    ready_count = sum(1 for c in snapshot["candidates"].values() if c["py314t_recommended"])
    print(f"\n=== {ready_count}/{len(CANDIDATES)} candidates py314t_recommended (parallel + import OK) ===")

    if new_ready or args.notify:
        msg = (
            f"[PY314T READINESS] {ready_count}/{len(CANDIDATES)} ready+parallel. "
            f"NEW ready: {new_ready if new_ready else 'force-notify'}. "
            f"Snapshot: sandbox/py314t_readiness_history/latest.json"
        )
        print(msg)
        if hub_notify(msg):
            print("notified CLAUDE")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
