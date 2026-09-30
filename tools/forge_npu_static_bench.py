"""Le NPU refuse-t-il le modele a cause de ses formes DYNAMIQUES ?

Dix variantes (2 SDK x 5 firmware/overlay) rendent toutes le debit du CPU pur,
warmup <= 2 s : la chaine ne partitionne jamais vers les tuiles AIE. SDK, overlay
et nombre de colonnes sont donc hors de cause. Reste le modele : `minilm_int8.onnx`
declare `input_ids: ['batch', 'seq_len']`, or VitisAI exige des dimensions
STATIQUES pour compiler un graphe AIE.

Ce banc fige les dimensions avec l'outil officiel `make_dynamic_shape_fixed`, puis
rejoue la meme sonde. La signature attendue si l'hypothese est juste : un warmup
qui passe de ~1 s a plusieurs SECONDES (compilation reelle du graphe).

Lance par `run action=trusted_script` (cache de compilation en ecriture).
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
sys.path.insert(0, str(ROOT))

from nokido_agent.tools.forge_npu_bench import MODELE, _ENVS  # noqa: E402  (anti-dup : meme source)

BATCH, SEQ = 1, 128
FIRMWARE = r"C:\Windows\System32\AMD\1x4_3.5.0.0-2044_ipu_2.xclbin"
OVERLAY = "AMD_AIE2_Nx4_Overlay"

SONDE = r'''
import json, sys, time
import numpy as np
import onnxruntime as ort

modele, cache, B, L = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
res = {}

def bench(providers, opts):
    so = ort.SessionOptions(); so.log_severity_level = 1
    t = time.time()
    try:
        s = ort.InferenceSession(modele, so, providers=providers, provider_options=opts)
    except Exception as e:
        return {"erreur": f"{type(e).__name__}: {str(e)[:220]}"}
    warmup = time.time() - t
    feed = {i.name: np.ones((B, L), dtype=np.int64) for i in s.get_inputs()}
    s.run(None, feed)
    t = time.time(); N = 30
    for _ in range(N):
        s.run(None, feed)
    d = time.time() - t
    return {"warmup_s": round(warmup, 2), "debit_tps": round(B * N / d, 1),
            "formes": [(i.name, i.shape) for i in s.get_inputs()]}

res["npu"] = bench(["VitisAIExecutionProvider", "CPUExecutionProvider"],
                   [{"cacheDir": cache, "cacheKey": "minilm_static"}, {}])
res["cpu"] = bench(["CPUExecutionProvider"], [{}])
print("###JSON###" + json.dumps(res))
'''


def _figer(src: Path, dst: Path, py: str) -> bool:
    """Fige batch/seq_len via l'outil officiel onnxruntime (pas de re-export torch).

    Tourne dans l'environnement NPU et non celui du script : `make_dynamic_shape_fixed`
    importe `onnx`, absent de laforge_py314 (mesure 24-07, ModuleNotFoundError). L'env
    ryzen-ai le porte forcement, VitisAI en dependant.
    """
    etapes = [("batch", BATCH), ("seq_len", SEQ)]
    courant = src
    for i, (dim, val) in enumerate(etapes):
        sortie = dst if i == len(etapes) - 1 else dst.with_suffix(f".tmp{i}.onnx")
        r = subprocess.run(
            [py, "-m", "onnxruntime.tools.make_dynamic_shape_fixed",
             "--dim_param", dim, "--dim_value", str(val), str(courant), str(sortie)],
            capture_output=True, text=True, errors="replace", timeout=600)
        if r.returncode != 0 or not sortie.exists():
            print(f"  figeage {dim}={val} KO : {((r.stderr or '') + (r.stdout or ''))[-400:]}")
            return False
        print(f"  {dim} -> {val} OK ({sortie.stat().st_size / 1e6:.1f} Mo)")
        courant = sortie
    return True


def main() -> int:
    py_npu = _ENVS / "ryzen-ai-final" / "python.exe"
    if not py_npu.exists():
        print(f"env NPU introuvable : {py_npu}")
        return 2
    if not MODELE.exists():
        print(f"modele introuvable : {MODELE}")
        return 3

    # PAS tempfile.gettempdir() : sous LaForgeTrusted il resout vers
    # sandbox/workspace/tmp, sous ACL restrictive. VitisAI y echoue en
    # « weakly_canonical: Accès refusé », leve une exception FATALE, saute le
    # sous-graphe et bascule tout sur CPU — en affichant quand meme son provider.
    # Trois campagnes de mesure ont conclu « repli CPU » sur ce seul refus d'ecriture.
    travail = Path(os.environ.get("LAFORGE_NPU_CACHE", r"C:\tmp\npu_static"))
    shutil.rmtree(travail, ignore_errors=True)
    travail.mkdir(parents=True, exist_ok=True)
    statique = travail / "minilm_static.onnx"

    print(f"source : {MODELE.name} ({MODELE.stat().st_size / 1e6:.1f} Mo)")
    print(f"figeage des dimensions (batch={BATCH}, seq_len={SEQ}) :")
    if not _figer(MODELE, statique, str(py_npu)):
        print("\nECHEC du figeage — hypothese NON testee (ce n'est pas une refutation).")
        return 4

    cache = travail / "cache"
    cache.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["XLNX_VART_FIRMWARE"] = FIRMWARE
    env["XLNX_TARGET_NAME"] = OVERLAY
    env["PYTHONIOENCODING"] = "utf-8"
    # `${vaimlconf.install_dir}` sort NON SUBSTITUE dans les chemins que construit le
    # compilateur : il remonte huit niveaux depuis une racine indefinie, obtient un
    # chemin invalide, et Windows le rapporte en « Accès refusé » — ce qui se lit a
    # tort comme un probleme de droits. Aucun fichier de l'environnement ne definit
    # cette racine : l'installation conda ne pose pas ce que l'installeur du SDK
    # renseigne normalement. On la fournit ici, par les noms que le SDK reconnait.
    racine = str(_ENVS / "ryzen-ai-final" / "Lib" / "site-packages")
    for cle in ("RYZEN_AI_INSTALLATION_PATH", "VAIML_INSTALL_DIR", "VAIP_INSTALL_DIR",
                "XLNX_VAIML_INSTALL_DIR"):
        env.setdefault(cle, racine)
    env["XLNX_ENABLE_DUMP_XIR_SUBGRAPH"] = "1"

    r = subprocess.run([str(py_npu), "-c", SONDE, str(statique), str(cache),
                        str(BATCH), str(SEQ)],
                       capture_output=True, text=True, errors="replace",
                       env=env, timeout=900)
    brut = (r.stdout or "") + (r.stderr or "")
    m = brut.find("###JSON###")
    if m < 0:
        print(f"\nSONDE KO (rc={r.returncode}) :\n{brut[-2000:]}")
        return 5

    d = json.loads(brut[m + 10:].splitlines()[0])
    print("\nMODELE FIGE")
    for cle in ("npu", "cpu"):
        v = d[cle]
        if "erreur" in v:
            print(f"  {cle:4} ERREUR {v['erreur']}")
            continue
        print(f"  {cle:4} warmup={v['warmup_s']:6.2f}s  debit={v['debit_tps']:7.1f} t/s  "
              f"formes={v['formes']}")

    # Le compilateur DIT pourquoi il refuse — encore faut-il ne pas le faire taire.
    # log_severity_level=3 masquait tout ; on relit sa sortie brute et le cache.
    print("\nCE QUE DIT LE COMPILATEUR AIE")
    motifs = ("unsupported", "fallback", "not supported", "CPU EP", "partition",
              "vaiml", "DPU", "subgraph", "assigned")
    lignes = [l.strip() for l in brut.splitlines()
              if any(m.lower() in l.lower() for m in motifs)]
    for l in lignes[:14]:
        print(f"  {l[:160]}")
    if not lignes:
        print("  (aucun message — le compilateur n'a rien dit, pas meme un refus)")
    fichiers = sorted(p.name for p in cache.rglob("*") if p.is_file())
    print(f"\n  cache : {len(fichiers)} fichier(s) — {fichiers[:10]}")
    for p in cache.rglob("*unsupported*"):
        try:
            print(f"\n  {p.name} :\n    {p.read_text(encoding='utf-8', errors='replace')[:700]}")
        except OSError:
            pass

    npu, cpu = d.get("npu", {}), d.get("cpu", {})
    if "erreur" in npu:
        print("\nVERDICT : VitisAI refuse meme le modele fige — la cause est ailleurs.")
        return 0
    w = npu.get("warmup_s", 0)
    print("\nVERDICT")
    print(f"  compilation de graphe (warmup > 8s)  : {w > 8}  (mesure {w}s)")
    if w > 8:
        print("  => LES FORMES DYNAMIQUES ETAIENT LA CAUSE : le NPU compile desormais.")
        print(f"     debit NPU {npu.get('debit_tps')} t/s vs CPU {cpu.get('debit_tps')} t/s")
    else:
        print("  => figer les formes NE SUFFIT PAS : toujours aucune compilation AIE.")
        print("     Suspect suivant : operateurs non supportes par le compilateur AIE")
        print("     (relever aie_unsupported_original_ops.json dans le cache).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
