#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Acceptation de l'installation COMPLETE sur une machine vierge (runner GitHub windows-latest / ubuntu-latest).

__FORGE_COLOR__ = "infra/dist : acceptation de l'installation complete sur machine vierge (protheses, RAG, hub)"

POURQUOI (2026-10-07, demande owner) : « Nokido installable par un debutant » se prouve sur une machine NEUVE, pas sur
le poste de developpement. Un runner GitHub heberge est une VM vierge a chaque execution (gratuite pour un depot
public). `forge_dist_install_probe` juge le PAQUET (installe, entrypoints, imports, venv local) ; ce script juge
l'ORGANISME : protheses, modeles epingles, embedder, Knowledge Pack, recherche RAG, hub et interface.

REGLE : chaque etape rend PASS / FAIL / ILLISIBLE / NON_TESTE avec sa raison, et un echec n'arrete pas les suivantes
(elles deviennent NON_TESTE si elles en dependent). Le rapport dit tout l'ecart en un passage. Rien n'est devine :
URL et sommes viennent de distribution/packs/*.toml (un composant non epingle n'est pas telecharge).
Sortie : rapport_installation.json + resume Markdown ($GITHUB_STEP_SUMMARY s'il existe).
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("NOKIDO_RUNTIME", Path.home() / "nokido-runtime"))
WIN = os.name == "nt"
PLATEFORME = "windows-x64" if WIN else "linux-x64"
# Une seule question NATURELLE, validee (3e passe : 1er resultat docs/wiki/01-Installation.md, 0,72). La 2e question
# de la 3e passe (« vault... » -> page Vault attendue) etait choisie au juge : remplacee par la recherche de SOI-MEME
# (voir _rag_direct), qui ne depend d'aucun choix.
REQUETES = (("How do I install Nokido with pip?", "Installation"),)
R: dict[str, dict] = {}


def etape(nom, *depend):
    def deco(f):
        def run():
            manque = [d for d in depend if R.get(d, {}).get("etat") != "PASS"]
            if manque:
                R[nom] = {"etat": "NON_TESTE", "detail": "depend de %s" % ", ".join(manque)}
            else:
                t = time.time()
                try:
                    etat, detail = f()
                except Exception as e:  # noqa: BLE001 -- l'etape echoue, le rapport continue
                    etat, detail = "FAIL", "%s: %s" % (type(e).__name__, str(e)[:400])
                R[nom] = {"etat": etat, "detail": detail, "duree_s": round(time.time() - t, 1)}
            print("[%s] %s -- %s" % (nom, R[nom]["etat"], str(R[nom]["detail"])[:300]), flush=True)
        run.nom = nom
        return run
    return deco


def sh(cmd, timeout=1800, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       cwd=kw.pop("cwd", ROOT), **kw)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def composant(pack, cid):
    with open(ROOT / "distribution" / "packs" / ("%s.toml" % pack), "rb") as fh:
        for c in tomllib.load(fh).get("composant", []):
            if c.get("id") == cid:
                return c
    raise LookupError("%s absent de %s.toml (non epingle)" % (cid, pack))


def telecharger(c, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(c["url"], dest)
    h = hashlib.sha256()
    with open(dest, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 22), b""):
            h.update(b)
    if h.hexdigest() != c["sha256"] or dest.stat().st_size != c["taille"]:
        raise ValueError("somme ou taille FAUSSE pour %s (refus)" % c["id"])
    return dest


def attendre_http(url, delai):
    fin = time.time() + delai
    while time.time() < fin:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return r.status
        except Exception:  # noqa: BLE001 -- pas encore pret
            time.sleep(2)
    return None


def demarrer(cmd, journal: Path, env=None):
    journal.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(cmd, cwd=ROOT, stdout=open(journal, "w", encoding="utf-8"), stderr=subprocess.STDOUT,
                            env=dict(os.environ, **(env or {})))


def queue(journal: Path, n=1200):
    try:
        return journal.read_text(encoding="utf-8", errors="replace")[-n:]
    except OSError:
        return "journal ILLISIBLE"


@etape("environnement")
def _env():
    d = shutil.disk_usage(ROOT)
    return "PASS", {"os": platform.platform(), "python": sys.version.split()[0], "cpu": os.cpu_count(),
                    "disque_libre_go": round(d.free / 2**30, 1)}


@etape("dependances")
def _deps():
    rc, out = sh([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], timeout=2700)
    if rc:
        return "FAIL", out[-1500:]
    rc, out = sh([sys.executable, "-m", "pip", "install", "-e", ".", "--no-deps"])
    return ("PASS", "requirements.txt + paquet editable") if rc == 0 else ("FAIL", out[-1500:])


def _lancer_doctor():
    exe = shutil.which("nokido-doctor")
    if not exe:
        return None, "nokido-doctor introuvable dans le PATH apres installation"
    rc, out = sh([exe], timeout=300)
    bloquant = next((l.strip() for l in out.splitlines() if l.strip().startswith("BLOQUANT")), "aucun BLOQUANT")
    return rc, "%s || %s" % (bloquant, out[-2500:])


@etape("doctor_initial", "dependances")
def _doctor_initial():
    """Etat AVANT l'installation des protheses : informatif (un manque est attendu ici, pas une panne)."""
    rc, detail = _lancer_doctor()
    return ("FAIL" if rc is None else "PASS"), "rc=%s ; %s" % (rc, detail)


@etape("doctor_final", "dependances")
def _doctor_final():
    """Le critere d'acceptation : apres installation, doctor rend 0 (aucun BLOQUANT)."""
    rc, detail = _lancer_doctor()
    return ("PASS" if rc == 0 else "FAIL"), "rc=%s ; %s" % (rc, detail)


@etape("llama_cpp")
def _llama():
    c = composant("local-llm", "llama-server-%s-cpu" % PLATEFORME)
    arch = telecharger(c, RUNTIME / "dl" / Path(c["url"]).name)
    extrait = RUNTIME / "llama_extrait"
    if arch.suffix == ".zip":
        zipfile.ZipFile(arch).extractall(extrait)
    else:
        with tarfile.open(arch) as t:
            t.extractall(extrait, filter="data")
    trouve = next((p for p in extrait.rglob("llama-server.exe" if WIN else "llama-server")), None)
    if not trouve:
        return "FAIL", "llama-server absent de l'archive"
    # emplacement STANDARD d'une installation (connu de nokido-doctor) : le dossier du binaire et ses bibliotheques
    cible = ROOT / "runtime" / "llama"
    shutil.copytree(trouve.parent, cible, dirs_exist_ok=True)
    exe = cible / trouve.name
    if not WIN:
        for p in cible.iterdir():
            p.chmod(0o755)
    rc, out = sh([str(exe), "--version"], timeout=60, cwd=exe.parent)
    R.setdefault("_", {})["llama"] = str(exe)
    return ("PASS" if rc == 0 else "FAIL"), out.strip()[-300:]


@etape("modeles")
def _modeles():
    faits = []
    for cid in ("bge-m3-Q8_0.gguf", "bge-reranker-v2-m3-Q8_0.gguf"):
        telecharger(composant("local-llm", cid), ROOT / "data" / "llm_models" / cid)
        faits.append(cid)
    return "PASS", "sommes verifiees : %s" % faits


def embedder(texte):
    req = urllib.request.Request("http://127.0.0.1:8099/embedding", data=json.dumps({"content": texte}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read())
    v = d[0]["embedding"] if isinstance(d, list) else d["embedding"]
    return v[0] if v and isinstance(v[0], list) else v


@etape("embedder", "llama_cpp", "modeles")
def _embedder():
    exe = R["_"]["llama"]
    demarrer([exe, "-m", str(ROOT / "data/llm_models/bge-m3-Q8_0.gguf"), "--embedding", "--pooling", "cls",
              "-ngl", "0", "--host", "127.0.0.1", "--port", "8099", "-c", "2048", "-b", "2048", "--ubatch-size", "1024"],
             RUNTIME / "logs" / "embedder.log")
    if attendre_http("http://127.0.0.1:8099/health", 300) != 200:
        return "FAIL", queue(RUNTIME / "logs" / "embedder.log")
    import numpy as np
    v = np.asarray(embedder("Nokido local-first hub"), dtype=np.float32)
    n = float(np.linalg.norm(v))
    return ("PASS" if v.shape == (1024,) and abs(n - 1) < 0.05 else "FAIL"), "dim %s, norme %.4f" % (v.shape, n)


@etape("base", "dependances")
def _base():
    """Chemin DOCUMENTE (message de forge_db_bootstrap) : le schema vient du hub demarre AVANT. On dit ce qui existe
    avant l'amorcage : un schema absent apres le demarrage du hub est un trou du PRODUIT, pas du test."""
    import sqlite3
    db = ROOT / "RAG" / "embeddings.db"
    avant = "base absente"
    if db.exists():
        con = sqlite3.connect(db)
        avant = "tables avant amorcage : %s" % sorted(r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('rag_chunks','rag_fts')"))
        con.close()
    rc, out = sh([sys.executable, "tools/forge_db_bootstrap.py"], timeout=900)
    # 2e passe : un fichier cree SANS table passait pour reussi (Windows). On exige la table du RAG.
    tables = []
    if db.exists():
        con = sqlite3.connect(db)
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rag_chunks'")]
        con.close()
    return ("PASS" if rc == 0 and tables else "FAIL"), "%s || rag_chunks %s || %s" % (
        avant, "PRESENTE" if tables else "ABSENTE", out[-600:])


@etape("pack", "base")
def _pack():
    version = os.environ.get("NOKIDO_PACK_VERSION", "")
    cmd = [sys.executable, "tools/forge_knowledge_pack_import.py", "--download"] + (["--version", version] if version else [])
    rc, out = sh(cmd, timeout=1200)
    return ("PASS" if rc == 0 and '"inserted"' in out else "FAIL"), out[-1200:]


@etape("rag_direct", "embedder", "pack")
def _rag_direct():
    import sqlite3
    import numpy as np
    con = sqlite3.connect(ROOT / "RAG" / "embeddings.db")
    lignes = [(i, s, t, np.frombuffer(b, dtype=np.float32)) for i, s, t, b in
              con.execute("SELECT id, source, text, embedding FROM rag_chunks WHERE embedding IS NOT NULL")
              if b and len(b) == 4096]
    con.close()
    m = np.stack([l[3] for l in lignes])
    res, ok = {}, True
    for q, attendu in REQUETES:
        sc = m @ np.asarray(embedder(q), dtype=np.float32)
        top = [lignes[i][1] for i in np.argsort(-sc)[:10]]
        res[q] = {"top": top[:5], "score_max": round(float(sc.max()), 3), "attendu_dans_top10": any(attendu in s for s in top)}
        ok = ok and res[q]["attendu_dans_top10"]
    # Recherche de SOI-MEME : le texte d'un fragment du pack, plonge par l'embedder de CETTE machine, doit retrouver
    # ce fragment en tete (cosinus > 0,95). Prouve que le bge-m3 installe reproduit l'espace de vecteurs du pack.
    cid, _, texte, _ = min((l for l in lignes if l[1].startswith("docs/wiki/")), key=lambda l: l[0])
    sc = m @ np.asarray(embedder(texte), dtype=np.float32)
    tete = lignes[int(np.argmax(sc))]
    retrouve = tete[0] == cid or tete[2] == texte   # un doublon de texte dans le pack n'est pas un echec
    res["soi_meme"] = {"fragment": cid, "en_tete": tete[0], "retrouve": retrouve, "cosinus": round(float(sc.max()), 4)}
    ok = ok and retrouve and float(sc.max()) > 0.95
    return ("PASS" if ok else "FAIL"), {"vecteurs": len(lignes), "requetes": res}


@etape("hub", "dependances")
def _hub():
    demarrer([sys.executable, "tools/nokido_hub.py"], RUNTIME / "logs" / "hub.log")
    st = attendre_http("http://127.0.0.1:8766/health", 300)
    return ("PASS" if st == 200 else "FAIL"), "HTTP %s ; %s" % (st, queue(RUNTIME / "logs" / "hub.log", 800))


@etape("rag_hub", "hub", "pack")
def _rag_hub():
    url = "http://127.0.0.1:8766/api/rag/stream?q=%s&limit=10" % urllib.parse.quote(REQUETES[0][0])
    with urllib.request.urlopen(url, timeout=120) as r:
        corps = r.read(65536).decode("utf-8", "replace")
    return ("PASS" if REQUETES[0][1] in corps else "FAIL"), corps[:800]


@etape("interface", "hub")
def _ui():
    demarrer([sys.executable, "tools/nokido_web_hub.py", "--host", "127.0.0.1", "--port", "7400"],
             RUNTIME / "logs" / "web_hub.log")
    st = attendre_http("http://127.0.0.1:7400/health", 180)
    return ("PASS" if st == 200 else "FAIL"), "HTTP %s ; %s" % (st, queue(RUNTIME / "logs" / "web_hub.log", 800))


@etape("docker")
def _docker():
    if WIN:
        return "NON_TESTE", "runner Windows : conteneurs Linux indisponibles (Docker y fait tourner des images Windows)"
    if not shutil.which("docker"):
        return "FAIL", "docker absent"
    rc, out = sh(["docker", "compose", "-f", "docker-compose.yml", "config", "--services"], timeout=120)
    return ("PASS" if rc == 0 else "FAIL"), "services declares : %s" % out.split()


@etape("ollama", "docker")
def _ollama():
    sh(["docker", "run", "-d", "--name", "ollama", "-p", "11434:11434", "ollama/ollama"], timeout=600)
    if attendre_http("http://127.0.0.1:11434/api/version", 120) != 200:
        return "FAIL", "ollama ne repond pas"
    rc, out = sh(["docker", "exec", "ollama", "ollama", "pull", "qwen2.5:0.5b"], timeout=900)
    req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=json.dumps(
        {"model": "qwen2.5:0.5b", "prompt": "Say OK.", "stream": False}).encode())
    with urllib.request.urlopen(req, timeout=300) as r:
        rep = json.loads(r.read()).get("response", "")
    return ("PASS" if rep.strip() else "FAIL"), "reponse : %r" % rep[:120]


@etape("lmstudio")
def _lms():
    return "NON_TESTE", "LM Studio est une application de bureau ; aucun installeur sans interface n'est epingle"


def resume() -> str:
    lignes = ["## Installation complete -- %s" % PLATEFORME, "", "| Etape | Etat | Detail |", "|---|---|---|"]
    for nom, r in R.items():
        if nom != "_":
            lignes.append("| %s | %s | %s |" % (nom, r["etat"], str(r["detail"]).replace("|", "/").replace("\n", " ")[:220]))
    return "\n".join(lignes) + "\n"


def main() -> int:
    # ordre = chemin d'installation documente : protheses et embedder, PUIS le hub (qui pose le schema), PUIS la base
    # et le pack ; doctor a la fin juge l'installation terminee.
    for f in (_env, _deps, _doctor_initial, _llama, _modeles, _embedder, _hub, _base, _pack, _rag_direct, _rag_hub,
              _ui, _docker, _ollama, _lms, _doctor_final):
        f()
    R.pop("_", None)
    (ROOT / "rapport_installation.json").write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str),
                                                    encoding="utf-8")
    md = resume()
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(md)
    print(md)
    return 0 if all(r["etat"] in ("PASS", "NON_TESTE") for r in R.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
