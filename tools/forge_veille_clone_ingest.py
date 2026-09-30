#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_veille_clone_ingest.py — veille souveraine sans SearXNG/SDK gitingest.

git clone --depth 1 de repos cibles (trusted = git + internet) -> concat des
sources au format SEPARATOR de forge_gitingest_sdk_ingest -> docs/gitingest_veille_*.txt
-> ingest RAG (domain=sdk_gitingest, FTS immédiat). Pour la veille CLI + systolic
arrays (cf [[roadmap_nano_ami_biblio]] / hardware NPU). SearXNG down -> ce chemin.

Usage (via trusted_script) :
  forge_veille_clone_ingest.py [name1 name2 ...]   # subset ; vide = tous
Noms : scalesim sysarray_nmigen systolicdemo tinytinytpu gemini_cli copilot_cli

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `DisqueSature` — Le volume de la base passe sous le seuil PENDANT l'ingestion d'un depot.
- `chemins_invalides_windows` — Chemins de l'arbre qu'un checkout NTFS refuse.
- `decision_regulation` — CONTINUER | ATTENDRE | INCONNU, a partir du retour de `checkpoint_wal` (PURE).
- `priorite_memoire` — Pose la priorite memoire du processus COURANT (Windows). Rend l'issue DITE.
- `refiltrer_dossier_local` — Re-filtre tous les dumps d'un dossier. Idempotent (meme source -> saute).
- `refiltrer_dump_local` — Rejoue le filtre COURANT (v3 : substance + resumes) sur un dump existant.
- `seuil_disque_go` — Espace libre minimal (Go) sur le volume de la base RAG. Decision owner 2026-09-23 : 30.
"""
import os
import sys
import json
import shutil
import subprocess
import tempfile
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DB_PATH = ROOT / "RAG" / "embeddings.db"
# Temp clone HORS repo (git subprocess ne peut pas écrire sous sandbox/ du repo
# = guard/ACL). C:/tmp = scratch trusted libre (cf RULES_SHARED).
# Scratch du clone. `C:/tmp` etait code en dur : le module ne pouvait pas
# tourner ailleurs que sur ce poste, et l'echec s'y serait lu comme « le clone
# ne marche pas » plutot que « le chemin n'existe pas ici ».
CLONE_BASE = Path(os.environ.get("NOKIDO_VEILLE_CLONE_BASE") or
                  (Path("C:/tmp") if os.name == "nt" else Path(tempfile.gettempdir()))
                  ) / "nokido_veille"
SEPARATOR = "=" * 80
# --force : re-cloner et re-dumper meme si un dump est deja sur le disque. Sans
# lui, un dump ancien fige le contenu et une re-ingestion ne rafraichit rien.
FORCE = False

sys.path.insert(0, str(ROOT))

# Le contenu GENERE (traces de simulation, formes d'onde, lockfiles, sorties de
# build) est refuse a l'entree. Ce n'est PAS un cap de volume -- la decision owner
# du 30/08 tient -- c'est un refus par NATURE : une sortie de machine n'est pas
# une connaissance. Effet mesure sur le corpus deja ingere (rejeu du 31/08) :
# 36,5 % des 308 366 chunks de veille, dont 98,6 % de scalesim et 96,6 % de
# tinytinytpu, pour 0 faux positif dans les 25 plus gros refus.
from nokido_agent.tools.forge_veille_intake_filter import (
    FILTRE_VERSION,
    est_autolance,
    est_genere,
    est_hors_substance,
    marqueurs_ver,
    resume_hors_substance,
)
from nokido_agent.tools.forge_veille_registre import (
    ABSENT,
    READY,
    STALE,
    CibleInconnue,
    EcrivainAtomique,
    RegistreInvalide,
    calcul_generation_id,
    chemin_dump,
    chemin_manifeste,
    charger_registre,
    dossier_ecriture_dumps,
    dossiers_dumps,
    ecrire_atomique,
    nom_fichier_dump,
    etat_dump,
    slug_affichage,
    target_id,
    url_canonique,
)

REPOS = {
    # Veille owner 2026-07-30 — evolution de code par algorithmes genetiques + LLM.
    # Par CLONE et non par crawl : ShinkaEvolve est du code, et son interet est dans
    # ses operateurs de mutation et son critere de survie, qui ne sont pas dans la page
    # d'accueil. `sakanaai` est l'organisation : le clone echouera si le nom n'est pas
    # un depot, et ce refus est une information (l'URL owner pointe une org, pas un repo).
    "shinkaevolve": "https://github.com/SakanaAI/ShinkaEvolve",
    "sakana_evo_merge": "https://github.com/SakanaAI/evolutionary-model-merge",
    "scalesim": "https://github.com/scalesim-project/SCALE-Sim",
    "sysarray_nmigen": "https://github.com/ecqin/SysArray-nMigen",
    "systolicdemo": "https://github.com/antonpaquin/SystolicArrayDemo",
    "tinytinytpu": "https://github.com/Alanma23/tinytinyTPU-co",
    # Veille du 2026-09-22 (demande owner). OpenWiki ecrit et MAINTIENT un wiki
    # d'agent pour un codebase. Interet direct pour Nokido : son mecanisme de
    # « Grounded Claims » adosse chaque fait a une preuve VERSIONNEE et le
    # signale quand la preuve bouge -- exactement ce que nos memoires et nos NR
    # font a la main, sans token de version. Voir aussi son OKF v0.2 (bundle
    # portable a provenance deterministe), cousin de notre `ci_proof.json`.
    "openwiki": "https://github.com/langchain-ai/openwiki",
    "gemini_cli": "https://github.com/google-gemini/gemini-cli",
    "copilot_cli": "https://github.com/github/copilot-cli",
    "exploitgym": "https://github.com/sunblaze-ucb/exploitgym",
    "aichat": "https://github.com/sigoden/aichat",
    "pentestgpt": "https://github.com/greydgl/pentestgpt",
    # Veille owner 2026-08-30 : « il y a bcp a apprendre ». Depot majoritairement
    # RUST (codex-rs/) -- sans `.rs` dans KEEP_EXT on n'aurait ingere que les
    # .md, soit la vitrine et pas le moteur.
    "codex": "https://github.com/openai/codex",
}

# DECISION OWNER 2026-08-30 : « il ne faut pas de limite a l'ingestion d'un depot
# GitHub ! le travail de raffinage fera ensuite le reste pour ne garder que la
# substantifique moelle ». Un cap a l'ingestion n'est pas un tri : c'est une
# perte decidee par l'ordre du systeme de fichiers, et elle est IRREVERSIBLE --
# ce qui n'entre pas ne pourra jamais etre raffine. Le tri appartient a l'aval
# (dedup, distillation, compaction), qui dispose du texte pour choisir.
# Vide : un depot ne recoit un cap que sur decision explicite.
CAP_PAR_REPO: dict[str, int] = {}

# Registre des cibles, produit par `forge_veille_backlog_github`. Le dict REPOS
# ci-dessus n'est plus la source : il reste la CARTE DE COMPATIBILITE des noms
# locaux historiques (`scalesim`, `tinytinytpu`), sans quoi les dumps deja sur le
# disque deviendraient orphelins de leur cible.
REGISTRE = ROOT / "sandbox" / "veille_targets.json"


# Noms de dump HISTORIQUES, indexes par URL canonique. Les dumps deja sur le
# disque s'appellent `gitingest_veille_scalesim.txt` : si le registre imposait
# son slug (`scalesim_project_scale_sim`), ils deviendraient orphelins et
# seraient re-clones pour rien.
_NOM_HISTORIQUE = {url_canonique(u.split("github.com/")[-1]).lower(): n
                   for n, u in REPOS.items()}


def _cibles_legacy() -> dict:
    """Les 12 depots historiques, au MEME format que le registre.

    Sert uniquement au repli explicite `--allow-legacy`. Ils portent la priorite
    `demande` : ce sont des depots que l'owner a nommes.
    """
    cibles = {}
    for ordinal, (nom, url_brute) in enumerate(REPOS.items()):
        url = url_canonique(url_brute.split("github.com/")[-1])
        cibles[slug_affichage(url.split("github.com/")[-1])] = {
            "target_id": target_id(url), "repo": url.split("github.com/")[-1],
            "url": url, "ordinal": ordinal, "priorite": "demande",
            "mentions_owner": 0, "mentions_agent": 0, "nom_dump": nom,
        }
    return cibles


def charger_cibles(chemin=None, allow_legacy: bool = False) -> dict:
    """{slug: cible}. FAIL-CLOSED : pas de registre, pas de campagne.

    Le repli sur les 12 depots historiques n'est PAS automatique. Une campagne
    qui se croit a 342 cibles et n'en traite que 12 rend un rapport de succes
    sur 3,5 % du travail — c'est le mode de panne exact que ce module doit
    rendre impossible. Le repli existe, mais il se demande (`--allow-legacy`)
    et il s'annonce.
    """
    p = Path(chemin) if chemin else REGISTRE
    try:
        doc = charger_registre(p)
    except RegistreInvalide as exc:
        if not allow_legacy:
            raise
        print("[cibles] REPLI LEGACY EXPLICITE — %s. %d cibles historiques "
              "SEULEMENT : ce n'est PAS la campagne complete."
              % (exc, len(REPOS)), flush=True)
        return _cibles_legacy()
    cibles = {}
    for slug, c in doc["cibles"].items():
        cible = dict(c)
        cible["nom_dump"] = _NOM_HISTORIQUE.get(c["url"].lower(), slug)
        cibles[slug] = cible
    print("[cibles] registre %s, generation %s du %s : %d cibles"
          % (p.name, doc["generation_id"], doc["generated_at"], len(cibles)),
          flush=True)
    return cibles


def alias_historiques(cibles: dict) -> dict:
    """{ancien nom: slug} — les 12 noms explicites restent utilisables en CLI."""
    par_url = {c["url"].lower(): slug for slug, c in cibles.items()}
    alias = {}
    for url, nom in _NOM_HISTORIQUE.items():
        slug = par_url.get(url)
        if slug:
            alias[nom] = slug
    return alias


def _valeur(args: list, cle: str):
    """`--lot=20` ou `--lot 20`. Rend None si absent."""
    for i, a in enumerate(args):
        if a.startswith(cle + "="):
            return a.split("=", 1)[1]
        if a == cle and i + 1 < len(args):
            return args[i + 1]
    return None


# Options qui consomment la valeur suivante quand elles sont ecrites sans `=`.
_OPTIONS_A_VALEUR = ("--lot", "--depuis", "--priorite", "--generation",
                     "--campagne", "--registre", "--exclure")


def positionnels(args: list) -> list:
    """Arguments qui designent une CIBLE, options et leurs valeurs retirees."""
    sortie, saute = [], False
    for i, a in enumerate(args):
        if saute:
            saute = False
            continue
        if a.startswith("--"):
            if a in _OPTIONS_A_VALEUR and i + 1 < len(args):
                saute = True
            continue
        sortie.append(a)
    return sortie


def selectionner(cibles: dict, args: list, ordre_fige=None) -> list:
    """Slugs a traiter. Leve `CibleInconnue` sur une cible non reconnue.

    C'est le garde le plus important du module. L'ancienne forme filtrait les
    arguments (`[a for a in args if a in cibles]`) puis, la liste etant vide,
    basculait sur TOUTES les cibles : une faute de frappe declenchait 342
    clones. Une cible inconnue est desormais une ERREUR, jamais un « tout ».
    """
    alias = alias_historiques(cibles)
    demandes = positionnels(args)
    if demandes:
        choisis, inconnues = [], []
        for nom in demandes:
            slug = nom if nom in cibles else alias.get(nom)
            if slug is None:
                inconnues.append(nom)
            elif slug not in choisis:
                choisis.append(slug)
        if inconnues:
            raise CibleInconnue(
                "cible(s) inconnue(s) au registre : %s. Aucune campagne lancee "
                "— une faute de frappe ne doit pas declencher %d clones."
                % (", ".join(inconnues), len(cibles)))
        return choisis

    # Ordre = l'`ordinal` FIGE par le registre, jamais un tri recalcule ici.
    # Recalculer l'ordre a chaque lancement ferait glisser les lots d'une passe
    # a l'autre : le lot 2 d'aujourd'hui ne serait pas celui d'hier.
    ordre = ([s for s in ordre_fige if s in cibles] if ordre_fige
             else sorted(cibles, key=lambda s: cibles[s]["ordinal"]))
    # --exclure a,b : mettre de cote NOMMEMENT (owner 2026-09-23 : heyputer_firefox,
    # des heures au 1er passage). Un exclu est ANNONCE, jamais oublie en silence.
    exclus = {s.strip() for s in (_valeur(args, "--exclure") or "").split(",") if s.strip()}
    if exclus:
        inconnus = sorted(exclus - set(cibles))
        if inconnus:
            raise CibleInconnue("exclusion(s) inconnue(s) au registre : %s"
                                % ", ".join(inconnus))
        print("[selection] %d cible(s) mise(s) de cote : %s"
              % (len(exclus), ", ".join(sorted(exclus))), flush=True)
        ordre = [s for s in ordre if s not in exclus]
    filtre = _valeur(args, "--priorite")
    if filtre:
        ordre = [s for s in ordre if cibles[s]["priorite"] == filtre]
    depuis = int(_valeur(args, "--depuis") or 0)
    lot = _valeur(args, "--lot")
    return ordre[depuis:depuis + int(lot)] if lot is not None else ordre[depuis:]


def snapshot_campagne(chemin, ordre: list, generation_id: str,
                      rebase: bool = False) -> list:
    """Fige l'ordre d'une campagne pour qu'un lot reste le meme d'un jour a l'autre.

    Sans instantane, regenerer le registre entre deux lots redistribue les
    ordinaux : le « lot 3 » designerait d'autres depots, et on croirait avoir
    traite ce qu'on n'a jamais vu.
    """
    p = Path(chemin)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        ecrire_atomique(p, json.dumps(
            {"generation_id": generation_id, "ordre": ordre}, ensure_ascii=False,
            indent=1))
        print("[campagne] instantane cree : %d cible(s), generation %s"
              % (len(ordre), generation_id), flush=True)
        return ordre
    except (OSError, ValueError) as exc:
        raise RegistreInvalide(
            "instantane de campagne illisible (%s): %s" % (type(exc).__name__, p)
        ) from exc
    if d.get("generation_id") != generation_id and not rebase:
        raise RegistreInvalide(
            "campagne figee sur la generation %s, registre en %s. Terminer la "
            "campagne, ou la reprendre explicitement (--rebase-campagne)."
            % (d.get("generation_id"), generation_id))
    if rebase:
        ecrire_atomique(p, json.dumps(
            {"generation_id": generation_id, "ordre": ordre}, ensure_ascii=False,
            indent=1))
        return ordre
    return [s for s in d.get("ordre") or [] if isinstance(s, str)]

# Extensions sources retenues (texte utile) ; le reste ignoré (binaires, assets)
# LISTE NOIRE, et non plus liste blanche. Une allowlist d'extensions est une
# limite deguisee : elle echoue EN SILENCE pour tout langage non prevu. Mesure
# 2026-08-30 : `.rs` en etait absent, si bien qu'ingerer openai/codex -- depot
# majoritairement Rust -- n'aurait rapporte que la vitrine `.md`, avec un
# rapport de succes. On ne peut pas lister a l'avance les langages qu'on
# rencontrera ; on peut lister ce qui n'est pas du texte.
SKIP_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".avif", ".svg",
    ".mp4", ".mov", ".avi", ".webm", ".mp3", ".wav", ".ogg", ".flac",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".obj", ".o", ".a", ".lib",
    ".wasm", ".class", ".pyc", ".pyo", ".pdb", ".node",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".pdf", ".doc", ".docx",
    ".xls", ".xlsx", ".ppt", ".pptx",
    ".db", ".sqlite", ".sqlite3", ".mdb", ".dat", ".pack", ".idx",
    ".npy", ".npz", ".pt", ".pth", ".onnx", ".safetensors", ".gguf", ".pkl",
}
SONDE_BINAIRE = 8192  # octets lus pour trancher texte vs binaire
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".github", "dist", "build",
             "test_data", "tests/data", "venv", ".venv", "images", "img", "assets"}
# Plafond par FICHIER : garde-fou memoire, PAS critere de pertinence. Il etait a
# 60 000 o et ecartait 199 fichiers de codex, dont du code reel. A 8 Mo, ce qui
# depasse est du genere ou de la donnee, jamais de la substance a raffiner --
# et les fichiers ecartes sont NOMMES dans le rapport.
MAX_FILE = 8_000_000
MAX_TOTAL = None           # PAS de cap par depot (decision owner 2026-08-30)


def est_binaire(chemin: str) -> bool:
    """Un octet nul dans la tete du fichier = binaire.

    Complete la liste noire : un binaire peut porter n'importe quel suffixe, et
    `read_text(errors="replace")` ne LEVE pas dessus -- il rend une bouillie de
    U+FFFD qui s'ingere silencieusement et pollue le lexical.
    """
    try:
        with open(chemin, "rb") as fh:
            return b"\x00" in fh.read(SONDE_BINAIRE)
    except OSError:
        return True  # illisible : pas ingere, et l'appelant le compte


_CARS_INTERDITS_WIN = set('<>:"|?*')
_NOMS_RESERVES_WIN = {"con", "prn", "aux", "nul"} | {"com%d" % i for i in range(1, 10)} | {
    "lpt%d" % i for i in range(1, 10)}


def chemins_invalides_windows(chemins) -> list:
    """Chemins de l'arbre qu'un checkout NTFS refuse : caractere interdit, nom
    reserve (CON, NUL...), segment finissant par un point ou une espace.

    Mesure du 2026-09-23 : `searxng/searxng` porte `...searxng.conf:socket` ; le
    clone reussit, le CHECKOUT echoue, et tout le depot etait perdu pour un fichier.
    """
    out = []
    for p in chemins:
        for seg in p.split("/"):
            base = seg.split(".")[0].lower()
            if (set(seg) & _CARS_INTERDITS_WIN or base in _NOMS_RESERVES_WIN
                    or seg.endswith((".", " "))):
                out.append(p)
                break
    return out


def _extraire_par_archive(git, dst: str, invalides: list) -> bool:
    """Extrait HEAD via `git archive` en SAUTANT les chemins invalides.

    Le sparse-checkout ne suffit pas (mesure 2026-09-23) : git pour Windows
    verifie TOUS les chemins de l'index au checkout, meme ceux exclus. L'archive
    ne passe pas par l'index : on lit l'arbre, et l'on n'ecrit que le valide.
    """
    import io
    import tarfile

    # `git archive` valide lui aussi l'arbre (mesure : « invalid path ») : on leve
    # protectNTFS POUR CETTE LECTURE SEULE. L'archive n'ecrit RIEN sur disque ; ce
    # qui est ecrit passe par le filtre ci-dessous, qui ne laisse passer aucun
    # chemin invalide. La protection reste donc tenue la ou elle compte.
    r = subprocess.run(git + ["-c", "core.protectNTFS=false", "archive", "--format=tar",
                              "HEAD"], capture_output=True, timeout=300)
    if r.returncode != 0:
        print("  clone KO (archive): %s" % r.stderr.decode("utf-8", "replace").strip()[:200])
        return False
    exclus = set(invalides)
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tar:
        for m in tar.getmembers():
            if m.name in exclus or chemins_invalides_windows([m.name]):
                continue
            if not (m.isfile() or m.isdir()):
                continue  # liens et speciaux : jamais ecrits (surete d'extraction)
            cible = os.path.normpath(os.path.join(dst, m.name))
            if not cible.startswith(os.path.normpath(dst) + os.sep):
                continue  # pas d'ecriture hors du dossier de clone
            if m.isdir():
                os.makedirs(cible, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(cible), exist_ok=True)
            with open(cible, "wb") as f:
                f.write(tar.extractfile(m).read())
    return True


def clone(url: str, dst: str) -> bool:
    # `GIT_TERMINAL_PROMPT=0` est OBLIGATOIRE : sans lui git attend un prompt qui
    # ne viendra jamais depuis un job detache, et le clone PEND au lieu d'echouer.
    # Mesure 2026-08-30 : quatre `git` du matin (dont un `credential-manager`)
    # etaient encore suspendus TREIZE HEURES plus tard, et le job de veille est
    # mort en laissant un dossier de clone vide. Un echec franc vaut mieux qu'une
    # attente muette -- c'est la meme famille que « ne pas conclure d'une source
    # qui se tait », vue du cote de l'appelant.
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    env["GIT_ASKPASS"] = ""
    try:
        # SANS checkout : un seul chemin invalide sous NTFS ferait echouer tout le
        # depot (searxng, 2026-09-23). On liste l'arbre, on exclut NOMMEMENT les
        # chemins impossibles, puis on extrait le reste.
        # `core.longpaths` (2026-09-26) : sous un dossier de travail PROFOND, git depasse MAX_PATH des le
        # fichier `.keep` du pack -- « fatal: cannot write keep file », clone KO. Mesure : les 2 tests
        # dump_repo rouges en CI de reference (basetemp de 149 car.), reproduits a l'identique, verts
        # avec cette option. Un vrai depot a chemins profonds tombait de la meme facon.
        r = subprocess.run(
            ["git", "-c", "credential.helper=", "-c", "core.longpaths=true", "clone", "--depth", "1",
             "--quiet", "--no-checkout", url, dst],
            capture_output=True, text=True, errors="replace", timeout=300, env=env,
        )
        if r.returncode != 0:
            print(f"  clone KO: {r.stderr.strip()[:200]}")
            return False

        def _git(*a, **kw):
            return subprocess.run(["git", "-c", "safe.directory=*", "-c", "core.longpaths=true", "-C", dst]
                                  + list(a),
                                  capture_output=True, text=True, errors="replace",
                                  timeout=300, env=env, **kw)

        arbre = _git("ls-tree", "-r", "--name-only", "-z", "HEAD")
        chemins = [c for c in (arbre.stdout or "").split("\0") if c]
        invalides = chemins_invalides_windows(chemins) if os.name == "nt" else []
        if invalides:
            for c in invalides:
                print(f"  chemin invalide sous Windows, NON extrait : {c}")
            return _extraire_par_archive(["git", "-c", "safe.directory=*", "-C", dst],
                                         dst, invalides)
        co = _git("checkout", "--quiet", "HEAD")
        if co.returncode != 0:
            print(f"  clone KO (checkout): {co.stderr.strip()[:200]}")
            return False
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  clone EXC: {type(e).__name__}: {e}")
        return False


def priorite(rel: str) -> tuple:
    """Ordre de selection SOUS CAP. Le cap coupe : ce qui reste doit etre CHOISI.

    Avant ce tri, la selection suivait l'ordre de `os.walk` et s'arretait au
    premier depassement : sur un gros depot on gardait les premiers repertoires
    rencontres et on jetait le reste, en silence. L'ordre du systeme de fichiers
    n'est pas un critere de pertinence.

    Rang 0 = les fichiers ou un depot DIT ce qu'il fait (AGENTS.md, README) ;
    1 = le reste de la doc ; 2 = la configuration ; 3 = le code. A rang egal, le
    chemin le plus court d'abord : le coeur avant la peripherie.
    """
    bas = rel.lower()
    nom = bas.rsplit("/", 1)[-1]
    profondeur = bas.count("/")
    if nom in ("agents.md", "readme.md", "contributing.md", "architecture.md"):
        return (0, profondeur, len(rel))
    if bas.endswith((".md", ".rst", ".txt")):
        return (1, profondeur, len(rel))
    if bas.endswith((".toml", ".yaml", ".yml", ".json", ".cfg")):
        return (2, profondeur, len(rel))
    return (3, profondeur, len(rel))


def sha_clone(dst: str) -> str:
    """Commit exact du clone, ou 'inconnu'.

    Sans lui, un chunk ingere n'est rattachable a AUCUNE version : le clone est
    ephemere (`rmtree` en sortie), donc l'information disparait pour toujours si
    on ne la capture pas ici. Une connaissance qu'on ne peut pas re-verifier
    contre sa source n'est pas une connaissance, c'est une croyance.
    """
    try:
        r = subprocess.run(
            ["git", "-C", dst, "rev-parse", "HEAD"],
            capture_output=True, text=True, errors="replace", timeout=30,
        )
        return r.stdout.strip() or "inconnu"
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  sha du clone illisible : {type(exc).__name__}")
        return "inconnu"


def _chemin_dump(nom: str, racine=None) -> Path:
    """Dump existant (docs/ puis dossiers de `sandbox/veille_dumps.dir`), sinon
    son chemin dans docs/ — un ABSENT reste nomme la ou on l'attendait."""
    ds = dossiers_dumps(racine or ROOT)
    return chemin_dump(nom, ds) or (ds[0] / nom_fichier_dump(nom))


def _sortie_dump(nom: str, racine=None) -> Path:
    """Ou ECRIRE le dump : la ou il existe, sinon le dernier dossier declare.

    Mesure 2026-09-23 : sous `run_job online`, `docs/` est refuse en ecriture
    (PermissionError) ; E: est accepte, et relu par le compte de l'ingestion.
    """
    return dossier_ecriture_dumps(nom, dossiers_dumps(racine or ROOT)) / nom_fichier_dump(nom)


def dump_repo(cible: dict) -> Path | None:
    name, url = cible["nom_dump"], cible["url"]
    out = _sortie_dump(name)
    # L'ETAT se lit sur la copie EXISTANTE (la plus recente), jamais sur le chemin
    # d'ecriture : sinon un dump READY de docs/ se lit ABSENT sur E: et se re-clone.
    existant = _chemin_dump(name)
    etat, raison = etat_dump(existant, cible, FILTRE_VERSION)
    if etat == READY and not FORCE:
        print(f"[{name}] dump READY ({raison}) — clone inutile")
        return existant
    if etat == STALE:
        # Un dump dont on ignore la provenance ne doit PAS servir : l'ancienne
        # forme testait `taille > 1000` et rendait un succes sur un dump de
        # version inconnue.
        print(f"[{name}] dump PERIME ({raison}) — re-clone")
    CLONE_BASE.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=f"{name}_", dir=str(CLONE_BASE))
    ecrivain = None
    try:
        print(f"[{name}] clone {url}")
        if not clone(url, tmp):
            return None
        sha = sha_clone(tmp)
        print(f"[{name}] commit {sha[:12]}")
        cap = CAP_PAR_REPO.get(name, MAX_TOTAL)  # None = aucune limite
        # 1) recenser TOUS les candidats avant de couper quoi que ce soit
        candidats = []
        trop_gros: list[str] = []
        apercu_generes: list[str] = []
        illisibles = hors_ext = generes = 0
        autolances: list[str] = []
        hors_substance: list = []
        resumes = 0
        for dirpath, dirnames, filenames in os.walk(tmp):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() in SKIP_EXT:
                    hors_ext += 1
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    taille = os.path.getsize(fp)
                except OSError:
                    illisibles += 1
                    continue
                rel = os.path.relpath(fp, tmp).replace("\\", "/")
                # Securite AVANT pertinence : un vecteur d'auto-lancement est
                # refuse et NOMME, jamais ouvert (incident Shai-Hulud 2026-09-23).
                lance, motif_l = est_autolance(rel)
                if lance:
                    autolances.append(f"{rel} — {motif_l}")
                    continue
                est_gen, motif = est_genere(rel)
                if est_gen:
                    generes += 1
                    if len(apercu_generes) < 10:
                        apercu_generes.append(f"{rel} — {motif}")
                    continue
                if taille > MAX_FILE:
                    # Nommer, pas seulement compter : un fichier ecarte doit
                    # pouvoir etre reclame.
                    trop_gros.append(f"{rel} ({taille} o)")
                    continue
                if est_binaire(fp):
                    hors_ext += 1
                    continue
                # SUBSTANCE (owner 2026-09-23) : ecarte du contenu integral, mais
                # RESUME au 2e passage — la moelle est gardee, pas le volume.
                hs, motif_hs = est_hors_substance(rel, taille)
                if hs:
                    hors_substance.append((rel, fp, motif_hs))
                    continue
                candidats.append((rel, fp, taille))

        # 2) trier par PERTINENCE, puis remplir jusqu'au cap
        candidats.sort(key=lambda c: priorite(c[0]))
        total = 0
        # PROVENANCE en tete : devient un chunk ingere comme les autres, donc
        # retrouvable par la recherche. C'est le lien vers la preuve source --
        # sans lui, aucune connaissance tiree de ce depot ne peut etre datee ni
        # re-verifiee contre le code dont elle est issue.
        # ECRITURE EN FLUX (2026-09-23) : tout garder en memoire puis `join` a fait
        # tuer un job a 6 151 Mo de RSS. Chaque fichier retenu est ecrit aussitot ;
        # la memoire est bornee par le plus gros fichier (MAX_FILE).
        ecrivain = EcrivainAtomique(out)
        ecrivain.write(
            f"{name}/_PROVENANCE\n"
            f"repo: {url}\n"
            f"commit: {sha}\n"
            f"clone_utc: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
            f"candidats: {len(candidats)}\n"
        )
        retenus = 0
        ecartes_cap = 0
        for rel, fp, _taille in candidats:
            if cap is not None and total >= cap:
                ecartes_cap += 1
                continue
            try:
                txt = Path(fp).read_text(encoding="utf-8", errors="replace")
            except OSError:
                illisibles += 1
                continue
            # Second passage, sur le CONTENU : le marqueur « DO NOT EDIT » /
            # « @generated » est le seul juge fiable, c'est le producteur qui le
            # pose. Il n'est lisible qu'ici, une fois le fichier ouvert.
            lance, motif_l = est_autolance(rel, txt)
            if lance:
                autolances.append(f"{rel} — {motif_l}")
                continue
            est_gen, motif = est_genere(rel, txt)
            if est_gen:
                generes += 1
                if len(apercu_generes) < 10:
                    apercu_generes.append(f"{rel} — {motif}")
                continue
            ecrivain.write("\n" + SEPARATOR + "\n" + f"{name}/{rel}\n{txt}")
            retenus += 1
            total += len(txt)

        # MOELLE des fichiers hors substance : un resume deterministe (<= 2 Ko)
        # a la place du contenu integral — contrat des tests, schema des donnees,
        # bilan des sorties, identite des vendors (owner 2026-09-23).
        for rel, fp, motif_hs in hors_substance:
            try:
                txt = Path(fp).read_text(encoding="utf-8", errors="replace")
            except OSError:
                illisibles += 1
                continue
            if est_autolance(rel, txt)[0]:
                autolances.append(f"{rel} - marqueur (resume refuse)")
                continue
            ecrivain.write("\n" + SEPARATOR + "\n" + f"{name}/{rel}\n"
                           + resume_hors_substance(rel, txt, motif_hs))
            resumes += 1
            retenus += 1

        # `sections` porte desormais la PROVENANCE en tete : elle n'est jamais
        # vide, donc elle ne peut plus servir de test « rien retenu ».
        if retenus == 0:
            print(f"[{name}] aucune source retenue "
                  f"(candidats={len(candidats)} hors_ext={hors_ext} "
                  f"trop_gros={len(trop_gros)} generes={generes} "
                  f"illisibles={illisibles})")
            return None          # le finally abandonne le temporaire
        # Ecriture atomique : un dump tronque par un plantage se lirait comme un
        # dump valide (il depasse le seuil de taille) et serait ingere.
        ecrivain.valider()
        # MANIFESTE : sans lui, un dump ne porte aucune trace de son commit
        # source, et toute connaissance qu'on en tire devient inverifiable.
        ecrire_atomique(chemin_manifeste(out), json.dumps({
            "repo": cible.get("repo"), "url": url,
            "target_id": cible.get("target_id"), "commit": sha,
            "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "filtre_version": FILTRE_VERSION,
            "fichiers_retenus": retenus,
            "fichiers_candidats": len(candidats),
            "octets": total,
            "refus": {"cap": ecartes_cap, "trop_gros": len(trop_gros),
                      "genere": generes, "hors_ext": hors_ext,
                      "illisibles": illisibles, "autolance": len(autolances),
                      "hors_substance_resume": resumes},
            "autolances": autolances,
        }, ensure_ascii=False, indent=1))
        # Denominateur : « N fichiers ingeres » seul laisse croire a l'exhaustivite.
        print(f"[{name}] dump -> {out.name} : retenus {retenus}/{len(candidats)} "
              f"candidats ({total} o, cap {'AUCUN' if cap is None else cap}) | "
              f"ecartes: cap={ecartes_cap} trop_gros={len(trop_gros)} "
              f"genere={generes} hors_ext={hors_ext} illisibles={illisibles}")
        for t in trop_gros[:10]:
            print(f"    trop gros (>{MAX_FILE} o), NON ingere : {t}")
        # Nommer les refus : un garde qui ecarte sans dire quoi est indistinguable
        # d'une perte silencieuse, et c'est ainsi qu'un faux positif survit.
        for g in apercu_generes:
            print(f"    genere, NON ingere : {g}")
        for a in autolances:
            print(f"    AUTO-LANCEMENT, NON ingere : {a}")
        return out
    finally:
        if ecrivain is not None:
            ecrivain.abandonner()     # sans effet si valide ; sinon jette le temporaire
        _effacer_clone(tmp)


def _effacer_clone(tmp: str) -> bool:
    """Efface le clone, objets `.git` en lecture seule compris.

    Mesure 2026-09-23 : `rmtree(ignore_errors=True)` echouait EN SILENCE sous
    Windows sur les objets `.git` en lecture seule ; ~145 clones s'etaient
    accumules dans le scratch depuis juillet, dont un depot porteur du ver
    Shai-Hulud. Un clone non efface est desormais DIT.
    """
    import stat

    def _forcer(fonction, chemin, _exc):
        try:
            os.chmod(chemin, stat.S_IWRITE)
            fonction(chemin)
        except OSError:  # muet-ok : le reste est constate juste apres
            pass

    shutil.rmtree(tmp, onexc=_forcer)   # runtimes certifies >= 3.12
    if os.path.exists(tmp):
        print(f"  clone NON efface (reste sur disque) : {tmp}")
        return False
    return True


def _scan_defender(chemin, lanceur=None) -> tuple[str, str]:
    """('PROPRE'|'MENACE'|'ILLISIBLE', detail) — Defender en RAPPORT SEUL.

    `-DisableRemediation` : ne modifie rien. Mesure 2026-09-23 : fonctionne sous
    `LaForgeSbxOffline` (le compte de l'ingestion). ILLISIBLE n'est JAMAIS
    PROPRE : l'appelant refuse (UNKNOWN != NO).
    """
    mp = r"C:\Program Files\Windows Defender\MpCmdRun.exe"
    lanceur = lanceur or (lambda cmd: subprocess.run(
        cmd, capture_output=True, text=True, errors="replace", timeout=600))
    try:
        r = lanceur([mp, "-Scan", "-ScanType", "3", "-File", str(chemin),
                     "-DisableRemediation"])
    except (OSError, subprocess.SubprocessError) as exc:
        return "ILLISIBLE", "Defender injoignable (%s)" % type(exc).__name__
    sortie = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode == 0 and "found no threats" in sortie:
        return "PROPRE", ""
    if r.returncode == 2 or "threat" in sortie.lower():
        return "MENACE", sortie[-300:]
    return "ILLISIBLE", "rc=%s %s" % (r.returncode, sortie[-200:])


# Au-dela, le WAL est RENDU au disque entre deux depots (TRUNCATE), pas seulement
# verse (PASSIVE). Mesure 2026-09-23 : en PASSIVE, 32 depots (+468 111 chunks)
# ont porte le WAL a 23,1 Go pour 1,4 Go de base reelle, et le garde des 30 Gio a
# arrete la campagne sur de l'espace RECUPERABLE ; le TRUNCATE l'a rendu en 67 s.
SEUIL_WAL_TRUNCATE_MO = 2048.0
# Attente COURTE : un TRUNCATE tient le verrou d'ecriture pendant qu'il attend les
# lecteurs (60 s par defaut). Repete entre depots, il bloquait tous les ecrivains
# et a fini par faire echouer l'ingestion elle-meme (`database is locked`).
ATTENTE_TRUNCATE_S = 5.0


# REGULATION DU WAL entre deux depots (2026-09-23). Mesure : un lecteur long EXTERIEUR a fige
# le repere de checkpoint ~4 min ; l'ingestion, elle, continuait d'ecrire -> WAL 151 Mo ->
# 21 375 Mo en 18 min, jusqu'au garde disque. Le TRUNCATE rendait busy=1 et on repartait.
# Ici on ATTEND que le checkpoint rattrape (PASSIVE : ne bloque personne), borne dans le temps ;
# au-dela on s'arrete en le disant. Ce n'est PAS la correction du lecteur (non identifie) :
# c'est le symptome rendu inoffensif, la variable WAL enfin regulee (fiche V5).
SEUIL_REGULATION_MO = 2048.0
ATTENTE_REPERE_MAX_S = 900.0
PAS_REPERE_S = 15.0


def decision_regulation(ck: dict) -> str:
    """CONTINUER | ATTENDRE | INCONNU, a partir du retour de `checkpoint_wal` (PURE)."""
    if not ck.get("fait"):
        raison = str(ck.get("raison", ""))
        if "illisible" in raison or raison.startswith("sqlite"):
            return "INCONNU"          # mesure absente : ne bloque pas, mais se NOMME
        return "CONTINUER"            # sous le seuil ou pas de WAL
    if ck.get("busy"):
        return "ATTENDRE"             # un ecrivain/checkpointeur tient la base
    if (ck.get("verses") or 0) < (ck.get("pages") or 0):
        return "ATTENDRE"             # un lecteur fige le repere : on n'empile pas
    return "CONTINUER"


def _reguler_wal(checkpoint=None, dormir=None, horloge=None) -> dict:
    """Attend que le checkpoint rattrape. {'etat': LIBRE|INCONNU|GEL_PERSISTANT, ...}."""
    import time as _t
    dormir = dormir or _t.sleep
    horloge = horloge or _t.time
    if checkpoint is None:
        from app.forge_db_path import checkpoint_wal as checkpoint  # noqa: PLC0415
    debut, essais, ck = horloge(), 0, {}
    while True:
        ck = checkpoint(SEUIL_REGULATION_MO, truncate=False, attente_s=2.0)
        d = decision_regulation(ck)
        attente = horloge() - debut
        if d in ("CONTINUER", "INCONNU"):
            return {"etat": "LIBRE" if d == "CONTINUER" else "INCONNU", "essais": essais,
                    "attente_s": round(attente, 1), "ck": ck}
        if attente >= ATTENTE_REPERE_MAX_S:
            return {"etat": "GEL_PERSISTANT", "essais": essais, "attente_s": round(attente, 1),
                    "ck": ck}
        essais += 1
        dormir(PAS_REPERE_S)


def _rendre_wal(checkpoint=None) -> dict:
    """Checkpoint entre depots : TRUNCATE au-dela du seuil, sinon rien a faire.

    `busy=1` reste l'abstention normale (un lecteur tient la base) : le depot
    suivant reessaiera. Le garde disque, lui, lit l'espace APRES ce rendu.
    """
    if checkpoint is not None:          # injection (NR)
        return checkpoint(SEUIL_WAL_TRUNCATE_MO, truncate=True,
                          attente_s=ATTENTE_TRUNCATE_S)
    from app.forge_db_path import checkpoint_wal  # noqa: PLC0415
    return checkpoint_wal(SEUIL_WAL_TRUNCATE_MO, truncate=True,
                          attente_s=ATTENTE_TRUNCATE_S)


def _sections_dump(chemin):
    """Sections (en-tete, corps) d'un dump PRODUIT PAR CE MODULE, en flux.

    Format : `<nom>/<chemin>\\n<texte>` separees par une ligne SEPARATOR. On ne passe
    PAS par `_source_de_section` (ingestion) : elle ne reconnait un chemin qu'a son
    extension et perdrait `Makefile`, `LICENSE`... — ici l'en-tete EST toujours le chemin.
    """
    with open(chemin, encoding="utf-8", errors="replace") as fh:
        tete, corps = None, []
        for ligne in fh:
            if ligne.rstrip("\r\n") == SEPARATOR:
                if tete is not None:
                    yield tete, "".join(corps).rstrip("\n")
                tete, corps = None, []
                continue
            if tete is None:
                if ligne.strip():
                    tete = ligne.strip()
                continue
            corps.append(ligne)
        if tete is not None:
            yield tete, "".join(corps).rstrip("\n")


def _sha256_fichier(chemin) -> str:
    from nokido_agent.app.forge_utils import sha256_fichier  # noqa: PLC0415 -- corps partage (cliquet clones, 26/09)

    return sha256_fichier(chemin)


def refiltrer_dump_local(source: Path, sortie_dir: Path) -> dict:
    """Rejoue le filtre COURANT (v3 : substance + resumes) sur un dump existant.

    Decision owner 2026-09-23 : ne pas re-cloner ~340 depots pour rejouer un filtre
    deterministe sur des donnees deja presentes. La SOURCE n'est jamais modifiee ; la
    sortie porte un manifeste tracable (source, sha256, version de filtre d'origine).
    """
    man_src = json.loads(chemin_manifeste(source).read_text(encoding="utf-8"))
    out = Path(sortie_dir) / source.name
    sha = _sha256_fichier(source)
    stats = {"examines": 0, "gardes": 0, "resumes": 0, "autolance": 0, "genere": 0}
    ecrivain = EcrivainAtomique(out)
    try:
        premiere = True
        for tete, corps in _sections_dump(source):
            rel = tete.split("/", 1)[1] if "/" in tete else tete
            if rel != "_PROVENANCE":
                stats["examines"] += 1
                if est_autolance(rel, corps)[0]:
                    stats["autolance"] += 1
                    continue
                if est_genere(rel, corps)[0]:
                    stats["genere"] += 1
                    continue
                hs, motif = est_hors_substance(rel, len(corps.encode("utf-8")))
                if hs:
                    corps = resume_hors_substance(rel, corps, motif)
                    stats["resumes"] += 1
                else:
                    stats["gardes"] += 1
            ecrivain.write(("" if premiere else "\n" + SEPARATOR + "\n") + tete + "\n" + corps)
            premiere = False
        ecrivain.valider()
    finally:
        ecrivain.abandonner()
    man = {k: man_src.get(k) for k in ("repo", "url", "target_id", "commit")}
    man.update({
        "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "filtre_version": FILTRE_VERSION,
        "fichiers_retenus": stats["gardes"] + stats["resumes"],
        "fichiers_candidats": stats["examines"],
        "refus": {"autolance": stats["autolance"], "genere": stats["genere"],
                  "hors_substance_resume": stats["resumes"]},
        "refiltre_local": {"source_dump": str(source), "source_sha256": sha,
                           "source_filtre_version": str(man_src.get("filtre_version"))},
    })
    ecrire_atomique(chemin_manifeste(out), json.dumps(man, ensure_ascii=False, indent=1))
    return stats


def refiltrer_dossier_local(source_dir, sortie_dir, exclus=()) -> dict:
    """Re-filtre tous les dumps d'un dossier. Idempotent (meme source -> saute) ; un dump
    sans manifeste n'est PAS re-filtre (provenance inconnue) : il est COMPTE."""
    # Un chemin RELATIF se lit depuis la racine du depot, pas depuis le cwd du job :
    # `run_job` decoupe script_args sur les espaces, et la racine en contient.
    # Mesure 2026-09-23 : `E:\nokido...` passe par script_args a perdu sa barre
    # (`\n`) -> `E:nokido...`, chemin RELATIF AU LECTEUR (depend du repertoire courant
    # de E:). Il a ete ecrit tel quel dans 210 manifestes : provenance non
    # reproductible. Ambigu = refuse ; tout chemin enregistre est ABSOLU.
    for p in (Path(source_dir), Path(sortie_dir)):
        if p.drive and not p.root:
            raise ValueError("chemin relatif au lecteur, ambigu : %s -- ecrire %s/..."
                             % (p, p.drive))
    source_dir, sortie_dir = ((p if p.is_absolute() else ROOT / p).resolve()
                              for p in (Path(source_dir), Path(sortie_dir)))
    # Mesure 2026-09-23 : une source MAL ORTHOGRAPHIEE rendait un bilan a zero et rc=0
    # -- un silence lu comme un succes vide. Une source absente est une ERREUR, levee
    # AVANT de creer la sortie (sinon un dossier vide temoigne d'un travail fantome).
    if not source_dir.is_dir():
        raise FileNotFoundError("source de re-filtrage introuvable : %s" % source_dir)
    sortie_dir.mkdir(parents=True, exist_ok=True)
    bilan = {"source": str(source_dir), "sortie": str(sortie_dir), "dumps_vus": 0,
             "dumps_refiltres": 0, "deja_faits": 0, "sans_manifeste": 0, "exclus": 0,
             "erreurs": 0, "fichiers_examines": 0, "gardes": 0, "resumes": 0,
             "autolance": 0, "genere": 0, "par_version_source": {}}
    for src in sorted(source_dir.glob("gitingest_veille_*.txt")):
        bilan["dumps_vus"] += 1
        nom = src.name[len("gitingest_veille_"):-len(".txt")]
        if nom in exclus:
            bilan["exclus"] += 1
            continue
        if not chemin_manifeste(src).exists():
            bilan["sans_manifeste"] += 1
            print("[refiltre] %s : SANS manifeste, NON re-filtre" % src.name, flush=True)
            continue
        out_man = chemin_manifeste(sortie_dir / src.name)
        try:
            if out_man.exists():
                deja = json.loads(out_man.read_text(encoding="utf-8")).get("refiltre_local") or {}
                if deja.get("source_sha256") == _sha256_fichier(src):
                    bilan["deja_faits"] += 1
                    continue
                if deja.get("source_dump") and Path(deja["source_dump"]) != src:
                    # Une sortie issue d'une AUTRE source (ex. v2 recent sur E: vs v1 de docs/)
                    # n'est jamais ecrasee en silence : conflit COMPTE et NOMME.
                    bilan["conflit_source"] = bilan.get("conflit_source", 0) + 1
                    print("[refiltre] %s : CONFLIT, deja produit depuis %s -- non ecrase"
                          % (src.name, deja["source_dump"]), flush=True)
                    continue
            version = str(json.loads(chemin_manifeste(src).read_text(encoding="utf-8"))
                          .get("filtre_version"))
            s = refiltrer_dump_local(src, sortie_dir)
        except Exception as exc:  # noqa: BLE001
            bilan["erreurs"] += 1
            print("[refiltre] %s : ERREUR %s %s" % (src.name, type(exc).__name__, exc), flush=True)
            continue
        bilan["dumps_refiltres"] += 1
        bilan["par_version_source"][version] = bilan["par_version_source"].get(version, 0) + 1
        bilan["fichiers_examines"] += s["examines"]
        for k in ("gardes", "resumes", "autolance", "genere"):
            bilan[k] += s[k]
        print("[refiltre] %s (source v%s) : %d examines, %d gardes, %d resumes, %d autolance"
              % (src.name, version, s["examines"], s["gardes"], s["resumes"], s["autolance"]),
              flush=True)
    return bilan


def _refus_ingestion(chemin, scanner=None) -> str:
    """Motif de refus d'un dump avant ingestion RAG, ou '' s'il peut entrer.

    Deux controles independants (une sonde unique ne decide pas) : les marqueurs
    du ver dans le TEXTE, puis Defender sur le FICHIER. Le moindre doute refuse.
    """
    # EN FLUX : lire le dump entier ici a fait tuer l'ingestion a 7 577 Mo sur un
    # dump de ~950 Mo (2026-09-23). Fenetre de DEUX lignes : un marqueur JSON peut
    # etre coupe (`"runOn":` / `"folderOpen"`).
    trouves = set()
    try:
        with open(chemin, encoding="utf-8", errors="replace") as fh:
            precedente = ""
            for ligne in fh:
                trouves.update(marqueurs_ver(precedente + ligne))
                precedente = ligne
    except OSError as exc:
        return "dump illisible (%s)" % type(exc).__name__
    trouves = sorted(trouves)
    if trouves:
        return "marqueur du ver : %s" % ", ".join(trouves)
    etat, detail = (scanner or _scan_defender)(chemin)
    if etat != "PROPRE":
        return "Defender %s %s" % (etat, detail)
    return ""


def seuil_disque_go() -> float:
    """Espace libre minimal (Go) sur le volume de la base RAG. Decision owner 2026-09-23 : 30."""
    try:
        return float(os.environ.get("NOKIDO_VEILLE_DISQUE_MIN_GO", "30"))
    except ValueError:
        return 30.0


def _libre_go(chemin):
    """Go libres sur le volume REEL de `chemin` (jonction RAG/ -> V: resolue) ; None = illisible."""
    try:
        return shutil.disk_usage(str(Path(chemin).resolve())).free / 2 ** 30
    except OSError:
        return None


def _ceder_la_priorite(proc=None) -> dict:
    """Priorite I/O BASSE + CPU sous la normale : le job de veille CEDE le disque.

    Mesure 2026-09-23 (owner) : « NVMe a 100 % ». V: est un volume virtuel sur le
    NVMe systeme : une ingestion a pleine priorite prend le disque a tout le poste.
    Une campagne de fond n'a pas a etre rapide ; elle doit ne gener personne.
    """
    try:
        import psutil  # noqa: PLC0415
        p = proc or psutil.Process()
        if os.name == "nt":
            p.ionice(psutil.IOPRIO_LOW)
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:
            p.ionice(psutil.IOPRIO_CLASS_IDLE)
            p.nice(10)
        etat = {"ok": True, "ionice": str(p.ionice()), "nice": str(p.nice())}
        if proc is None:
            etat["memoire"] = priorite_memoire(MEMORY_PRIORITY_LOW)
    except Exception as exc:  # noqa: BLE001
        etat = {"ok": False, "raison": "%s: %s" % (type(exc).__name__, exc)}
    print("[priorite] %s" % etat, flush=True)
    return etat


# PRIORITE MEMOIRE (veille RAM prioritaire owner 2026-09-23, doc Microsoft
# SetProcessInformation / MEMORY_PRIORITY_INFORMATION ingeree ce jour) : les
# pages d'un processus de basse priorite quittent la RAM EN PREMIER sous pression
# — le pendant memoire de IOPRIO_LOW. Le poste interactif garde sa RAM.
PROCESS_MEMORY_PRIORITY = 0          # PROCESS_INFORMATION_CLASS.ProcessMemoryPriority
MEMORY_PRIORITY_LOW = 2
MEMORY_PRIORITY_NORMAL = 5


def priorite_memoire(niveau: int) -> str:
    """Pose la priorite memoire du processus COURANT (Windows). Rend l'issue DITE."""
    if os.name != "nt":
        return "sans objet hors Windows"
    try:
        import ctypes  # noqa: PLC0415

        class _MPI(ctypes.Structure):
            _fields_ = [("MemoryPriority", ctypes.c_ulong)]

        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        info = _MPI(niveau)
        ok = k32.SetProcessInformation(ctypes.c_void_p(k32.GetCurrentProcess()),
                                       PROCESS_MEMORY_PRIORITY, ctypes.byref(info),
                                       ctypes.sizeof(info))
        return "ok niveau %d" % niveau if ok else "refus (GetLastError=%d)" % k32.GetLastError()
    except Exception as exc:  # noqa: BLE001
        return "ILLISIBLE (%s)" % type(exc).__name__


BESOIN_RAM_GO = 4.0


def _declarer_besoin_ram(demander=None) -> dict:
    """`request_resources(BESOIN_RAM_GO, allow_evict=True)` ; le verdict est DIT.

    Un refus (`ok=False`) n'arrete pas le job : les caps RSS et la regulation
    restent les gardes ; on ne fait que ne plus attendre en silence."""
    try:
        if demander is None:
            from nokido_agent.app.forge_resource_manager import (  # noqa: PLC0415
                request_resources as demander)
        verdict = demander(BESOIN_RAM_GO, allow_evict=True)
    except Exception as exc:  # noqa: BLE001
        verdict = {"ok": None, "raison": "regulation injoignable (%s)" % type(exc).__name__}
    print("[ram] besoin %.1f Go declare : %s" % (BESOIN_RAM_GO, verdict), flush=True)
    return verdict


class DisqueSature(RuntimeError):
    """Le volume de la base passe sous le seuil PENDANT l'ingestion d'un depot."""


def _garde_pendant_ingestion(checkpoint=None, refus=None) -> None:
    """Appele tous les N chunks DANS un depot : rend le WAL, puis verifie le disque.

    Mesure 2026-09-23 : V: est passe de 53 a 4,1 Go libres PENDANT un seul dump
    (~950 Mo) ; garde et TRUNCATE n'agissaient qu'entre deux depots. Leve
    `DisqueSature` pour un arret propre (rc=5) au lieu d'un volume sature.
    """
    _rendre_wal(checkpoint)
    motif = (refus or _disque_refuse)(DB_PATH.parent)
    if motif:
        raise DisqueSature(motif)


def _disque_refuse(chemin) -> str:
    """Motif d'arret, ou '' si l'ingestion peut continuer.

    Incident du 2026-09-01 : WAL a 53 Go, V: sature, `disk I/O error` sur toute
    ecriture RAG. Le checkpoint entre depots borne le WAL, pas la croissance de
    la base. Un volume illisible n'est PAS un volume libre (UNKNOWN != NO).
    """
    seuil = seuil_disque_go()
    libre = _libre_go(chemin)
    if libre is None:
        return "espace libre ILLISIBLE sur le volume de %s (seuil %.0f Go)" % (chemin, seuil)
    if libre < seuil:
        return "%.1f Go libres < seuil %.0f Go sur le volume de %s" % (libre, seuil, chemin)
    return ""


def main() -> int:
    try:
        # line_buffering : sous run_job, stdout est un FICHIER, donc tamponne par
        # blocs. Mesure 2026-09-23 : journal muet 15 min pendant que 14 dumps
        # s'ecrivaient -> le moniteur a crie FIGE sur un job vivant.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:  # muet-ok
        pass
    global FORCE
    args = sys.argv[1:]
    FORCE = "--force" in args
    # Le CLONE exige un compte qui atteigne GitHub ; l'INGESTION est purement
    # locale mais longue. Mesure 2026-08-30 : sous `run_job`, meme avec le
    # drapeau reseau, le clone ne demarre pas (dossier cree, 0 fichier, 19 min),
    # alors que le MEME clone aboutit en 1,58 s sous `trusted_script`. Separer
    # les deux phases est donc le seul montage qui marche : dump en trusted,
    # ingestion en job detache.
    dump_only = "--dump-only" in args
    # AUTOREGULATION (owner 2026-09-23) : DECLARER le besoin au corps, jamais
    # attendre qu'un operateur libere la RAM. L'echelle gouvernee rend d'abord
    # les caches, puis les charges evincables ; jamais un pilier sain.
    _declarer_besoin_ram()
    _ceder_la_priorite()
    if "--refiltrer-local" in args:
        # Owner 2026-09-23 : rejouer le filtre v3 sur les dumps existants, sans re-cloner.
        i = args.index("--refiltrer-local")
        exclus = {s.strip() for s in (_valeur(args, "--exclure") or "").split(",") if s.strip()}
        b = refiltrer_dossier_local(Path(args[i + 1]), Path(args[i + 2]), exclus)
        print("BILAN_REFILTRE", json.dumps(b, ensure_ascii=False), flush=True)
        if b["erreurs"]:
            return 4
        # Aucun dump VU n'est pas un succes : c'est une source vide ou mauvaise, on le DIT.
        return 3 if not b["dumps_vus"] else 0
    ingest_only = "--ingest-only" in args

    try:
        cibles = charger_cibles(_valeur(args, "--registre"),
                                allow_legacy="--allow-legacy" in args)
    except RegistreInvalide as exc:
        print("ARRET : %s\nAucun repli implicite. `--allow-legacy` donne les %d "
              "depots historiques — ce n'est PAS la campagne complete."
              % (exc, len(REPOS)), flush=True)
        return 2

    # La generation se RECALCULE depuis les cibles chargees : meme fonction que
    # celle du registre, donc meme resultat. Pas de valeur transportee a la main
    # qu'on pourrait oublier de mettre a jour.
    generation = calcul_generation_id(cibles)
    attendue = _valeur(args, "--generation")
    if attendue and attendue != generation:
        print("ARRET : registre en generation %s, campagne attendue %s."
              % (generation, attendue), flush=True)
        return 2

    ordre_fige = None
    campagne = _valeur(args, "--campagne")
    if campagne:
        base = sorted(cibles, key=lambda s: cibles[s]["ordinal"])
        try:
            ordre_fige = snapshot_campagne(campagne, base, generation,
                                           "--rebase-campagne" in args)
        except RegistreInvalide as exc:
            print("ARRET : %s" % exc, flush=True)
            return 2

    try:
        names = selectionner(cibles, args, ordre_fige=ordre_fige)
    except CibleInconnue as exc:
        print("ARRET : %s" % exc, flush=True)
        return 2

    print("=== Veille clone+ingest : %d cible(s) sur %d, generation %s "
          "(dump_only=%s ingest_only=%s) ==="
          % (len(names), len(cibles), generation, dump_only, ingest_only))
    dumped = []
    recensement = {READY: 0, STALE: 0, ABSENT: 0}
    allow_stale = "--allow-stale" in args
    for n in names:
        cible = cibles[n]
        if ingest_only:
            chemin = _chemin_dump(cible["nom_dump"])
            etat, raison = etat_dump(chemin, cible, FILTRE_VERSION)
            recensement[etat] += 1
            if etat == READY or (etat == STALE and allow_stale):
                dumped.append(chemin)
                if etat != READY:
                    print("[%s] PERIME ingere sur demande explicite (%s)"
                          % (n, raison))
            else:
                # Ni ingere, ni compte comme succes : c'est le point 9.
                print("[%s] %s — NON ingere (%s)" % (n, etat, raison))
            continue
        p = dump_repo(cible)
        if p:
            dumped.append(p)
    manque = recensement[STALE] + recensement[ABSENT]
    if ingest_only:
        print("=== dumps : READY %d | PERIME %d | ABSENT %d ==="
              % (recensement[READY], recensement[STALE], recensement[ABSENT]))

    if dump_only:
        print(f"=== dumps produits : {len(dumped)}/{len(names)} "
              f"(ingestion NON faite : relancer avec --ingest-only) ===")
        return 0 if dumped else 1

    if not dumped:
        print("Aucun dump produit.")
        # 4 = des cibles DEMANDEES n'ont pas ete servies (perimees ou absentes) ;
        # 1 = rien a faire. Les confondre ferait passer une campagne incomplete
        # pour un simple coup dans le vide.
        return 4 if manque else 1

    # Garde disque AVANT toute ouverture en ecriture de la base (rc=5 distinct).
    refus = _disque_refuse(DB_PATH.parent)
    if refus:
        print("=== ARRET avant ingestion : %s — 0 depot ingere ===" % refus, flush=True)
        return 5

    # Ingest RAG via la fonction existante (réutilise, pas réécrit)
    from nokido_agent.tools.forge_gitingest_sdk_ingest import ingest_file

    # `sqlite3.connect()` nu ouvre une transaction IMPLICITE au premier INSERT et
    # tient le verrou d'ecriture pendant TOUTE la boucle. Mesure 2026-08-30 :
    # l'ingestion de codex sans limite (66,9 Mo) est morte sur
    # `OperationalError: database is locked` -- exactement le cas que
    # `forge_db_path` documente, et dont le message d'erreur dit « chercher un
    # sqlite3.connect() nu chez l'ecrivain concurrent ». C'etait ici.
    # `open_writer` = autocommit + WAL + busy_timeout ; `write_retry` reprend sur
    # verrou avec recul et jitter. La reprise est SANS RISQUE de doublon :
    # `ingest_file` calcule chunk_id = sha256(source+chunk) et fait
    # INSERT OR IGNORE, donc un rejeu ne fait que gonfler le compteur `skip`.
    sys.path.insert(0, str(ROOT))
    from app.forge_db_path import checkpoint_wal, open_writer, write_retry

    conn = open_writer()
    try:
        conn.execute("ALTER TABLE rag_chunks ADD COLUMN created_at INTEGER")
    except sqlite3.OperationalError:  # muet-ok : colonne deja presente
        pass
    finally:
        conn.close()

    tot_in = tot_skip = 0
    refuses_secu = verrous = 0
    for i_p, p in enumerate(dumped):
        refus = _disque_refuse(DB_PATH.parent)
        if refus:
            print("=== ARRET : %s — %d/%d depot(s) ingere(s), +%d chunks ; le reste "
                  "N'EST PAS ingere ===" % (refus, i_p, len(dumped), tot_in), flush=True)
            return 5
        # POINT DE PASSAGE UNIQUE vers le RAG, quel que soit le chemin (--ingest-only
        # ou clone+ingest) : aucun dump n'y entre sans le controle securite.
        refus_secu = _refus_ingestion(p)
        if refus_secu:
            refuses_secu += 1
            print("  REFUSE a l'ingestion (securite) %s : %s" % (p.name, refus_secu),
                  flush=True)
            continue
        try:
            ins, skip = write_retry(lambda c, _p=p: ingest_file(
                _p, c, pendant=_garde_pendant_ingestion))
        except sqlite3.OperationalError as exc:
            # Un VERROU sur un depot ne tue plus la campagne : ce depot n'est pas
            # servi (reprise sans doublon plus tard), les suivants continuent.
            verrous += 1
            print("  VERROU sur %s, NON ingere cette passe : %s"
                  % (p.name, str(exc)[:120]), flush=True)
            continue
        except DisqueSature as exc:
            print("=== ARRET PENDANT %s : %s — %d/%d depot(s) complets, +%d chunks ; "
                  "ce depot est PARTIEL (la reprise complete sans doublon), le reste "
                  "N'EST PAS ingere ===" % (p.name, exc, i_p, len(dumped), tot_in),
                  flush=True)
            return 5
        tot_in += ins
        tot_skip += skip
        print(f"  ingest {p.name}: +{ins} chunks, {skip} skip")
        # Rendre la main au disque ENTRE deux depots. Sans cela le WAL ne
        # redescend jamais : le 2026-09-01, une campagne a 408 325 chunks l'a
        # porte a 53 Go et sature V:, jusqu'a `disk I/O error` sur toute ecriture
        # RAG. `busy=1` ici n'est pas un echec, c'est un lecteur qu'on refuse de
        # bloquer — on reessaiera au depot suivant.
        ck = _rendre_wal()
        if ck.get("fait"):
            print("     WAL {wal_mo_avant} -> {wal_mo_apres} Mo (busy={busy})"
                  .format(**ck), flush=True)
        reg = _reguler_wal()
        if reg["essais"] or reg["etat"] != "LIBRE":
            c = reg["ck"]
            print("     REGULATION WAL : %s apres %.0f s (%d attente(s)) ; wal=%s Mo pages=%s "
                  "reversees=%s" % (reg["etat"], reg["attente_s"], reg["essais"],
                                    c.get("wal_mo_avant", c.get("wal_mo")), c.get("pages"),
                                    c.get("verses")), flush=True)
        if reg["etat"] == "GEL_PERSISTANT":
            print("=== ARRET : repere de checkpoint FIGE depuis %.0f s (lecteur long) — %d/%d "
                  "depot(s) ingere(s), +%d chunks ; on n'empile pas le WAL ===" %
                  (reg["attente_s"], i_p + 1, len(dumped), tot_in), flush=True)
            return 6
    print(f"=== RAG : +{tot_in} chunks (domain=sdk_gitingest), {tot_skip} skip ===")
    if verrous:
        print("=== %d depot(s) NON ingere(s) sur VERROU — relancer la passe ===" % verrous)
        return 4
    if refuses_secu:
        print("=== %d dump(s) REFUSE(S) pour raison de securite — campagne INCOMPLETE ==="
              % refuses_secu)
        return 4
    if manque:
        # Rendre 0 ici annoncerait une campagne complete alors que des cibles
        # demandees n'ont pas ete servies.
        print("=== %d cible(s) demandee(s) NON servie(s) — campagne INCOMPLETE ==="
              % manque)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
