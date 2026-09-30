#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_archeo_socle.py — socle commun des outils d'archeologie et d'audit.

POURQUOI. Le cliquet de duplication a mordu le 2026-08-18 (run GHA 32077672167) :
six groupes de clones NOUVEAUX, tous entre les outils d'archeologie ajoutes les
trois jours precedents. Le diagnostic etait exact -- `_git`, `_est_bruit` et
`decouvrir` etaient recopies a l'identique dans huit fichiers, et le squelette
`main` (argparse `--json` + rendu) dans huit autres.

Un helper recopie huit fois, c'est huit endroits ou corriger le prochain defaut
de `safe.directory` -- et sept qu'on oubliera. Ce module est la reponse : une
seule definition, importee.

LECTURE SEULE : aucune fonction d'ici n'ecrit dans un depot analyse.

Import depuis un outil de `tools/` :

    from forge_archeo_socle import git, est_bruit, decouvrir_depots, cli, sortie
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/audit : socle commun des outils d'archeologie et d'audit"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import os
import re
import socket
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(ROOT)
CLONES = os.path.join(ROOT, "sandbox", "archaeology_clones")

# Repertoires dont l'histoire n'est pas du patrimoine owner (deps vendored).
BRUIT_CHEMIN = ("node_modules/", "site-packages/", ".venv/", "venv/",
                "dist/", "build/", "__pycache__/", "attic/", "backups/")

CODE_EXT = {".py", ".ps1", ".ts", ".tsx", ".js", ".jsx", ".sh", ".rs", ".go",
            ".c", ".cpp", ".h", ".swift", ".java", ".cs", ".rb", ".sql"}
DOC_EXT = {".md", ".json", ".yml", ".yaml", ".toml"}

# Depots freres du super-repo, tentes systematiquement.
DEPOTS_VOISINS = ("netcfg-agent", "netcfg-agent-mcp", "netcfg-agent-tui",
                  "netcfg-agent-web", "laforge-cowork", "PentestGPT", "xbox-llm")


def git(depot, *args, timeout=300):
    """git en LECTURE SEULE ; `safe.directory=*` neutralise le dubious ownership
    (le job tourne sous un compte different du proprietaire des dossiers).

    Rend "" sur echec : l'appelant distingue le vide du plantage par le CONTENU
    attendu, jamais par un code de retour qu'on ne lui donne pas.
    """
    cmd = ["git", "-c", "safe.directory=*", "-C", depot] + list(args)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return p.stdout if p.returncode == 0 else ""
    except Exception:
        return ""


def git_rc(repo, *args, timeout=120):
    """Variante de `git` qui rend (rc, sortie).

    Certains appelants ont besoin de DISTINGUER "git a repondu vide" de "git a
    echoue" -- ils ne peuvent pas se contenter du "" de `git()`.
    """
    try:
        r = subprocess.run(["git", "-c", "safe.directory=*", "-C", repo, *args],
                           capture_output=True, text=True, errors="replace",
                           timeout=timeout)
        return r.returncode, (r.stdout or "")
    except Exception as e:  # noqa: BLE001
        return -1, "%s: %s" % (type(e).__name__, e)


def bruit_motifs(chemin, motifs, prefixes=()):
    """Bruit PARAMETRABLE : chaque outil a son idee de ce qui n'est pas du
    patrimoine (l'archeologie ecarte `test_`, l'indexeur non)."""
    c = str(chemin).replace("\\", "/")
    base = c.rsplit("/", 1)[-1]
    return any(m in c for m in motifs) or (bool(prefixes) and base.startswith(prefixes))


def est_bruit(chemin):
    """Vrai si le chemin appartient a une dependance vendored, pas au patrimoine."""
    return bruit_motifs(chemin, BRUIT_CHEMIN)


def depots_candidats(extra=(), inclure_workspace=True):
    """Candidats a analyser, dans l'ordre de priorite. `extra` : "nom=chemin"."""
    cands = []
    if inclure_workspace:
        cands.append(("nokido-workspace", WORKSPACE))
    cands.append(("nokido", ROOT))
    for d in DEPOTS_VOISINS:
        cands.append((d, os.path.join(WORKSPACE, d)))
    if os.path.isdir(CLONES):
        for d in sorted(os.listdir(CLONES)):
            cands.append((d, os.path.join(CLONES, d)))
    for spec in extra:
        if "=" in spec:
            nom, chemin = spec.split("=", 1)
            cands.append((nom, chemin))
    return cands


def decouvrir_depots(extra=(), inclure_workspace=True):
    """Depots reellement lisibles -> (depots, refuses).

    Un depot TU est pire qu'un depot absent : il fabrique un silence que le
    rapport presente ensuite comme une couverture complete. Les refus sont donc
    rendus, jamais avales.
    """
    depots = {}
    refuses = {}
    for nom, chemin in depots_candidats(extra, inclure_workspace):
        if nom in depots:
            continue
        if not os.path.exists(chemin):
            refuses.setdefault(nom, "chemin invisible sous ce compte (ACL ou absent)")
            continue
        if git(chemin, "rev-parse", "--git-dir", timeout=20).strip():
            # Un clone accessible prime sur un chemin refuse du meme depot :
            # sinon l'ACL du premier candidat masque une source lisible.
            depots[nom] = chemin
            refuses.pop(nom, None)
        else:
            refuses.setdefault(nom, "git refuse l'acces sous ce compte")
    return depots, refuses


def port_ouvert(port, timeout=0.4):
    """Un port TCP ecoute-t-il en local ? Sonde de PRESENCE, jamais de sante :
    un port ouvert ne prouve pas que l'application repond (cf. etat `degraded`
    de forge_ui_manifest)."""
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex(("127.0.0.1", int(port))) == 0
    except OSError:
        return False
    finally:
        s.close()


# Lien markdown vers un fichier memoire : `](nom_du_fichier.md)`.
LIEN_MEMOIRE = re.compile(r"\]\(([A-Za-z0-9_.-]+\.md)\)")


def liens_memoire(chemin):
    """Fichiers memoire cites par un index (chaud ou froid). Absent -> vide."""
    p = chemin if hasattr(chemin, "read_text") else None
    if p is None:
        if not os.path.exists(chemin):
            return set()
        with open(chemin, encoding="utf-8", errors="replace") as fh:
            return set(LIEN_MEMOIRE.findall(fh.read()))
    if not p.exists():
        return set()
    return set(LIEN_MEMOIRE.findall(p.read_text(encoding="utf-8", errors="replace")))


def noms_par(dico, cle, valeur):
    """Noms dont l'entree porte `dico[nom][cle] == valeur`, tries.

    Regroupement d'un rapport par verdict : recopie a l'identique dans
    forge_provider_reachability et forge_capability_execution_trace.
    """
    return sorted(n for n, d in dico.items() if d.get(cle) == valeur)


def cli(description, **options):
    """Parseur commun des outils d'audit : `--json` partout, le reste par mot-cle.

        a = cli("mon audit", seuil={"type": int, "default": 30})
    """
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--json", action="store_true")
    for nom, spec in options.items():
        ap.add_argument("--" + nom.replace("_", "-"), **spec)
    return ap.parse_args()


def sortie(res, json_mode, rendu, code=None):
    """Rendu unique des outils d'audit.

    Le code de retour vient du CONTENU mesure (`code(res)`), jamais du fait
    d'avoir tourne sans planter -- c'est la distinction rc/contenu que l'owner
    a du rappeler trois fois le 2026-08-12.
    """
    if json_mode:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    else:
        rendu(res)
    return int(code(res)) if code else 0


def ecrire_json(chemin, obj):
    """Ecrit un rapport, cree le repertoire, rend le chemin relatif a ROOT."""
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, default=str)
    return os.path.relpath(chemin, ROOT)
