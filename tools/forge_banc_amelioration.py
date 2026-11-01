"""BANC D'AMELIORATION de Nokido (owner 29/10) : la methode du take-home, generalisee et branchee sur le RSI.

Methode (1017 -> 975 cycles, chaque pas PROUVE) : juge DETERMINISTE gele ; reference MESUREE au registre de preuves
CHAINE ; candidats generes (modele GRATUIT) dans une COPIE ISOLEE ; seul « exact ET strictement meilleur que le
meilleur prouve » est retenu ; la promotion est un geste owner (la boucle ne commite JAMAIS).

Pourquoi un module neuf (aucune brique existante ne convient) :
  - forge_takehome_evolution.iteration est DEDIEE au take-home (kernel_v2.py, cycles, README du defi) ; decision owner
    27/10 : ne pas la modifier. On en reutilise `_generer` (cascade gratuite).
  - forge_self_patcher (RSI) repare des tests ROUGES ; il n'optimise aucune metrique. On reutilise
    `_apply_search_replace` et le thymus (forge_autonomous_loops.submit_candidate_to_judge), pas son flux.
  - forge_auto_evolution_loop ne porte aucune boucle « candidat -> juge » (heartbeats, lecons, fichiers perimes).
  - forge_bench_takehome.consigner est cable sur l'empreinte du defi : on reprend SON format de chaine
    (`_canon`, `precedent`, `empreinte`) pour que `verifier_registre` valide aussi ces registres.

Usage : forge_banc_amelioration.py --cible <nom> --iterations N | --rapport | --verifier <nom>
Lancer EN JOB (run_job) : l'admission verifie la RAM ; la boucle re-verifie `check_ressources(heavy=True)` (fail-closed).
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/banc d'amelioration : candidats juges par une mesure deterministe, jamais par un modele"

import argparse
import ast
import difflib
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent


def _racine_donnees():
    """DONNEES par forge_db_path.racine_donnees() (cliquet racine_donnees) ; repli : racine du code, comme avant."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        try:
            from forge_db_path import racine_donnees
        except ImportError:
            return ROOT
    return racine_donnees()


_RACINE_DONNEES = _racine_donnees()
CONFIG = ROOT / "config" / "bancs_amelioration.json"
BANCS = _RACINE_DONNEES / "sandbox" / "workspace" / "bancs"
COPIES = _RACINE_DONNEES / "sandbox" / "bancs_copies"
# Marqueurs SEARCH/REPLACE construits (jamais litteraux dans ce fichier : les outils d'edition les interpretent).
_M_S, _M_E, _M_R = "<" * 7 + " SEARCH", "=" * 7, ">" * 7 + " REPLACE"
_RE_BLOC = re.compile(r"(?:FICHIER:[ \t]*(\S+)[ \t]*\n)?" + _M_S + r"\n(.*?)\n" + _M_E + r"\n(.*?)\n" + _M_R, re.S)
_PAYANTS = re.compile(r"claude|anthropic", re.I)
VERDICTS = ("AMELIORE", "EGAL", "REGRESSION", "GARDE_ROUGE", "NON_APPLICABLE", "HORS_PERIMETRE")
PROUVES = ("REFERENCE", "AMELIORE")


# ---------------------------------------------------------------- registre des bancs
def charger_bancs(chemin: Path = CONFIG) -> tuple:
    """(bancs valides, {nom: motif de refus}). Un banc SANS juge deterministe (commande, metrique, sens max|min)
    est REFUSE ici : sans mesure, « meilleur » n'a pas de sens."""
    brut = json.loads(Path(chemin).read_text(encoding="utf-8"))
    ok, refus = {}, {}
    for nom, b in brut.items():
        j = b.get("juge") if isinstance(b, dict) else None
        if not isinstance(j, dict) or not j.get("commande") or not j.get("metrique"):
            refus[nom] = "refuse : pas de juge deterministe (juge.commande et juge.metrique requis)"
        elif j.get("sens") not in ("max", "min"):
            refus[nom] = "refuse : juge.sens doit etre max ou min (recu %r)" % (j.get("sens"),)
        elif not b.get("perimetre"):
            refus[nom] = "refuse : perimetre vide (rien de modifiable)"
        elif not b.get("garde_tests"):
            refus[nom] = "refuse : garde_tests vide (aucune non-regression)"
        else:
            import forge_banc_strategies as S
            sok, smotif = S.valider_strategies(b.get("strategies", {}))
            if sok:
                ok[nom] = b
            else:
                refus[nom] = "refuse : strategies invalides (%s)" % smotif
    return ok, refus


def generateurs_gratuits(env=None) -> tuple:
    """(ok, motif). Jamais Claude, jamais un generateur payant : on lit les listes de fournisseurs configurees."""
    env = os.environ if env is None else env
    for k in ("TAKEHOME_PROVIDERS", "LAFORGE_PATCHER_PROVIDERS"):
        if _PAYANTS.search(env.get(k, "")):
            return False, "%s contient un fournisseur non gratuit" % k
    return True, None


# ---------------------------------------------------------------- patch
def parser_patch(texte: str, defaut: Optional[str]) -> list:
    return [((f or defaut or ""), s, r) for f, s, r in _RE_BLOC.findall(texte or "")]


def _est_test(rel: str) -> bool:
    p = rel.split("/")
    return "tests" in p[:-1] or p[-1].startswith("test_") or p[-1] == "conftest.py"


def controler_perimetre(blocs: list, banc: dict) -> Optional[str]:
    """Motif de refus, ou None. Un test n'est JAMAIS modifiable, meme s'il figurait au perimetre."""
    permis = {str(p).replace("\\", "/") for p in banc["perimetre"]}
    for rel, _, _ in blocs:
        n = os.path.normpath(rel.replace("\\", "/")).replace("\\", "/") if rel else ""
        if not n or n.startswith("..") or os.path.isabs(n):
            return "fichier non nomme ou chemin hors arbre : %r" % rel
        if _est_test(n):
            return "le patch touche un test : %s" % n
        if n not in permis:
            return "hors perimetre : %s (perimetre %s)" % (n, sorted(permis))
    return None


def meilleur_que(a: float, b: float, sens: str) -> bool:
    return a > b if sens == "max" else a < b


# ---------------------------------------------------------------- registre de preuves chaine
def consigner_banc(registre: Path, cible: str, statut: str, metrique, sens: str, provenance: str,
                   patch: str = "", meilleur_avant=None, raison: str = "", reference: Optional[dict] = None,
                   extra: Optional[dict] = None) -> dict:
    """Maillon du registre CHAINE (meme chaine que forge_bench_takehome.consigner : verifiable par
    `verifier_registre`). Append-only ; chaque maillon porte l'empreinte du precedent."""
    from forge_bench_takehome import _canon
    registre = Path(registre)
    precedent = None
    if registre.is_file():
        lignes = [l for l in registre.read_text(encoding="utf-8").splitlines() if l.strip()]
        if lignes:
            precedent = json.loads(lignes[-1])["empreinte"]
    ligne = {"quand": time.strftime("%Y-%m-%dT%H:%M:%S"), "provenance": provenance, "cible": cible,
             "statut": statut, "metrique": metrique, "sens": sens, "meilleur_avant": meilleur_avant,
             "sha256_patch": hashlib.sha256(patch.encode("utf-8")).hexdigest() if patch else None,
             "reference": reference or {}, "raison": raison, **(extra or {}), "precedent": precedent}
    ligne["empreinte"] = hashlib.sha256(_canon(ligne).encode("utf-8")).hexdigest()
    registre.parent.mkdir(parents=True, exist_ok=True)
    with registre.open("a", encoding="utf-8") as f:
        f.write(_canon(ligne) + "\n")
    return ligne


def lire_registre(registre: Path) -> list:
    if not Path(registre).is_file():
        return []
    return [json.loads(l) for l in Path(registre).read_text(encoding="utf-8").splitlines() if l.strip()]


def meilleur_prouve(registre: Path, sens: str, juge_ref: Optional[dict] = None) -> Optional[dict]:
    """Meilleur maillon PROUVE ; avec `juge_ref`, seulement ceux mesures par CE juge gele (memes empreintes).

    29/10 (job_1a73a9186e99) : corpus enrichi (F1 1,0 -> 0,578), le banc gardait la reference de l'ANCIEN corpus
    (1,0) : deux mesures de juges differents ne se comparent pas."""
    best = None
    for d in lire_registre(registre):
        m = d.get("metrique")
        if juge_ref is not None and (d.get("reference") or {}) != juge_ref:
            continue
        if d.get("statut") in PROUVES and isinstance(m, (int, float)):
            if best is None or meilleur_que(m, best["metrique"], sens):
                best = d
    return best


# ---------------------------------------------------------------- dependances (injectables)
@dataclass
class Deps:
    copier: Callable          # (racine, dest) -> None : copie ISOLEE (worktree detache)
    generer: Callable         # (prompt) -> (texte | None, fournisseur | motif)
    appliquer: Callable       # (fp, search, replace) -> (ok, original | erreur)
    garde: Callable           # (banc, copie) -> (ok, detail)
    juge: Callable            # (banc, copie) -> float | None
    thymus: Callable          # (ref, rel, new_text, tests) -> dict
    pre_flight: Callable      # (texte) -> (ok, motif)
    retirer: Optional[Callable] = None  # (racine, dest) -> None
    generer_local: Optional[Callable] = None  # (prompt, cfg) -> (texte | None, fournisseur | motif) ; rien ne sort


def _adresse_locale(base: str) -> bool:
    """Vrai SEULEMENT pour une boucle locale : un generateur « local » qui parlerait a un hote distant ferait sortir
    le code du perimetre sans passer par le pare-feu."""
    from urllib.parse import urlsplit
    return (urlsplit(str(base or "")).hostname or "") in ("127.0.0.1", "localhost", "::1")


def _generer_local_ollama(prompt: str, cfg: dict):
    """Generation par Ollama en boucle locale (29/10 soir : le pare-feu refuse, a bon droit, d'envoyer son propre code
    au cloud). (texte | None, fournisseur | motif)."""
    import urllib.request
    charge = {"model": cfg["modele"], "messages": [{"role": "user", "content": prompt}], "stream": False,
              "options": {"num_predict": int(cfg.get("num_predict", 4000))}}
    try:
        req = urllib.request.Request(str(cfg["base"]).rstrip("/") + "/api/chat", data=json.dumps(charge).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=float(cfg.get("delai_s", 900))) as rep:
            texte = (json.loads(rep.read().decode("utf-8", "replace")).get("message") or {}).get("content") or ""
    except Exception as e:  # noqa: BLE001 -- generateur local indisponible : DIT, jamais un candidat vide pris pour un avis
        return None, "local:%s indisponible (%s)" % (cfg.get("modele"), type(e).__name__)
    return (texte.strip() or None), "local:%s" % cfg["modele"]


def _retirer_defaut(racine: Path, dest: Path) -> None:
    try:
        subprocess.run(["git", "-C", str(racine), "worktree", "remove", "--force", str(dest)],
                       capture_output=True, timeout=120, check=True)
    except Exception:  # noqa: BLE001 -- pas un worktree (ou git absent) : suppression directe
        shutil.rmtree(dest, ignore_errors=True)


def _worktree_add(racine: Path, dest: Path) -> None:
    subprocess.run(["git", "-C", str(racine), "worktree", "add", "--detach", str(dest), "HEAD"],
                   capture_output=True, text=True, errors="replace", timeout=300, check=True)


def _copier_archive(racine: Path, dest: Path) -> None:
    """Copie de HEAD par `git archive` (lecture seule) : rien n'est ecrit dans `.git/`.

    29/10 : sous le compte du job (LaForgeSbxOnline), le depot appartient a l'owner -> « dubious ownership » ;
    `safe.directory` limite a CETTE invocation (jamais dans la config globale du compte)."""
    import io
    import tarfile
    sd = str(racine).replace("\\", "/")
    r = subprocess.run(["git", "-c", "safe.directory=" + sd, "-C", str(racine), "archive", "--format=tar", "HEAD"],
                       capture_output=True, timeout=300, check=True)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as t:
        t.extractall(dest, filter="data")


def _copier_worktree(racine: Path, dest: Path) -> None:
    """Worktree detache si le compte le peut, sinon archive de HEAD (motif journalise, jamais tu)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        _worktree_add(racine, dest)
    except subprocess.CalledProcessError as e:
        err = e.stderr if isinstance(e.stderr, str) else ""
        motif = (err.strip().splitlines() or ["?"])[0]
        print("[copie] worktree refuse (rc %s : %s) -> archive de HEAD" % (e.returncode, motif), flush=True)
        shutil.rmtree(dest, ignore_errors=True)
        _copier_archive(racine, dest)


def _argv_juge(banc: dict, copie: Path, racine: Path) -> list:
    sub = {"{python}": sys.executable, "{copie}": str(copie), "{racine}": str(racine)}
    out = []
    for t in shlex.split(banc["juge"]["commande"], posix=True):
        for k, v in sub.items():
            t = t.replace(k, v)
        out.append(sys.executable if t == "python" else t)
    return out


def _juge_defaut(racine: Path) -> Callable:
    def juge(banc: dict, copie: Path):
        try:
            p = subprocess.run(_argv_juge(banc, copie, racine), cwd=racine, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=900)
            d = json.loads(p.stdout.strip().splitlines()[-1])
            m = d.get(banc["juge"]["metrique"], d.get("metrique"))
            return float(m) if p.returncode == 0 and m is not None else None
        except Exception:  # noqa: BLE001 -- juge illisible = pas de mesure, jamais un score invente
            return None
    return juge


def _garde_defaut(banc: dict, copie: Path) -> tuple:
    tests = list(banc["garde_tests"])
    notes = []
    try:
        from nokido_agent.app.forge_mutation_judge import perimetre_mesure
        for rel in banc["perimetre"]:
            tests += [t for t in perimetre_mesure(rel) if t not in tests]
    except Exception as e:  # noqa: BLE001 -- perimetre illisible : garde seule, et on le DIT
        notes.append("perimetre_mesure illisible (%s)" % type(e).__name__)
    cmd = [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"] + tests
    p = subprocess.run(cmd, cwd=copie, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=1800)
    return p.returncode == 0, ("; ".join(notes) + " " + (p.stdout + p.stderr)[-300:]).strip()


def _soumettre(ref, rel, new_text, tests):
    """Thymus existant (forge_autonomous_loops.submit_candidate_to_judge) avec les tests de garde ; fail-closed."""
    try:
        from nokido_agent.app.forge_autonomous_loops import submit_candidate_to_judge
    except Exception as e:  # noqa: BLE001
        return {"status": "BLOCKED", "verdict": "REFUSE", "pourquoi": "thymus injoignable: %s" % e}
    return submit_candidate_to_judge(ref, rel, new_text, tests)


def _appliquer_tolerant(fp: Path, search: str, replace: str, exact) -> tuple:
    """Applique un bloc SEARCH/REPLACE par `exact` (outil existant, controle AST compris), avec deux gardes du banc :
    (1) un SEARCH present PLUSIEURS fois est refuse (l'outil remplacerait le premier en silence) ;
    (2) un SEARCH absent tel quel est cherche en repli : fenetre UNIQUE dont les lignes non vides egalent les siennes,
    espaces de tete ignores, remplacee par `replace` reindente du meme decalage. Ambigu ou rien = refus, fichier intact.
    Mesure 29/10 : qwen2.5-coder 7B rend des blocs justes mais desindentes (2 NON_APPLICABLE sur 3).
    NR tests/nr/test_banc_appliquer_indentation_nr.py.
    """
    texte = Path(fp).read_text(encoding="utf-8", errors="replace")
    n = texte.count(search) if search else 0
    if n > 1:
        return False, "SEARCH ambigu : %d occurrences exactes" % n
    if n == 1:
        return exact(fp, search, replace)
    cherches = [l.strip() for l in search.splitlines() if l.strip()]
    lignes = texte.splitlines(keepends=True)
    pleines = [i for i, l in enumerate(lignes) if l.strip()]
    k_max = len(pleines) - len(cherches) + 1
    fenetres = [(pleines[k], pleines[k + len(cherches) - 1]) for k in range(max(k_max, 0))
                if cherches and [lignes[pleines[k + j]].strip() for j in range(len(cherches))] == cherches]
    if len(fenetres) != 1:
        return False, "search string not found in file (repli tolerant : %s)" % (
            "ambigu, %d fenetres" % len(fenetres) if fenetres else "aucune fenetre")
    a, b = fenetres[0]
    premiere = next(l for l in search.splitlines() if l.strip())
    decal_fichier = lignes[a][:len(lignes[a]) - len(lignes[a].lstrip())]
    decal_bloc = premiere[:len(premiere) - len(premiere.lstrip())]
    if not decal_fichier.startswith(decal_bloc):
        return False, "search string not found in file (repli tolerant : indentation incompatible)"
    prefixe = decal_fichier[len(decal_bloc):]
    fin = "\n" if lignes[b].endswith("\n") else ""
    nouveau = "\n".join((prefixe + l) if l.strip() else l for l in replace.splitlines()) + fin
    return exact(fp, "".join(lignes[a:b + 1]), nouveau)


def deps_reelles(racine: Path = ROOT) -> Deps:
    def generer(prompt: str):
        ok, motif = generateurs_gratuits()
        if not ok:
            return None, motif
        import forge_takehome_evolution as E  # boucle takehome : UTILISEE, jamais modifiee
        return E._generer(prompt)

    def appliquer(fp, s, r):
        from nokido_agent.tools.forge_self_patcher import _apply_search_replace
        return _appliquer_tolerant(fp, s, r, _apply_search_replace)

    def pre_flight(texte):
        import forge_cli_swarm as S
        return S._pre_flight_envoi(texte, "banc_amelioration")

    return Deps(_copier_worktree, generer, appliquer, _garde_defaut, _juge_defaut(racine), _soumettre, pre_flight,
                _retirer_defaut)


# ---------------------------------------------------------------- boucle
def _segments(texte: str, noms) -> str:
    """Source VERBATIM des definitions nommees (fonctions, methodes, classes, affectations de module), dans l'ordre du
    fichier ; le fichier ENTIER si aucune n'est trouvee ou si l'analyse echoue (jamais un prompt vide).

    Mesure 29/10 : app/forge_rag_engine.py entier (102 Ko, ~25 000 jetons) partait au generateur -> deepseek-coder:6.7b
    0 bloc exploitable sur 3, et au-dela du plafond Groq gratuit. NR tests/nr/test_banc_prompt_fonctions_seules_nr.py.
    """
    voulus = set(noms or ())
    if not voulus:
        return texte
    try:
        arbre = ast.parse(texte)
    except SyntaxError:
        return texte
    morceaux = []
    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            noms_n = {n.name}
        elif isinstance(n, (ast.Assign, ast.AnnAssign)) and n in arbre.body:
            cibles = n.targets if isinstance(n, ast.Assign) else [n.target]
            noms_n = {t.id for t in cibles if isinstance(t, ast.Name)}
        else:
            continue
        seg = ast.get_source_segment(texte, n, padded=True) if noms_n & voulus else None
        if seg:
            morceaux.append((n.lineno, seg))
    if not morceaux:
        return texte
    return "\n\n# [...]\n\n".join(s for _, s in sorted(morceaux))


def _prompt(banc: dict, copie: Path, i: int) -> str:
    axes = banc.get("axes") or [{"nom": "libre", "description": "toute amelioration de la metrique"}]
    axe = axes[i % len(axes)]
    j = banc["juge"]
    src = "\n".join("### %s\n```python\n%s\n```" % (rel, _segments((copie / rel).read_text(encoding="utf-8"),
                                                                   banc.get("fonctions")))
                    for rel in banc["perimetre"])
    sens = "plus haut = meilleur" if j["sens"] == "max" else "plus bas = meilleur"
    gabarit = "\n".join(["FICHIER: <chemin du perimetre>", _M_S, "<lignes copiees A L'IDENTIQUE>", _M_E,
                         "<remplacement>", _M_R])
    regles = ("Tu es un GENERATEUR DE PATCH, pas un debatteur : UNIQUEMENT des blocs SEARCH/REPLACE, sans prose.\n"
              "REGLES : ne modifie QUE les fichiers du perimetre %s (fonctions visees : %s) ; aucun test ; la "
              "metrique %s (%s) est mesuree par un juge deterministe que tu ne vois pas et ne peux pas modifier ; "
              "les tests existants doivent rester verts.\n")
    regles = regles % (banc["perimetre"], banc.get("fonctions"), j["metrique"], sens)
    # 30/10 : 4 candidats sur 6 refuses « patch too large » (32-35 lignes) par la garde de l'outil, que le prompt ne
    # disait pas. Plafond LU dans l'outil, jamais recopie. NR tests/nr/test_banc_prompt_annonce_plafond_nr.py.
    try:
        from nokido_agent.tools.forge_self_patcher import MAX_PATCH_LINES as _plafond
        regles += ("PLAFOND : chaque REPLACE fait au plus %d lignes (au-dela, le patch est refuse) ; prefere une "
                   "modification courte et ciblee.\n" % _plafond)
    except Exception:  # noqa: BLE001 -- muet-ok : outil illisible = prompt d'avant, la garde de l'outil refuse toujours
        pass
    axe_txt = "## AXE : %s : %s\n\n" % (axe["nom"], axe.get("description", ""))
    return regles + axe_txt + src + "\n\nFORMAT EXACT, un bloc par modification :\n" + gabarit


def _reference_juge(banc: dict, racine: Path) -> dict:
    """Empreintes du juge gele (script, corpus...) : le maillon prouve QUEL juge a mesure."""
    out = {}
    for rel in banc["juge"].get("empreintes", []):
        p = Path(racine) / rel
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "ABSENT"
    return out


def _lire(copie: Path, banc: dict) -> dict:
    return {rel: (copie / rel).read_text(encoding="utf-8") for rel in banc["perimetre"]}


def _juger_candidat(banc: dict, copie: Path, deps: Deps, r: dict, meilleur, sens: str, avant: dict) -> None:
    import forge_banc_strategies as S
    apres0 = _lire(copie, banc)
    for rel in banc["perimetre"]:  # anti-triche : seules les lignes AJOUTEES sont lues (phase 15)
        ajoute = "".join(l[2:] for l in difflib.ndiff(avant[rel].splitlines(True), apres0[rel].splitlines(True))
                         if l.startswith("+ "))
        triche = S.controler_triche(ajoute, banc)
        if triche:
            r.update(verdict="TRICHE_REFUSEE", motif=triche)
            return
    garde_ok, detail = deps.garde(banc, copie)
    if not garde_ok:
        r.update(verdict="GARDE_ROUGE", motif=str(detail)[:300])
        return
    m = deps.juge(banc, copie)
    if m is None:
        r.update(verdict="JUGE_ILLISIBLE", motif="le juge n'a rendu aucune mesure")
        return
    r["metrique"] = m
    if meilleur is None or meilleur_que(m, meilleur, sens):
        r["verdict"] = "AMELIORE"
    else:
        r["verdict"] = "EGAL" if m == meilleur else "REGRESSION"
    if r["verdict"] == "AMELIORE":
        apres = _lire(copie, banc)
        diffs = []
        for rel in banc["perimetre"]:
            diffs += list(difflib.unified_diff(avant[rel].splitlines(True), apres[rel].splitlines(True),
                                               "a/" + rel, "b/" + rel, n=2))
        r["diff"] = "".join(diffs)
        r["_nouveaux"] = apres


def iteration(nom: str, banc: dict, i: int, racine: Path, dossier: Path, deps: Deps, copies: Path,
              meilleur=None) -> dict:
    racine, dossier, copies = Path(racine), Path(dossier), Path(copies)
    reg, sens = dossier / "registre.jsonl", banc["juge"]["sens"]
    if meilleur is None:
        b = meilleur_prouve(reg, sens)
        meilleur = b["metrique"] if b else None
    refj = _reference_juge(banc, racine)
    copie = copies / ("%s_%s_%d" % (nom, time.strftime("%Y%m%d_%H%M%S"), i))
    r = {"i": i, "cible": nom, "meilleur_avant": meilleur}
    deps.copier(racine, copie)
    try:
        # 30/10 (owner) : EVOLUTION, declaree par le banc (`"evolution": true`) -- la copie part du meilleur noeud de
        # la lignee compatible avec HEAD. Sans le drapeau : depuis HEAD, comme avant.
        noeud, motifs = base_evolution(dossier, banc, racine) if banc.get("evolution") else (None, [])
        r["base_noeud"] = noeud["id"] if noeud else None
        if noeud:
            for rel, chemin in noeud["fichiers"].items():
                (copie / rel).write_text((dossier / chemin).read_text(encoding="utf-8"), encoding="utf-8")
        if motifs:
            r["evolution"] = " ; ".join(motifs)
        prompt = _prompt(banc, copie, i)
        gl = banc.get("generateur_local")
        if gl:
            # 29/10 soir : generation LOCALE declaree par le banc (code que le pare-feu ne laisse pas sortir).
            # Adresse non locale = refus, rien n'est appele ; adresse locale = rien ne sort, pas de pre_flight cloud.
            if not _adresse_locale(gl.get("base", "")):
                r.update(verdict="GENERATEUR_LOCAL_REFUSE", motif="adresse non locale : %s" % gl.get("base"))
                return r
            texte, prov = (deps.generer_local or _generer_local_ollama)(prompt, gl)
        else:
            ok, motif = deps.pre_flight(prompt)
            if not ok:
                r.update(verdict="PRE_FLIGHT_REFUSE", motif=str(motif)[:200])
                return r
            texte, prov = deps.generer(prompt)
        r["fournisseur"] = prov
        blocs = parser_patch(texte, banc["perimetre"][0] if len(banc["perimetre"]) == 1 else None)
        if not texte:
            r.update(verdict="GENERATION_ECHEC", motif=str(prov)[:200])
            return r
        if not blocs:
            r.update(verdict="SANS_BLOC", motif="aucun bloc SEARCH/REPLACE")
            return r
        refus = controler_perimetre(blocs, banc)
        if refus:
            r.update(verdict="HORS_PERIMETRE", motif=refus)
        else:
            avant = _lire(copie, banc)
            for rel, s, rep in blocs:
                ok, err = deps.appliquer(copie / rel, s, rep)
                if not ok:
                    r.update(verdict="NON_APPLICABLE", motif=str(err)[:200])
                    break
            else:
                _juger_candidat(banc, copie, deps, r, meilleur, sens, avant)
                if r.get("verdict") == "AMELIORE" and banc.get("evolution"):
                    enregistrer_noeud(dossier, banc, racine, r)
        maillon = consigner_banc(reg, nom, r["verdict"], r.get("metrique"), sens, "banc:%s:%s" % (prov, i),
                                 r.get("diff") or texte, meilleur, r.get("motif", ""), refj)
        r["registre"] = maillon["empreinte"]
        if r["verdict"] == "AMELIORE":
            _promouvoir(nom, banc, r, dossier, deps, reg, sens, refj, prov, i)
        return r
    finally:
        r.pop("_nouveaux", None)
        (deps.retirer or _retirer_defaut)(racine, copie)


# ---------------------------------------------------------------- lignee d'evolution (owner 30/10)
# « ecris le banc d'evolution avec retour arriere possible » : chaque AMELIORE devient un NOEUD (contenu complet du
# perimetre, empreinte de la base HEAD, parent) ; le tour suivant part du dernier noeud actif ; `retour(n)` en ecarte
# sans rien effacer ; un noeud dont la base n'est plus HEAD est ecarte AUTOMATIQUEMENT et c'est dit.
# NR tests/nr/test_banc_evolution_lignee_nr.py.
LIGNEE = "lignee.jsonl"


def _sha(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def _lignes_lignee(dossier: Path) -> list:
    f = Path(dossier) / LIGNEE
    if not f.exists():
        return []
    out = []
    for ligne in f.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ligne))
        except ValueError:
            continue  # muet-ok : ligne illisible ignoree, jamais un noeud invente
    return out


def noeuds_actifs(dossier: Path) -> list:
    """Noeuds de la lignee dans l'ordre, sans ceux qu'un retour arriere a ecartes (rien n'est efface)."""
    lignes = _lignes_lignee(dossier)
    retires = {x["retire"] for x in lignes if "retire" in x}
    return [x for x in lignes if "id" in x and x["id"] not in retires]


def retour(dossier: Path, n: int = 1) -> list:
    """Retour arriere : ecarte les n derniers noeuds actifs (lignes RETIRE ajoutees, aucun noeud efface)."""
    actifs = noeuds_actifs(dossier)
    ecartes = [x["id"] for x in actifs[-int(n):]] if int(n) > 0 else []
    if ecartes:
        with open(Path(dossier) / LIGNEE, "a", encoding="utf-8") as f:
            for nid in ecartes:
                f.write(json.dumps({"retire": nid, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
    return ecartes


def base_evolution(dossier: Path, banc: dict, racine: Path) -> tuple:
    """(noeud | None, motifs) : le dernier noeud actif dont la BASE (empreinte de HEAD a sa creation) egale HEAD ;
    sinon retour arriere AUTOMATIQUE vers le precedent compatible, puis HEAD -- chaque noeud ecarte est DIT."""
    motifs = []
    for noeud in reversed(noeuds_actifs(dossier)):
        bouges = [rel for rel in banc["perimetre"]
                  if noeud.get("base", {}).get(rel) != _sha((Path(racine) / rel).read_text(encoding="utf-8"))]
        absents = [rel for rel in banc["perimetre"]
                   if not (Path(dossier) / noeud.get("fichiers", {}).get(rel, "__absent__")).exists()]
        if not bouges and not absents:
            return noeud, motifs
        motifs.append("noeud %s ecarte : %s" % (noeud["id"], "base HEAD changee (%s)" % ", ".join(bouges) if bouges
                                                else "fichiers absents (%s)" % ", ".join(absents)))
    return None, motifs


def enregistrer_noeud(dossier: Path, banc: dict, racine: Path, r: dict) -> dict:
    """AMELIORE -> noeud : contenu complet du perimetre, empreinte de la base HEAD, parent ; r['diff'] devient le
    patch CUMULATIF par rapport a HEAD (integrable seul par l'owner)."""
    nid = "%s_%d" % (time.strftime("%Y%m%d_%H%M%S"), r["i"])
    rep = Path(dossier) / "lignee" / nid
    rep.mkdir(parents=True, exist_ok=True)
    fichiers, base, diffs = {}, {}, []
    for rel, nouveau in r["_nouveaux"].items():
        tete = (Path(racine) / rel).read_text(encoding="utf-8")
        p = rep / rel.replace("/", "__")
        p.write_text(nouveau, encoding="utf-8")
        fichiers[rel] = p.relative_to(dossier).as_posix()
        base[rel] = _sha(tete)
        diffs += list(difflib.unified_diff(tete.splitlines(True), nouveau.splitlines(True), "a/" + rel, "b/" + rel,
                                           n=2))
    noeud = {"id": nid, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "metrique": r.get("metrique"),
             "parent": r.get("base_noeud"), "base": base, "fichiers": fichiers}
    with open(Path(dossier) / LIGNEE, "a", encoding="utf-8") as f:
        f.write(json.dumps(noeud, ensure_ascii=False) + "\n")
    r["diff"], r["noeud"] = "".join(diffs), nid
    return noeud


def _promouvoir(nom, banc, r, dossier, deps, reg, sens, refj, prov, i) -> None:
    """AMELIORE -> thymus existant -> AWAITING_OWNER. Patch conserve ; JAMAIS de commit par la boucle."""
    cand = dossier / "candidats"
    cand.mkdir(parents=True, exist_ok=True)
    pf = cand / ("%s_%d.patch" % (time.strftime("%Y%m%d_%H%M%S"), i))
    pf.write_text(r["diff"], encoding="utf-8")
    r["patch"] = str(pf)
    thymus = []
    for rel, new in r["_nouveaux"].items():
        try:
            t = deps.thymus("banc:%s" % nom, rel, new, list(banc["garde_tests"]))
        except Exception as e:  # noqa: BLE001 -- thymus en panne : fail-closed, DIT
            t = {"status": "BLOCKED", "verdict": "REFUSE", "pourquoi": "%s: %s" % (type(e).__name__, str(e)[:120])}
        thymus.append({"fichier": rel, "verdict": t.get("verdict"), "status": t.get("status")})
    r["thymus"], r["statut"] = thymus, "AWAITING_OWNER"
    raison = "thymus=%s ; promotion = geste owner" % json.dumps(thymus)
    consigner_banc(reg, nom, "AWAITING_OWNER", r["metrique"], sens, "banc:%s:%s" % (prov, i), r["diff"],
                   r["meilleur_avant"], raison, refj, {"patch": str(pf)})


def boucle(nom: str, banc: dict, n: int, racine: Path, dossier: Path, deps: Deps, copies: Path) -> dict:
    """Reference (1er maillon) puis `n` candidats, bornes par le budget du banc."""
    racine, dossier = Path(racine), Path(dossier)
    reg, sens = dossier / "registre.jsonl", banc["juge"]["sens"]
    n = min(n, int(banc.get("budget_iterations", n)))
    refj = _reference_juge(banc, racine)
    if not any(l.get("statut") == "REFERENCE" and (l.get("reference") or {}) == refj for l in lire_registre(reg)):
        ref = Path(copies) / ("%s_ref_%s" % (nom, time.strftime("%Y%m%d_%H%M%S")))
        deps.copier(racine, ref)
        try:
            m = deps.juge(banc, ref)
        finally:
            (deps.retirer or _retirer_defaut)(racine, ref)
        if m is None:
            return {"cible": nom, "erreur": "reference illisible : le juge n'a rien mesure", "verdicts": {}}
        consigner_banc(reg, nom, "REFERENCE", m, sens, "banc:reference", "", None,
                       "mesure du code actuel (HEAD) sous ce juge gele", refj)
    import forge_banc_strategies as S
    stop = S.passe_borne(nom, banc, reg)
    if stop:  # phase 3 : borne atteinte, rien a chercher de plus
        return {"cible": nom, "verdicts": {"BORNE_ATTEINTE": 1}, "journal": [],
                "meilleur_prouve": stop["metrique"]}
    verdicts, journal = {}, []
    for i in range(n):
        b = meilleur_prouve(reg, sens, refj)
        try:
            r = iteration(nom, banc, i, racine, dossier, deps, copies, b["metrique"])
        except Exception as e:  # noqa: BLE001 -- une iteration en panne est DITE, jamais avalee
            r = {"i": i, "verdict": "PANNE", "motif": "%s: %s" % (type(e).__name__, str(e)[:300])}
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
        # 30/10 : base_noeud/evolution/noeud visibles -- sans eux, rien ne prouvait d'ou partait le candidat
        champs = ("i", "verdict", "metrique", "motif", "fournisseur", "statut", "patch", "base_noeud", "evolution",
                  "noeud")
        journal.append({k: r.get(k) for k in champs})
    k = (banc.get("strategies") or {}).get("plateau")
    if k:  # phase 10/12 : plateau consigne, jamais presente comme preuve
        hist = [j["metrique"] for j in journal if isinstance(j.get("metrique"), (int, float))]
        b0 = meilleur_prouve(reg, sens, refj)
        if b0 is not None:
            S.consigner_plateau(reg, nom, [b0["metrique"]] + hist, int(k), sens)
    best = meilleur_prouve(reg, sens, refj)
    return {"cible": nom, "verdicts": verdicts, "journal": journal,
            "meilleur_prouve": best["metrique"] if best else None}


DECISIONS_OWNER = ("integre", "rejete")


def _decides(lignes: list) -> set:
    return {l.get("patch") for l in lignes if l.get("statut") == "DECIDE_OWNER"}


def decider(registre: Path, patch: str, decision: str, preuve: str) -> dict:
    """Consigne la DECISION owner sur un candidat AWAITING_OWNER : maillon du registre chaine, jamais une reecriture.
    30/10 : le gain 0,630 integre restait « en attente » faute de ligne pour le dire. Refus explicite d'une decision
    inconnue, d'un patch jamais en attente, ou d'une seconde decision."""
    if decision not in DECISIONS_OWNER:
        raise ValueError("decision %r hors de %s" % (decision, DECISIONS_OWNER))
    lignes = lire_registre(registre)
    en_attente = {l.get("patch") for l in lignes if l.get("statut") == "AWAITING_OWNER"}
    if patch not in en_attente:
        raise ValueError("aucun candidat AWAITING_OWNER %r dans %s" % (patch, registre))
    if patch in _decides(lignes):
        raise ValueError("candidat %r deja decide" % patch)
    cible = Path(registre).parent.name
    sens = lignes[0].get("sens", "max") if lignes else "max"
    return consigner_banc(registre, cible, "DECIDE_OWNER", None, sens, "owner", raison=preuve,
                          extra={"patch": patch, "decision": decision, "preuve": preuve})


def rapport(dossier_bancs: Path = BANCS) -> dict:
    """Par cible : meilleur prouve, candidats AWAITING_OWNER, taux de pertinence = AMELIORE / essais."""
    out = {}
    for reg in sorted(Path(dossier_bancs).glob("*/registre.jsonl")):
        lignes = lire_registre(reg)
        if not lignes:
            continue
        sens = lignes[0].get("sens", "max")
        essais = [l for l in lignes if l.get("statut") in VERDICTS]
        am = [l for l in essais if l["statut"] == "AMELIORE"]
        # 29/10 soir : le rapport melangeait les juges (1,0 de l'ancien corpus affiche quand le juge actuel mesure
        # 0,576) ; il suit le DERNIER juge consigne, comme l'execution (meilleur_prouve avec juge_ref).
        refs = [l.get("reference") for l in lignes if l.get("reference")]
        best = meilleur_prouve(reg, sens, refs[-1] if refs else None)
        attente = [l.get("patch") for l in lignes
                   if l.get("statut") == "AWAITING_OWNER" and l.get("patch") not in _decides(lignes)]
        out[reg.parent.name] = {
            "meilleur_prouve": best["metrique"] if best else None,
            "empreinte": best["empreinte"] if best else None,
            "essais": len(essais), "ameliores": len(am),
            "taux_pertinence": (len(am) / len(essais)) if essais else None,
            "awaiting_owner": attente}
    return out


def _garde_ram() -> Optional[str]:
    """Garde RAM du corps (jamais contournee, fail-closed) : motif de refus ou None."""
    try:
        from nokido_agent.app import forge_lane_admission as la
        res = la.check_ressources(heavy=True)
    except Exception as e:  # noqa: BLE001
        return "garde RAM illisible (%s) : refus fail-closed" % type(e).__name__
    return None if res.get("ok") else "machine saturee : %s" % res.get("reason")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cible")
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--rapport", action="store_true")
    ap.add_argument("--verifier", metavar="CIBLE")
    ap.add_argument("--retour", type=int, default=0, metavar="N",
                    help="retour arriere : ecarte les N derniers noeuds de la lignee de --cible (rien n'est efface)")
    ap.add_argument("--config", type=Path, default=CONFIG)
    ap.add_argument("--decider", metavar="PATCH", help="decision owner sur un candidat AWAITING_OWNER de --cible")
    ap.add_argument("--decision", choices=DECISIONS_OWNER)
    ap.add_argument("--preuve", default="", help="commit ou motif de la decision")
    a = ap.parse_args(argv)
    if a.decider:
        if not (a.cible and a.decision and a.preuve):
            ap.error("--decider exige --cible, --decision et --preuve")
        print(json.dumps(decider(BANCS / a.cible / "registre.jsonl", a.decider, a.decision, a.preuve),
                         ensure_ascii=False))
        return 0
    if a.rapport:
        print(json.dumps(rapport(), ensure_ascii=False, indent=1))
        return 0
    if a.verifier:
        from forge_bench_takehome import verifier_registre
        v = verifier_registre(BANCS / a.verifier / "registre.jsonl")
        print(json.dumps(v))
        return 0 if v["ok"] else 1
    if not a.cible:
        ap.error("--cible requis (ou --rapport / --verifier)")
    if a.retour:
        print(json.dumps({"retour_arriere": retour(BANCS / a.cible, a.retour),
                          "actifs": [x["id"] for x in noeuds_actifs(BANCS / a.cible)]}))
        return 0
    bancs, refus = charger_bancs(a.config)
    if a.cible not in bancs:
        print("REFUS : %s" % refus.get(a.cible, "cible inconnue"))
        return 2
    ok, motif = generateurs_gratuits()
    if not ok:
        print("REFUS : %s" % motif)
        return 2
    motif = _garde_ram()
    if motif:
        print("REFUS : %s" % motif)
        return 2
    bilan = boucle(a.cible, bancs[a.cible], a.iterations, ROOT, BANCS / a.cible, deps_reelles(ROOT), COPIES)
    print(json.dumps(bilan, ensure_ascii=False, indent=1))
    print(json.dumps(rapport().get(a.cible), ensure_ascii=False))
    return 0 if "erreur" not in bilan else 2


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tools"))
    raise SystemExit(main())
