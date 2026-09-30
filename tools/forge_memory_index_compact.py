"""forge_memory_index_compact.py — compacte un INDEX memoire markdown sans rien perdre.

Probleme resolu (mesure 2026-08-20) : `MEMORY.md` est charge en contexte a chaque
session et son lecteur a une limite dure (24,4 Ko ici). Au-dela, **tout ce qui
depasse est silencieusement coupe** — et c'est la FIN du fichier qui saute, donc
les entrees les plus anciennes, celles qui portent la doctrine. Un index qui
deborde perd exactement ce qu'on lui demande de retenir.

Principe : l'index n'est qu'une TABLE DE POINTEURS. Le detail vit deja dans les
fichiers pointes. On ne supprime donc AUCUNE ligne et AUCUNE cible de lien : on
raccourcit uniquement les LIBELLES `[texte](cible)`, du plus long au plus court,
jusqu'a passer sous la cible.

INVARIANT VERIFIE AVANT ECRITURE, sinon on n'ecrit pas :
  - meme nombre de lignes ;
  - meme liste de cibles de liens, dans le meme ordre.

Usage :
    python tools/forge_memory_index_compact.py <chemin> [--cible-ko 17.0] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

LIEN = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def _cibles(txt: str) -> list[str]:
    return [c for _, c in LIEN.findall(txt)]


def _compacter_ligne(ligne: str, budget: int) -> str:
    """Raccourcit les libelles de liens d'UNE ligne pour tenir dans `budget`."""
    if len(ligne) <= budget:
        return ligne
    liens = LIEN.findall(ligne)
    if not liens:
        return ligne  # rien a raccourcir sans perdre du texte : on laisse
    fixe = len(LIEN.sub("", ligne))
    coût_cibles = sum(len(c) + 4 for _, c in liens)
    reste = budget - fixe - coût_cibles
    par = max(24, reste // len(liens))

    def rep(m: re.Match) -> str:
        t = m.group(1)
        if len(t) <= par:
            return m.group(0)
        return "[%s…](%s)" % (t[:par].rstrip(), m.group(2))

    return LIEN.sub(rep, ligne)


def _poids(ligne: str) -> float:
    """Budget RELATIF d'une entree, selon la priorite qu'elle porte deja.

    Idee empruntee a jayzeng/agentmemory (lu le 2026-08-20) : il n'alloue pas un
    budget uniforme, il REPARTIT un budget total par section selon l'utilite
    (scratchpad 2K > topics 2K > MEMORY.md 4K > hier 3K). Transpose a un index :
    une entree de doctrine ***  ne doit pas etre rabotee autant qu'une note
    ancienne. On lit la priorite deja ECRITE dans la ligne (les etoiles), on
    n'en invente pas une.
    """
    n = ligne.count("⭐")
    if n >= 3:
        return 1.8
    if n == 2:
        return 1.15
    if n == 1:
        return 0.9
    return 0.7


def compacter(txt: str, cible_octets: int) -> tuple[str, int]:
    """Rend (texte_compacte, budget_retenu). Essaie des budgets decroissants.

    Le budget de base est PONDERE par ligne (cf `_poids`) : la doctrine garde son
    texte, la longue traine se comprime. Aucune ligne n'est jamais SUPPRIMEE —
    contrairement a une troncature de fin (qui mange les entrees les plus
    anciennes, donc la doctrine) ou du milieu.
    """
    for budget in (1200, 900, 700, 600, 520, 460, 400, 360, 320, 280, 240, 200):
        out = "\n".join(
            _compacter_ligne(l, max(140, int(budget * _poids(l)))) for l in txt.splitlines()
        ) + "\n"
        if len(out.encode("utf-8")) <= cible_octets:
            return out, budget
    return out, budget


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compacte un index memoire markdown")
    ap.add_argument("chemin")
    ap.add_argument("--cible-ko", type=float, default=17.0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    src = open(a.chemin, encoding="utf-8").read()
    avant = len(src.encode("utf-8"))
    out, budget = compacter(src, int(a.cible_ko * 1024))
    apres = len(out.encode("utf-8"))

    # INVARIANTS — un compacteur qui perd une entree est pire que pas de compacteur.
    ok_lignes = len(src.splitlines()) == len(out.splitlines())
    ok_cibles = _cibles(src) == _cibles(out)
    print("avant %.1f Ko -> apres %.1f Ko (budget/ligne=%d)" % (avant / 1024, apres / 1024, budget))
    print("lignes %d -> %d  | cibles %d -> %d | invariants: lignes=%s cibles=%s"
          % (len(src.splitlines()), len(out.splitlines()),
             len(_cibles(src)), len(_cibles(out)), ok_lignes, ok_cibles))
    if not (ok_lignes and ok_cibles):
        print("REFUS : invariant rompu, rien n'est ecrit.")
        return 2
    if apres > int(a.cible_ko * 1024):
        print("ATTENTION : cible non atteinte meme au budget minimal.")
    if a.dry_run:
        print("(dry-run : rien ecrit)")
        return 0
    shutil.copy2(a.chemin, a.chemin + ".bak")
    with open(a.chemin, "w", encoding="utf-8") as f:
        f.write(out)
    print("ECRIT (sauvegarde %s.bak)" % os.path.basename(a.chemin))
    return 0


if __name__ == "__main__":
    sys.exit(main())
