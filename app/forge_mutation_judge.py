#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LE JUGE des mutations — le milieu implacable, sans lequel l'arbre ne vaut rien.

Ce module vient AVANT toute generation de variantes, et c'est un choix d'ordre motive.
Ce qui rend la methode DeepMind eprouvee n'est pas l'arbre, c'est le JUGE : AlphaZero a
les regles du go, AlphaCode des tests unitaires, AlphaProof le compilateur Lean. Le
filtrage est impitoyable PARCE QUE le verdict est incontestable. Un arbre geant filtre
par un juge faible ne produit pas de l'innovation, il produit du Goodhart a l'echelle --
mille remedes optimises pour tromper la metrique qui les mesure.

## Deux etages, parce que la cellule WASM ne peut pas tout juger (MESURE 2026-07-30)

Interroge, le bac a sable Pyodide rend : `ast` OUI, `unittest` OUI, `compile`/`exec` OUI
(il a calcule 42), mais `sqlite3` NON, `psutil` NON, acces au depot NON. Donc :

  ETAGE CELLULE  — code PUR (algorithme, fonction sans entree/sortie). Juge dans la
      sandbox WASM, avec apoptose reelle : une variante qui part en boucle sans fin est
      detruite a son budget et l'organe survit (mesure : 4,03 s, organe a 0,0 s apres).
      Risque hote NUL. C'est ici que l'arbre pourra grossir sans danger.
  ETAGE HOTE     — module Nokido qui touche la base ou le systeme. La cellule ne peut
      pas l'importer, donc le verdict est : parse AST, import reel, tests cibles. Le
      risque n'est pas nul, d'ou le perimetre immuable et le patron ci-dessous.

## Trois garde-fous, dont deux corrigent ce que j'allais faire (revue AGY, tour 4)

1. PERIMETRE IMMUABLE PAR GRAPHE, pas par liste. « Tout fichier present dans la pile
   d'execution directe ou indirecte de la boucle de mutation est IMMUTABLE par cette
   meme instance. » Une liste statique est toujours incomplete ; et une mutation qui
   casse le chemin d'execution de son propre correcteur est IRREPARABLE par lui.
2. PATRON = DERNIER ETAT SAIN VERIFIE (git HEAD), pas le `.bak`. Le `.bak` protege d'une
   ECRITURE ratee ; il n'aide pas contre une degradation silencieuse deja presente dans
   l'etat immediatement anterieur. L'analogie biologique tient : la reparation par
   recombinaison homologue prend la chromatide SOEUR comme patron, pas la lesion.
   Le `.bak` horodate est ecrit quand meme (demande owner) : il sert de trace, pas de
   patron.
3. UNE MUTATION A LA FOIS. Le parallelisme produit un bruit de correlation insoluble --
   on ne sait plus attribuer une degradation. Un lot se traite en pipeline sequentiel
   avec bissection. Le verrou est un fichier, donc il survit au process.

Usage :
    from forge_mutation_judge import juger_pur, juger_module, perimetre_immuable
    LAFORGE_PYTHON app/forge_mutation_judge.py --perimetre
"""

from __future__ import annotations

__FORGE_COLOR__ = "cognition/juge-mutations"

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

CELL_URL = os.environ.get("LAFORGE_PYEXEC_URL", "http://127.0.0.1:7402/pyexec")
VERROU = ROOT / "sandbox" / "mutation.lock"
BAK_DIR = ROOT / "sandbox" / "mutation_bak"
# Budget par defaut d'une variante dans la cellule. Court : une variante qui n'a pas
# conclu en 8 s sur un probleme jouet est deja disqualifiee sur la performance.
BUDGET_MS = int(os.environ.get("LAFORGE_MUTATION_BUDGET_MS", "8000"))
# Racines de la boucle de mutation : le point de depart du calcul d'immutabilite.
RACINES = (
    "app/forge_mutation_judge.py",
    "app/forge_proposal_applier.py",
    "app/forge_autonomous_loops.py",
    "app/forge_signal_coupling.py",
    "app/forge_resource_manager.py",
    "tools/nokido_hub.py",
    "app/forge_mcp_registry.py",
)


# ── PERIMETRE IMMUABLE (critere dynamique, pas liste) ─────────────────────────
def _imports_locaux(chemin: Path) -> set[str]:
    """Modules du depot importes par ce fichier. Rend un ensemble de noms de module."""
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return set()  # muet-ok : un fichier illisible n'ajoute rien, il ne casse rien
    noms: set[str] = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.Import):
            for a in n.names:
                noms.add(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            noms.add(n.module.split(".")[0])
    return noms


def _resoudre(nom: str) -> Path | None:
    for d in ("app", "tools"):
        p = ROOT / d / (nom + ".py")
        if p.exists():
            return p
    return None


def perimetre_immuable(profondeur: int = 4) -> dict:
    """Cloture des dependances de la boucle de mutation : ces fichiers sont INTOUCHABLES.

    Critere dynamique demande par la revue AGY (tour 4, B1) : une liste statique est
    toujours incomplete, et le jour ou elle l'est, la mutation casse le chemin
    d'execution de son propre correcteur -- panne irreparable par l'agent qui l'a faite.
    """
    vus: set[str] = set()
    file = [ROOT / r for r in RACINES if (ROOT / r).exists()]
    for p in file:
        vus.add(str(p.relative_to(ROOT)).replace("\\", "/"))
    for _ in range(max(1, profondeur)):
        nouveaux: list[Path] = []
        for p in list(file):
            for nom in _imports_locaux(p):
                q = _resoudre(nom)
                if not q:
                    continue
                rel = str(q.relative_to(ROOT)).replace("\\", "/")
                if rel not in vus:
                    vus.add(rel)
                    nouveaux.append(q)
        if not nouveaux:
            break
        file = nouveaux
    return {"n": len(vus), "fichiers": sorted(vus), "profondeur": profondeur,
            "critere": "cloture des imports depuis la boucle de mutation (AGY B1)"}


# L'EVALUATEUR est hors de portee de toute mutation (veille RSI 26/09 : autoresearch n'edite jamais
# son `prepare.py` ; rsiagent `core/checks.py:41` a MESURE des agents qui apprenaient a ecrire des
# verifications plus faibles). La cloture d'IMPORTS ci-dessous ne couvre ni tests/, ni la CI, ni les
# socles : une mutation pouvait affaiblir le test qui la juge. Liste BLANCHE de zones interdites.
_ZONE_EVALUATEUR = ("tests/", "tools/ci_local.py", "config/constitution.toml", "sandbox/evolution/",
                    "sandbox/mutation_ledger.jsonl", "app/forge_mutation_judge.py",
                    "app/forge_guarded_mutation_loop.py")


def mutable(rel: str, perim: dict | None = None) -> dict:
    """Ce fichier peut-il etre mute par CETTE instance ? Refus motive sinon."""
    rel = str(rel).replace("\\", "/").lstrip("./")
    if any(rel == z or rel.startswith(z) for z in _ZONE_EVALUATEUR):
        return {"mutable": False,
                "raison": "zone de l'evaluateur (tests, CI, constitution, registre, juge) : une "
                          "mutation ne touche jamais ce qui la juge"}
    p = perim or perimetre_immuable()
    if rel in set(p["fichiers"]):
        return {"mutable": False,
                "raison": "dans la cloture d'execution de la boucle de mutation — "
                          "une mutation fatale y serait irreparable par cette instance"}
    if not (ROOT / rel).exists():
        return {"mutable": False, "raison": "fichier inexistant"}
    return {"mutable": True}


# ── PATRON SAIN + trace .bak ──────────────────────────────────────────────────
def patron_sain(rel: str) -> dict:
    """Contenu du dernier etat SAIN VERIFIE (git HEAD), pas de l'etat anterieur.

    Le `.bak` est une trace, pas un patron : il peut porter une degradation deja
    presente. `git HEAD` a passe le gate au commit, c'est la chromatide soeur.
    """
    try:
        r = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(ROOT), "show", "HEAD:" + rel],
            capture_output=True, timeout=30, errors="replace",
        )
        if r.returncode != 0:
            return {"ok": False, "raison": (r.stderr or "")[:200]}
        return {"ok": True, "contenu": r.stdout, "source": "git HEAD"}
    except Exception as exc:
        # Rendre l'echec EXPLICITE : sans patron, aucune mutation ne doit partir.
        return {"ok": False, "raison": "%s: %s" % (type(exc).__name__, str(exc)[:160])}


def tracer_bak(rel: str) -> str | None:
    """Copie horodatee AVANT mutation (demande owner). Trace d'enquete, pas patron."""
    src = ROOT / rel
    if not src.exists():
        return None
    BAK_DIR.mkdir(parents=True, exist_ok=True)
    cible = BAK_DIR / ("%s.%d.bak" % (rel.replace("/", "__"), int(time.time())))
    try:
        shutil.copy2(src, cible)
        return str(cible.relative_to(ROOT))
    except Exception as exc:
        print("[juge] .bak IMPOSSIBLE pour %s (%s)" % (rel, type(exc).__name__),
              file=sys.stderr)
        return None


# ── VERROU : une mutation a la fois (AGY B3) ──────────────────────────────────
def prendre_verrou(quoi: str, ttl_s: float = 1800.0) -> dict:
    """Verrou FICHIER, donc il survit au process. Un bail expire est repris."""
    VERROU.parent.mkdir(parents=True, exist_ok=True)
    if VERROU.exists():
        age = time.time() - VERROU.stat().st_mtime
        if age < ttl_s:
            return {"ok": False, "raison": "mutation deja en cours depuis %.0f s : %s"
                    % (age, VERROU.read_text(errors="replace")[:120])}
    VERROU.write_text(json.dumps({"quoi": quoi, "ts": time.time()}), encoding="utf-8")
    return {"ok": True}


def rendre_verrou() -> None:
    try:
        VERROU.unlink(missing_ok=True)
    except OSError:  # muet-ok : un verrou deja rendu est l'etat voulu
        # Le marqueur va sur la ligne du `except`, pas sur celle du `pass` : c'est la
        # seule que le detecteur du gate inspecte. Mesure sur mon propre juge, qui se
        # signalait lui-meme en RECIDIVE — un garde qui crie a faux se fait desarmer.
        pass


# ── ETAGE CELLULE : juger du code PUR dans la sandbox WASM ────────────────────
def _cellule(code: str, budget_ms: int) -> dict:
    req = urllib.request.Request(
        CELL_URL, data=json.dumps({"code": code, "timeout_ms": budget_ms}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=(budget_ms / 1000.0) + 20) as r:
            return json.loads(r.read().decode())
    except Exception as exc:
        return {"ok": False, "injoignable": True,
                "error": "%s: %s" % (type(exc).__name__, str(exc)[:140])}


def juger_pur(source: str, verification: str, budget_ms: int | None = None) -> dict:
    """Verdict INCONTESTABLE sur du code pur : il tourne dans la cellule, ou il meurt.

    `source` = le code de la variante. `verification` = le code qui la met a l'epreuve
    et doit lever si elle est fausse (un `assert` suffit). Aucun acces hote possible,
    donc rien a proteger : c'est ici que l'arbre pourra grossir librement.

    Trois verdicts, jamais deux : SURVIT · MEURT · INDECIDABLE (cellule injoignable).
    Confondre les deux derniers ferait passer une panne d'infrastructure pour une
    variante mauvaise, et l'arbre eliminerait des branches saines.
    """
    b = int(budget_ms or BUDGET_MS)
    charge = source + "\n" + verification
    out = _cellule(charge, b)
    if out.get("injoignable"):
        return {"verdict": "INDECIDABLE", "pourquoi": out.get("error"),
                "note": "cellule WASM injoignable — ce n'est PAS un echec de la variante"}
    if out.get("ok"):
        return {"verdict": "SURVIT", "stdout": out.get("stdout", ""), "budget_ms": b}
    if out.get("apoptose"):
        return {"verdict": "MEURT", "cause": "apoptose",
                "pourquoi": "n'a pas conclu dans %d ms — disqualifiee sur le temps" % b}
    return {"verdict": "MEURT", "cause": "erreur",
            "pourquoi": str(out.get("error"))[:400]}


# ── ETAGE MEMOIRE : ce qui a DEJA coute ne se represente pas ───────────────────
# Mandat owner du 2026-07-30 : « la memoire des precedentes sessions doit aussi servir ».
# Un juge purement fonctionnel (ca compile, les tests passent) laisse repasser une
# mutation qui REINTRODUIT un defaut connu : le corps a 268 pieges indexes sur 58
# sessions, et un `except: pass` ou une ecriture dans la mauvaise table FTS passe tous
# les tests du monde. C'est l'etage le moins cher et il tourne donc EN PREMIER.
#
# On REUTILISE les detecteurs existants au lieu d'en ecrire un troisieme :
#   * `forge_git_gate._recidive_warn` — motifs re-consignes (chemin d'erreur muet 74x,
#     mauvaise cible d'indexation 25x). Il IMPRIME, on capture sa sortie.
#   * `forge_symptom_index.demander` — les sessions anterieures qui ont paye ce symptome.
def juger_memoire(rel: str) -> dict:
    """Cette mutation rejoue-t-elle un defaut deja paye ? Verdict AVANT tout test.

    Rend `verdict` = PROPRE · RECIDIVE · SANS_MESURE. Le troisieme etat compte : un
    detecteur injoignable n'est pas un fichier propre, et le confondre ferait passer
    l'absence d'outil pour une absence de defaut.
    """
    import contextlib
    import io

    res: dict = {"verdict": "SANS_MESURE", "motifs": [], "aveugle": []}

    # 1. Motifs re-consignes, par le detecteur du gate (il lit le fichier sur disque).
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_git_gate import _recidive_warn
        tampon = io.StringIO()
        with contextlib.redirect_stdout(tampon):
            _recidive_warn([rel])
        sortie = tampon.getvalue()
        for ligne in sortie.splitlines():
            if ligne.strip().startswith("!"):
                res["motifs"].append(ligne.strip()[:180])
    except Exception as exc:
        res["aveugle"].append("recidive(%s)" % type(exc).__name__)

    # 2. Index d'enquetes : ce fichier a-t-il DEJA fait l'objet d'un piege ?
    try:
        from nokido_agent.tools.forge_symptom_index import demander
        # Chemin DEMANDE au module proprietaire, pas devine : mes trois candidats etaient
        # tous faux (mesure 2026-07-30), et un chemin invente aurait rendu « index absent »
        # a jamais — un aveuglement silencieux deguise en absence de piege.
        from nokido_agent.tools.forge_symptom_index import INDEX as _IDX_PATH
        idx = None
        if Path(_IDX_PATH).exists():
            idx = json.loads(Path(_IDX_PATH).read_text(encoding="utf-8", errors="replace"))
        if idx is None:
            res["aveugle"].append("index_enquetes(absent)")
        else:
            terme = Path(rel).stem
            hits = demander(terme, idx, 3) or []
            res["pieges_anterieurs"] = [
                {"session": h.get("session"), "extrait": str(h.get("piege", h))[:160]}
                for h in hits]
    except Exception as exc:
        res["aveugle"].append("index_enquetes(%s)" % type(exc).__name__)

    if res["motifs"]:
        res["verdict"] = "RECIDIVE"
        res["pourquoi"] = ("rejoue %d motif(s) deja re-consigne(s) — un defaut connu ne "
                           "se represente pas, quels que soient les tests" % len(res["motifs"]))
    elif len(res["aveugle"]) < 2:
        res["verdict"] = "PROPRE"
    return res


# ── ETAGE HOTE : juger un module Nokido ───────────────────────────────────────
def juger_module(rel: str, nouveau: str, tests: list[str] | None = None) -> dict:
    """Applique une mutation a un module du depot, la JUGE, et RESTAURE si elle echoue.

    Sequence : verrou -> mutable ? -> patron sain -> .bak -> ecriture -> parse -> import
    -> tests -> verdict. Toute etape qui echoue restaure depuis le PATRON, pas depuis le
    `.bak`. Le verrou est rendu dans tous les cas.
    """
    rel = str(rel).replace("\\", "/").lstrip("./")
    etapes: list[str] = []
    v = prendre_verrou(rel)
    if not v["ok"]:
        return {"verdict": "REFUSE", "pourquoi": v["raison"], "etapes": etapes}
    try:
        m = mutable(rel)
        if not m["mutable"]:
            return {"verdict": "REFUSE", "pourquoi": m["raison"], "etapes": etapes}
        etapes.append("mutable:ok")

        pat = patron_sain(rel)
        if not pat["ok"]:
            # Sans patron verifie, on NE MUTE PAS : le filet passe avant le geste.
            return {"verdict": "REFUSE",
                    "pourquoi": "patron sain indisponible (%s) — aucune mutation sans "
                                "chemin de retour" % pat["raison"], "etapes": etapes}
        etapes.append("patron:git HEAD")

        bak = tracer_bak(rel)
        etapes.append("bak:%s" % (bak or "absent"))

        cible = ROOT / rel
        try:
            ast.parse(nouveau)
        except SyntaxError as e:
            return {"verdict": "MEURT", "cause": "syntaxe",
                    "pourquoi": "%s ligne %s" % (e.msg, e.lineno),
                    "etapes": etapes, "ecrit": False}
        etapes.append("parse:ok")

        cible.write_text(nouveau, encoding="utf-8")
        etapes.append("ecrit")

        def _restaurer(raison: str, cause: str, extra: dict | None = None) -> dict:
            cible.write_text(pat["contenu"], encoding="utf-8")
            etapes.append("RESTAURE depuis git HEAD")
            out = {"verdict": "MEURT", "cause": cause, "pourquoi": raison,
                   "etapes": etapes, "restaure": True}
            if extra:
                out.update(extra)
            return out

        # MEMOIRE D'ABORD : c'est l'etage le moins cher, et le seul que les tests ne
        # savent pas rendre. Un defaut deja paye 74 fois n'a pas a etre re-teste.
        mem = juger_memoire(rel)
        etapes.append("memoire:%s" % mem["verdict"])
        if mem["verdict"] == "RECIDIVE":
            return _restaurer(mem["pourquoi"], "recidive", {"memoire": mem})

        # Import REEL : le parse ne voit pas un nom non defini (lecon du 28/07).
        mod = Path(rel).stem
        r = subprocess.run([sys.executable, "-c", "import %s" % mod],
                           cwd=str(ROOT / Path(rel).parent), capture_output=True,
                           timeout=120, errors="replace",
                           env={**os.environ, "PYTHONNOUSERSITE": "1"})
        if r.returncode != 0:
            return _restaurer((r.stderr or "")[-500:], "import")
        etapes.append("import:ok")

        for t in (tests or []):
            rt = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", t],
                                cwd=str(ROOT), capture_output=True, timeout=900,
                                errors="replace",
                                env={**os.environ, "PYTHONNOUSERSITE": "1"})
            if rt.returncode != 0:
                return _restaurer("%s : %s" % (t, (rt.stdout or "")[-500:]), "test")
            etapes.append("test:%s ok" % t)

        return {"verdict": "SURVIT", "etapes": etapes, "bak": bak,
                "note": "mutation CONSERVEE — le commit reste une decision separee"}
    finally:
        rendre_verrou()


def perimetre_mesure(rel: str, racine=None, max_tests: int = 8) -> list[str]:
    """PERIMETRE DE MESURE d'un module : les tests qui le couvrent, par convention.

    ⚠️ Nom SANS prefixe `test` a dessein : pytest collecte comme test toute fonction
    dont le nom commence par `test`, y compris IMPORTEE dans un fichier de test — la
    premiere version s'appelait `tests_cibles` et sortait « fixture 'rel' not found »
    chez chaque importateur.

    `juger_gain` ne peut pas inventer ce qu'est une amelioration — il lui faut des
    tests a jouer avant et apres. Cette fonction repond a « lesquels ? », et c'est la
    precondition du chemin ferme : sans elle, `juger_module_avec_gain` rend
    GAIN_INDECIDABLE (cf. tests/nr/test_gain_indecidable_nr.py).

    EXTRAITE, pas ecrite : ces quatre conventions vivaient EN LIGNE dans
    `forge_self_mutation.MutationCycle.run_cycle`, donc inutilisables par
    `forge_autonomous_loops` — qui emprunte pour cette raison le chemin SANS gain.
    Le comportement est rigoureusement celui d'avant (meme ordre, meme filtre
    d'existence), verrouille par NR.

    Pour `app/forge_x.py` : tests/test_forge_x.py · tests/nr/test_forge_x_nr.py ·
    tests/nr/test_x_nr.py · tests/test_x.py (variante sans le prefixe `forge_`).

    Rend une liste EVENTUELLEMENT VIDE — c'est un etat legitime et le juge le
    traduit en INDECIDABLE, jamais en « pas de gain ».
    """
    return perimetre_mesure_detail(rel, racine=racine, max_tests=max_tests)["retenus"]


_IMPORT_TEST = re.compile(
    r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*))", re.M)
# `importlib.import_module("x")` exerce le module autant qu'un import statique. Les
# tests d'APPUI generes n'utilisent que cette forme : sans elle, 57 tests etaient
# invisibles au capteur qu'ils devaient faire monter (mesure 2026-09-08).
_IMPORT_DYN = re.compile(r"import_module\(\s*['\"]([\w.]+)['\"]")
_INDEX_IMPORTATEURS: dict[str, dict[str, list[str]]] = {}


def _importateurs(r: Path) -> dict[str, list[str]]:
    """{module: [tests qui l'IMPORTENT]}. Indexe une fois par racine, puis cache.

    Un test qui importe un module l'EXERCE : c'est le signal le plus honnete
    disponible, et il rattrape ce que les conventions de nommage ne voient pas.
    Mesure du 2026-09-08 : 264 modules etaient couverts par import SEUL, invisibles
    au capteur d'origine — 59 % de plus que ce qu'il voyait.
    """
    cle = str(r)
    if cle in _INDEX_IMPORTATEURS:
        return _INDEX_IMPORTATEURS[cle]
    index: dict[str, list[str]] = {}
    base = r / "tests"
    if base.is_dir():
        for racine_d, dossiers, fichiers in os.walk(base):
            dossiers[:] = [d for d in dossiers if d != "__pycache__" and not d.startswith(".")]
            for f in fichiers:
                if not f.endswith(".py"):
                    continue
                p = Path(racine_d) / f
                try:
                    txt = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue  # illisible : compte comme absent, jamais comme couvrant
                relt = str(p.relative_to(r)).replace("\\", "/")
                for m in _IMPORT_TEST.finditer(txt):
                    nom = (m.group(1) or m.group(2)).split(".")[0]
                    index.setdefault(nom, []).append(relt)
                for m in _IMPORT_DYN.finditer(txt):
                    nom = m.group(1).split(".")[0]
                    if relt not in index.setdefault(nom, []):
                        index[nom].append(relt)
    for v in index.values():
        v.sort()  # ordre DETERMINISTE : sinon la baseline n'est pas comparable
    _INDEX_IMPORTATEURS[cle] = index
    return index


def perimetre_mesure_detail(rel: str, racine=None, max_tests: int = 8) -> dict:
    """Perimetre DETAILLE : ce qui est retenu, par quelle voie, et ce qui est ECARTE.

    La borne existe parce que `mesurer` lance un pytest PAR fichier : un module
    importe par vingt tests couterait vingt executions, deux fois (baseline puis
    candidat). Mais une borne muette ferait croire a une couverture plus etroite
    qu'elle n'est — motif `borne_trop_serree`, deja paye sur 377 documents de veille.
    Elle NOMME donc ce qu'elle laisse de cote.
    """
    base = str(rel).replace("\\", "/").rsplit("/", 1)[-1]
    stem = base[:-3] if base.endswith(".py") else base
    court = stem[6:] if stem.startswith("forge_") else stem
    r = Path(racine) if racine is not None else ROOT

    vus: set[str] = set()
    convention: list[str] = []
    # La 5e convention est celle des tests d'APPUI generes. Elle vient EN DERNIER :
    # un NR ecrit a la main en dit plus qu'un appui, qui ne prouve que le chargement.
    for c in ("tests/test_%s.py" % stem, "tests/nr/test_%s_nr.py" % stem,
              "tests/nr/test_%s_nr.py" % court, "tests/test_%s.py" % court,
              "tests/nr/test_appui_%s_nr.py" % stem):
        if c not in vus and (r / c).is_file():
            vus.add(c)
            convention.append(c)

    par_import = [t for t in _importateurs(r).get(stem, []) if t not in vus]
    for t in par_import:
        vus.add(t)

    ordonne = convention + par_import  # la convention passe DEVANT
    borne = max(0, int(max_tests))
    return {"retenus": ordonne[:borne], "ecartes": ordonne[borne:],
            "par_convention": convention, "par_import": par_import, "borne": borne}


def mesurer(tests: list[str] | None = None, cwd: str | None = None) -> dict:
    """Metrique MESUREE d'un etat du depot : tests qui PASSENT + duree. Base du GAIN.

    juger_module prouve la SURVIE (returncode 0) ; il ne dit rien du GAIN. Cette mesure
    capture les dimensions COMPARABLES avant/apres une mutation : nombre de tests qui
    passent (plus haut = mieux) et duree totale (plus bas = mieux, proxy latence).
    Multidimensionnel a dessein : un seul nombre s'optimise pour tromper (Goodhart,
    cf. l'en-tete de ce module).
    """
    import time as _t

    tests = tests or []
    passes = []
    t0 = _t.monotonic()
    for t in tests:
        rt = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", t],
                            cwd=cwd or str(ROOT), capture_output=True, timeout=900,
                            errors="replace", env={**os.environ, "PYTHONNOUSERSITE": "1"})
        if rt.returncode == 0:
            passes.append(t)
    # L'IDENTITE des tests verts, pas seulement leur nombre : c'est elle qui permet a juger_gain
    # d'exiger une non-regression PAR test (DGM require_per_benchmark_non_regression, 26/09).
    return {"tests_ok": len(passes), "tests_total": len(tests), "tests_passes": passes,
            "duree_s": round(_t.monotonic() - t0, 3)}


def juger_gain(baseline: dict, candidat: dict, marge_duree: float = 0.10) -> dict:
    """Verdict de GAIN vs baseline — le chainon MANQUANT (Codex 2026-08-27 = reserve du 30/07).

    juger_module rend SURVIT (aucune regression) ; SURVIT n'est PAS AMELIORE. Une mutation
    qui PASSE les tests ET degrade obtient SURVIT et serait gardee a tort (« un .bak ne
    protege pas d'une mutation qui passe les tests et degrade »). Ce stage tranche
    AMELIORE / NEUTRE / DEGRADE sur la metrique MESUREE ; la boucle ne GARDE que sur
    AMELIORE (aucune mutation conservee sans gain mesure).

    Anti-Goodhart : une degradation sur N'IMPORTE quelle dimension surveillee => jamais
    AMELIORE. On EXIGE un progres (plus de tests OK, ou meme couverture sensiblement plus
    rapide) SANS recul ailleurs.
    """
    bo, co = int(baseline.get("tests_ok", 0)), int(candidat.get("tests_ok", 0))
    bt, ct = int(baseline.get("tests_total", 0)), int(candidat.get("tests_total", 0))
    bd, cd = float(baseline.get("duree_s", 0.0)), float(candidat.get("duree_s", 0.0))
    # TROIS etats, jamais deux (constitution 2026-09-05) : sans AUCUN test des deux
    # cotes, rien n'a ete mesure. Les trois branches capables de trancher exigent
    # `bd > 0` ; le verdict tombait donc en NEUTRE, « aucun gain », alors que la
    # bonne lecture est « aucune MESURE ». La difference oriente l'appelant : NEUTRE
    # l'envoie chercher un meilleur patch, INDECIDABLE lui dit de fournir des tests.
    if bt == 0 and ct == 0:
        return {"verdict": "INDECIDABLE",
                "pourquoi": "aucun test fourni : le gain n'est pas mesurable, "
                            "il n'est pas nul",
                "baseline": baseline, "candidat": candidat}
    # Non-regression PAR test (veille RSI 26/09, darwin-godel-machine parent_selector.py:50) : compter
    # ne suffit pas -- reparer 2 tests et en casser 1 rendait AMELIORE (3 > 2), regression comprise.
    bp, cp = baseline.get("tests_passes"), candidat.get("tests_passes")
    if isinstance(bp, list) and isinstance(cp, list):
        perdus = sorted(set(bp) - set(cp))
        if perdus:
            return {"verdict": "DEGRADE",
                    "pourquoi": "test(s) qui passai(en)t ne passe(nt) plus : %s" % ", ".join(perdus[:5]),
                    "baseline": baseline, "candidat": candidat}
    if co < bo:  # un test qui passait ne passe plus : DEGRADE, sans appel.
        return {"verdict": "DEGRADE", "pourquoi": "moins de tests passent (%d < %d)" % (co, bo),
                "baseline": baseline, "candidat": candidat}
    if co > bo and ct >= bt:  # plus de tests verts a couverture au moins egale.
        return {"verdict": "AMELIORE", "pourquoi": "%d tests passent vs %d" % (co, bo),
                "baseline": baseline, "candidat": candidat}
    if co == bo and ct == bt and bd > 0 and cd <= bd * (1 - marge_duree):
        return {"verdict": "AMELIORE",
                "pourquoi": "meme couverture, %.1f%% plus rapide" % (100 * (1 - cd / bd)),
                "baseline": baseline, "candidat": candidat}
    if co == bo and bd > 0 and cd > bd * (1 + marge_duree):  # plus lent sans contrepartie.
        return {"verdict": "DEGRADE",
                "pourquoi": "meme couverture mais %.1f%% plus lent" % (100 * (cd / bd - 1)),
                "baseline": baseline, "candidat": candidat}
    return {"verdict": "NEUTRE", "pourquoi": "aucun gain mesure vs baseline",
            "baseline": baseline, "candidat": candidat}


def juger_module_avec_gain(rel: str, nouveau: str, tests: list[str] | None = None) -> dict:
    """Juge FERME : SURVIT (non-regression) PUIS AMELIORE (gain vs baseline).

    C'est le chemin que la boucle doit emprunter (Codex 2026-08-27) : une mutation n'est
    CONSERVEE que si elle passe les tests ET ameliore une metrique mesuree. Une mutation
    SURVIT-mais-sans-gain (NEUTRE) ou qui degrade est RESTAUREE depuis git HEAD, meme si
    les tests sont verts -- « un .bak ne protege pas d'une mutation qui passe les tests et
    degrade » (reserve owner du 2026-07-30).

    Sequence : baseline(tests) -> juger_module (applique + SURVIT/MEURT) -> si SURVIT :
    candidat(tests) -> juger_gain -> garde si AMELIORE, sinon RESTAURE git HEAD.
    """
    tests = tests or []
    baseline = mesurer(tests)
    r = juger_module(rel, nouveau, tests)
    if r.get("verdict") != "SURVIT":
        r = {**r, "gain": None, "baseline": baseline}
        _journaliser(rel, r)
        return r
    candidat = mesurer(tests)
    g = juger_gain(baseline, candidat)
    r = {**r, "gain": g, "baseline": baseline, "candidat": candidat}
    if g["verdict"] == "AMELIORE":
        r["verdict"] = "AMELIORE"
        r["note"] = "mutation CONSERVEE : survit ET ameliore (%s)" % g["pourquoi"]
        _journaliser(rel, r)
        return r
    # Pas de gain PROUVE : on REVERTE, tests verts ou non. Le geste est le meme dans
    # les deux cas -- on ne conserve que ce qui est prouve meilleur -- mais le VERDICT
    # distingue « mesure sans gain » de « pas pu mesurer ».
    pat = patron_sain(rel)
    if pat.get("ok"):
        (ROOT / str(rel).replace("\\", "/").lstrip("./")).write_text(pat["contenu"], encoding="utf-8")
        r["restaure_sans_gain"] = True
    if g["verdict"] == "INDECIDABLE":
        r["verdict"] = "GAIN_INDECIDABLE"
        r["note"] = ("RESTAUREE par PRUDENCE, non par jugement : %s. Fournir des tests "
                     "cibles a juger_module_avec_gain(rel, nouveau, tests=[...]) pour "
                     "que le gain devienne mesurable." % g["pourquoi"])
    else:
        r["verdict"] = "SURVIT_SANS_GAIN"
        r["note"] = ("REJETEE malgre tests verts : %s (%s) -- pas de gain mesure vs baseline"
                     % (g["verdict"], g["pourquoi"]))
    _journaliser(rel, r)
    return r


_LEDGER = ROOT / "sandbox" / "mutation_ledger.jsonl"


def _journaliser(rel: str, r: dict) -> None:
    """Trace UNE tentative dans le ledger (base du tableau de bord). Best-effort."""
    try:
        _LEDGER.parent.mkdir(parents=True, exist_ok=True)
        entree = {
            "rel": str(rel),
            "verdict": r.get("verdict"),
            "cause": r.get("cause"),
            "gain": (r.get("gain") or {}).get("verdict") if isinstance(r.get("gain"), dict) else None,
            "baseline": r.get("baseline"),
            "candidat": r.get("candidat"),
        }
        with open(_LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(entree, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001  # muet-ok : le journal est un bonus, pas un garde
        pass


def tableau_de_bord(entrees: list[dict] | None = None, n: int = 500) -> dict:
    """Tableau de bord minimal de la boucle (Codex pt6) : APPREND-on, ou accumule-t-on ?

    Sans mesure agregee, « on ne sait pas si le systeme apprend ou accumule du texte ».
    Rend : tentatives, acceptees (AMELIORE), taux d'acceptation, rejets-sans-gain,
    morts, regressions (DEGRADE), recidives rappelees (memoire), gain median (duree).
    `entrees` injectable pour le test ; sinon lit le ledger (n dernieres).
    """
    if entrees is None:
        entrees = []
        if _LEDGER.exists():
            for _ln in _LEDGER.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]:
                try:
                    entrees.append(json.loads(_ln))
                except Exception:  # noqa: BLE001
                    pass
    tot = len(entrees)

    def _c(v):
        return sum(1 for e in entrees if e.get("verdict") == v)

    deltas = []
    for e in entrees:
        if e.get("verdict") == "AMELIORE":
            b = (e.get("baseline") or {}).get("duree_s")
            c = (e.get("candidat") or {}).get("duree_s")
            if isinstance(b, (int, float)) and isinstance(c, (int, float)):
                deltas.append(round(b - c, 3))
    deltas.sort()
    median = deltas[len(deltas) // 2] if deltas else 0.0
    ameliore = _c("AMELIORE")
    return {
        "tentatives": tot,
        "acceptees_AMELIORE": ameliore,
        "taux_acceptation": round(ameliore / tot, 3) if tot else 0.0,
        "rejets_sans_gain": _c("SURVIT_SANS_GAIN"),
        "morts_MEURT": _c("MEURT"),
        "regressions_DEGRADE": sum(1 for e in entrees if e.get("gain") == "DEGRADE"),
        "recidives_rappelees": sum(1 for e in entrees if e.get("cause") == "recidive"),
        "gain_median_duree_s": median,
    }


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Juge des mutations (cellule / hote).")
    ap.add_argument("--perimetre", action="store_true", help="lister les fichiers immuables")
    ap.add_argument("--test-cellule", action="store_true", help="auto-test du juge pur")
    args = ap.parse_args(argv)

    if args.perimetre:
        p = perimetre_immuable()
        print("PERIMETRE IMMUABLE — %d fichiers (%s)" % (p["n"], p["critere"]))
        for f in p["fichiers"]:
            print("   ", f)
        return 0
    if args.test_cellule:
        bon = juger_pur("def f(x):\n    return x * 2\n", "assert f(21) == 42\nprint('ok')")
        print("variante JUSTE   :", bon)
        faux = juger_pur("def f(x):\n    return x + 2\n", "assert f(21) == 42")
        print("variante FAUSSE  :", faux)
        lent = juger_pur("def f(x):\n    n = 0\n    while n >= 0:\n        n += 1\n",
                         "f(1)", budget_ms=3000)
        print("variante EMBALLEE:", lent)
        return 0
    print(json.dumps({"perimetre_n": perimetre_immuable()["n"],
                      "cellule": CELL_URL, "budget_ms": BUDGET_MS}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
