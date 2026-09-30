#!/usr/bin/env python3
"""forge_signal_graph.py — GRAPHE DE SIGNAUX resolu sur l'AST + la config parsee.

Remplace le grep-sur-texte de ax17 (instable : sa sortie bougeait au gre des
regex). Ici un signal — un pouls `.heartbeat`, un flag `.wanted`, un port ZMQ —
a des ECRIVAINS et des LECTEURS resolus, pas devines :

  * l'ecriture passe presque toujours par une VARIABLE :
        HEARTBEAT = ROOT / "x.heartbeat"     # ligne 52  (liaison var -> signal)
        HEARTBEAT.write_text(...)            # ligne 68  (ecriture, sans le nom)
    Un resolveur AST suit la liaison ; un grep ligne par ligne ne le peut pas.
  * l'emission par helper : `beat_daemon("autonomous_loops")` ecrit
    autonomous_loops.heartbeat — le chemin n'apparait jamais.
  * la DECLARATION en config (`heartbeat = "..."` dans un [[service]]) n'est pas
    une ecriture mais le CONTRAT DE SURVEILLANCE : le superviseur LIT ce pouls.
    Un service `disabled = true` est ETEINT -> son pouls absent n'est pas une panne.

Sortie : {signal: {"writers": [(file,line)], "readers": [(file,line)]}}.
Asymetries = un signal LU par quelqu'un que personne n'ECRIT (garde qui surveille
un mort) ou ECRIT par quelqu'un que personne ne LIT (on parle dans le vide).

Agnostique de la source : `build_graph(files, read)` prend une liste de chemins
et un lecteur `read(path) -> str|None`. Le backtest fournit un acces `git show`
au commit ; l'usage live fournit un acces disque. AUCUN chemin en dur.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

# Un signal = un nom de fichier-flag ou un endpoint. On canonise sur le BASENAME
# (le chemin varie ; "sandbox/x.heartbeat" et "x.heartbeat" sont le meme signal).
SIG_LITTERAL = re.compile(r"([A-Za-z0-9_.\-*]+\.(?:heartbeat|wanted))$")
SIG_ENDPOINT = re.compile(r"(tcp://127\.0\.0\.1:\d+)")

WRITE_METHODS = {"write_text", "write_bytes", "touch", "dump", "mkdir"}
READ_METHODS = {"read_text", "read_bytes", "exists", "is_file", "getmtime", "stat", "load"}
WRITE_HELPERS = {"beat_daemon", "beat", "heartbeat"}   # 1er arg = nom du signal


def _canon(valeur: str) -> str | None:
    v = valeur.strip()
    m = SIG_ENDPOINT.search(v)
    if m:
        return m.group(1)
    m = SIG_LITTERAL.search(Path(v).name)
    return m.group(1) if m else None


def _litteraux(node: ast.AST) -> list:
    """Tous les fragments str constants d'une expression (Constant, BinOp `/`,
    f-string a parties constantes). Permet de reconstituer un nom de signal
    assemble par `ROOT / "x.heartbeat"` ou `f\"{base}.heartbeat\"`."""
    out = []
    if isinstance(node, ast.JoinedStr):
        pat = ""
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                pat += v.value
            elif isinstance(v, ast.FormattedValue):
                pat += "*"
        if pat:
            out.append(pat)
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return out


def _resoud_fichier(src: str, chemin: str, graphe: dict) -> None:
    try:
        arbre = ast.parse(src)
    except SyntaxError:
        return
    var_signal: dict = {}          # nom de variable -> signal canonique

    # 1re passe : liaisons variable -> signal (assignations a un litteral signal)
    for n in ast.walk(arbre):
        if isinstance(n, ast.Assign):
            sig = next((s for s in (_canon(x) for x in _litteraux(n.value)) if s), None)
            if sig:
                for cible in n.targets:
                    if isinstance(cible, ast.Name):
                        var_signal[cible.id] = sig

    def _ajoute(role: str, sig: str, ligne: int) -> None:
        graphe.setdefault(sig, {"writers": [], "readers": []})[role].append((chemin, ligne))

    # 2e passe : appels -> ecriture ou lecture d'un signal connu
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        # helper d'emission : beat_daemon("nom") -> nom.heartbeat
        nom_f = getattr(f, "id", None) or getattr(f, "attr", None)
        if nom_f in WRITE_HELPERS and n.args:
            a0 = n.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                _ajoute("writers", f"{a0.value}.heartbeat", n.lineno)
                continue
        # open(X, "w"|"a") = ecrivain ; open(X) = lecteur
        if nom_f == "open" and n.args:
            base = getattr(n.args[0], "id", None)
            sig = var_signal.get(base) or next(
                (s for s in (_canon(x) for x in _litteraux(n.args[0])) if s), None)
            if sig:
                mode = n.args[1].value if len(n.args) > 1 and isinstance(
                    n.args[1], ast.Constant) else "r"
                _ajoute("writers" if any(c in str(mode) for c in "wa") else "readers",
                        sig, n.lineno)
            continue
        # methode sur une variable liee : HEARTBEAT.write_text(...) / .exists()
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            sig = var_signal.get(f.value.id)
            if not sig:
                continue
            if f.attr in WRITE_METHODS:
                _ajoute("writers", sig, n.lineno)
            elif f.attr in READ_METHODS:
                _ajoute("readers", sig, n.lineno)


# ── Config : services.toml = contrats de surveillance ───────────────────────
_HB_LINE = re.compile(r"heartbeat\s*=\s*['\"]([^'\"]+)['\"]")
_DISABLED = re.compile(r"disabled\s*=\s*true")


def _resoud_config(src: str, chemin: str, graphe: dict) -> None:
    """Chaque [[service]] NON disabled avec un heartbeat = un LECTEUR (le
    superviseur surveille ce pouls). Un bloc disabled est ignore (service eteint)."""
    bloc: list = []
    disabled = False
    ligne_base = 0

    def _vider(depart: int) -> None:
        if disabled:
            return
        for i, b in enumerate(bloc):
            m = _HB_LINE.search(b)
            if m:
                sig = _canon(m.group(1))
                if sig:
                    graphe.setdefault(sig, {"writers": [], "readers": []})[
                        "readers"].append((chemin, depart + i))

    for i, l in enumerate(src.splitlines(), 1):
        if l.strip().startswith("[[service]]"):
            _vider(ligne_base)
            bloc, disabled, ligne_base = [], False, i
        else:
            bloc.append(l)
            if _DISABLED.search(l):
                disabled = True
    _vider(ligne_base)

def _resoud_ts(src: str, chemin: str, graphe: dict) -> None:
    """Resolveur regex basique pour les organes Deno (.ts). Les signaux sont 
    souvent ecrits / lus via Deno.writeTextFile, Deno.remove, Deno.readTextFile.
    On recupere aussi les strings litterales et on deduit le role selon le contexte."""
    for i, ligne in enumerate(src.splitlines(), 1):
        for m in SIG_LITTERAL.finditer(ligne):
            sig = _canon(m.group(1))
            if not sig:
                continue
            ligne_lower = ligne.lower()
            role = "readers" if any(x in ligne_lower for x in ("read", "stat", "watch")) else "writers"
            graphe.setdefault(sig, {"writers": [], "readers": []})[role].append((chemin, i))


def build_graph(files: list, read) -> dict:
    """Construit le graphe de signaux. `files` = chemins relatifs ; `read(path)`
    rend le contenu (ou None). .py -> AST ; services.toml -> parse config."""
    graphe: dict = {}
    for chemin in files:
        if chemin.startswith("tests/"):
            continue
        src = None
        try:
            src = read(chemin)
        except Exception:  # noqa: BLE001
            src = None
        if not src:
            continue
        if chemin.endswith(".py"):
            _resoud_fichier(src, chemin, graphe)
        elif chemin.endswith(".ts"):
            _resoud_ts(src, chemin, graphe)
        elif chemin.endswith(".toml") and "services" in chemin:
            _resoud_config(src, chemin, graphe)

    # Resolution des wildcards f-strings (ex: task_executor_*.heartbeat)
    import fnmatch
    wildcards = [s for s in graphe if '*' in s]
    for w in wildcards:
        for s in list(graphe.keys()):
            if s != w and fnmatch.fnmatch(s, w):
                graphe[s]["writers"].extend(graphe[w]["writers"])
                graphe[s]["readers"].extend(graphe[w]["readers"])
        del graphe[w]

    return graphe


def asymetries(graphe: dict) -> list:
    """Les deux pannes vecues : un garde sans emetteur, un emetteur sans lecteur."""
    out = []
    for sig, g in graphe.items():
        if g["readers"] and not g["writers"]:
            f, ln = g["readers"][0]
            out.append({"signal": sig, "verdict": "garde_sans_emetteur", "file": f, "line": ln})
        elif g["writers"] and not g["readers"]:
            f, ln = g["writers"][0]
            out.append({"signal": sig, "verdict": "emetteur_sans_lecteur", "file": f, "line": ln})
    return out
