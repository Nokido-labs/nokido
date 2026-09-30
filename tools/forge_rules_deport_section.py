"""forge_rules_deport_section.py — deporter UNE section de regles hors du noyau resident.

Le noyau resident (RULES_SHARED.md + CLAUDE.md + MEMORY.md) est re-envoye a CHAQUE
tour de CHAQUE session : un octet y coute N fois, pas une. `forge_context_budget.py`
mesure ce noyau et le plafonne ; ce module-ci est le geste qui le fait BAISSER.

Il DEPLACE, il ne supprime jamais -- regle owner du 2026-09-03. Et il verifie la
reconstitution AVANT d'ecrire : le 2026-09-02, une edition de RULES_SHARED.md a
DETRUIT 31 775 octets en emportant deux sections voisines, ce qui a exige d'ecrire
`tools/forge_rules_restore.py`. Le garde central ci-dessous (`avant + section +
apres == original`) existe pour que cela ne se reproduise pas.

Contrat :
  - dry-run par DEFAUT (comme forge_rules_restore) ; `--appliquer` pour ecrire ;
  - refus si le titre ne designe pas EXACTEMENT une section ;
  - refus si la cible existe deja (on n'ecrase pas une deportation anterieure) ;
  - la CIBLE est ecrite AVANT que la source soit modifiee : si le second temps
    echoue, le contenu existe en deux endroits, jamais en zero ;
  - un pointeur remplace la section : une section deportee sans pointeur est une
    section perdue pour le lecteur qui ne sait pas qu'elle a bouge.

Usage :
    tools/forge_rules_deport_section.py --source RULES_SHARED.md \\
        --section "Capacites d'execution" --vers docs/RULES_CAPACITES_EXECUTION.md
    ... --appliquer
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/deport-regles"

import argparse
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

# Meme perimetre que forge_rules_restore : on ne deporte pas n'importe quel fichier.
AUTORISES = {"RULES_SHARED.md", "CLAUDE.md", "GEMINI.md", "AGENTS.md"}

_TITRE_RE = re.compile(r"(?m)^(## .+)$")


def _norm(s: str) -> str:
    """Comparaison de titres insensible aux accents et a la casse.

    Les titres portent des accents ('Capacites' vs 'Capacités') et un agent qui
    tape la commande ne les reproduira pas toujours. Tolerer la saisie, JAMAIS
    l'ambiguite : un prefixe qui designe deux sections reste un refus.
    """
    s = s.lower()
    for a, b in (("éèêë", "e"), ("àâä", "a"), ("îï", "i"), ("ôö", "o"),
                 ("ûüù", "u"), ("ç", "c")):
        for c in a:
            s = s.replace(c, b)
    return " ".join(s.split())


def decouper(texte: str):
    """[(titre, corps, debut, fin)] pour chaque section `## `."""
    bornes = [(m.start(), m.end(), m.group(1)) for m in _TITRE_RE.finditer(texte)]
    out = []
    for i, (d, f, titre) in enumerate(bornes):
        fin = bornes[i + 1][0] if i + 1 < len(bornes) else len(texte)
        out.append((titre, texte[f:fin], d, fin))
    return out


def trouver(texte: str, motif: str):
    """La section unique designee par `motif`, ou une erreur qui DIT pourquoi."""
    cible = _norm(motif)
    vus = [(t, c, d, f) for (t, c, d, f) in decouper(texte) if cible in _norm(t)]
    if not vus:
        raise SystemExit("REFUS : aucune section ne contient %r. Titres presents :\n  %s"
                         % (motif, "\n  ".join(t for t, _, _, _ in decouper(texte))))
    if len(vus) > 1:
        raise SystemExit("REFUS : %d sections contiennent %r -- preciser :\n  %s"
                         % (len(vus), motif, "\n  ".join(t for t, _, _, _ in vus)))
    return vus[0]


def _entete_cible(titre: str, source: str) -> str:
    return (
        "<!-- DEPORTE depuis %s le 2026-09-19 pour tenir le budget du noyau resident.\n"
        "     Le contenu n'a pas ete modifie : seul son LIEU a change.\n"
        "     Mesure : cette section pesait 52%% de %s, re-facture a chaque tour. -->\n\n"
        "# %s\n\n"
        "> Section de regles **deportee** hors du noyau resident. Elle n'est plus\n"
        "> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,\n"
        "> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par\n"
        "> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :\n"
        "> deporter la prose ne desarme rien.\n\n"
        % (source, source, titre.lstrip("# ").strip())
    )


def _pointeur(titre: str, vers: str, taille: int, pct: float, resume) -> str:
    """Le residu ne s'INVENTE pas : il est FOURNI, sinon on refuse.

    Defaut mesure le 2026-09-19 : ces trois puces etaient CODEES EN DUR — le
    resume de la section « Capacites d'execution » de RULES_SHARED. Deportee
    la section « Cartographie anatomique » de CLAUDE.md, le pointeur a donc
    affirme que la suite parlait de `hook_capability_gate` et de
    `forge_retrieval_sweep`. Le controle `perdu == 0` etait VRAI et ne disait
    rien la-dessus : il mesure la reconstitution de ce qui est PARTI, jamais
    l'exactitude de ce qui RESTE. Un pointeur faux est pire qu'un pointeur
    absent — il se lit comme un resume autorise.
    """
    resume = [str(x).strip() for x in (resume or []) if str(x).strip()]
    tete = (
        "%s — DEPORTEE\n\n"
        "Cette section pesait **%d caracteres, %.0f%% de ce fichier**, et le noyau\n"
        "resident est re-envoye a CHAQUE tour. Elle vit desormais dans\n"
        "[`%s`](%s) — **rien n'a ete supprime**.\n"
        % (titre, taille, pct, vers, vers))
    if not resume:
        # ABSENCE, jamais invention : un pointeur qui ne porte qu'un lien est
        # complet et vrai. `main` exige `--resume`, donc le chemin humain en a
        # toujours un ; ici on garantit seulement qu'on n'en FABRIQUE pas.
        return tete + "\n"
    return (tete + "\nCe qui reste vrai et n'a pas besoin d'etre relu pour agir :\n\n"
            + "\n".join("- %s" % b for b in resume) + "\n\n")


def deporter(source: Path, motif: str, vers: Path, appliquer: bool, resume=None,
             meme_si_plus_gros: bool = False) -> int:
    if source.name not in AUTORISES:
        raise SystemExit("REFUS : %s hors du perimetre %s" % (source.name, sorted(AUTORISES)))
    original = source.read_text(encoding="utf-8")
    titre, corps, debut, fin = trouver(original, motif)
    section = original[debut:fin]

    # Garde central : la reconstitution doit etre EXACTE avant toute ecriture.
    avant, apres = original[:debut], original[fin:]
    if avant + section + apres != original:
        raise SystemExit("REFUS : reconstitution non exacte -- rien n'est ecrit "
                         "(c'est le garde ecrit apres la destruction du 2026-09-02).")

    try:
        lien = vers.relative_to(RACINE).as_posix()
    except ValueError:  # cible hors depot (bac de test, ou deport explicite ailleurs)
        lien = vers.as_posix()
    pct = 100.0 * len(section) / len(original)
    pointeur = _pointeur(titre, lien, len(section), pct, resume)
    neuf = avant + pointeur + apres
    perdu = len(original) - (len(neuf) - len(pointeur)) - len(section)

    print("section       %s" % titre)
    print("taille        %d car. (%.1f%% de %s)" % (len(section),
                                                    100.0 * len(section) / len(original),
                                                    source.name))
    print("source        %d -> %d car. (%+d)" % (len(original), len(neuf),
                                                 len(neuf) - len(original)))
    print("cible         %s" % vers)
    print("perdu         %d car. (doit etre 0)" % perdu)
    if perdu != 0:
        raise SystemExit("REFUS : comptabilite non nulle -- rien n'est ecrit.")
    if vers.exists():
        raise SystemExit("REFUS : %s existe deja -- on n'ecrase pas une deportation." % vers)
    if len(pointeur) >= len(section) and not meme_si_plus_gros:
        # Le but du deport est de FAIRE MAIGRIR le noyau resident. Sur une petite
        # section, le pointeur coute plus cher que ce qu'il remplace : le geste se
        # retourne contre lui-meme, en silence. Mesure 2026-09-19 : pointeur 834 car.
        # pour une section de 208. Le dire, et refuser par defaut.
        raise SystemExit(
            "REFUS : le pointeur (%d car.) est plus gros que la section (%d car.) -- "
            "ce deport FERAIT GROSSIR %s au lieu de l'alleger. Deporter une section "
            "plus grosse, ou forcer avec --meme-si-plus-gros si le but n'est pas le "
            "budget." % (len(pointeur), len(section), source.name))
    if not appliquer:
        print("\n[dry-run] rien n'a ete ecrit. Ajouter --appliquer.")
        return 0

    vers.parent.mkdir(parents=True, exist_ok=True)
    # La CIBLE d'abord : si la suite echoue, le contenu est en DEUX endroits, jamais zero.
    vers.write_text(_entete_cible(titre, source.name) + section.lstrip(), encoding="utf-8")
    relu = vers.read_text(encoding="utf-8")
    if section.strip() not in relu:
        raise SystemExit("REFUS : cible relue sans la section -- source INTACTE.")
    source.write_text(neuf, encoding="utf-8")
    print("\nOK — deporte. Verifier : LAFORGE_PYTHON tools/forge_context_budget.py")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", required=True)
    ap.add_argument("--section", required=True)
    ap.add_argument("--vers", required=True)
    ap.add_argument("--resume", action="append", metavar="PUCE", default=None,
                    required=True,
                    help="Ce qui reste vrai APRES le deport, une puce par "
                         "occurrence. OBLIGATOIRE : le pointeur etait CODE EN "
                         "DUR et affirmait le resume d'une AUTRE section "
                         "(defaut paye le 2026-09-19).")
    ap.add_argument("--appliquer", action="store_true")
    ap.add_argument("--meme-si-plus-gros", action="store_true",
                    dest="meme_si_plus_gros",
                    help="deporter meme si le pointeur coute plus cher que la section")
    a = ap.parse_args(argv)
    src = Path(a.source) if Path(a.source).is_absolute() else RACINE / a.source
    dst = Path(a.vers) if Path(a.vers).is_absolute() else RACINE / a.vers
    return deporter(src, a.section, dst, a.appliquer, a.resume,
                    a.meme_si_plus_gros)


if __name__ == "__main__":
    sys.exit(main())
