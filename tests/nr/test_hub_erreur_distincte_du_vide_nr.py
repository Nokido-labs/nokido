# -*- coding: utf-8 -*-
"""NR U1.2 — un echec HTTP ne s'ecrit pas dans la valeur du VIDE.

CE QUE CE TEST EMPECHE DE REVENIR (mesure du 2026-09-11, temoin
`tools/forge_ui_contrat_etats.py`, verdict INDISTINCT sur deux vues) :

    persona  : LOADING == DATA_VIDE == ERROR   -> une seule empreinte pour trois etats
    accueil  : LOADING == ERROR                -> « Chargement… » pour un echec definitif

La cause tient en deux gestes, tous deux presents dans la page Hub :

    .then(r => r.ok ? r.json() : [])      <- l'echec HTTP devient une donnee valide
    .catch(() => setMem([]))              <- l'echec reseau devient une donnee valide

Le meme fichier porte DEJA la forme correcte, sur `/api/hub/modules` :

    .then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)))
    .catch(e => setErr(String(e && e.message || e)))

Ce NR ne demande donc rien de neuf : il exige que les cinq autres appels fassent ce
que le sixieme fait deja.

DEUX FICHIERS, PAS UN. `hub-views.ref.jsx` est la source lue par les humains,
`hub-compiled.js` est l'artefact SERVI au navigateur. Le second n'est pas regenere
depuis la premiere (`tools/deploy_hub_bundle.py` est un COPIEUR, et le compilateur
externe date de trois mois avant le bundle du depot) : corriger la source seule
laisserait l'utilisateur devant le defaut intact.

POURQUOI UN DETECTEUR TESTE. Un controle qui cherche un mot dans un texte se trompe
dans les deux sens et ne le dit jamais. Les deux premiers tests ci-dessous verifient
le DETECTEUR sur des echantillons fabriques -- l'un fautif, l'autre correct -- avant
que les suivants ne l'appliquent aux vrais fichiers. Sans cela, un detecteur casse
rendrait « 0 defaut » et passerait pour une preuve.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus node (l.162)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
HUB = RACINE / "design_handoff_nokido" / "ui_kits" / "hub"
SOURCE = HUB / "hub-views.ref.jsx"
BUNDLE = HUB / "hub-compiled.js"

# Nombre d'appels `/api/hub/*` mesures le 2026-09-11 dans chacun des deux fichiers.
# Affirme comme plancher : un denominateur qui peut sortir vide doit etre dit non vide,
# sinon le test se tait en paraissant rigoureux.
FETCH_ATTENDUS = 6

# Fenetre de lecture apres un `fetch(` : la chaine `.then().then().catch()` tient
# largement dedans dans les deux fichiers. La borne est DITE quand elle n'est pas
# trouvee, jamais avalee.
FENETRE = 1200
FIN_DE_CHAINE = "}, []);"

DEBUT = re.compile(r'fetch\(\s*"(/api/hub/[a-z_]+)"')

# L'echec HTTP transforme en valeur de succes.
ECRASE_STATUT = re.compile(r"r\.ok\s*\?\s*r\.json\(\)\s*:\s*(\[\]|null|\{\})")

# L'echec reseau transforme en valeur de succes. Couvre `() =>` comme `e =>` :
# c'est la VALEUR posee qui est fautive, pas la presence d'un parametre.
CATCH_MUET = re.compile(r"\.catch\(\s*\(?\s*\w*\s*\)?\s*=>\s*set\w+\(\s*(\[\]|null|\{\})\s*\)")


def chaines_fetch(texte: str) -> list:
    """Rend [(endpoint, chaine, borne_trouvee)] pour chaque appel `/api/hub/*`."""
    trouve = []
    for m in DEBUT.finditer(texte):
        fenetre = texte[m.start(): m.start() + FENETRE]
        coupe = fenetre.find(FIN_DE_CHAINE)
        trouve.append((m.group(1), fenetre[:coupe] if coupe != -1 else fenetre, coupe != -1))
    return trouve


def defauts(chaine: str) -> list:
    """Rend les defauts d'UNE chaine fetch. Liste vide = la chaine propage l'echec."""
    d = []
    if ECRASE_STATUT.search(chaine):
        d.append("statut HTTP non-ok transforme en valeur vide")
    if CATCH_MUET.search(chaine):
        d.append("catch qui pose une valeur vide au lieu d'un etat d'erreur")
    return d


FAUTIF = '''fetch("/api/hub/persona", { credentials: "same-origin" })
  .then((r) => (r.ok ? r.json() : []))
  .then((d) => setMem(Array.isArray(d) ? d : []))
  .catch(() => setMem([]));
}, []);'''

CORRECT = '''fetch("/api/hub/modules", { credentials: "same-origin" })
  .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
  .then((d) => setMods(Array.isArray(d) ? d : []))
  .catch((e) => setErr(String(e && e.message || e)));
}, []);'''


def test_le_detecteur_voit_les_deux_gestes_fautifs():
    """Sans ce controle, un detecteur casse rendrait « 0 defaut » et passerait
    pour une preuve d'innocence."""
    d = defauts(FAUTIF)
    assert len(d) == 2, "le detecteur doit voir les DEUX gestes, il a vu %r" % d


def test_le_detecteur_acquitte_la_forme_deja_correcte():
    """La forme de reference vit deja dans le fichier : si le detecteur la refusait,
    il exigerait quelque chose que le code ne peut pas satisfaire."""
    assert defauts(CORRECT) == []


@pytest.mark.parametrize("fichier", [SOURCE, BUNDLE], ids=["source_jsx", "bundle_servi"])
def test_le_denominateur_est_affirme_non_vide(fichier):
    """Un fichier renomme, deplace ou lu avec le mauvais encodage rendrait zero
    chaine -- et zero defaut. Le plancher transforme ce silence en echec."""
    assert fichier.exists(), "fichier absent: %s" % fichier
    chaines = chaines_fetch(fichier.read_text(encoding="utf-8", errors="replace"))
    assert len(chaines) >= FETCH_ATTENDUS, (
        "%s : %d appels /api/hub/* trouves, au moins %d attendus — le detecteur ne "
        "lit pas ce qu'il croit lire" % (fichier.name, len(chaines), FETCH_ATTENDUS))
    sans_borne = [e for e, _c, ok in chaines if not ok]
    assert not sans_borne, (
        "fin de chaine %r introuvable pour %s : la fenetre de lecture ne couvre pas "
        "l'appel, le verdict porterait sur un texte tronque" % (FIN_DE_CHAINE, sans_borne))


@pytest.mark.parametrize("fichier", [SOURCE, BUNDLE], ids=["source_jsx", "bundle_servi"])
def test_aucun_appel_hub_n_ecrase_l_echec_dans_le_vide(fichier):
    """LE contrat. Un echec doit rester distinguable d'une donnee legitimement vide."""
    texte = fichier.read_text(encoding="utf-8", errors="replace")
    fautifs = []
    for endpoint, chaine, _ok in chaines_fetch(texte):
        d = defauts(chaine)
        if d:
            fautifs.append("%s -> %s" % (endpoint, " + ".join(d)))
    assert not fautifs, (
        "%s : %d appel(s) rendent un echec indistinguable d'une donnee vide :\n  %s\n"
        "Forme attendue, deja presente sur /api/hub/modules dans ce meme fichier : "
        "rejeter le statut non-ok et poser un etat d'erreur dans le catch."
        % (fichier.name, len(fautifs), "\n  ".join(fautifs)))


def test_le_bundle_servi_reste_du_javascript_valide():
    """`hub-compiled.js` se patche A LA MAIN — `tools/deploy_hub_bundle.py` est un
    COPIEUR, pas un generateur, et le compilateur externe est plus ancien de trois
    mois que le bundle du depot. Une parenthese de trop dans du JSX compile ne casse
    pas un test Python : elle casse la page, en silence, chez l'utilisateur.

    Si node est absent, le test est SKIP et le dit — un skip visible, jamais un vert
    qui n'a rien verifie.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent — parsabilite du bundle NON VERIFIEE (ce n'est pas un succes)")
    # `errors="replace"` n'est pas une precaution de style : en mode texte sans lui,
    # un octet non decodable dans la sortie fait crasher le thread de lecture de
    # subprocess, et le test echoue en accusant le bundle.
    r = subprocess.run([node, "--check", str(BUNDLE)],
                       capture_output=True, text=True, errors="replace", timeout=60)
    assert r.returncode == 0, (
        "%s n'est pas du JavaScript valide :\n%s" % (BUNDLE.name, (r.stderr or r.stdout)[:1500]))
