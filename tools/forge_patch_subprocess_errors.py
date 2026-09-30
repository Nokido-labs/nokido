# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "immunitaire/decodage-subprocess"
PATCH : `subprocess` en mode texte SANS `errors=` -> plantage du thread lecteur.

LE DEFAUT, MESURE LE 2026-08-05
===============================
Sur un Windows francophone, `icacls` repond en **cp1252**. Un `subprocess.run(...,
text=True)` sans `errors=` leve alors `UnicodeDecodeError` **dans `_readerthread`**,
c'est-a-dire APRES que la commande a reussi : l'ACL etait accordee, la sortie disait
« OK », et une trace de plantage suivait. De quoi croire l'operation ratee alors
qu'elle avait abouti — et, dans un daemon, de quoi tuer un thread sans que la
fonction appelante ne le sache.

C'est l'anti-regression que le git-gate signale sous « incident 47GB ».

POURQUOI CE PATCH EST MECANISABLE
=================================
Contrairement aux chemins d'erreur muets — qui demandent un jugement par site —
celui-ci a **une seule bonne reponse**. `errors="replace"` ne change aucun
comportement quand le decodage reussit ; il evite seulement la levee quand il
echoue. Le risque du patch est donc borne, et la verification (`compile()` +
relecture) le clot.

PERIMETRE ASSUME, ET IL EST PARTIEL
===================================
On ne patche QUE les appels ecrits `subprocess.<fn>(...)` — attribut sur un nom
contenant « subprocess ». Les formes `from subprocess import run` puis `run(...)`
sont VOLONTAIREMENT laissees : distinguer ce `run` d'une methode maison du meme nom
demanderait une analyse de portee, et un faux positif ici modifierait un appel qui
n'a rien a voir. Le compte des sites ecartes est AFFICHE — un filtre qui tait ce
qu'il ecarte fait surestimer sa couverture.

    LAFORGE_PYTHON tools/forge_patch_subprocess_errors.py            # dry-run
    LAFORGE_PYTHON tools/forge_patch_subprocess_errors.py --apply
"""
from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MORT = ("backups", "_attic", "inspirations", "swebench", "eval_repos", "node_modules",
        "__pycache__", "tests", "RAG_plain_bak", ".venv", "site-packages")
APPELS = {"run", "Popen", "check_output", "call", "check_call"}
AJOUT = 'errors="replace"'


def _alias_subprocess(arbre) -> set:
    """Noms locaux qui designent le module `subprocess` DANS CE FICHIER.

    Amelioration du 2026-08-05 : la premiere version exigeait que le nom contienne
    « subprocess », ce qui ecartait `import subprocess as _sp` — 9 appels laisses de
    cote, tous authentiques. Deviner sur le nom etait le mauvais critere ; LIRE les
    imports du fichier est exact et ne peut pas produire de faux positif sur une
    methode maison qui s'appellerait `run`.
    """
    noms = {"subprocess"}
    for n in ast.walk(arbre):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name == "subprocess" and a.asname:
                    noms.add(a.asname)
    return noms


def _cibles(src: str):
    """(ligne, col_fin) des appels subprocess en mode texte sans errors=.

    Rend aussi le nombre d'appels ECARTES faute d'etre surement des subprocess."""
    try:
        arbre = ast.parse(src)
    except SyntaxError:
        return [], 0
    alias = _alias_subprocess(arbre)
    trouves, ecartes = [], 0
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Call):
            continue
        nom = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
        if nom not in APPELS:
            continue
        kw = {k.arg for k in n.keywords if k.arg}
        if not any(k in kw for k in ("text", "universal_newlines", "encoding")):
            continue
        if "errors" in kw:
            continue
        # SUR = attribut sur un nom que les IMPORTS de ce fichier lient a subprocess.
        # Reste ecarte : `from subprocess import run` puis `run(...)`, ou distinguer
        # ce `run` d'une methode maison exigerait une analyse de portee.
        base = getattr(getattr(n.func, "value", None), "id", "") or ""
        if base not in alias:
            ecartes += 1
            continue
        trouves.append((n.end_lineno, n.end_col_offset))
    return trouves, ecartes


def _inserer(src: str, cibles) -> str:
    """Insere `errors="replace"` juste avant la parenthese fermante de chaque appel.

    On travaille en OFFSETS ABSOLUS sur la source entiere, et non ligne par ligne.
    Defaut mesure le 2026-08-05 : la premiere version ne regardait que la ligne
    courante pour decider s'il fallait une virgule. Or dans la forme la plus
    frequente

        subprocess.run(
            [...],
            text=True,
        )

    la ')' est SEULE sur sa ligne et la virgule finale se trouve a la ligne
    PRECEDENTE : on produisait `,\\n, errors=...` — six fichiers abandonnes au
    `compile()`. Le garde a fait son travail ; l'insertion, non.

    On traite du DERNIER au PREMIER : une insertion decale les positions suivantes.
    """
    # table des offsets de debut de ligne
    debuts, acc = [], 0
    for ligne in src.splitlines(keepends=True):
        debuts.append(acc)
        acc += len(ligne)
    out = src
    for ln, col in sorted(cibles, reverse=True):
        if ln - 1 >= len(debuts):
            continue
        pos = debuts[ln - 1] + col - 1  # index absolu de la ')'
        if pos < 0 or pos >= len(out) or out[pos] != ")":
            continue  # forme inattendue : on s'abstient plutot que de deviner
        # Dernier caractere significatif AVANT la parenthese, quelles que soient les
        # lignes traversees.
        j = pos - 1
        while j >= 0 and out[j] in " \t\r\n":
            j -= 1
        sep = "" if (j >= 0 and out[j] == ",") else ", "
        out = out[:pos] + sep + AJOUT + out[pos:]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ajoute errors=replace aux subprocess texte")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limite", type=int, default=0, help="ne traiter que N fichiers")
    a = ap.parse_args(argv)

    total_sites = total_fichiers = total_ecartes = echecs = 0
    for sous in ("app", "tools"):
        for base, dirs, files in os.walk(ROOT / sous):
            dirs[:] = [d for d in dirs if d not in MORT]
            if any(m in base.replace("\\", "/") for m in MORT):
                continue
            for f in sorted(files):
                if not f.endswith(".py"):
                    continue
                p = Path(base) / f
                rel = str(p.relative_to(ROOT)).replace("\\", "/")
                if rel == "tools/forge_patch_subprocess_errors.py":
                    continue
                try:
                    src = p.read_text(encoding="utf-8")
                except Exception:  # noqa: BLE001
                    print("  [illisible] %s" % rel)
                    continue
                cibles, ecartes = _cibles(src)
                total_ecartes += ecartes
                if not cibles:
                    continue
                patche = _inserer(src, cibles)
                if patche == src:
                    continue
                try:
                    compile(patche, rel, "exec")
                except SyntaxError as e:
                    echecs += 1
                    print("  [ABANDON] %s : le resultat ne compile pas (%s l.%s)"
                          % (rel, e.msg, e.lineno))
                    continue
                total_fichiers += 1
                total_sites += len(cibles)
                print("  %-52s %d site(s)" % (rel, len(cibles)))
                if a.apply:
                    p.write_text(patche, encoding="utf-8")
                    if p.read_text(encoding="utf-8") != patche:
                        p.write_text(src, encoding="utf-8")
                        print("     RELECTURE DIFFERENTE -> restaure")
                        return 1
                if a.limite and total_fichiers >= a.limite:
                    break
            if a.limite and total_fichiers >= a.limite:
                break

    print("\n%d site(s) dans %d fichier(s) %s"
          % (total_sites, total_fichiers, "PATCHES" if a.apply else "a patcher"))
    print("%d appel(s) ECARTES (forme non surement subprocess : `from subprocess "
          "import run` puis `run(...)`) — perimetre partiel ASSUME" % total_ecartes)
    if echecs:
        print("%d fichier(s) abandonnes car le resultat ne compilait pas" % echecs)
    if not a.apply:
        print("DRY-RUN — relancer avec --apply pour ecrire")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
