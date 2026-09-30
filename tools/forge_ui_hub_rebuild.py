"""Recompile l'artefact servi du hub depuis ses sources de reference.

POURQUOI CET OUTIL EXISTE (mesure du 2026-09-18).

`design_handoff_nokido/ui_kits/hub/hub-compiled.js` est ce que le navigateur
execute ; `hub-shell.ref.jsx` et `hub-views.ref.jsx` sont ce qu'on relit et ce
qu'on corrige. Entre les deux, il faut une compilation -- et elle n'etait
declenchee par rien.

Consequence MESUREE : la correction qui rendait cliquables les onze tuiles
« etat non mesure », ecrite le 2026-09-17 dans `hub-views.ref.jsx`, etait bien
presente dans l'artefact ; mais celle du logo, ecrite le 2026-09-18, ne pouvait
pas y arriver, et le compte qui fait tourner les agents ne peut PAS ecrire dans
ce dossier (`EPERM` mesure sur `node build-hub.js`). Un correctif de design qui
n'atteint jamais l'ecran se relit comme un correctif applique.

CE QUE CET OUTIL N'EST PAS. Il n'ecrit rien lui-meme : il appelle le builder
git-tracke du depot (`build-hub.js`), qui est la seule autorite sur le format de
sortie. Il n'est pas non plus un deployeur : le piege du 2026-09-14 est connu --
un deployeur de bundle aurait ecrase un artefact du 11 septembre par un fichier
du 20 juin, soit quatre-vingt-trois jours de regression sur un fichier maintenu
a la main, donc irrecuperable. Rien ici ne copie un artefact d'ailleurs.

LE GARDE. Une recompilation qui RETRECIT fortement la sortie, ou qui en fait
disparaitre des reperes attendus, est refusee : sur un artefact que personne ne
sait reconstruire autrement, mieux vaut ne rien ecrire que d'ecrire moins.
"""
from __future__ import annotations

__FORGE_COLOR__ = "interface:design/build"

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DOSSIER = RACINE / "design_handoff_nokido" / "ui_kits" / "hub"
BUILDER = DOSSIER / "build-hub.js"
ARTEFACT = DOSSIER / "hub-compiled.js"
SOURCES = (DOSSIER / "hub-shell.ref.jsx", DOSSIER / "hub-views.ref.jsx")

# Reperes que la sortie DOIT contenir. Ils ne decrivent pas un style : ce sont
# les composants que la coquille expose et sans lesquels la page est blanche.
REPERES = ("HubSidebar", "HubTopbar", "React.createElement")
# En dessous de cette part de la taille precedente, on refuse : une sortie qui
# fond de moitie signale un builder qui a echoue en silence, pas une
# simplification.
PART_MINIMALE = 0.60


def _dire(msg: str) -> None:
    print(msg, flush=True)


def recompiler(applique: bool = False) -> int:
    for chemin in (BUILDER, *SOURCES):
        if not chemin.exists():
            _dire("ABSENT : %s -- rien n'est tente" % chemin)
            return 2
    avant = ARTEFACT.read_text(encoding="utf-8", errors="replace") if ARTEFACT.exists() else ""
    _dire("artefact avant : %d caracteres" % len(avant))
    for s in SOURCES:
        _dire("  source %-22s %s" % (s.name, time.strftime(
            "%Y-%m-%d %H:%M", time.localtime(s.stat().st_mtime))))
    if not applique:
        _dire("DRY-RUN : rien n'est ecrit. Relancer avec --apply pour recompiler.")
        return 0

    faute = _accent_grave_en_commentaire(BUILDER)
    if faute:
        _dire("REFUS AVANT BUILD : %s" % faute)
        return 1

    secours = ARTEFACT.with_suffix(".js.avant_rebuild")
    if avant:
        shutil.copy2(ARTEFACT, secours)
        _dire("copie de secours : %s" % secours.name)

    r = subprocess.run([shutil.which("node") or "node", BUILDER.name],
                       cwd=str(DOSSIER), capture_output=True, text=True,
                       errors="replace", timeout=180)
    if r.stdout.strip():
        _dire(r.stdout.strip()[:1200])
    if r.returncode != 0:
        _dire("BUILDER EN ECHEC (rc=%d) : %s" % (r.returncode, (r.stderr or "")[:600]))
        return 1

    apres = ARTEFACT.read_text(encoding="utf-8", errors="replace")
    _dire("artefact apres : %d caracteres" % len(apres))
    manquants = [x for x in REPERES if x not in apres]
    trop_petit = bool(avant) and len(apres) < len(avant) * PART_MINIMALE
    rompues = _liaisons_window_rompues(apres)
    if manquants or trop_petit or rompues:
        if avant:
            ARTEFACT.write_text(avant, encoding="utf-8")
            _dire("RESTAURE l'artefact precedent.")
        _dire("REFUS : %s%s%s" % (
            ("reperes manquants %s " % manquants) if manquants else "",
            ("sortie tombee a %.0f%% de la precedente " % (100.0 * len(apres) / max(len(avant), 1)))
            if trop_petit else "",
            ("composants lus sur window sans etre poses nulle part : %s" % rompues)
            if rompues else ""))
        return 1
    _dire("OK : recompile, %d reperes presents, aucune liaison window rompue." % len(REPERES))
    return 0


def _accent_grave_en_commentaire(builder) -> str:
    """Refuse un accent grave dans un commentaire de ligne du builder.

    PAYE DEUX FOIS LE 2026-09-18, et la seconde fois en ayant ecrit l'avertissement
    soi-meme douze lignes plus bas dans le fichier. Le JSX de `build-hub.js` vit dans un
    litteral gabarit : un accent grave dans un commentaire REFERME la chaine, et le build
    meurt en SyntaxError a une ligne qui n'a rien a voir avec la faute.

    Le diagnostic coute cher parce que node pointe la ligne ou la syntaxe devient
    invalide, pas celle qui a ouvert le probleme. D'ou ce controle AVANT le build : il
    nomme la ligne fautive, ce que le message de node ne fait pas.

    Une lecon qui ne devient pas un garde se repaye -- celle-ci l'a ete dans l'heure.
    """
    try:
        lignes = builder.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return "builder illisible (%s)" % type(exc).__name__
    fautives = []
    for i, ligne in enumerate(lignes, 1):
        nu = ligne.lstrip()
        if nu.startswith("//") and "`" in ligne:
            fautives.append("L%d : %s" % (i, nu[:70]))
    if not fautives:
        return ""
    return ("accent grave dans %d commentaire(s) de %s -- il referme le litteral "
            "gabarit et le build mourra en SyntaxError ailleurs : %s"
            % (len(fautives), builder.name, " | ".join(fautives[:3])))


def _liaisons_window_rompues(artefact: str, voisins: bool = True) -> list:
    """Composants CONSOMMES sur `window` que plus aucun bundle charge n'y affecte.

    POURQUOI CE GARDE EXISTE (regression du 2026-09-18, causee par cet outil meme).
    Les deux controles precedents -- reperes presents, taille >= 60 % -- regardaient la
    QUANTITE et la PRESENCE, jamais la COHERENCE. Une recompilation a donc produit un
    artefact parfaitement volumineux, portant tous ses reperes, et dans lequel les six
    vues du hub etaient appelees par `window.ViewX` alors que RIEN n'affecte ces
    proprietes : `React.createElement(undefined)` leve, les six vues cassent, et aucun
    controle ne le voyait. Le cablage local avait ete pose a la main dans l'artefact
    COMPILE le 2026-09-11 ; regenerer depuis une source non corrigee l'a efface.

    Lecon generale : un garde de regeneration doit verifier que la sortie se TIENT, pas
    seulement qu'elle est grosse et qu'elle contient les bons mots.

    On ne retient que les identifiants en PascalCase -- la convention des composants
    React. `window.location`, `window.matchMedia` et consorts sont des proprietes
    natives : les signaler ferait crier le garde a faux, et un garde qui crie a faux se
    fait desarmer.
    """
    import re as _re

    # Le `\b` n'est PAS decoratif. Sans lui, `\w*` est gourmand et le lookahead le fait
    # RECULER d'un caractere jusqu'a reussir : sur `window.HubIco =`, le moteur renonce a
    # `HubIco` (suivi de `=`) et retient `HubIc`, un nom qui n'existe pas. Mesure du
    # 2026-09-18 : le garde a refuse un build correct en citant `HubIc`, `HubSideba` et
    # `HubTopba`. Avec `\b`, toute troncature echoue parce qu'une lettre suit.
    lus = set(_re.findall(r"window\.([A-Z]\w*)\b(?!\s*=)", artefact))
    if not lus:
        return []
    poses = _poses_sur_window(artefact)
    # `voisins=False` sert aux TESTS : sans ce drapeau, la fonction melangeait l'artefact
    # qu'on lui donne et les fichiers reels du disque, si bien qu'un artefact temoin
    # volontairement rompu etait blanchi par le vrai bundle. Un garde qu'on ne peut pas
    # eprouver sur une entree choisie ne se teste pas, il se constate.
    if not voisins:
        return sorted(lus - poses)
    # Les autres bundles charges par la page peuvent legitimement poser ces globales.
    for voisin in sorted(DOSSIER.glob("*.js")) + sorted(DOSSIER.parent.parent.glob("*.js")):
        try:
            poses |= _poses_sur_window(voisin.read_text(encoding="utf-8", errors="replace"))
        except OSError:  # noqa: PERF203 — un voisin illisible n'est pas un voisin absent
            _dire("  (voisin illisible, non compte : %s)" % voisin.name)
    return sorted(lus - poses)


def _poses_sur_window(code: str) -> set:
    """Globales REELLEMENT posees sur window, quelle que soit la FORME de l'affectation.

    ERREUR PAYEE LE 2026-09-18, et c'est la plus instructive de la journee. Ce garde ne
    cherchait que `window.X =`. Or le bundle expose ses vues par
    `Object.assign(window, { ViewAccueil, ... })` -- une affectation parfaitement
    valide que ce motif ne voit pas. Le garde a donc declare six liaisons rompues sur
    un artefact SAIN, j'ai "corrige" la lecture en retirant `window.`, et comme chaque
    module vit dans son IIFE, les six vues sont passees hors de portee : le hub s'est
    mis a lever a l'affichage. Le garde n'a pas rate un defaut, il en a FABRIQUE un.

    Lecon, deja ecrite ailleurs dans ce depot et re-payee ici : un motif litteral
    absent ne prouve pas que la chose est absente. On mesure ce qui est POSE, pas ce
    qui est ECRIT d'une certaine facon.
    """
    import re as _re

    poses = set(_re.findall(r"window\.([A-Z]\w*)\s*=", code))
    # Forme 2 : Object.assign(window, { A, B, C }) — y compris `A: valeur`.
    for bloc in _re.findall(r"Object\.assign\(\s*window\s*,\s*\{([^}]*)\}", code, _re.S):
        for frag in bloc.split(","):
            nom = frag.split(":")[0].strip()
            if _re.fullmatch(r"[A-Z]\w*", nom or ""):
                poses.add(nom)
    return poses


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--apply", action="store_true",
                   help="recompile reellement (sans ce drapeau, rien n'est ecrit)")
    a = p.parse_args(argv)
    return recompiler(applique=a.apply)


if __name__ == "__main__":
    raise SystemExit(main())
