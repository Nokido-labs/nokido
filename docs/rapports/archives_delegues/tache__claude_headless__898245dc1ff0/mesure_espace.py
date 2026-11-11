"""Mesure de l'espace vectoriel commun local / Modal / Cloudflare.
Client HTTP seul. Aucun vecteur ecrit ailleurs qu'en memoire; aucune base. Sortie: JSON stdout."""
import hashlib, io, json, logging, math, os, statistics, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

buf = io.StringIO()
h = logging.StreamHandler(buf)
h.setLevel(logging.WARNING)
logging.getLogger().addHandler(h)

raw = (HERE / "lot_public.txt").read_bytes()
TEXTS = [t for t in raw.decode("utf-8").split("\n") if t.strip()]
out = {"lot_sha256": hashlib.sha256(raw).hexdigest(), "n": len(TEXTS), "chemins": {}}

from app import forge_embed_router as R  # noqa: E402


def trace(nom):
    s = buf.getvalue()
    buf.truncate(0); buf.seek(0)
    return {"http429_vu": ("429" in s), "log_len": len(s),
            "extrait": s[-160:] if "429" not in s else "429 present"}


def norm(v):
    n = math.sqrt(sum(x * x for x in v))
    return n, [x / n for x in v]


# local
loc = None
t0 = time.time()
for i in range(10):
    loc = R._llama8099_call(TEXTS, 120.0)
    if loc:
        break
    try:
        R.declare_embed_wanted(0.0)
    except Exception:
        pass
    time.sleep(20)
out["chemins"]["local"] = {"obtenu": bool(loc), "essais": i + 1, "s": round(time.time() - t0, 1)}
trace("local")

# modal : chauffe non comptee
mod = None
t0 = time.time()
try:
    R._modal_call(TEXTS[:2], 150.0)
except Exception as e:
    out["chemins"]["modal_chauffe_exc"] = type(e).__name__
trace("m0")
for i in range(3):
    mod = R._modal_call(TEXTS, 150.0)
    if mod:
        break
    time.sleep(30)
out["chemins"]["modal"] = {"obtenu": bool(mod), "essais": i + 1, "s": round(time.time() - t0, 1), **trace("modal")}

# cloudflare : au plus un lot par minute
cf = None
t0 = time.time()
tr = []
for i in range(4):
    cf = R._cloudflare_call(TEXTS, 60.0)
    tr.append(trace("cf")["http429_vu"])
    if cf:
        break
    time.sleep(65)
out["chemins"]["cloudflare"] = {"obtenu": bool(cf), "essais": i + 1, "429_par_essai": tr, "s": round(time.time() - t0, 1)}

vec = {k: v for k, v in (("local", loc), ("modal", mod), ("cloudflare", cf)) if v}
try:
    import numpy as np
except Exception:
    np = None

info = {}
nv = {}
for k, v in vec.items():
    dims = {len(x) for x in v}
    norms = [math.sqrt(sum(x * x for x in r)) for r in v]
    info[k] = {"n": len(v), "dims": sorted(dims), "norme_min": min(norms), "norme_max": max(norms)}
    nv[k] = [norm(r)[1] for r in v]
out["formes"] = info

paires = {}
ks = list(vec)
for a in range(len(ks)):
    for b in range(a + 1, len(ks)):
        A, B = nv[ks[a]], nv[ks[b]]
        if len(A[0]) != len(B[0]):
            paires[f"{ks[a]}-{ks[b]}"] = {"verdict": "DIMENSIONS DIFFERENTES"}
            continue
        if np is not None:
            M = np.array(A) @ np.array(B).T
            M = M.tolist()
        else:
            M = [[sum(x * y for x, y in zip(r, s)) for s in B] for r in A]
        n = len(A)
        diag = [M[i][i] for i in range(n)]
        rang1 = sum(1 for i in range(n) if max(range(n), key=lambda j: M[i][j]) == i)
        # temoin : plus proche voisin hors diagonale (textes differents)
        hors = [max(M[i][j] for j in range(n) if j != i) for i in range(n)]
        med = statistics.median(diag)
        paires[f"{ks[a]}-{ks[b]}"] = {
            "cos_min": min(diag), "cos_mediane": med, "cos_max": max(diag),
            "voisin_rang1": f"{rang1}/{n}",
            "temoin_textes_differents_max_cos": max(hors),
            "temoin_textes_differents_mediane": statistics.median(hors),
            "verdict": "OK" if (min(diag) >= 0.9990 and med >= 0.9995 and rang1 == n) else "ECHEC"}
out["paires"] = paires
print("RESULTAT_JSON " + json.dumps(out))
