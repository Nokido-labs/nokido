#!/usr/bin/env python3
"""forge_axis_backtest.py — BACKTEST d'un axe de detection de regression.

Un axe qui affirme "je detecte les regressions" doit le PROUVER sur des regressions
DEJA survenues. Verite terrain gratuite et datee : les commits de CORRECTION. Pour
chaque commit C qui repare quelque chose, on rejoue l'etat AVANT (C~1) et l'etat
APRES (C) des fichiers .py touches, et on exige de l'axe :

    AVANT le fix  -> il TIRE      (sinon il aurait rate cette regression : MISS)
    APRES le fix  -> il se TAIT   (sinon il crie sur du code repare : BRUIT)

On en tire deux nombres qu'aucune opinion ne remplace : le RAPPEL (part des
regressions historiques vues) et le BRUIT RESIDUEL. Un axe sans ces deux nombres
n'est pas un axe, c'est une intuition.

Axes backtestes ici (les deux proposes par Antigravity, reformules) :
  ax13_except_avale_signal  : except nu dont le try ECRIT un signal dont un autre
                              organe depend (flag, publication, verdict, statut).
                              Precedent : docker.wanted pose dans un except pass ->
                              le keeper est reste spectateur.
  ax14_env_hors_shim        : lecture d'un nom d'env herite LAFORGE_* dans un module
                              qui n'est PAS sous la portee du shim dual-read
                              forge_env_alias. Compter les occurrences du nom, lui,
                              rend ~263 faux positifs : le shim les rend legitimes.

Usage :
  LAFORGE_PYTHON tools/forge_axis_backtest.py --since 2026-05-01 --limit 60
  LAFORGE_PYTHON tools/forge_axis_backtest.py --axis ax13_except_avale_signal --json
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "qualite/quality : backtest d'un axe de detection de regression"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Ecritures qu'un autre organe OBSERVE. Avaler l'une d'elles, c'est mentir a un tiers.
SIGNAUX = {
    "post", "publish", "emit", "notify", "broadcast", "send", "sendall", "put",
    "propose_fact", "anchor_solution", "write_text", "touch", "commit", "execute",
    "executemany", "set_mode", "set_status", "mark", "ack", "ack_mail", "report",
}
SIGNAL_ATTR = re.compile(r"\.(wanted|status|health|verdict|flag|state)\b")


def _git(*args: str, texte: bool = True):
    """git en compte sandbox : le depot appartient a l'owner, d'ou safe.directory."""
    return subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(ROOT), *args],
        capture_output=True, text=texte, encoding="utf-8" if texte else None,
        errors="replace" if texte else None, timeout=120)


def commits_de_correction(since: str, limit: int) -> list:
    g = _git("log", f"--since={since}", "-i", "--grep=fix", "--grep=incident",
             "--grep=regress", "--pretty=%H%x09%cI%x09%s")
    out = []
    for l in g.stdout.splitlines():
        p = l.split("\t", 2)
        if len(p) != 3:
            continue
        out.append({"sha": p[0], "date": p[1][:10], "sujet": p[2].strip()})
    if not out:
        return []
    pas = max(1, len(out) // limit)      # echantillon ETALE : les N derniers = un prefixe
    return out[::pas][:limit]


# Familles de fichiers. Le harnais ne lisait QUE les .py : tout axe visant les
# wrappers (.cmd/.ps1) ou la configuration (.yml) etait donc structurellement
# inmesurable, et son rappel sous-estime sans que rien ne le dise. Chantier
# choisi par le pair au tour 11.
EXT_FAMILLE = {
    ".py": "py",
    ".cmd": "script", ".bat": "script", ".ps1": "script", ".psm1": "script", ".sh": "script",
    ".yml": "config", ".yaml": "config", ".json": "config", ".toml": "config",
    ".ini": "config", ".cfg": "config", ".env": "config",
}
# Perimetre DECLARE de chaque axe. Un axe non declare est traite en 'py' seul et
# la supposition est IMPRIMEE : un perimetre implicite est un plafond silencieux.
FAMILLES_AXE = {
    "ax13_except_avale_signal": {"py"},          # AST Python
    "ax16_ast_unresolved_names": {"py"},         # pyflakes
    "ax14_env_hors_shim": {"py", "script", "config"},
    "ax15_hardcoded_legacy_paths": {"py", "script", "config"},
}


def _famille(chemin: str) -> str:
    p = chemin.lower()
    for ext, fam in EXT_FAMILLE.items():
        if p.endswith(ext):
            return fam
    return ""


def fichiers_cibles(sha: str, familles: set) -> list:
    """Fichiers touches par le commit, restreints aux familles de l'axe."""
    g = _git("show", "--name-only", "--pretty=", sha)
    out = []
    for l in g.stdout.splitlines():
        c = l.strip()
        if not c or c.startswith("tests/"):
            continue
        if _famille(c) in familles:
            out.append(c)
    return out


def fichiers_py(sha: str) -> list:
    """Compat : le sous-ensemble Python (utilise par les sondes existantes)."""
    return fichiers_cibles(sha, {"py"})


def blob(sha: str, chemin: str) -> str | None:
    g = _git("show", f"{sha}:{chemin}")
    return g.stdout if g.returncode == 0 else None


# ----------------------------------------------------------------- axe 13
def ax13_except_avale_signal(src: str, chemin: str) -> list:
    """except nu/large dont le corps est muet ET dont le try ecrit un signal observe."""
    try:
        arbre = ast.parse(src)
    except SyntaxError:
        return [{"illisible": chemin}]
    trouves = []
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Try):
            continue
        emet = False
        for x in ast.walk(n):
            if isinstance(x, ast.Call):
                f = x.func
                nom = getattr(f, "attr", None) or getattr(f, "id", None)
                if nom in SIGNAUX:
                    emet = True
            elif isinstance(x, (ast.Assign, ast.AugAssign)):
                if SIGNAL_ATTR.search(ast.dump(x)):
                    emet = True
        if not emet:
            continue
        for h in n.handlers:
            muet = all(isinstance(s, (ast.Pass, ast.Continue)) or
                       (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
                       for s in h.body)
            large = h.type is None or getattr(h.type, "id", "") in ("Exception", "BaseException")
            if muet and large:
                trouves.append({"file": chemin, "line": h.lineno})
    return trouves


# ----------------------------------------------------------------- axe 14
# Python : os.environ["LAFORGE_X"] / getenv("LAFORGE_X")
# Scripts et config : %LAFORGE_X% (cmd), $env:LAFORGE_X (PowerShell), ${LAFORGE_X}
# et LAFORGE_X: (yml). Sans ces formes, l'extension aux wrappers ne verrait rien.
LIT_ENV = re.compile(
    r"""(?:environ(?:\.get)?\(|getenv\()\s*['"](LAFORGE_[A-Z0-9_]+)['"]"""
    r"""|%(LAFORGE_[A-Z0-9_]+)%"""
    r"""|\$env:(LAFORGE_[A-Z0-9_]+)"""
    r"""|\$\{?(LAFORGE_[A-Z0-9_]+)\}?"""
    r"""|^\s*(LAFORGE_[A-Z0-9_]+)\s*:""")


def ax14_env_hors_shim(src: str, chemin: str) -> list:
    """Lecture d'un nom herite HORS portee du shim dual-read. La simple occurrence du
    nom n'est PAS un defaut : forge_env_alias miroite LAFORGE_ <-> NOKIDO_."""
    if ("forge_env_alias" in src) or ("env_alias" in src):
        return []
    out = []
    for i, ligne in enumerate(src.splitlines(), 1):
        for groupes in LIT_ENV.findall(ligne):
            v = next((g for g in (groupes if isinstance(groupes, tuple) else (groupes,)) if g), "")
            if v:
                out.append({"file": chemin, "var": v, "line": i})
    return out


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+")

# ----------------------------------------------------------------- axe 15
def ax15_hardcoded_legacy_paths(src: str, chemin: str) -> list:
    """Recherche des chemins absolus codés en dur pointant vers l'ancien dossier LaForge."""
    out = []
    for i, ligne in enumerate(src.splitlines(), 1):
        if "Script python IA\\LaForge" in ligne or "Script python IA/LaForge" in ligne:
            out.append({"file": chemin, "line": i})
    return out

# ----------------------------------------------------------------- axe 16
def ax16_ast_unresolved_names(src: str, chemin: str) -> list:
    """Détecte statiquement les noms non résolus (NameError) en utilisant pyflakes."""
    import io
    import re
    from pyflakes.api import check
    from pyflakes.reporter import Reporter
    
    out = io.StringIO()
    err = io.StringIO()
    rep = Reporter(out, err)
    
    check(src, chemin, rep)
    
    trouves = []
    pattern = re.compile(r"^.*?:(\d+):(?:\d+:)? undefined name '.*?'")
    
    for line in out.getvalue().splitlines():
        if "undefined name" in line:
            m = pattern.match(line)
            if m:
                trouves.append({"file": chemin, "line": int(m.group(1))})
    return trouves


def lignes_reparees(sha: str, chemin: str) -> set:
    """Les lignes du fichier AVANT le fix que le fix a effectivement touchees. C'est la
    cible : un axe n'a pas 'vu' la regression s'il pointait ailleurs dans le fichier."""
    g = _git("diff", "-U0", f"{sha}~1", sha, "--", chemin)
    lignes = set()
    for l in g.stdout.splitlines():
        m = HUNK.match(l)
        if m:
            debut = int(m.group(1))
            n = int(m.group(2) or 1)
            lignes.update(range(debut, debut + max(n, 1)))
    return lignes


# ═══════════════════════════════════════════════════════════════════
# AXE REPO — l'unite n'est plus le fichier, c'est le SIGNAL
# ═══════════════════════════════════════════════════════════════════
# Les regressions qui echappent a TOUS les axes par fichier ont la meme forme :
# un pouls declare et surveille avec ZERO emetteur ; docker.wanted pose dans un
# except muet donc jamais pose ; un PUSH ZMQ vers un port ferme, ACCEPTE, quatre
# organes croyant reveiller un vivant. Syntaxiquement parfait partout. Le defaut
# n'est DANS aucun fichier : il est dans l'ASYMETRIE entre celui qui ecrit un
# signal et celui qui le lit. On raisonne donc sur l'arbre entier, via `git grep`
# au commit (pas de lecture fichier par fichier : le cout resterait prohibitif).
SIG_MOTIFS = [r"\.wanted", r"\.heartbeat", r"tcp://127\.0\.0\.1:[0-9]+"]
SIG_NOM = re.compile(r"([A-Za-z0-9_.\-]+\.(?:wanted|heartbeat))|(tcp://127\.0\.0\.1:[0-9]+)")
ECRIT = re.compile(r"write_text|open\([^)]*['\"][wa]|touch\(|\.dump|mkdir|"
                   r"\bsend\b|send_json|send_string|\bpost\b|publish|beat_")
# Les lecteurs ne sont PAS tous en Python : le superviseur qui surveille les
# heartbeats est en Deno/TypeScript. Sans ses idiomes, l'axe declarait
# `emetteur_sans_lecteur` sur des signaux parfaitement surveilles — et le total
# passait de 25 a 105 findings au moindre ajustement, preuve qu'il mesurait mes
# regex et non le systeme.
LIT = re.compile(r"\bexists\(|is_file\(|read_text|getmtime|\.load|\bglob\b|"
                 r"\brecv\b|connect\(|watch|surveil|monitor|read\("
                 r"|readTextFile|existsSync|statSync|readFileSync|Deno\.stat"
                 r"|heartbeat\s*=|heartbeat\s*:")


def _fichiers_qui_ecrivent(sha: str) -> set:
    """Fichiers contenant un verbe d'ecriture, quel que soit l'objet ecrit.

    Necessaire parce que l'ecriture passe presque toujours par une VARIABLE :
    `HEARTBEAT = SANDBOX / "x.heartbeat"` en ligne 52, puis `HEARTBEAT.write_text(...)`
    en ligne 68 — la ligne qui ecrit ne contient PAS le nom du signal. Classer
    ligne par ligne accusait donc d'emetteur-manquant des fichiers qui emettent
    (faux positif mesure le 2026-08-13 sur forge_watch_agent_worker.py).
    """
    g = _git("grep", "-l", "-I", "-E", "-e", r"write_text|open\([^)]*['\"][wa]|touch\(|beat_"
                                             r"|send_json|send_string|\.dump", sha)
    return {l.split(":", 1)[1] for l in g.stdout.splitlines() if ":" in l}


def _signaux_desactives(sha: str) -> set:
    """Heartbeats declares dans un bloc de service `disabled = true`. Un service
    eteint ne DOIT pas ecrire son pouls : l'absence d'emetteur est normale, pas
    une panne. Parse par blocs [[service]] de services.toml au commit."""
    off: set = set()
    try:
        g = _git("show", f"{sha}:proxy_deno/core/services.toml")
        bloc, disabled = [], False
        for ligne in (g.stdout or "").splitlines():
            if ligne.strip().startswith("[[service]]"):
                if disabled:
                    for b in bloc:
                        m = re.search(r"heartbeat\s*=\s*['\"]([^'\"]+)['\"]", b)
                        if m:
                            off.add(Path(m.group(1)).name)
                bloc, disabled = [], False
            else:
                bloc.append(ligne)
                if re.match(r"\s*disabled\s*=\s*true", ligne):
                    disabled = True
        if disabled:                                  # dernier bloc du fichier
            for b in bloc:
                m = re.search(r"heartbeat\s*=\s*['\"]([^'\"]+)['\"]", b)
                if m:
                    off.add(Path(m.group(1)).name)
    except Exception:  # noqa: BLE001
        pass
    return off


def _grep_signaux(sha: str) -> list:
    args = ["grep", "-n", "-I", "-E"]
    for m in SIG_MOTIFS:
        args += ["-e", m]
    g = _git(*args, sha)
    out = []
    for l in g.stdout.splitlines():
        # format : <sha>:<chemin>:<ligne>:<contenu>
        p = l.split(":", 3)
        if len(p) < 4 or p[1].startswith("tests/"):
            continue
        try:
            out.append((p[1], int(p[2]), p[3]))
        except ValueError:
            continue
    return out


def ax17_signal_asymetrie(sha: str) -> list:
    """Un signal ECRIT que personne ne lit, ou LU que personne n'ecrit.

    Verdicts (les deux sont des pannes vecues) :
      - `garde_sans_emetteur` : des lecteurs, zero ecrivain -> quelqu'un
        surveille un mort (le pouls du daemon, mesure le 2026-08-02) ;
      - `emetteur_sans_lecteur` : des ecrivains, zero lecteur -> on parle dans
        le vide (PUSH ZMQ vers un port ferme, 4 organes concernes).
    """
    # DELEGUE au resolveur AST (forge_signal_graph) : DETERMINISTE, la ou le grep
    # (conserve inerte en _ax17_grep_LEGACY) faisait osciller la sortie 25/105/95/
    # 42/32/29 au gre des regex. Depuis le 13/08 le resolveur couvre AUSSI les
    # organes Deno (.ts, resolveur regex prudent ajoute par ANTIGRAVITY) : l'angle
    # mort TypeScript est LEVE, la neutralisation _organes_deno n'a plus lieu d'etre
    # (elle masquait des gardes que le TS confirme desormais ou apparie).
    from nokido_agent.tools.forge_signal_graph import asymetries, build_graph

    graphe = build_graph(_fichiers_signaux(sha), lambda p: _blob(sha, p))
    return asymetries(graphe)


def _fichiers_signaux(sha: str) -> list:
    """Fichiers du commit portant un signal (grep -l) : .py, services.toml, .ts.

    ⚠️ On grep AUSSI `beat_daemon(` : un emetteur qui bat son pouls via le helper
    (`beat_daemon("comm_watch")`) n'ecrit JAMAIS le littoral `.heartbeat` — sans
    cette clause son fichier n'etait pas collecte, son signal restait sans
    ecrivain, et 4 organes (comm_watch, parietal_fusion, phenom_buffer,
    gate_consumer) remontaient en FAUX gardes. Le defaut etait dans la COLLECTE,
    pas dans le resolveur (mesure le 2026-08-13)."""
    g = _git("grep", "-l", "-I", "-E", "-e", r"\.heartbeat", "-e", r"\.wanted",
             "-e", r"tcp://127\.0\.0\.1", "-e", r"beat_daemon\(", sha)
    out = []
    for l in g.stdout.splitlines():
        chemin = l.split(":", 1)[1] if ":" in l else l
        if (chemin.endswith(".py")
                or chemin.endswith(".ts")
                or (chemin.endswith(".toml") and "services" in chemin)):
            out.append(chemin)
    return out


def _blob(sha: str, chemin: str):
    g = _git("show", f"{sha}:{chemin}")
    return g.stdout if g.returncode == 0 else None


def _ax17_grep_LEGACY(sha: str) -> list:
    """Ancienne implementation par grep — CONSERVEE INERTE (jamais appelee).
    Version dont la sortie oscillait, remplacee le 2026-08-13 par le resolveur
    AST. Doctrine owner : garder le legacy."""
    ecrivains: dict = {}
    lecteurs: dict = {}
    f_ecrivent = _fichiers_qui_ecrivent(sha)

    # DEUX FAUX POSITIFS MESURES le 2026-08-13 (2 suspects sur 2 = 0 vrai) :
    #  1) un service `disabled = true` dans services.toml est ETEINT — son pouls
    #     n'a pas a etre ecrit. Le declarer garde_sans_emetteur est faux.
    #  2) l'emission passe souvent par un nom CONSTRUIT (f"task_executor_{slug}.
    #     heartbeat") : le littoral n'apparait jamais, mais le fichier ecrit bien.
    # On collecte donc, dans les fichiers ecrivains, la RACINE des heartbeats
    # construits par f-string, et on desarme les signaux des blocs disabled.
    # Emission par nom CONSTRUIT (f"task_executor_{slug}.heartbeat") : on ne peut
    # pas nommer le signal, mais on connait sa RACINE litterale ("task_executor_").
    # On l'attribue donc PREFIXE PAR PREFIXE, jamais a tous les heartbeats — une
    # regle globale masquait le seul vrai positif (regression introduite puis
    # retiree le 2026-08-13 : la sortie bougeait au gre de la regex).
    hb_prefixes = set()
    try:
        g = _git("grep", "-h", "-I", "-E", "-e", r"f['\"][^'\"{]*_\{", sha)
        for l in g.stdout.splitlines():
            for m in re.finditer(r"f['\"]([^'\"{]*?)_\{", l):
                if m.group(1):
                    hb_prefixes.add(m.group(1))
    except Exception:  # noqa: BLE001
        pass
    disabled_sig = _signaux_desactives(sha)

    # EMISSION PAR HELPER CANONIQUE : `beat_daemon("autonomous_loops")` ecrit
    # sandbox/autonomous_loops.heartbeat, mais le nom du signal est un ARGUMENT,
    # jamais un chemin. Sans cette regle l'axe ratait 88505606 — le commit meme
    # qui reparait « le daemon bat enfin le pouls que le superviseur surveille »,
    # c'est-a-dire le cas pour lequel il a ete ecrit.
    try:
        g = _git("grep", "-n", "-I", "-E", "-e", r"beat_daemon\(\s*['\"][a-zA-Z0-9_]+['\"]", sha)
        for l in g.stdout.splitlines():
            p = l.split(":", 3)
            if len(p) < 4:
                continue
            m = re.search(r"beat_daemon\(\s*['\"]([a-zA-Z0-9_]+)['\"]", p[3])
            if m:
                try:
                    ecrivains.setdefault(f"{m.group(1)}.heartbeat", []).append((p[1], int(p[2])))
                except ValueError:
                    continue
    except Exception:  # noqa: BLE001
        pass
    for chemin, ligne, contenu in _grep_signaux(sha):
        m = SIG_NOM.search(contenu)
        if not m:
            continue
        sig = (m.group(1) or m.group(2)).strip()
        # UNE DECLARATION EN CONFIGURATION N'EST PAS UNE ECRITURE, c'est le
        # CONTRAT DE SURVEILLANCE : `heartbeat = "sandbox/x.heartbeat"` dans
        # services.toml dit « le superviseur surveille ce pouls », donc un
        # LECTEUR. Classee en ecriture, elle donnait un emetteur a chaque signal
        # et l'axe rendait 95 faux `emetteur_sans_lecteur` — il ne pouvait plus
        # voir le seul cas qui compte : un garde qui surveille un mort.
        if _famille(chemin) == "config":
            lecteurs.setdefault(sig, []).append((chemin, ligne))
            continue
        # Le nom du signal LIE a une variable dans un fichier qui ecrit = emetteur.
        liaison = "=" in contenu.split("#", 1)[0]
        if ECRIT.search(contenu) or (liaison and chemin in f_ecrivent):
            ecrivains.setdefault(sig, []).append((chemin, ligne))
        elif LIT.search(contenu):
            lecteurs.setdefault(sig, []).append((chemin, ligne))
    # Attribution par prefixe : `task_executor_worker_code.heartbeat` est emis
    # des lors qu'un fichier construit `f"task_executor_{...}"`. On ne touche que
    # les signaux dont la racine matche, jamais tous.
    for sig in list(lecteurs):
        base = Path(sig).stem
        if sig not in ecrivains and any(base.startswith(p) for p in hb_prefixes):
            ecrivains.setdefault(sig, []).append(("<f-string>", 0))

    trouves = []
    for sig, pos in lecteurs.items():
        if sig in ecrivains or sig in disabled_sig:   # disabled = eteint, pas mort
            continue
        for chemin, ligne in pos[:3]:
            trouves.append({"file": chemin, "line": ligne, "signal": sig,
                            "verdict": "garde_sans_emetteur"})
    for sig, pos in ecrivains.items():
        if sig not in lecteurs:
            for chemin, ligne in pos[:3]:
                trouves.append({"file": chemin, "line": ligne, "signal": sig,
                                "verdict": "emetteur_sans_lecteur"})
    return trouves


AXES_REPO = {"ax17_signal_asymetrie": ax17_signal_asymetrie}


AXES = {
    "ax13_except_avale_signal": ax13_except_avale_signal,
    "ax14_env_hors_shim": ax14_env_hors_shim,
    "ax15_hardcoded_legacy_paths": ax15_hardcoded_legacy_paths,
    "ax16_ast_unresolved_names": ax16_ast_unresolved_names,
}


def backtest(nom_axe: str, commits: list) -> dict:
    """AVANT le fix l'axe doit TIRER, APRES il doit se TAIRE. Tout le reste est du bruit."""
    det = AXES[nom_axe]
    familles = FAMILLES_AXE.get(nom_axe, {"py"})
    vus, rate, bruit, sans_etat, illisibles = [], [], [], [], 0
    for c in commits:
        fics = fichiers_cibles(c["sha"], familles)
        if not fics:
            sans_etat.append({"sha": c["sha"][:8],
                              "why": f"aucun fichier des familles {sorted(familles)}"})
            continue
        sur_cible, hors_cible, eteintes, lisible, cible_connue = 0, 0, 0, False, False
        for f in fics[:12]:
            av = blob(c["sha"] + "~1", f)
            if av is None:
                continue
            ra = det(av, f)
            if ra and "illisible" in ra[0]:
                illisibles += 1
                continue
            lisible = True
            reparees = lignes_reparees(c["sha"], f)
            if reparees:
                cible_connue = True
            for t in ra:
                ln = t.get("line")
                # +-2 lignes : un except muet repare deplace souvent la ligne exacte
                if ln is not None and reparees and any(abs(ln - r) <= 2 for r in reparees):
                    sur_cible += 1
                else:
                    hors_cible += 1
            # CRITERE D'EXTINCTION — decouvert le 2026-08-13 en confrontant ax16 au
            # commit a3844d6f : le detecteur criait aux lignes 789 et 807 (les usages
            # de `sys.`) alors que le fix reparait la LIGNE 21 (l'import ajoute en
            # tete). Exiger que l'axe pointe une ligne reparee le comptait RATE alors
            # qu'il avait vu le vrai defaut. La cause est souvent AILLEURS que le
            # symptome. Le critere causal, lui, ne s'y trompe pas : une alerte
            # presente AVANT et absente APRES a bien ete ETEINTE par le fix.
            ap = blob(c["sha"], f)
            if ap is not None:
                rb = det(ap, f)
                if not (rb and "illisible" in rb[0]) and len(rb) < len(ra):
                    eteintes += len(ra) - len(rb)
        if not lisible or not cible_connue:
            sans_etat.append({"sha": c["sha"][:8],
                              "why": "etat avant illisible, absent, ou diff sans cible"})
            continue
        fiche = {"sha": c["sha"][:8], "sujet": c["sujet"][:90], "sur_cible": sur_cible,
                 "hors_cible": hors_cible, "eteintes": eteintes,
                 "par": "ligne" if sur_cible else ("extinction" if eteintes else "")}
        if sur_cible > 0 or eteintes > 0:
            vus.append(fiche)             # ligne reparee OU alerte eteinte par le fix
        else:
            rate.append(fiche)
            if hors_cible > 0:
                bruit.append(fiche)       # il a crie, et le fix ne l'a pas fait taire
    juges = len(vus) + len(rate)
    return {
        "axe": nom_axe,
        "familles": sorted(familles),
        "famille_declaree": nom_axe in FAMILLES_AXE,
        "commits_juges": juges,
        "commits_ecartes": len(sans_etat),
        "fichiers_illisibles": illisibles,
        "rappel_pct": round(100.0 * len(vus) / juges, 1) if juges else None,
        "vus_par_ligne": sum(1 for v in vus if v["par"] == "ligne"),
        "vus_par_extinction": sum(1 for v in vus if v["par"] == "extinction"),
        # a crie, et le fix ne l'a NI localisee NI eteinte : du bruit, pas une detection
        "bruit_hors_cible_pct": round(100.0 * len(bruit) / juges, 1) if juges else None,
        "vus": vus[:12],
        "RATES": rate[:20],
        "ecartes": sans_etat[:8],
    }


def split_temporel(commits: list, coupe: str = "") -> tuple:
    """CALIBRATION (avant la coupe) / HOLDOUT (apres). Anti-sur-apprentissage.

    Ecrire un detecteur PARCE QU IL attrape les commits qu on a sous les yeux, c est
    se noter sur sa copie. Le seul chiffre qui vaut est celui obtenu sur des commits
    JAMAIS VUS pendant l ecriture du detecteur. Sans coupe fournie : la mediane des
    dates de l echantillon, et elle est IMPRIMEE (un split silencieux ne vaut rien).
    """
    dates = sorted(c.get("date", "") for c in commits if c.get("date"))
    if not dates:
        return commits, [], ""
    c0 = coupe or dates[len(dates) // 2]
    return ([c for c in commits if c.get("date", "") < c0],
            [c for c in commits if c.get("date", "") >= c0], c0)


def backtest_repo(nom_axe: str, commits: list) -> dict:
    """Backtest d'un axe REPO. Meme contrat de preuve, autre unite d'observation :
    l'axe TIRE avant le fix et se TAIT apres. Le critere de ligne n'a pas de sens
    ici (le defaut n'appartient a aucun fichier) : seule l'EXTINCTION compte."""
    det = AXES_REPO[nom_axe]
    vus, rate, ecartes = [], [], []
    for c in commits:
        try:
            av = {(t["signal"], t["verdict"]) for t in det(c["sha"] + "~1")}
            ap = {(t["signal"], t["verdict"]) for t in det(c["sha"])}
        except Exception as e:  # noqa: BLE001
            ecartes.append({"sha": c["sha"][:8], "why": f"grep KO {str(e)[:60]}"})
            continue
        if not av and not ap:
            ecartes.append({"sha": c["sha"][:8], "why": "aucun signal trace a ce commit"})
            continue
        eteintes = av - ap
        fiche = {"sha": c["sha"][:8], "sujet": c["sujet"][:90],
                 "avant": len(av), "apres": len(ap), "eteintes": len(eteintes),
                 "exemples": sorted(eteintes)[:3]}
        (vus if eteintes else rate).append(fiche)
    juges = len(vus) + len(rate)
    return {
        "axe": nom_axe, "unite": "repo (signal, pas fichier)",
        "commits_juges": juges, "commits_ecartes": len(ecartes),
        "fichiers_illisibles": 0,       # sans objet : l'unite est l'arbre, pas le fichier
        "rappel_pct": round(100.0 * len(vus) / juges, 1) if juges else None,
        "vus_par_ligne": 0, "vus_par_extinction": len(vus),
        "bruit_hors_cible_pct": None,   # sans objet : pas de ligne cible
        "vus": vus[:8], "RATES": rate[:20], "ecartes": ecartes[:6],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-05-01")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--axis", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--coupe", default="",
                    help="date de split calibration/holdout (defaut: mediane, imprimee)")
    ap.add_argument("--sans-split", action="store_true",
                    help="mesure globale seulement (deconseille : pas d anti-surapprentissage)")
    a = ap.parse_args()

    commits = commits_de_correction(a.since, a.limit)
    if not commits:
        print(json.dumps({"ok": False, "erreur": "0 commit de correction — git muet ou "
                                                 "compte sans acces au depot"}, ensure_ascii=False))
        return 2
    noms = [a.axis] if a.axis else (list(AXES) + list(AXES_REPO))
    calib, holdout, coupe = ([], [], "") if a.sans_split else split_temporel(commits, a.coupe)
    res = {"commits_echantillonnes": len(commits), "since": a.since, "axes": {},
           "split": {"coupe": coupe, "calibration": len(calib), "holdout": len(holdout)}
           if coupe else {"actif": False}}
    for n in noms:
        if n in AXES_REPO:                       # axe a l'echelle de l'arbre
            r = backtest_repo(n, commits)
            r["familles"] = ["repo"]
            r["famille_declaree"] = True
            if coupe and holdout:
                r["calibration"] = {"rappel_pct": backtest_repo(n, calib)["rappel_pct"],
                                    "juges": len(calib)}
                r["holdout"] = {"rappel_pct": backtest_repo(n, holdout)["rappel_pct"],
                                "juges": len(holdout)}
            res["axes"][n] = r
            continue
        if n not in AXES:
            res["axes"][n] = {"erreur": f"axe inconnu, dispo={list(AXES)}"}
            continue
        r = backtest(n, commits)
        if coupe and holdout:
            rc, rh = backtest(n, calib), backtest(n, holdout)
            r["calibration"] = {"rappel_pct": rc["rappel_pct"], "juges": rc["commits_juges"]}
            r["holdout"] = {"rappel_pct": rh["rappel_pct"], "juges": rh["commits_juges"]}
            # Un axe qui s effondre sur des commits jamais vus est surajuste,
            # pas un capteur. Le dire ICI, pas dans une note de bas de page.
            c_pct, h_pct = rc["rappel_pct"] or 0.0, rh["rappel_pct"] or 0.0
            r["SURAJUSTE"] = bool(c_pct >= 10.0 and h_pct < c_pct / 2)
        res["axes"][n] = r

    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    sp = res.get("split") or {}
    print(f"BACKTEST sur {len(commits)} commits de correction depuis {a.since}")
    if sp.get("coupe"):
        print(f"  split temporel a {sp['coupe']} : calibration {sp['calibration']} "
              f"/ holdout {sp['holdout']} (le holdout n a JAMAIS servi a ecrire l axe)")
    print()
    for n, r in res["axes"].items():
        if "erreur" in r:
            print(f"  {n}: {r['erreur']}")
            continue
        print(f"  {n}   [familles: {', '.join(r['familles'])}"
              + ("" if r.get("famille_declaree") else " — NON DECLARE, suppose py seul") + "]")
        print(f"    rappel      : {r['rappel_pct']}%  ({r['commits_juges']} commits juges, "
              f"{r['commits_ecartes']} ecartes, {r['fichiers_illisibles']} fichiers illisibles)")
        print(f"      dont      : {r['vus_par_ligne']} par ligne reparee, "
              f"{r['vus_par_extinction']} par EXTINCTION de l'alerte")
        print(f"    hors cible  : {r['bruit_hors_cible_pct']}%  (a crie dans le fichier, "
              f"mais pas sur la ligne reparee)")
        if "holdout" in r:
            print(f"    calibration : {r['calibration']['rappel_pct']}% "
                  f"({r['calibration']['juges']} juges)   "
                  f"HOLDOUT : {r['holdout']['rappel_pct']}% ({r['holdout']['juges']} juges)"
                  + ("   ⚠️ SURAJUSTE" if r.get("SURAJUSTE") else ""))
        for m in r["RATES"][:6]:
            print(f"    RATE  {m['sha']}  {m['sujet']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
