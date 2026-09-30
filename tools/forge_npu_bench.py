"""Le NPU XDNA travaille-t-il VRAIMENT ? — banc de mesure, pas de declaration.

`get_providers()[0]` liste les providers ENREGISTRES, jamais celui qui a execute :
un partitionnement AIE qui echoue retombe sur CPU en affichant quand meme
« VitisAIExecutionProvider ». Mesure 24-07 depuis le bac a sable : 194 textes/s
annonces NPU, mais warmup de 2.9 s seulement (une compilation de graphe AIE en
demande ~15) et « Accès refusé » sur le cache vaip — c'etait le CPU.

Ce banc ne croit aucune declaration. Il tranche par TROIS signatures :
  1. WARMUP a froid eleve (compilation du graphe) puis quasi nul a chaud (cache) ;
  2. CHARGE CPU proche de zero pendant la boucle d'inference ;
  3. Debit compare a une session CPU-only du meme modele.

Passe par `run action=trusted_script` : le compte du bac a sable ne peut pas
ecrire le cache de compilation, ce qui suffit a fausser tout le resultat.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# PAS d'expanduser : sous un compte de service, « ~ » resout vers C:\Users\Default
# et l'environnement conda de l'owner devient introuvable (mesure 24-07, exit=2).
# L'env vit dans le profil OWNER ; on le nomme, on ne le devine pas.
_ENVS = Path(os.environ.get("LAFORGE_CONDA_ENVS", r"%USERPROFILE%\miniforge3\envs"))
NPU_PYTHON = Path(os.environ.get("LAFORGE_NPU_PYTHON", str(_ENVS / "ryzen-ai-final" / "python.exe")))
MODELE = ROOT / "app" / "models" / "npu" / "minilm_int8.onnx"
FIRMWARE = r"C:\Windows\System32\AMD\1x4_3.5.0.0-2044_ipu_2.xclbin"

# Execute DANS l'environnement ryzen-ai (le python du hub n'a ni VitisAI ni DML).
SONDE = r'''
import json, os, sys, time
import numpy as np
import onnxruntime as ort
try:
    import psutil
except Exception:
    psutil = None

modele, cache = sys.argv[1], sys.argv[2]
B, L, PASSES = 50, 128, 4
res = {"providers_dispo": ort.get_available_providers()}

def bench(providers, opts, etiquette):
    so = ort.SessionOptions(); so.log_severity_level = 3
    t = time.time()
    try:
        s = ort.InferenceSession(modele, so, providers=providers, provider_options=opts)
    except Exception as e:
        return {"erreur": f"{type(e).__name__}: {str(e)[:200]}"}
    warmup = time.time() - t
    feed = {i.name: np.ones((B, L), dtype=np.int64) for i in s.get_inputs()}
    s.run(None, feed)                       # premiere passe hors mesure
    if psutil:
        psutil.cpu_percent(interval=None)   # amorce le compteur
    t = time.time()
    for _ in range(PASSES):
        s.run(None, feed)
    d = time.time() - t
    cpu = psutil.cpu_percent(interval=None) if psutil else None
    return {"warmup_s": round(warmup, 2), "debit_tps": round(B * PASSES / d, 1),
            "cpu_pct_pendant": cpu, "providers_session": s.get_providers()}

# 1) VitisAI a FROID : le cache est vide, la compilation du graphe doit couter cher
res["npu_froid"] = bench(["VitisAIExecutionProvider", "CPUExecutionProvider"],
                         [{"cacheDir": cache, "cacheKey": "minilm_l12"}, {}], "froid")
# 2) VitisAI a CHAUD : meme cache, la compilation doit avoir disparu
res["npu_chaud"] = bench(["VitisAIExecutionProvider", "CPUExecutionProvider"],
                         [{"cacheDir": cache, "cacheKey": "minilm_l12"}, {}], "chaud")
# 3) Reference CPU pure, meme modele, meme charge
res["cpu_seul"] = bench(["CPUExecutionProvider"], [{}], "cpu")
res["cache_ecrit"] = sorted(os.listdir(cache))[:8] if os.path.isdir(cache) else "CACHE ABSENT"
print("###JSON###" + json.dumps(res))
'''


def _variantes() -> list[dict]:
    """Matrice (environnement x firmware x overlay) reellement PRESENTE sur disque.

    Un seul triplet a ete essaye jusqu'ici. Trois hypotheses restent ouvertes sur
    l'echec de partitionnement AIE : la version du SDK, la generation d'overlay
    (les fichiers presents sont nommes AIE2P, le code demande AIE2), et le nombre
    de colonnes (1x4 contre 4x4). On les balaie au lieu d'en elire une.
    """
    amd = Path(r"C:\Windows\System32\AMD")
    envs = [(d.name, d / "python.exe") for d in sorted(_ENVS.glob("ryzen-ai*"))
            if (d / "python.exe").exists()]
    fw = {
        "1x4_2044": amd / "1x4_3.5.0.0-2044_ipu_2.xclbin",
        "4x4_2046": amd / "4x4_3.5.0.0-2046_ipu_2.xclbin",
        "AIE2P_Nx4": amd / "AMD_AIE2P_Nx4_Overlay_3.5.0.0-2353_ipu_2.xclbin",
        "AIE2P_4x4": amd / "AMD_AIE2P_4x4_Overlay_3.5.0.0-2354_ipu_2.xclbin",
    }
    combos = [
        ("1x4_2044", "AMD_AIE2_Nx4_Overlay"),    # configuration actuellement cablee
        ("1x4_2044", "AMD_AIE2P_Nx4_Overlay"),   # meme firmware, overlay de la bonne generation
        ("AIE2P_Nx4", "AMD_AIE2P_Nx4_Overlay"),  # firmware ET overlay accordes
        ("4x4_2046", "AMD_AIE2P_4x4_Overlay"),   # 4 colonnes
        ("AIE2P_4x4", "AMD_AIE2P_4x4_Overlay"),
    ]
    out = []
    for nom_env, py in envs:
        for cle, overlay in combos:
            f = fw.get(cle)
            if f and f.exists():
                out.append({"env": nom_env, "python": py, "fw_cle": cle,
                            "firmware": str(f), "overlay": overlay})
    return out


def _mesure(v: dict, cache: Path) -> dict:
    shutil.rmtree(cache, ignore_errors=True)   # FROID veut dire froid
    cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["XLNX_VART_FIRMWARE"] = v["firmware"]
    env["XLNX_TARGET_NAME"] = v["overlay"]
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        r = subprocess.run([str(v["python"]), "-c", SONDE, str(MODELE), str(cache)],
                           capture_output=True, text=True, errors="replace",
                           env=env, timeout=600)
    except subprocess.TimeoutExpired:
        return {"ko": "timeout 600s"}
    brut = (r.stdout or "") + (r.stderr or "")
    m = brut.find("###JSON###")
    if m < 0:
        ligne = next((l for l in brut.splitlines() if "error" in l.lower()), "")
        return {"ko": f"rc={r.returncode} {ligne[:110]}"}
    return json.loads(brut[m + 10:].splitlines()[0])


def main() -> int:
    if not MODELE.exists():
        print(f"modele introuvable : {MODELE}")
        return 3
    variantes = _variantes()
    if not variantes:
        print(f"aucun environnement ryzen-ai sous {_ENVS}")
        return 2

    print(f"modele : {MODELE.name} ({MODELE.stat().st_size / 1e6:.1f} Mo)")
    print(f"{len(variantes)} variante(s) a mesurer\n")
    print(f"{'env':18} {'firmware':11} {'overlay':24} {'warm':>7} {'NPU t/s':>9} {'CPU t/s':>9}  verdict")
    print("-" * 104)

    cache = Path(tempfile.gettempdir()) / "npu_bench_cache"
    gagnantes = []
    for v in variantes:
        d = _mesure(v, cache)
        etq = f"{v['env'][:18]:18} {v['fw_cle']:11} {v['overlay'][:24]:24}"
        if "ko" in d:
            print(f"{etq} {'—':>7} {'—':>9} {'—':>9}  ECHEC {d['ko']}")
            continue
        f, c = d.get("npu_froid", {}), d.get("cpu_seul", {})
        if "erreur" in f:
            print(f"{etq} {'—':>7} {'—':>9} {'—':>9}  session KO {f['erreur'][:40]}")
            continue
        w, npu, cpu = f.get("warmup_s", 0), f.get("debit_tps", 0), c.get("debit_tps", 0)
        # Le NPU travaille si la COMPILATION coute (signature robuste) ou si le debit
        # s'ecarte franchement du CPU. Mesure 24-07 : le seul critere d'ecart a produit
        # un FAUX POSITIF a +27% — le debit « NPU » (187 t/s) etait dans la plage des
        # neuf autres variantes (184-208), c'est la reference CPU qui avait chute a 147.
        # Comparer deux mesures bruitees fabrique des victoires ; le warmup, lui, ne
        # ment pas : une compilation AIE coute des SECONDES, un repli CPU coute zero.
        ecart = (npu / cpu - 1) * 100 if cpu else 0
        actif = w > 8 or (ecart > 40 and npu > 260)
        verdict = f"NPU ACTIF (ecart {ecart:+.0f}%)" if actif else f"repli CPU (ecart {ecart:+.0f}%)"
        print(f"{etq} {w:6.2f}s {npu:9.1f} {cpu:9.1f}  {verdict}")
        if actif:
            gagnantes.append((v, d))

    print("\nSYNTHESE")
    if gagnantes:
        for v, d in gagnantes:
            print(f"  NPU exploitable : env={v['env']} firmware={v['fw_cle']} overlay={v['overlay']}")
    else:
        print("  AUCUNE variante n'active le NPU : toutes rendent le debit du CPU pur.")
        print("  => la cause n'est ni le SDK ni l'overlay. Suspect suivant : les formes")
        print("     DYNAMIQUES du modele (VitisAI exige des dimensions statiques).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
