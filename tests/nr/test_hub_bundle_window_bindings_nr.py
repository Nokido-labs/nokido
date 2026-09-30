#!/usr/bin/env python3
"""test_hub_bundle_window_bindings_nr.py — tout `window.X` CONSOMME doit etre AFFECTE.

INCIDENT GARDE, mesure du 2026-09-11 (chantier U0/U1 de l interface).

Le Hub servait une page parfaite et AVEUGLE : 58 839 caracteres de DOM, 47 ressources
chargees, et ZERO donnee du corps. Cause racine prouvee : `hub-app.jsx` consomme les
cinq vues via `React.createElement(window.ViewAccueil, ...)` alors qu AUCUNE couche
ne les affecte a `window` -- ni la source des vues (`hub-views.ref.jsx`), ni la source
de l app, ni le bundle compile, ni `_ds_bundle.js`. `window.ViewAccueil` valait donc
`undefined`, `React.createElement(undefined)` levait, le rendu de `App` cassait APRES
que le HTML et le CSS statiques soient peints, et le `useEffect` de `ViewAccueil` --
donc `fetch('/api/hub/overview')` -- n etait JAMAIS execute.

CE QUI REND CE DEFAUT INVISIBLE, et pourquoi un garde STRUCTUREL est necessaire :
la page repond 200, le DOM est volumineux, aucune requete ne tombe en erreur. Une
sonde qui mesure « la page se charge » la declare verte. Le contrat casse ne vit pas
dans un fichier mais ENTRE deux fichiers, et aucun des deux n est fautif isolement.

CE QUE CE NR N EST PAS : il ne prouve pas que l interface fonctionne. Il verifie une
condition NECESSAIRE (les symboles se resolvent), jamais suffisante. La preuve
comportementale -- `/api/hub/overview` reellement appelee dans un navigateur -- est un
test distinct, et l absence de celui-ci ne doit pas etre comblee par celui-la.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
HUB = RACINE / "design_handoff_nokido" / "ui_kits" / "hub"

# PERIMETRE : la page HUB, et elle seule.
#
# Les FOURNISSEURS sont tous les scripts que la page charge -- c est `_ds_bundle.js`
# qui affecte HubTopbar, HubSidebar, HubIco, et `laforge-prefs.js` qui est charge en
# premier. Les CONSOMMATEURS, eux, sont le bundle du Hub et sa source : ce que
# `_ds_bundle.js` consomme pour SON compte regarde les douze autres pages qui le
# chargent, pas celle-ci.
#
# Cette distinction n affaiblit pas le contrat, elle l ATTRIBUE. Mesure du
# 2026-09-11 : le meme contrat est casse pour 13 symboles de `_ds_bundle.js`
# (AnatomyView, RagView, SwarmView...), sur 13 pages. C est une DETTE distincte
# (DESIGN_SYSTEM_WINDOW_BINDINGS), a couvrir par son propre garde -- la faire porter
# par celui-ci le rendrait rouge en permanence pour des surfaces hors mission, et un
# garde durablement rouge finit desarme.
FOURNISSEURS = [
    RACINE / "design_handoff_nokido" / "assets" / "laforge-prefs.js",
    RACINE / "design_handoff_nokido" / "_ds_bundle.js",
    HUB / "hub-compiled.js",
]
CONSOMMATEURS = [HUB / "hub-compiled.js"]
SOURCES = [HUB / "hub-app.jsx", HUB / "hub-views.ref.jsx"]

# CE QUE CE CONTRAT COUVRE, et pourquoi il est aussi etroit.
#
# Le defaut mesure est : un COMPOSANT passe a `React.createElement` doit etre
# resolvable, sinon l appel LEVE et tout le rendu s arrete. On ne cherche donc pas
# tous les `window.X`, mais ceux qui atterrissent dans un createElement -- en JSX
# comme en JS compile.
#
# Contre-exemple garde a l esprit : `const PREF = window.LaForgePrefs` (hub-compiled
# L346 et L1252) n a AUCUN fournisseur non plus, mais il est lu derriere une garde
# (`PREF ? PREF.get(...) : []`). Il degrade en SILENCE, il ne casse pas le rendu.
# C est un defaut REEL et d une autre NATURE, suivi separement -- l inclure ici
# melangerait « la page ne rend plus » et « une preference est perdue », deux
# urgences qui n ont rien a voir.
CONSOMME = re.compile(
    r"createElement\(\s*window\.([A-Z][A-Za-z0-9_]{2,})"     # bundle compile
    r"|<\s*window\.([A-Z][A-Za-z0-9_]{2,})")                  # source JSX
AFFECTE = re.compile(r"window\.([A-Z][A-Za-z0-9_]{2,})\s*=")
# SECONDE FORME D AFFECTATION, et elle a coute cher (2026-09-18).
#
# `hub-views.ref.jsx` termine par UNE ligne qui pose ses six vues d un coup :
#     Object.assign(window, { ViewAccueil, ViewCap, ViewMaison, ... });
# C est une affectation globale parfaitement valide, que la regex ci-dessus ne voit
# pas. Le garde declarait donc SIX vues orphelines alors que le bundle les posait.
#
# Ce faux positif n est pas theorique : c est exactement lui qui m a fait conclure, le
# matin meme, que six vues etaient cassees. La « correction » qui a suivi -- retirer le
# prefixe `window.` cote consommateur -- a mis les vues HORS PORTEE (chaque module du
# bundle vit dans sa propre IIFE, `window` est le seul pont entre blocs) et a servi un
# bundle reellement casse. Le garde avait tort, et on a casse le code pour lui donner
# raison.
#
# Le meme aveuglement existait dans `tools/forge_ui_hub_rebuild._poses_sur_window`, qui
# a ete corrige le jour meme. Celui-ci ne l avait pas ete : DEUX gardes portant le meme
# controle, un seul repare. C est le motif « un seul defaut par garde » du depot, paye
# une fois de plus -- quand un controle est duplique, il faut corriger TOUTES ses copies
# ou n en garder qu une.
#
# Reconnaitre cette forme n ASSOUPLIT rien : un composant lu et pose nulle part reste
# un echec (cf. test_le_controle_sait_refuser_une_forme_non_posee).
AFFECTE_ASSIGN = re.compile(r"Object\.assign\(\s*window\s*,\s*\{([^}]*)\}", re.DOTALL)


def _noms_assignes_en_bloc(texte: str) -> set[str]:
    """Noms poses par `Object.assign(window, {...})`.

    On lit les CLES, pas les valeurs : dans `{Public: Interne}` c est `Public` qui
    devient global. La forme abregee `{Vue}` a la cle et la valeur confondues.
    """
    trouves: set[str] = set()
    for bloc in AFFECTE_ASSIGN.findall(texte):
        for morceau in bloc.split(","):
            cle = morceau.split(":", 1)[0].strip()
            if re.fullmatch(r"[A-Z][A-Za-z0-9_]{2,}", cle):
                trouves.add(cle)
    return trouves
# Globaux fournis par des tiers ou le navigateur, jamais par nos bundles.
EXTERNES = {"React", "ReactDOM", "Promise", "Object", "Array", "String", "Number",
            "Math", "JSON", "Date", "Map", "Set", "Boolean", "Error", "URL",
            "FormData", "Headers", "Request", "Response", "WebSocket", "EventSource",
            "MutationObserver", "IntersectionObserver", "ResizeObserver"}


# Les commentaires PARLENT des symboles sans les consommer. Mesure du 2026-09-11 :
# la ligne « Sert les vraies vues (window.View*) » de hub-compiled.js a produit un
# faux positif nomme `View`. Un garde qui crie a faux se fait desarmer -- on retire
# donc les commentaires AVANT de chercher, plutot que d ajouter `View` a une liste
# d exceptions, ce qui aurait masque le defaut suivant du meme genre.
_COMMENTAIRE = re.compile(r"/\*.*?\*/|(?<![:\w])//[^\n]*", re.DOTALL)


def _lire(p: Path) -> str:
    """Le contenu SANS ses commentaires, ou '' si illisible (l illisibilite est DITE)."""
    try:
        return _COMMENTAIRE.sub(" ", p.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""


def bindings(fichiers) -> tuple[set[str], set[str], list[str]]:
    """(consommes, affectes, illisibles) sur l ensemble des fichiers donnes."""
    consommes, affectes, illisibles = set(), set(), []
    for p in fichiers:
        if not p.exists():
            illisibles.append(f"{p.name} ABSENT")
            continue
        t = _lire(p)
        if not t:
            illisibles.append(f"{p.name} ILLISIBLE")
            continue
        for paires in CONSOMME.findall(t):
            for n in (paires if isinstance(paires, tuple) else (paires,)):
                if n and n not in EXTERNES:
                    consommes.add(n)
        affectes |= set(AFFECTE.findall(t))
        affectes |= _noms_assignes_en_bloc(t)
    return consommes, affectes, illisibles


def test_le_denominateur_n_est_pas_vide():
    """Un scan qui ne trouve rien passerait tous les tests suivants en silence.

    C est le defaut mesure le 2026-09-10 : un instrument qui rend VIDE parait
    rigoureux. On exige donc que les fichiers existent et portent des bindings.
    """
    consommes, _c, illisibles = bindings(CONSOMMATEURS)
    _x, affectes, ill2 = bindings(FOURNISSEURS)
    illisibles += ill2
    assert not illisibles, f"fichiers du Hub non lus : {illisibles}"
    # UN SEUIL CALIBRE SUR L ETAT CASSE DEVIENT FAUX DES QU ON REPARE. Premiere
    # version : `>= 3` consommations, mesuree quand il y en avait 8 dont 6 fautives.
    # Le patch en a supprime 6, il en reste 2 -- LEGITIMES, fournies par _ds_bundle
    # (HubSidebar, HubTopbar). Le garde criait donc sur le succes. Ce qu il doit
    # verifier est que les regex MORDENT ENCORE, pas qu un defaut subsiste.
    assert consommes, (
        "aucune consommation `createElement(window.X)` trouvee : la regex ne mord "
        "plus (bundle reformate, minifie, ou motif change) -- le contrat serait "
        "vert par aveuglement")
    assert len(affectes) >= 3, (
        f"seulement {len(affectes)} affectation(s) window reperee(s) : le scan des "
        "FOURNISSEURS est suspect (_ds_bundle en declare au moins trois)")


def test_tout_composant_consomme_via_window_est_affecte_quelque_part():
    """LE contrat. Il vit ENTRE les fichiers, jamais dans un seul."""
    consommes, _c, _i = bindings(CONSOMMATEURS)
    _x, affectes, _j = bindings(FOURNISSEURS)
    orphelins = sorted(consommes - affectes)
    assert not orphelins, (
        "composant(s) lus sur `window` sans qu AUCUN bundle charge ne les y affecte "
        f": {orphelins}\n"
        "  -> `window.X` vaut undefined, React.createElement(undefined) leve, et le "
        "rendu casse APRES le HTML statique : la page parait saine et n affiche "
        "aucune donnee.\n"
        "  -> corriger en consommant le symbole LOCAL (il est dans la meme portee) "
        "plutot qu en ajoutant un global de plus.")


def test_le_controle_sait_refuser_une_forme_non_posee():
    """MORSURE — apprendre `Object.assign` ne doit pas rendre le garde permissif.

    Sans cette contre-epreuve, elargir la reconnaissance serait indistinguable de
    desarmer le controle : les deux rendent le test vert.
    """
    pose = "Object.assign(window, { ViewAccueil, ViewCap });"
    assert _noms_assignes_en_bloc(pose) == {"ViewAccueil", "ViewCap"}
    # Les valeurs ne sont PAS des globaux : seule la cle le devient.
    assert _noms_assignes_en_bloc("Object.assign(window, { Public: Interne });") == {"Public"}
    # Un assign qui ne vise PAS window ne pose aucun global.
    assert _noms_assignes_en_bloc("Object.assign(cible, { ViewAccueil });") == set()
    # Et une vue consommee que personne ne pose reste ORPHELINE.
    consommes = {"ViewAccueil", "ViewFantome"}
    affectes = _noms_assignes_en_bloc(pose)
    assert sorted(consommes - affectes) == ["ViewFantome"], \
        "le garde ne repererait plus un composant lu et pose nulle part"


def test_la_source_consommatrice_est_coherente_avec_le_bundle():
    """Si la source garde l indirection, la prochaine compilation ramene le bug.

    `hub-compiled.js` n est pas regenere par le depot (le compilateur vit hors
    arbre, cf. tools/deploy_hub_bundle.py qui ne fait qu une copie). Corriger le
    seul artefact servi laisserait donc le contrat casse dans la source.
    """
    consommes_src, affectes_src, illisibles = bindings(SOURCES)
    assert not illisibles, f"sources du Hub non lues : {illisibles}"
    _, affectes_bundle, _ = bindings(FOURNISSEURS)
    orphelins = sorted(consommes_src - affectes_src - affectes_bundle)
    assert not orphelins, (
        f"la SOURCE lit encore sur `window` des composants que personne n affecte : "
        f"{orphelins}\n"
        "  -> le bundle servi peut etre corrige a la main, la source le "
        "reintroduirait a la prochaine compilation.")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
