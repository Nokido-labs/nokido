#!/usr/bin/env python3
"""forge_regression_sweep.py — les trois familles que la sentinelle d'ancres ne voit pas.

`forge_fix_sentinel` ne detecte qu'un identifiant DISPARU d'un `.py` encore
existant. Mesure du 2026-08-14 : cela laisse dehors 4 270 fichiers supprimes,
~3 000 touches non-Python, et toute regression qui ne deplace aucun symbole.
Ce balayage ouvre les trois familles manquantes.

AXE 1 — VALEUR ABAISSEE. Un garde ne meurt pas toujours par suppression : il
meurt aussi quand sa constante passe de 1800 a 300, ou quand son drapeau
bascule a False. Aucun symbole ne bouge, donc aucune sentinelle d'ancre ne
bronche. On lit les hunks : meme nom, valeur numerique en BAISSE (ou booleen
qui s'eteint), et on confronte a la valeur ACTUELLE — une baisse deja corrigee
depuis n'est pas une dette.

AXE 2 — CONFIG NON-PYTHON. `services.toml`, `.yml`, `.ps1`, `.bat`, `.ts` : un
service passe `enabled = false` est une capacite perdue, invisible a un
scanner Python. On suit les bascules vrai -> faux et les cles retirees.

AXE 3 — IMPORT ORPHELIN. 4 270 fichiers ont ete supprimes. Un `from forge_x
import y` qui survit a la suppression de `forge_x` est une panne DIFFEREE :
elle n'eclate qu'au premier appel du chemin concerne, souvent en production.

AXE 4 — BACKEND CABLE SUPPRIME. Un module LANCE, ROUTE ou ENREGISTRE dont le
`.py` a disparu, mais dont le nom reste cite dans le tree vivant. L'axe 3 ne le
voit pas : il n'inspecte que les imports prefixes `forge_`/`nokido`, alors que
`from recon_silo import ...` a survecu a la suppression de recon_silo.py sans
alerter une seule sentinelle. Capacite affichee, corps absent : la surface
parait vivante, elle est morte. C'est la famille qui a laisse partir les
backends CTF/recon sous un pretexte faux.

Aucun axe ne rend un verdict : chacun rend des CANDIDATS avec leur commit, car
une baisse de seuil peut etre un reglage assume. C'est au lecteur de trancher,
avec la piece au dossier.

Sortie : sandbox/regression_sweep.json + rapport lisible.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sandbox" / "regression_sweep.json"
DEPUIS = "2026-03-01"
LIMITE = 5000

# Noms qui designent un GARDE : leur affaiblissement est un fait notable.
MOTS_GARDE = ("REFRACTORY", "COOLDOWN", "TIMEOUT", "GRACE", "THRESHOLD", "CAP",
              "LIMIT", "BUDGET", "RETRY", "TTL", "INTERVAL", "MAX", "DELAY",
              "BACKOFF", "QUOTA", "GUARD", "STUCK")
MOTS_DRAPEAU = ("ENABLED", "AUTOLAUNCH", "ACTIVE", "ARMED", "STRICT", "ENFORCE")

_VAL = re.compile(r"^([-+])\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.+?)\s*(?:#.*)?$")
_NOMBRE = re.compile(r'(?:"|\')?(-?\d+(?:\.\d+)?)(?:"|\')?')
_CONF = re.compile(r"^([-+])\s*([\w.\-]+)\s*[:=]\s*(.+?)\s*(?:#.*)?$")
EXT_CONF = (".toml", ".yml", ".yaml", ".ps1", ".bat", ".cmd", ".ts", ".ini", ".cfg")
FAUX = {"false", "0", "no", "off", '"0"', "'0'", "disabled"}
VRAI = {"true", "1", "yes", "on", '"1"', "'1'", "enabled"}


def _git(*args: str, timeout: int = 180) -> str:
    r = subprocess.run(
        ["git", "-C", str(ROOT), "-c", "safe.directory=*", *args],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout,
    )
    return r.stdout or ""


def _nombre(txt: str) -> float | None:
    """Valeur numerique portee par la ligne, y compris via os.environ.get(...)."""
    m = _NOMBRE.search(txt)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _commits() -> list[dict]:
    brut = _git("log", f"--since={DEPUIS}", f"-n{LIMITE}",
                "--format=%H|%ad|%s", "--date=short").splitlines()
    out = []
    for l in brut:
        p = l.split("|", 2)
        if len(p) == 3:
            out.append({"sha": p[0], "date": p[1], "sujet": p[2]})
    return out


def axe_valeur_et_config(commits: list[dict]) -> tuple[list, list]:
    """Parcourt les diffs une seule fois pour les axes 1 et 2."""
    valeurs, configs = [], []
    for c in commits:
        diff = _git("show", c["sha"], "--unified=0", "--format=", "--",
                    "*.py", *(f"*{e}" for e in EXT_CONF))
        fichier, avant_v, avant_c = None, {}, {}
        for l in diff.splitlines():
            if l.startswith("+++ b/"):
                fichier = l[6:].strip()
                avant_v, avant_c = {}, {}
                continue
            if not fichier or l.startswith(("---", "+++")):
                continue
            py = fichier.endswith(".py")
            m = _VAL.match(l) if py else _CONF.match(l)
            if not m:
                continue
            signe, nom, val = m.group(1), m.group(2), m.group(3).strip()
            if signe == "-":
                (avant_v if py else avant_c)[nom] = val
                continue
            ancien = (avant_v if py else avant_c).get(nom)
            if ancien is None:
                continue
            if py:
                a, b = _nombre(ancien), _nombre(val)
                garde = any(w in nom for w in MOTS_GARDE)
                drapeau = any(w in nom for w in MOTS_DRAPEAU)
                if garde and a is not None and b is not None and b < a:
                    valeurs.append({"type": "SEUIL_ABAISSE", "fichier": fichier,
                                    "nom": nom, "avant": a, "apres": b,
                                    "sha": c["sha"][:8], "date": c["date"],
                                    "sujet": c["sujet"][:70]})
                elif drapeau and val.strip().lower() in FAUX \
                        and ancien.strip().lower() in VRAI:
                    valeurs.append({"type": "DRAPEAU_ETEINT", "fichier": fichier,
                                    "nom": nom, "avant": ancien, "apres": val,
                                    "sha": c["sha"][:8], "date": c["date"],
                                    "sujet": c["sujet"][:70]})
            else:
                # POLARITE : `disabled = true -> false` ACTIVE le service. Lire
                # la bascule sans regarder le sens de la cle faisait compter
                # deux reactivations comme des pertes de capacite (mesure 14/08).
                negative = any(m in nom.lower()
                               for m in ("disabled", "skip", "ignore", "off", "no_"))
                s_avant = ancien.strip().lower()
                s_apres = val.strip().lower()
                perdu = ((s_avant in VRAI and s_apres in FAUX) if not negative
                         else (s_avant in FAUX and s_apres in VRAI))
                if perdu:
                    configs.append({"type": "CONFIG_DESACTIVEE", "fichier": fichier,
                                    "cle": nom, "avant": ancien, "apres": val,
                                    "sha": c["sha"][:8], "date": c["date"],
                                    "sujet": c["sujet"][:70]})
    return valeurs, configs


def _valeur_actuelle(fichier: str, nom: str) -> str | None:
    p = ROOT / fichier
    if not p.exists():
        return None
    motif = re.compile(rf"^\s*{re.escape(nom)}\s*[:=]\s*(.+)$", re.M)
    m = motif.search(p.read_text(encoding="utf-8", errors="replace"))
    return m.group(1).strip() if m else None


def axe_imports_orphelins() -> list[dict]:
    """Imports internes pointant vers un module qui n'existe plus."""
    modules, fichiers = set(), []
    for zone in ("app", "tools", "forge_desktop"):
        for p in (ROOT / zone).glob("**/*.py"):
            if {"_attic", "node_modules", "backups", "archive"} & set(p.parts):
                continue
            modules.add(p.stem)
            fichiers.append(p)
    # Un module importable n'est pas toujours un `.py` a cote. Sans ces deux
    # familles l'axe denonce 35 imports parfaitement valides (mesure 14/08) :
    #   * les PACKAGES — `forge_desktop/__init__.py` s'importe `forge_desktop` ;
    #   * les EXTENSIONS NATIVES — `rust_ext/forge_bm25/.../forge_bm25.dll`.
    for init in ROOT.glob("*/__init__.py"):
        modules.add(init.parent.name)
    # Zones BORNEES : `ROOT.glob("**/*.dll")` traversait tout le depot — RAG,
    # .git, node_modules, cibles de compilation — pour trouver trois fichiers,
    # et faisait depasser le timeout de 30 s du test (mesure 2026-08-14). Les
    # extensions natives de ce depot vivent dans `rust_ext/`, les zones de code
    # ou a la racine ; chercher ailleurs coute cher et ne rapporte rien.
    for zone in ("rust_ext", "app", "tools", "forge_desktop"):
        for ext in ("*.dll", "*.pyd", "*.so"):
            for natif in (ROOT / zone).glob(f"**/{ext}"):
                modules.add(natif.stem.split(".")[0])
    for ext in ("*.dll", "*.pyd", "*.so"):
        for natif in ROOT.glob(ext):
            modules.add(natif.stem.split(".")[0])
    # Les BINAIRES ne sont pas versionnes : sur un clone frais (runner CI), la
    # DLL de `forge_bm25` n'existe pas et son import passait pour orphelin — la
    # CI GitHub echouait la ou le local passait, faute d'artefacts de build.
    # La SOURCE, elle, est dans le depot : un crate declare sous `rust_ext/` est
    # un module du projet, compile ou non.
    if (ROOT / "rust_ext").is_dir():
        for crate in (ROOT / "rust_ext").iterdir():
            if crate.is_dir():
                modules.add(crate.name)
    orphelins = []
    for p in fichiers:
        try:
            arbre = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):  # muet-ok : fichier illisible/non-parsable = hors scan
            continue
        # Un import DANS un `try/except` est une dependance OPTIONNELLE — la
        # convention Python pour « si c'est la, tant mieux ». `forge_auto_pilot`
        # importe ainsi `forge_desktop`, dossier volontairement gitignore : sur
        # un clone frais l'import echoue et le code l'a prevu (fire & forget).
        # Sans cette exclusion, la CI distante criait la ou le local se taisait.
        proteges = set()
        for n in ast.walk(arbre):
            if isinstance(n, ast.Try):
                for sub in ast.walk(n):
                    if isinstance(sub, (ast.Import, ast.ImportFrom)):
                        proteges.add(sub.lineno)
        for n in ast.walk(arbre):
            if getattr(n, "lineno", None) in proteges:
                continue
            cibles = []
            if isinstance(n, ast.Import):
                cibles = [a.name.split(".")[0] for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
                cibles = [n.module.split(".")[0]]
            for cible in cibles:
                # Seuls les modules INTERNES sont verifiables ici : une
                # dependance tierce absente est un probleme d'environnement,
                # pas une regression du depot.
                if not (cible.startswith("forge_") or cible.startswith("nokido")):
                    continue
                if cible not in modules:
                    orphelins.append({
                        "fichier": str(p.relative_to(ROOT)).replace("\\", "/"),
                        "ligne": n.lineno, "importe": cible})
    return orphelins


# Un BACKEND se reconnait a ce qu'on le LANCE, le ROUTE ou l'ENREGISTRE — pas
# n'importe quel helper supprime. Ces familles bornent la chasse aux modules
# dont la disparition casse une capacite affichee, sans noyer le rapport sous
# les `utils.py` sans consequence.
BACKEND_PREFIXES = ("forge_", "nokido", "recon", "ctf", "exegol", "redteam",
                    "pentest", "netcfg", "muscle", "cervelet", "silo")
BACKEND_SUFFIXES = ("_silo", "_master", "_runner", "_bridge", "_agent",
                    "_server", "_supervisor", "_engine", "_manager",
                    "_orchestrator", "_daemon", "_plugin", "_handler",
                    "_worker", "_mcp", "_dispatcher", "_proxy")
GENERIQUE_EXCLUS = {"utils", "config", "main", "setup", "conftest", "__init__",
                    "constants", "helpers", "common", "base", "types",
                    "schema", "models", "__main__"}


def _kind_cablage(ligne: str, stem: str, nom_fichier: str) -> str:
    """Nature du lien qui cite un module absent : plus il est structurel
    (import, lancement, route, registre), plus la disparition est grave. Un
    commentaire ne cable rien — il ne compte pas comme une capacite vivante."""
    if ligne.lstrip().startswith("#"):
        return "COMMENT"
    s = re.escape(stem)
    if (re.search(r"(?:^|[^\w.])(?:from|import)\s+" + s + r"\b", ligne)
            or re.search(r"(?:import_module|__import__)\(\s*[\"']" + s + r"[\"']", ligne)):
        return "IMPORT"
    bas = ligne.lower()
    fbas = nom_fichier.lower()
    if ("modulespec" in bas or "subprocess" in bas or "popen" in bas
            or "spawn" in bas or "launch" in bas or "launcher" in fbas
            or fbas.endswith((".toml", ".ps1", ".bat", ".cmd", ".ini", ".cfg"))):
        return "LAUNCHER"
    if (re.search(r"@\w+\.(?:get|post|put|delete|route|websocket)", ligne)
            or "add_route" in bas or "proxy" in bas or "mount(" in bas):
        return "ROUTE"
    if "register" in bas or "surfaces" in bas or "add_tool" in bas:
        return "REGISTRY"
    return "MENTION"


def axe_backends_supprimes() -> list[dict]:
    """AXE 4 — backend dont le fichier est SUPPRIME mais dont le nom reste
    cable dans le tree vivant. Angle mort des axes 1-3 : l'axe 3 n'inspecte que
    les imports prefixes `forge_`/`nokido`, or `from recon_silo import ...` a
    survecu a la suppression de recon_silo.py sans declencher de sentinelle."""
    brut = _git("log", "--all", "--diff-filter=D", "--name-only",
                "--format=COMMIT|%H|%ad|%s", "--date=short").splitlines()
    supprime: dict[str, dict] = {}
    cur = None
    for l in brut:
        if l.startswith("COMMIT|"):
            p = l.split("|", 3)
            cur = (p[1][:8], p[2], p[3][:70]) if len(p) == 4 else None
            continue
        if cur is None or not l.strip() or not l.strip().endswith(".py"):
            continue
        parts = [x for x in re.split(r"[\\/]+", l.strip()) if x]
        if {"_attic", "node_modules", "backups", "archive", ".git",
                "sandbox", "test", "tests"} & set(parts):
            continue
        stem = parts[-1][:-3]
        if (stem in supprime or stem in GENERIQUE_EXCLUS
                or stem.startswith("test_")):
            continue                    # git log = recent d'abord : garder le 1er
        if not (stem.startswith(BACKEND_PREFIXES)
                or stem.endswith(BACKEND_SUFFIXES)):
            continue
        supprime[stem] = {"sha": cur[0], "date": cur[1], "sujet": cur[2],
                          "chemin": l.strip()}
    if not supprime:
        return []

    # Corpus vivant : fichiers a fouiller + stems encore presents. Un module
    # dont le .py existe TOUJOURS est deplace/re-cree, pas perdu — recon_master,
    # forge_ctf_runner, forge_exegol_bridge existent, ils ne comptent pas.
    # EXISTENCE — repo-wide mais NOMS seulement (aucune lecture) : un module vit
    # peut-etre hors des zones canoniques (le package racine `ctf/` p.ex.) ; ne
    # chercher que dans app/tools ferait passer forge_exegol_bridge — bien vivant
    # sous ctf/ — pour supprime (faux positif paye le 2026-08-15).
    IGNORE_DIRS = {".git", "node_modules", "_attic", "backups", "archive",
                   "sandbox", "__pycache__", ".venv", "venv", "target", "rag",
                   "RAG", ".pytest_cache", "site-packages", ".mypy_cache", "dist"}
    stems_vivants = set()
    for base, dirs, fichiers in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        b = Path(base)
        if (b / "__init__.py").exists():
            stems_vivants.add(b.name)
        for f in fichiers:
            if f.endswith(".py"):
                stems_vivants.add(f[:-3])
    # RECHERCHE — zones de CABLAGE bornees : lire tout le depot stalle (mesure
    # 2026-08-15). Le cablage central vit dans le code applicatif, les organes de
    # domaine et la config racine ; y chercher suffit et reste rapide.
    vivants = []
    for zone in ("app", "tools", "forge_desktop", "ctf", "recon", "recon_silo",
                 "redteam", "netcfg", "config", "scripts", "services"):
        base = ROOT / zone
        if not base.is_dir():
            continue
        for p in base.glob("**/*.py"):
            if not ({"_attic", "node_modules", "backups", "archive"} & set(p.parts)):
                vivants.append(p)
        for ext in EXT_CONF:
            vivants.extend(base.glob(f"**/*{ext}"))
    for ext in EXT_CONF:
        vivants.extend(ROOT.glob(f"*{ext}"))

    absents = {s: m for s, m in supprime.items() if s not in stems_vivants}
    if not absents:
        return []

    # Alternation longue-d'abord : `recon_silo` avant `recon` pour ne pas
    # capturer un prefixe a la place du module. Bornes de mot strictes : dans
    # `_recon_silo_plugin`, le `_` en tete interdit le match (pas le module).
    noms = sorted(absents, key=len, reverse=True)
    motif = re.compile(r"(?<![\w])(" + "|".join(re.escape(s) for s in noms)
                       + r")(?![\w])")
    trouve: dict[str, list] = {}
    for p in vivants:
        try:
            if p.stat().st_size > 1_500_000:        # fichier genere geant : passe
                continue
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:  # muet-ok : fichier illisible = simplement ignore du scan
            continue
        if not any(s in txt for s in absents):      # rejet rapide par fichier
            continue
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        for i, ligne in enumerate(txt.splitlines(), 1):
            for m in motif.finditer(ligne):
                stem = m.group(1)
                if p.stem == stem:                  # shim auto-referent
                    continue
                trouve.setdefault(stem, []).append({
                    "kind": _kind_cablage(ligne, stem, p.name),
                    "fichier": rel, "ligne": i,
                    "extrait": ligne.strip()[:110]})

    FORTS = ("IMPORT", "LAUNCHER", "ROUTE", "REGISTRY")
    rang = {k: i for i, k in enumerate(FORTS)}
    out = []
    for stem, meta in absents.items():
        forts = [r for r in trouve.get(stem, []) if r["kind"] in FORTS]
        if not forts:
            continue                    # cite nulle part de structurel = pas cable
        forts.sort(key=lambda r: rang[r["kind"]])
        out.append({"module": stem, "type": "BACKEND_CABLE_SUPPRIME",
                    "supprime_par": {"sha": meta["sha"], "date": meta["date"],
                                     "sujet": meta["sujet"]},
                    "chemin_supprime": meta["chemin"],
                    "kind_fort": forts[0]["kind"], "cablages": forts[:5]})
    out.sort(key=lambda b: rang[b["kind_fort"]])
    return out


def main() -> int:
    commits = _commits()
    print(f"[sweep] {len(commits)} commits depuis {DEPUIS}", flush=True)

    orphelins = axe_imports_orphelins()
    print(f"[sweep] axe 3 — imports orphelins : {len(orphelins)}", flush=True)

    backends = axe_backends_supprimes()
    print(f"[sweep] axe 4 — backends cables supprimes : {len(backends)}", flush=True)

    valeurs, configs = axe_valeur_et_config(commits)
    # Une baisse deja rattrapee depuis n'est pas une dette : on confronte a
    # l'etat ACTUEL, sinon on ressort des incidents clos comme s'ils vivaient.
    persistants = []
    for v in valeurs:
        actuel = _valeur_actuelle(v["fichier"], v["nom"])
        v["actuel"] = actuel
        n = _nombre(actuel or "")
        if v["type"] == "SEUIL_ABAISSE" and n is not None and n >= v["avant"]:
            continue                     # remonte depuis
        if actuel is None:
            continue                     # symbole parti : c'est l'affaire de fix_sentinel
        persistants.append(v)

    res = {"commits": len(commits), "orphelins": orphelins,
           "backends_supprimes": backends,
           "valeurs_persistantes": persistants, "valeurs_brutes": len(valeurs),
           "configs": configs}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[sweep] axe 1 — valeurs affaiblies : {len(valeurs)} vues, "
          f"{len(persistants)} ENCORE en vigueur", flush=True)
    for v in persistants[:25]:
        print(f"    {v['type']:16s} {v['fichier']}:{v['nom']} "
              f"{v['avant']} -> {v['apres']} (actuel {v['actuel']}) "
              f"[{v['sha']} {v['date']}] {v['sujet']}", flush=True)
    print(f"[sweep] axe 2 — config desactivee : {len(configs)}", flush=True)
    for c in configs[:25]:
        print(f"    {c['fichier']}:{c['cle']} {c['avant']} -> {c['apres']} "
              f"[{c['sha']} {c['date']}] {c['sujet']}", flush=True)
    for o in orphelins[:25]:
        print(f"    ORPHELIN {o['fichier']}:{o['ligne']} importe '{o['importe']}'",
              flush=True)
    for b in backends[:25]:
        r = b["cablages"][0]
        print(f"    BACKEND {b['module']} supprime "
              f"[{b['supprime_par']['sha']} {b['supprime_par']['date']}] "
              f"{b['supprime_par']['sujet']} -> {b['kind_fort']} "
              f"{r['fichier']}:{r['ligne']}", flush=True)
    print(f"[sweep] -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
