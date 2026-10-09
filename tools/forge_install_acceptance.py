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

import ast
import hashlib
import importlib.util
import json
import os
import platform
import secrets
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


def plateforme(systeme: str, machine: str, win: bool) -> str:
    """windows-x64 / linux-x64 / macos-arm64 / macos-x64 : l'identifiant des composants de local-llm.toml."""
    if win:
        return "windows-x64"
    if systeme == "Darwin":
        return "macos-arm64" if machine.lower() in ("arm64", "aarch64") else "macos-x64"
    return "linux-x64"


PLATEFORME = plateforme(platform.system(), platform.machine(), WIN)
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


def _est_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 -- muet-ok : hors Windows ou API absente = pas administrateur, dit par l'appelant
        return False


def _ligne_torch() -> str:
    for ligne in (ROOT / "requirements-organisme.txt").read_text(encoding="utf-8").splitlines():
        if ligne.strip().startswith("torch=="):
            return ligne.split(";")[0].strip()
    return "torch"


@etape("dependances_organisme", "dependances")
def _deps_organisme():
    """Ce que les services importent au demarrage en plus du coeur (requirements-organisme.txt, mesure 3 du 08/10 :
    pywin32, qdrant-client, textual-serve, torch). Sous Linux, torch vient d'abord de l'index CPU de PyTorch : la roue
    PyPI Linux tire CUDA (plusieurs Go) pour un service qui n'en a pas l'usage."""
    if sys.platform.startswith("linux"):
        rc, out = sh([sys.executable, "-m", "pip", "install", _ligne_torch(), "--index-url",
                      "https://download.pytorch.org/whl/cpu"], timeout=2700)
        if rc:
            return "FAIL", "torch CPU : " + out[-1500:]
    rc, out = sh([sys.executable, "-m", "pip", "install", "-r", "requirements-organisme.txt"], timeout=2700)
    return ("PASS", "requirements-organisme.txt") if rc == 0 else ("FAIL", out[-1500:])


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


@etape("qdrant")
def _qdrant():
    """Build epinglee de Qdrant (local-llm.toml) extraite a l'emplacement STANDARD runtime/qdrant, ou nokido-doctor
    --ecrire-vars la trouve (QDRANT_BIN). Avant le 09/10, le lanceur visait C:\\tmp\\qdrant_bin en dur : mesure 3,
    NokidoQdrantServer « binaire absent » et EpistemicSoif bloque en attendant :6333."""
    c = composant("local-llm", "qdrant-%s" % PLATEFORME)
    arch = telecharger(c, RUNTIME / "dl" / Path(c["url"]).name)
    cible = ROOT / "runtime" / "qdrant"
    cible.mkdir(parents=True, exist_ok=True)
    if arch.suffix == ".zip":
        zipfile.ZipFile(arch).extractall(cible)
    else:
        with tarfile.open(arch) as t:
            t.extractall(cible, filter="data")
    exe = cible / ("qdrant.exe" if WIN else "qdrant")
    if not exe.is_file():
        return "FAIL", "binaire absent de l'archive : %s" % sorted(p.name for p in cible.iterdir())[:20]
    if not WIN:
        exe.chmod(0o755)
    rc, out = sh([str(exe), "--version"], timeout=60, cwd=cible)
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


# --- Imports tiers des services (2026-10-08) ---------------------------------------------------------------------------
# 3e mesure VM : 15 services plantaient au demarrage sur des modules jamais declares (pywin32, qdrant-client,
# textual-serve, torch), un par passe. Ici UNE passe les nomme tous : pour chaque service Python actif, on suit par AST
# les imports executes AU DEMARRAGE (niveau module, hors try) a travers les modules du depot, puis `find_spec` sur la VM,
# sans rien importer ni lancer. `forge_wheel_probe` teste une liste FIXE de paquets et `forge_deps_reconcilier` croise
# manifeste, environnement et CVE : aucun des deux ne part des points d'entree des services.
_LOCAL_SANS_FICHIER = Path("<local>")
_PREFIXES_LOCAUX = ("nokido_agent", "app", "tools")
_INTERPRETEURS = ("${PYTHON}", "${PY314}", "${PY314T}", "${PY312_RYZEN}")


def _locaux_du_depot() -> dict:
    """Noms importables du DEPOT : modules .py de app/ et tools/ (sous-dossiers compris) et vrais paquets (dossier avec
    __init__.py) de la racine, de app/ et de tools/. Un dossier SANS __init__.py (docker/, docs/) ne masque jamais un
    paquet tiers de meme nom (le SDK `docker`)."""
    locaux = {}
    for base in (ROOT, ROOT / "app", ROOT / "tools"):
        try:
            for p in base.iterdir():
                if p.is_dir() and (p / "__init__.py").is_file():
                    locaux.setdefault(p.name, p / "__init__.py")
                elif p.suffix == ".py":
                    locaux.setdefault(p.stem, p)
        except OSError as e:
            # Illisible n'est pas vide : ses modules passeraient pour des tiers MANQUANTS (faux manques).
            print("[imports] dossier ILLISIBLE %s (%s) : ses modules seront comptes comme tiers"
                  % (base, type(e).__name__), flush=True)
            continue
    for d in ("app", "tools"):
        for p in (ROOT / d).rglob("*.py"):
            locaux.setdefault(p.stem, p)
    return locaux


def _cible_locale(nom: str, locaux: dict):
    parties = nom.split(".")
    if parties[0] in _PREFIXES_LOCAUX:
        return locaux.get(parties[-1], _LOCAL_SANS_FICHIER) if len(parties) > 1 else _LOCAL_SANS_FICHIER
    return locaux.get(parties[0])


def _attrape_import_error(t: ast.Try) -> bool:
    for h in t.handlers:
        if h.type is None:
            return True
        types = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
        if any(isinstance(x, ast.Name) and x.id in ("ImportError", "ModuleNotFoundError", "Exception", "BaseException")
               for x in types):
            return True
    return False


def imports_tiers(fichier, locaux: dict, _vus=None) -> dict:
    """Modules TIERS importes par `fichier` : requis (au demarrage, hors try), optionnel (sous try/except ImportError),
    paresseux (dans une fonction). Les modules du depot importes au demarrage sont SUIVIS ; la stdlib est ignoree."""
    vus = _vus if _vus is not None else set()
    r = {"requis": set(), "optionnel": set(), "paresseux": set()}
    p = Path(fichier)
    if p in vus or not p.is_file():
        return r
    vus.add(p)
    try:
        arbre = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return r
    demarrage = {"main"}  # fonctions executees au demarrage : main() et celles appelees sous __main__
    for n in arbre.body:
        if isinstance(n, ast.If) and "__main__" in ast.dump(n.test):
            demarrage |= {c.func.id for c in ast.walk(n) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}

    def classer(nom: str, mode: str):
        top = nom.split(".")[0]
        if not top or top == "__future__" or top in sys.stdlib_module_names:
            return
        cible = _cible_locale(nom, locaux)
        if cible is None:
            r[mode].add(top)
        elif cible is not _LOCAL_SANS_FICHIER and mode == "requis":
            # Un module du depot importe AU DEMARRAGE s'execute : on le suit. Importe tard, il ne l'est pas (essai a
            # blanc du 08/10 : suivre tous les imports locaux tardifs rendait l'union des dependances du depot entier,
            # 81 tiers dont pwn et anthropic « requis » par 24 services).
            for k, v in imports_tiers(cible, locaux, vus).items():
                r[k] |= v

    def visiter(n, mode: str):
        if isinstance(n, ast.Import):
            for a in n.names:
                classer(a.name, mode)
            return
        if isinstance(n, ast.ImportFrom):
            if not n.level and n.module:
                classer(n.module, mode)
            return
        if isinstance(n, ast.Try) and mode == "requis" and _attrape_import_error(n):
            for c in n.body + [x for h in n.handlers for x in h.body]:
                visiter(c, "optionnel")
            for c in n.orelse + n.finalbody:
                visiter(c, mode)
            return
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # main() et les fonctions appelees sous __main__ s'executent au demarrage (le lanceur runAs importe pywin32
            # dans main()) : leurs imports sont requis ; ceux des autres fonctions, paresseux.
            enfant = mode if (mode == "requis" and n.name in demarrage) else "paresseux"
        elif isinstance(n, ast.Lambda):
            enfant = "paresseux"
        else:
            enfant = mode
        for c in ast.iter_child_nodes(n):
            visiter(c, enfant)

    visiter(arbre, "requis")
    return r


def _module_absent(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is None
    except (ImportError, ValueError):
        return True


def bilan_imports(entrees: dict, locaux: dict) -> dict:
    """{service: fichier(s) d'entree} -> modules manquants sur CETTE machine, par service et par module."""
    par_service, req, par, opt = {}, {}, {}, {}
    for svc, fichiers in entrees.items():
        cumul = {"requis": set(), "optionnel": set(), "paresseux": set()}
        for f in (fichiers if isinstance(fichiers, (list, tuple)) else [fichiers]):
            for k, v in imports_tiers(f, locaux).items():
                cumul[k] |= v
        manq = {k: sorted(m for m in v if _module_absent(m)) for k, v in cumul.items()}
        par_service[svc] = manq
        for cle, dest in (("requis", req), ("paresseux", par), ("optionnel", opt)):
            for m in manq[cle]:
                dest.setdefault(m, []).append(svc)
    # Bloque = un module REQUIS manque (niveau module, main() ou appele sous __main__) ; un paresseux ne manquera
    # qu'a l'usage de sa fonction : rapporte, pas bloquant.
    return {"par_service": par_service, "manquants_requis": req, "manquants_paresseux": par,
            "manquants_optionnels": opt,
            "services_bloques": sorted(s for s, m in par_service.items() if m["requis"])}


def entrees_des_services(services: list) -> tuple:
    """Fichiers d'entree des services Python actifs (+ le lanceur runAs) et modules lances en `-m`."""
    entrees, modules = {}, {}
    for s in services:
        if s.get("disabled") or str(s.get("cmd", "")) not in _INTERPRETEURS:
            continue
        args = [str(a) for a in s.get("args", [])]
        fichiers = [ROOT / "tools" / "forge_runas_launcher.py"] if s.get("runAs") else []
        if "-m" in args and args.index("-m") + 1 < len(args):
            mod = args[args.index("-m") + 1]
            cible = _cible_locale(mod, _locaux_du_depot())
            if cible is None:
                modules[s["name"]] = mod
            elif cible is not _LOCAL_SANS_FICHIER:
                fichiers.append(cible)
        else:
            script = next((a for a in args if a.endswith(".py")), None)
            if script:
                for pref in ("${ROOT}/", "${NOKIDO_DEPOT}/"):
                    script = script[len(pref):] if script.startswith(pref) else script
                if not script.startswith("${"):
                    fichiers.append(ROOT / script)
        if fichiers:
            entrees[s["name"]] = fichiers
    return entrees, modules


@etape("imports", "dependances")
def _imports():
    with open(ROOT / "proxy_deno" / "core" / "services.toml", "rb") as fh:
        services = tomllib.load(fh).get("service", [])
    entrees, modules = entrees_des_services(services)
    b = bilan_imports(entrees, _locaux_du_depot())
    for svc, mod in modules.items():  # services lances en `-m` sur un module tiers (netcfg_mcp...)
        if _module_absent(mod.split(".")[0]):
            b["manquants_requis"].setdefault(mod.split(".")[0], []).append(svc)
            b["services_bloques"] = sorted(set(b["services_bloques"]) | {svc})
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "imports.json").write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    return "MESURE", {"services_python": len(entrees) + len(modules), "services_bloques": len(b["services_bloques"]),
                      "manquants_requis": b["manquants_requis"], "manquants_paresseux": b["manquants_paresseux"],
                      "manquants_optionnels": {m: len(v) for m, v in b["manquants_optionnels"].items()}}


# --- Organisme COMPLET (owner 2026-10-08 : « aucune concession sur les services ») -----------------------------------
# Le superviseur lance TOUS les services declares actifs, comme sur le poste de reference ; on mesure, service par
# service, ce qui tourne et POURQUOI le reste echoue, et la RAM. Etat MESURE : observer avant d'enforcer (non bloquant).
STABILISATION_S = int(os.environ.get("NOKIDO_ORGANISME_STABILISATION_S", "420"))
_RAISONS = ("launch failed", "not open yet", "quarantine", "startCmd failed", "SIGKILL", "exit", "failed", "error")


def classer_service(e: dict) -> str:
    """Etat d'un service lu dans /supervisor/status. `running` SANS pid n'est pas une preuve de vie."""
    e = e or {}
    st, pid, rs = e.get("status"), e.get("pid"), e.get("restarts") or 0
    if st == "running":
        return "TOURNE" if pid else "ECHEC"
    if st == "sleeping":
        return "ENDORMI"
    if st in ("starting", "restarting"):
        return "BOUCLE" if rs >= 3 else "DEMARRAGE"
    if st in ("quarantine", "degraded", "stopped"):
        return "ECHEC"
    return "ILLISIBLE"


def raison_du_journal(nom: str, journal: str) -> str:
    """Derniere ligne du journal du superviseur qui dit pourquoi `nom` ne tourne pas ('' si aucune)."""
    for ligne in reversed(journal.splitlines()):
        if ("%s:" % nom) in ligne and any(k in ligne for k in _RAISONS):
            return ligne.strip()[:300]
    return ""


def bilan_organisme(statut: dict, journal: str, actifs: list, propres=frozenset()) -> dict:
    """Chaque service declare actif : son etat, et sa raison quand il ne tourne pas. Un absent du statut est DIT.
    Un service `propre_au_poste` (decision owner du 08/10 : le runner de la CI privee) que le superviseur n'a pas
    demarre est PROPRE_AU_POSTE, pas ABSENT : son absence sur une autre machine est voulue, pas un trou."""
    vus = (statut or {}).get("services") or {}
    services, compte = {}, {}
    for nom in actifs:
        etat = classer_service(vus[nom]) if nom in vus else ("PROPRE_AU_POSTE" if nom in propres else "ABSENT")
        services[nom] = {"etat": etat, "raison": "" if etat in ("TOURNE", "ENDORMI", "PROPRE_AU_POSTE")
                         else raison_du_journal(nom, journal),
                         **({k: vus[nom].get(k) for k in ("status", "pid", "restarts")} if nom in vus else {})}
        compte[etat] = compte.get(etat, 0) + 1
    return {"services": services, "compte": compte}


def _ram_utilisee_go():
    try:
        import psutil
        return round(psutil.virtual_memory().used / 2**30, 2)
    except Exception:  # noqa: BLE001 -- mesure indisponible : DITE (None), jamais 0
        return None


def _arreter_arbre(p):
    try:
        import psutil
        for enfant in psutil.Process(p.pid).children(recursive=True):
            enfant.kill()
    except Exception as e:  # noqa: BLE001 -- arbre deja parti ou illisible : on tue au moins la racine, et on le DIT
        print("[organisme] arret des services enfants incomplet (%s: %s) ; racine tuee seule" % (type(e).__name__, e),
              flush=True)
    p.kill()


@etape("organisme", "dependances")
def _organisme():
    deno = shutil.which("deno") or str(Path.home() / ".deno" / "bin" / ("deno.exe" if WIN else "deno"))
    with open(ROOT / "proxy_deno" / "core" / "services.toml", "rb") as fh:
        declares = [s for s in tomllib.load(fh).get("service", []) if not s.get("disabled")]
    actifs = [s["name"] for s in declares]
    propres = {s["name"] for s in declares if s.get("propre_au_poste")}
    journal = RUNTIME / "logs" / "superviseur.log"
    # Comme l'installeur : les chemins de CETTE machine d'abord (`nokido-doctor --ecrire-vars`), sinon le superviseur
    # lance les chemins generises du dist (`%USERPROFILE%/...`) -- 1re mesure du 08/10 : 0 service sur 60.
    doc = shutil.which("nokido-doctor")
    rc_vars, sortie_vars = sh([doc, "--ecrire-vars"], timeout=120) if doc else (None, "nokido-doctor introuvable")
    ram_avant = _ram_utilisee_go()
    jeton = secrets.token_hex(16)  # ephemere, propre a cette mesure
    # Windows administrateur : le CHEMIN DE L'INSTALLEUR (decisions owner des 08 et 09/10) -- comptes runAs crees par
    # forge_sandbox_setup, superviseur en tache planifiee SYSTEM (seul SYSTEM peut CreateProcessAsUser). Mesure 3 :
    # lances sous le compte du runner, les 10 services runAs ne pouvaient pas changer de compte.
    systeme = WIN and _est_admin()
    comptes = tache = None
    p = None
    if systeme:
        comptes = sh([sys.executable, "tools/forge_sandbox_setup.py"], timeout=2400)
        tache = sh([sys.executable, "tools/install_boot_hook.py", "--installer", "--env",
                    "LAFORGE_SUPERVISOR_TOKEN=" + jeton], timeout=300)
        journal = ROOT / "logs" / "supervisor" / "laforge-master.tache.log"
    else:
        p = demarrer([deno, "run", "-A", "proxy_deno/core/supervisor.ts"], journal,
                     env={"LAFORGE_SUPERVISOR_TOKEN": jeton})
    try:
        if attendre_http("http://127.0.0.1:8765/supervisor/status", 240) != 200:
            return "FAIL", "superviseur muet sur :8765 ; %s" % queue(journal)
        time.sleep(STABILISATION_S)
        with urllib.request.urlopen("http://127.0.0.1:8765/supervisor/status", timeout=30) as r:
            statut = json.loads(r.read())
        ram_apres = _ram_utilisee_go()
        b = bilan_organisme(statut, queue(journal, 4_000_000), actifs, propres)
        b["ram_go"] = {"avant": ram_avant, "apres": ram_apres,
                       "organisme": None if None in (ram_avant, ram_apres) else round(ram_apres - ram_avant, 2)}
        b["stabilisation_s"] = STABILISATION_S
        b["vars_machine"] = {"rc": rc_vars, "sortie": sortie_vars.strip()[-1500:]}
        b["superviseur"] = "tache planifiee SYSTEM" if systeme else "compte du runner"
        if systeme:
            b["comptes"] = {"rc": comptes[0], "sortie": comptes[1].strip()[-2500:]}
            b["tache"] = {"rc": tache[0], "sortie": tache[1].strip()[-1000:]}
        RUNTIME.mkdir(parents=True, exist_ok=True)
        (RUNTIME / "organisme.json").write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
        ko = {n: (s["etat"], s["raison"][:160]) for n, s in b["services"].items()
              if s["etat"] not in ("TOURNE", "ENDORMI", "PROPRE_AU_POSTE")}
        return "MESURE", {"actifs_declares": len(actifs), "compte": b["compte"], "ram_go": b["ram_go"],
                          "superviseur": b["superviseur"], "vars_machine": b["vars_machine"],
                          **({"comptes_rc": comptes[0], "tache_rc": tache[0]} if systeme else {}),
                          "ne_tournent_pas": ko}
    finally:
        if systeme:
            sh([sys.executable, "tools/install_boot_hook.py", "--arreter"], timeout=180)
        else:
            _arreter_arbre(p)


def code_de_sortie() -> int:
    """MESURE n'echoue jamais le job (observer avant d'enforcer) ; FAIL et ILLISIBLE, si."""
    return 0 if all(r.get("etat") in ("PASS", "NON_TESTE", "MESURE") for n, r in R.items() if n != "_") else 1


def resume() -> str:
    lignes = ["## Installation complete -- %s" % PLATEFORME, "", "| Etape | Etat | Detail |", "|---|---|---|"]
    for nom, r in R.items():
        if nom != "_":
            lignes.append("| %s | %s | %s |" % (nom, r["etat"], str(r["detail"]).replace("|", "/").replace("\n", " ")[:220]))
    return "\n".join(lignes) + "\n"


def main() -> int:
    organisme = "--organisme" in sys.argv[1:]
    if organisme:
        # Organisme complet : les protheses et modeles poses, PUIS le superviseur demarre tout -- rien n'est lance a la
        # main avant lui (le hub, l'embedder et l'interface sont SES services ; les lancer avant lui volerait leurs ports).
        # La base est amorcee AVANT le superviseur (forge_db_bootstrap pose le schema seul) : mesure 3, Homeostasis et
        # Hebbian mouraient sur « no such table » (rag_chunks, biblio_link).
        sequence = (_env, _deps, _deps_organisme, _llama, _modeles, _qdrant, _base, _imports, _organisme)
    else:
        # ordre = chemin d'installation documente : protheses et embedder, PUIS le hub (qui pose le schema), PUIS la
        # base et le pack ; doctor a la fin juge l'installation terminee.
        sequence = (_env, _deps, _doctor_initial, _llama, _modeles, _embedder, _hub, _base, _pack, _rag_direct,
                    _rag_hub, _ui, _docker, _ollama, _lms, _doctor_final)
    for f in sequence:
        f()
    R.pop("_", None)
    rapport = "rapport_organisme.json" if organisme else "rapport_installation.json"
    (ROOT / rapport).write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = resume()
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(md)
    print(md)
    return code_de_sortie()


if __name__ == "__main__":
    sys.exit(main())
