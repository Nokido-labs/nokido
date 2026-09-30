#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_llamaedge_bringup.py — monte le serveur LlamaEdge WASM (/v1 OpenAI-compat).

CONTEXTE OWNER REQUIS : wasmedge tourne dans WSL Debian (profil user). Le hub
sandbox (sans SeTcbPrivilege) ne peut PAS l'atteindre -> lancer ce script en
session owner :  !  ~/miniforge3/python.exe tools/forge_llamaedge_bringup.py

Telecharge llama-api-server.wasm + un petit GGUF instruct, genere le script de
lancement WSL, tente le start detache sur :8088, sonde /v1/models. Pose ensuite
LAFORGE_LLAMAEDGE_BASE pour que le provider LlamaEdgeOpenAI rejoigne la cascade.
"""
import json
import os
import subprocess
import time
import urllib.request

OUT = r"C:\nokido\llamaedge"      # dir SANS espace -> WSL /mnt/c/nokido/llamaedge propre
WPATH = "/mnt/c/nokido/llamaedge"
WASM_URL = "https://github.com/LlamaEdge/LlamaEdge/releases/latest/download/llama-api-server.wasm"
MODEL_URL = "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_NAME = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
PORT = 8088
report = {"out_dir": OUT, "port": PORT}


def _dl(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 1024:
        return f"exists ({os.path.getsize(path) // 1024 // 1024}MB)"
    urllib.request.urlretrieve(url, path)
    return f"downloaded ({os.path.getsize(path) // 1024 // 1024}MB)"


def _wsl(cmd, timeout=60):
    try:
        r = subprocess.run(["wsl", "--", "bash", "-lc", cmd], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout)
        return ((r.stdout or "") + (r.stderr or "")).strip()[:400]
    except Exception as e:  # noqa: BLE001
        return f"ERR {e}"


os.makedirs(OUT, exist_ok=True)
wasm_file = os.path.join(OUT, "llama-api-server.wasm")
model_file = os.path.join(OUT, MODEL_NAME)
for key, url, path in (("wasm", WASM_URL, wasm_file), ("model", MODEL_URL, model_file)):
    try:
        report[key] = _dl(url, path)
    except Exception as e:  # noqa: BLE001
        report[key] = f"ERR {e}"

report["wsl_wasmedge"] = _wsl("wasmedge --version 2>&1 | head -1", timeout=30)

launch = (
    "#!/bin/bash\n"
    f"cd {WPATH}\n"
    "wasmedge --dir .:. \\\n"
    f"  --nn-preload default:GGML:AUTO:{MODEL_NAME} \\\n"
    "  llama-api-server.wasm \\\n"
    "  --model-name laforge-llamaedge \\\n"
    "  --prompt-template chatml \\\n"
    "  --ctx-size 4096 \\\n"
    f"  --socket-addr 0.0.0.0:{PORT}\n"
)
sh_file = os.path.join(OUT, "start_llamaedge.sh")
with open(sh_file, "w", newline="\n", encoding="utf-8") as f:
    f.write(launch)
report["launch_script"] = sh_file

if "ERR" not in report.get("wsl_wasmedge", "ERR"):
    _wsl(f"nohup bash {WPATH}/start_llamaedge.sh > {WPATH}/server.log 2>&1 &", timeout=20)
    time.sleep(20)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=5) as r:
            data = json.loads(r.read())
        report["server"] = f"UP — models={[m.get('id') for m in data.get('data', [])]}"
    except Exception as e:  # noqa: BLE001
        report["server"] = f"pas encore up ({e}) — voir {WPATH}/server.log"
else:
    report["server"] = "wasmedge introuvable dans WSL — installer wasmedge 0.14.1 + wasi_nn (Debian)"

report["next"] = f'setx LAFORGE_LLAMAEDGE_BASE http://127.0.0.1:{PORT}  (+ reload hub -> provider llamaedge actif)'
report["manual_start"] = f"wsl -- bash {WPATH}/start_llamaedge.sh"
print(json.dumps(report, ensure_ascii=False, indent=2))
