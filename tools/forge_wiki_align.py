#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_wiki_align.py - aligne les noms de modules ET de commandes du wiki sur le code.

Commandes (2026-09-29) : les commandes installees renommees au cutover LaForge -> Nokido
(`laforge-vault` -> `nokido-vault`...) ne sont remplacees que si la cible est declaree dans
pyproject [project.scripts] et la source ne l'est plus, verifie a chaque passage.

Le balayage feature_checklist (2026-08-27) a montre que le wiki nomme des modules
sous un nom qui n'existe PAS comme fichier, alors qu'une variante existe. Seuls les
renommages SURS (le vrai fichier existe, le nom du wiki n'en est pas un, et la
correspondance est semantiquement evidente) sont appliques ici -- les cas ambigus
(forge_exec, forge_jepa core absent) sont laisses a l'humain, car un mauvais nom
colle dans la doc se propage (RAG, atlas).

Remplacement par FRONTIERE DE MOT + lookahead negatif : `forge_mcts` -> `forge_mcts_engine`
ne doit jamais transformer `forge_mcts_engine` en `forge_mcts_engine_engine`.

    run action=trusted_script path=tools/forge_wiki_align.py            # applique
    run action=trusted_script path=tools/forge_wiki_align.py --dry-run  # montre
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/coherence-doc-code"

import argparse
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIKI = os.path.join(ROOT, "docs", "wiki")
PYPROJECT = os.path.join(ROOT, "pyproject.toml")

# Renommages SURS uniquement (verifies : vrai fichier present, nom wiki absent).
TABLE = {
    "forge_brain_worker": "brain_worker",
    "forge_mcts": "forge_mcts_engine",
    "forge_spike_router_service": "forge_spike_router",
    "forge_litellm": "forge_litellm_bridge",
    "forge_mpc_planner": "forge_mpc",
}

# Commandes INSTALLEES renommees au cutover LaForge -> Nokido (2026-07) : 110 citations
# mortes dans le wiki au 2026-09-29 (revue des pages > 60 j). SURES seulement si la cible
# est DECLAREE dans pyproject [project.scripts] ET que la source ne l'est plus -- verifie a
# CHAQUE passage (`commandes_sures`) : une table qui ment sur le code ne s'applique pas.
# `laforge-hub` n'y est PAS : c'est aussi le NOM DU SERVICE Docker (compose), toujours
# valide ; la commande `nokido-hub` se corrige a la main, au cas par cas.
COMMANDES = {
    "laforge-secrets": "nokido-secrets",
    "laforge-vault": "nokido-vault",
    "laforge-cli": "nokido-cli",
}


def scripts_declares(texte_pyproject: str) -> set:
    """Noms de [project.scripts] (vide si la section manque : rien n'est alors applique)."""
    if "[project.scripts]" not in texte_pyproject:
        return set()
    section = texte_pyproject.split("[project.scripts]", 1)[1].split("\n[", 1)[0]
    return set(re.findall(r'^\s*"?([A-Za-z0-9][\w.-]*)"?\s*=\s*"', section, re.M))


def commandes_sures(texte_pyproject: str) -> tuple:
    """(appliquees, ecartees) : une commande n'est renommee que si sa cible existe et sa source plus."""
    scripts = scripts_declares(texte_pyproject)
    sures = {a: b for a, b in COMMANDES.items() if b in scripts and a not in scripts}
    return sures, sorted(set(COMMANDES) - set(sures))


def main() -> int:
    ap = argparse.ArgumentParser(description="Aligne les noms de modules du wiki sur les vrais fichiers")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        with open(PYPROJECT, encoding="utf-8") as f:
            sures, ecartees = commandes_sures(f.read())
    except OSError as exc:
        sures, ecartees = {}, sorted(COMMANDES)
        print(f"[commandes] pyproject ILLISIBLE ({type(exc).__name__}) : aucune commande renommee")
    if ecartees:
        print(f"[commandes] NON appliquees (cible non declaree ou source encore declaree) : {ecartees}")
    motifs = [(re.compile(r"\b" + re.escape(faux) + r"(?!\w)"), vrai) for faux, vrai in TABLE.items()]
    # Une commande est un mot a TIRETS : ni suivie d'un tiret (`laforge-vault-x` n'est pas elle),
    # ni precedee d'un separateur de chemin (`logs/laforge-cli.log` est un fichier, pas elle).
    motifs += [(re.compile(r"(?<![\w/.\\-])" + re.escape(faux) + r"(?![\w-])"), vrai)
               for faux, vrai in sures.items()]

    total = 0
    touches: dict[str, int] = {}
    for path in sorted(glob.glob(os.path.join(WIKI, "*.md"))):
        txt = open(path, encoding="utf-8", errors="replace").read()
        if "<!-- nokido:genere" in txt:
            # Page GENEREE (20-Modules-Reference) : la regeneration effacerait la retouche ; un
            # nom perime y vient d'une DOCSTRING, c'est la source qui se corrige (2026-09-29).
            print(f"   {os.path.basename(path)} : page generee, ecartee")
            continue
        neuf = txt
        n_page = 0
        for motif, vrai in motifs:
            # le nom entier, jamais un prefixe d'un nom plus long
            neuf, k = motif.subn(vrai, neuf)
            n_page += k
        if n_page and neuf != txt:
            touches[os.path.basename(path)] = n_page
            total += n_page
            if not args.dry_run:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(neuf)
    mode = "DRY-RUN" if args.dry_run else "APPLIQUE"
    print(f"[{mode}] {total} remplacement(s) sur {len(touches)} page(s)")
    for p, n in sorted(touches.items()):
        print(f"   {p}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
