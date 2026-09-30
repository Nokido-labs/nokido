"""Reunir les deux moities du SDK Ryzen AI dans le MEME environnement.

Cause racine mesuree le 24-07 : le SDK est scinde entre deux env conda et aucun
n'est complet.
  - `ryzen-ai-final` (= 1.7.0) porte onnxruntime-vitisai 1.23.2 -> le PROVIDER,
    mais PAS `flexmlrt` / `flexml_lite`.
  - `ryzen-ai-1.7.1` porte flexml/flexmlrt/atom/waic, mais son onnxruntime 1.25.1
    n'expose que Azure/CPU -> AUCUN provider NPU.

`vaimlconf` est fourni par **flexmlrt**. Absent de l'env qui execute, la variable
`${vaimlconf.install_dir}` sort NON SUBSTITUEE dans les chemins que construit le
compilateur, qui echoue en « Acces refuse », leve une exception fatale, saute le
sous-graphe et bascule tout sur CPU — en affichant quand meme VitisAIExecutionProvider.
Quatorze mesures ont conclu « repli CPU » sur ce seul manque.

On installe donc les wheels 1.7.0 (ceux qui APPARIENT le provider deja present)
dans `ryzen-ai-final`. `--no-deps` : on complete, on ne resout pas un graphe de
dependances qui pourrait deplacer onnxruntime et casser le provider.

Lance par `run action=trusted_script` : site-packages de l'env owner est refuse
au compte du bac a sable.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SDK = Path(r"C:\Program Files\RyzenAI\1.7.0")
PY = Path(r"%USERPROFILE%\miniforge3\envs\ryzen-ai-final\python.exe")
WHEELS = ["flexmlrt-1.7.0-py312-none-win_amd64.whl",
          "flexml_lite-1.7.0-py312-none-win_amd64.whl",
          "ryzenai_onnx_utils-1.7.0-py3-none-any.whl",
          "ryzen_ai_lt-1.7.0-py3-none-any.whl"]


def main() -> int:
    if not PY.exists():
        print(f"interpreteur introuvable : {PY}")
        return 2
    manquants = [w for w in WHEELS if not (SDK / w).exists()]
    if manquants:
        print(f"wheel(s) absent(s) du SDK : {manquants}")
        return 3

    env = os.environ.copy()
    # Le compte de service n'a pas de profil : sans ces variables pip ecrit dans
    # C:\Users\Default et echoue (mesure 24-07).
    env.update({"USERPROFILE": r"%USERPROFILE%", "HOME": r"%USERPROFILE%",
                "APPDATA": r"%USERPROFILE%\AppData\Roaming",
                "LOCALAPPDATA": r"%USERPROFILE%\AppData\Local",
                "PYTHONNOUSERSITE": "1", "TMPDIR": r"C:\tmp",
                "PYTHONIOENCODING": "utf-8"})

    cmd = [str(PY), "-m", "pip", "install", "--no-deps", "--no-index",
           "--no-cache-dir"] + [str(SDK / w) for w in WHEELS]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                       env=env, timeout=900)
    sortie = (r.stdout or "") + (r.stderr or "")
    for l in sortie.splitlines():
        if any(k in l.lower() for k in ("success", "error", "installing", "collected")):
            print(f"  {l.strip()[:160]}")
    if r.returncode != 0:
        print(f"\nPIP KO (rc={r.returncode})")
        return 4

    # Verifier ce qui compte VRAIMENT : le provider survit, et vaimlconf est la.
    sonde = ("import onnxruntime as o, importlib.util as u; "
             "print('providers:', o.get_available_providers()); "
             "print('flexmlrt:', u.find_spec('flexmlrt') is not None); "
             "print('flexml:', u.find_spec('flexml') is not None)")
    v = subprocess.run([str(PY), "-c", sonde], capture_output=True, text=True,
                       errors="replace", env=env, timeout=300)
    print("\nAPRES INSTALLATION")
    print((v.stdout or v.stderr or "").strip()[:500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
