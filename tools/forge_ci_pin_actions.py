"""Epingle les actions GitHub des workflows sur un SHA, au lieu d'un tag mobile.

REVUE DEFENSIVE SUPPLY-CHAIN du 2026-09-19, point 4. Tous les workflows
referencaient leurs actions par tag (`@v7`, `@v4`) ou par BRANCHE
(`@release/v1`). Un tag git se redeplace : celui qui controle le depot d'une
action peut faire pointer `v7` ailleurs, et la CI executera ce code au prochain
declenchement, sans qu'aucun diff du depot ne bouge.

CE QUI REND CE POINT CONCRET ICI, et pas seulement theorique :
  - la CI est SELF-HOSTED, donc ces actions s'executent sur la machine de
    l'owner, pas sur un runner jetable ;
  - `pypa/gh-action-pypi-publish` etait reference par une BRANCHE
    (`release/v1`), et c'est l'action qui PUBLIE sur PyPI.

Un SHA ne se redeplace pas. Le tag reste ecrit en commentaire pour que la
lisibilite ne soit pas perdue — c'est la forme recommandee par GitHub, et sans
elle personne ne saura plus quelle version est epinglee.

CE QUE CET OUTIL N'EST PAS : un resolveur. Il n'appelle pas le reseau et ne
decide rien. La table ci-dessous a ete resolue une fois, a la main, via l'API
GitHub, et elle est RELUE EN DIFF a chaque modification — c'est precisement ce
qu'on veut d'un epinglage. Rafraichir une version est un geste DELIBERE : on
resout le nouveau SHA, on l'ecrit ici, on relit le diff.

Usage :
    forge_ci_pin_actions.py             (dry-run : dit ce qui changerait)
    forge_ci_pin_actions.py --apply
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/chaine-approvisionnement"

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"

# reference telle qu'ecrite dans les workflows -> (sha, tag lisible)
# Resolue le 2026-09-19 via l'API GitHub (`repos/<o>/<r>/commits/<ref>` et
# GraphQL pour les tags annotes).
EPINGLES: dict[str, tuple[str, str]] = {
    "actions/checkout@v7": ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7"),
    "actions/setup-python@v7": ("5fda3b95a4ea91299a34e894583c3862153e4b97", "v7"),
    "actions/setup-go@v7": ("b7ad1dad31e06c5925ef5d2fc7ad053ef454303e", "v7"),
    "actions/upload-artifact@v7": ("043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", "v7"),
    "actions/download-artifact@v8": ("3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c", "v8"),
    "gitleaks/gitleaks-action@v3": ("e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e", "v3"),
    # `@v2` n'existe PAS comme tag chez cet auteur : c'etait une reference
    # mobile. Epingle sur v2.6.1, la plus recente de la serie v2 au 2026-09-19.
    "contributor-assistant/github-action@v2": (
        "ca4a40a7d1004f18d9960b404b97e5f30a505a08", "v2.6.1"),
    "docker/setup-qemu-action@v4": ("99012661954931238ded8c8b007157a8430204e1", "v4"),
    "docker/setup-buildx-action@v4": ("f87e5991a6d7451dcb8d9637bfbc97413f497069", "v4"),
    "docker/login-action@v4": ("dbcb813823bdd20940b903addbd779551569679f", "v4"),
    "docker/metadata-action@v6": ("dc802804100637a589fabce1cb79ff13a1411302", "v6"),
    "docker/build-push-action@v7": ("c3c9e263c25d99ce0380d002d59b67737d91b0dc", "v7"),
    "astral-sh/setup-uv@v7": ("37802adc94f370d6bfd71619e3f0bf239e1f3b78", "v7"),
    # BRANCHE, pas meme un tag — et c'est l'action qui publie sur PyPI.
    "pypa/gh-action-pypi-publish@release/v1": (
        "dc37677b2e1c63e2034f94d8a5b11f265b73ba33", "release/v1"),
}


def _remplacer(texte: str) -> tuple[str, dict[str, int]]:
    """Remplace chaque reference mobile par son SHA, tag conserve en commentaire.

    On remplace la reference COMPLETE (`owner/action@tag`) et jamais le seul
    tag : `@v7` seul apparait chez plusieurs actions differentes, et un
    remplacement par morceaux melangerait leurs SHA. On traite aussi les
    references les plus LONGUES d'abord, pour qu'une reference qui en prefixe
    une autre ne la mange pas.
    """
    compte: dict[str, int] = {}
    for ref in sorted(EPINGLES, key=len, reverse=True):
        sha, tag = EPINGLES[ref]
        if ref not in texte:
            continue
        n = texte.count(ref)
        base = ref.split("@", 1)[0]
        texte = texte.replace(ref, f"{base}@{sha} # {tag}")
        compte[ref] = n
    return texte, compte


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true", help="ecrire reellement")
    a = p.parse_args()

    if not WORKFLOWS.is_dir():
        print(f"[pin] {WORKFLOWS} introuvable")
        return 2

    total = 0
    restants: list[str] = []
    for f in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        avant = f.read_text(encoding="utf-8")
        apres, compte = _remplacer(avant)
        if compte:
            total += sum(compte.values())
            detail = ", ".join(f"{k.split('/')[-1]}x{v}" for k, v in compte.items())
            print(f"[pin] {f.name:26} {sum(compte.values()):>3} ref(s) : {detail}")
            if a.apply and apres != avant:
                f.write_text(apres, encoding="utf-8")
        # CE QUI RESTE MOBILE DOIT ETRE DIT. Un epinglage partiel qu'on croit
        # complet est pire qu'un epinglage absent : il rassure.
        for ligne in apres.splitlines():
            s = ligne.strip()
            if s.startswith(("- uses:", "uses:")) and "@" in s and "#" not in s:
                restants.append(f"{f.name}: {s}")

    print(f"\n[pin] {total} reference(s) {'epinglee(s)' if a.apply else 'a epingler (dry-run)'}")
    if restants:
        print(f"[pin] RESTENT MOBILES ({len(restants)}) — non couvertes par la table :")
        for r in restants:
            print(f"        {r}")
    else:
        print("[pin] aucune reference mobile restante")
    return 0


if __name__ == "__main__":
    sys.exit(main())
