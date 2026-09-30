# -*- coding: utf-8 -*-
"""NR — la vue fédérée agrège, elle n'arbitre pas et n'invente aucune arête.

__FORGE_COLOR__ = "observabilite/trace : non-regression du contrat de la vue federee"

CE QUE CETTE VUE EXISTE POUR EMPÊCHER (2026-09-07). Nokido porte plusieurs instruments
de câblage, et deux d'entre eux se **contredisent** : `module_wiring` dit `ORPHELIN`
là où `forge_body_regulation_audit` dit `INVOQUE`. Mesuré au premier passage :
**72 modules**, tous dans le même sens. Un vote entre les deux effacerait
l'information ; l'écart EST le renseignement.

Ce NR verrouille quatre propriétés, chacune payée cette nuit :

  1. la vue ne rend **aucun verdict** — aucune fonction n'arbitre un désaccord ;
  2. chaque arête porte `source`, `observe_le` et `authority: false` — une vue
     fédérée accélère l'exploration, elle ne certifie rien ;
  3. un artefact absent rend **ILLISIBLE avec son motif**, jamais une liste vide qui
     se relirait « aucune arête » ;
  4. `NON_COUVERT` (hors périmètre) ≠ `ABSENT` (regardé, rien trouvé) ≠ `ILLISIBLE`.
     Confondre les trois est la faute qui a fait lire « 0 importeur » comme « mort »
     alors que le module était invoqué par 14 fichiers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_wiring_view as w  # noqa: E402

SRC = ROOT / "tools" / "forge_wiring_view.py"


def _artefacts(tmp_path, monkeypatch, wiring, cards):
    """Rebranche les DEUX sources sur des artefacts fabriques — test hermetique."""
    fw = tmp_path / "wiring.json"
    fc = tmp_path / "cards.json"
    fw.write_text(json.dumps(wiring), encoding="utf-8")
    fc.write_text(json.dumps(cards), encoding="utf-8")
    monkeypatch.setattr(w, "RACINE", tmp_path)
    monkeypatch.setattr(w, "SOURCES", {
        "module_wiring": {"artefact": "wiring.json", "producteur": "x", "axe": "cablage"},
        "regulation": {"artefact": "cards.json", "producteur": "y", "axe": "regulation"},
        "census": {"artefact": "cards.json", "producteur": "z", "axe": "organe"},
    })


# --- 1. la vue n'arbitre jamais ---------------------------------------------------

def test_aucune_fonction_n_arbitre() -> None:
    """Verrou de CONCEPTION : si quelqu'un ajoute un arbitre, ce test rougit.

    C'est la seule chose qui empeche la vue de devenir un juge par glissement."""
    import re
    src = SRC.read_text(encoding="utf-8", errors="replace")
    defs = re.findall(r"^\s*def\s+(\w+)", src, re.M)
    interdits = [d for d in defs
                 if re.search(r"(arbitr|trancher|decide|verdict|resoudre|choisir)", d, re.I)]
    assert not interdits, (
        "une vue federee AGREGE : elle ne tranche pas un desaccord entre sources. "
        "Trouve : %r" % interdits)


def test_le_desaccord_porte_un_arbitrage_vide(tmp_path, monkeypatch) -> None:
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [{"module": "m", "chemin": "app/m.py", "etat": "ORPHELIN",
                            "voies": [], "defini": True, "teste": False}]},
               {"app/m.py": {"regulation": "INVOQUE", "regulation_why": "cite par 2",
                             "organ": "cognition"}})
    d = w.desaccords()
    assert len(d) == 1, "le desaccord doit etre VU"
    assert d[0]["arbitrage"] is None, "il ne doit pas etre RESOLU"
    assert d[0]["module_wiring"]["etat"] == "ORPHELIN"
    assert d[0]["regulation"]["etat"] == "INVOQUE"


# --- 2. provenance et autorité ----------------------------------------------------

def test_chaque_arete_porte_sa_provenance_et_authority_false(tmp_path, monkeypatch) -> None:
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [{"module": "m", "chemin": "app/m.py", "etat": "BRANCHE",
                            "voies": ["importe par 3 module(s)"]}]},
               {"app/m.py": {"regulation": "CABLE", "regulation_why": "importe par 3",
                             "organ": "memoire"}})
    d = w.module("app/m.py")
    assert d["aretes"], "les trois sources doivent produire des aretes"
    for a in d["aretes"]:
        assert a["authority"] is False, (
            "une vue federee ne certifie RIEN : authority reste false, meme a "
            "confiance elevee — confidence et authority sont ORTHOGONAUX")
        assert a["source"] in ("module_wiring", "regulation", "census")
        assert "observe_le" in a, "une arete sans date ne se re-verifie pas"


# --- 3. et 4. les trois trous, jamais confondus -----------------------------------

def test_artefact_absent_rend_illisible_et_nomme_le_motif(tmp_path, monkeypatch) -> None:
    """« je n'ai pas pu regarder » ne se lit jamais « il n'y a rien »."""
    monkeypatch.setattr(w, "RACINE", tmp_path)
    monkeypatch.setattr(w, "SOURCES", {
        "module_wiring": {"artefact": "absent.json", "producteur": "relancer X", "axe": "c"},
    })
    s = w.sources()["module_wiring"]
    assert s["etat"] == "ILLISIBLE"
    assert "absent" in s["motif"], "le motif doit NOMMER ce qu'on n'a pas pu lire"
    assert s["producteur"], "il doit dire QUOI relancer pour combler le trou"
    d = w.module("app/m.py")
    assert d["aretes"] == []
    assert d["silences"]["module_wiring"]["etat"] == "ILLISIBLE", (
        "un artefact manquant n'est PAS un module sans arete")


def test_hors_perimetre_est_non_couvert_pas_absent(tmp_path, monkeypatch) -> None:
    """HORS PERIMETRE = autre couche. Le nom de ce test etait juste, son entree non :
    il visait `app/jamais_vu.py`, MEME dossier et MEME extension que la fiche presente
    -- c'est-a-dire un ABSENT, pas un trou de couverture. Il ne passait que parce que
    le code confondait encore les deux, la confusion meme qu'il pretendait interdire."""
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [{"module": "autre", "chemin": "app/autre.py",
                            "etat": "BRANCHE", "voies": ["importe par 1 module(s)"]}]},
               {"app/autre.py": {"regulation": "CABLE", "organ": "x"}})
    d = w.module("proxy_deno/core/supervisor.ts")
    assert d["aretes"] == []
    etats = {s["etat"] for s in d["silences"].values()}
    assert etats == {"NON_COUVERT"}, (
        "une autre couche n'est ni ILLISIBLE ni « aucune arete » : %s" % etats)


def test_fiche_presente_mais_champ_absent_est_non_couvert(tmp_path, monkeypatch) -> None:
    """Le module est connu de la source, mais CET axe ne le couvre pas.

    C'est le cas des 233 cartes sans champ `regulation` : lues a la main, elles
    m'ont fait annoncer une regression inexistante."""
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [{"module": "m", "chemin": "app/m.py", "etat": "BRANCHE",
                            "voies": ["importe par 1 module(s)"]}]},
               {"app/m.py": {"organ": "cognition"}})     # ni regulation, ni why
    d = w.module("app/m.py")
    assert d["silences"]["regulation"]["etat"] == "NON_COUVERT"
    assert any(a["source"] == "census" for a in d["aretes"]), "le census, lui, couvre"


# --- garde-fous de methode --------------------------------------------------------

def test_la_vue_ne_lance_aucun_instrument() -> None:
    """`forge_body_regulation_audit` INGERE meme sans argument (cache + RAG reecrits).

    Une vue en lecture ne le declenche jamais au passage : elle lit des artefacts
    DEJA produits, et dit quoi relancer quand ils manquent."""
    src = SRC.read_text(encoding="utf-8", errors="replace")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    for interdit in ("subprocess", "Popen", "os.system", "run_job"):
        assert interdit not in code, (
            "la vue ne doit rien EXECUTER : %r trouve" % interdit)


# --- nature du desaccord : classer sans designer de vainqueur ---------------------

def test_un_desaccord_de_perimetre_n_est_pas_un_conflit(tmp_path, monkeypatch) -> None:
    """70 des 72 premiers desaccords venaient de la : la regulation compte les
    citations dans hook/config/script, `module_wiring` ne les scanne pas. Les
    compter comme conflits aurait remplace un bazar de modules par un bazar de
    72 conflits."""
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [{"module": "m", "chemin": "app/m.py", "etat": "ORPHELIN",
                            "voies": []}]},
               {"app/m.py": {"regulation": "INVOQUE",
                             "regulation_why": "cite par 3 fichier(s) (hook/config/script), sans import"}})
    p = w.pourquoi()
    assert len(p) == 1
    assert p[0]["nature"] == "PERIMETRE_D_ARETE"
    assert p[0]["qui_a_raison"] is None, "classer la NATURE n'est pas designer un vainqueur"


def test_un_import_contradictoire_est_un_conflit_a_instruire(tmp_path, monkeypatch) -> None:
    """Les DEUX sources scannent les imports : la contradiction est reelle.

    Mesure du 2026-09-07, et les deux cas tombent en sens OPPOSES — `forge_code_ast`
    a bien 2 importeurs (la regulation a raison), `forge_hw` n'en a aucun (wiring a
    raison). Aucun instrument n'est autoritaire, d'ou `qui_a_raison = None`."""
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [{"module": "m", "chemin": "app/m.py", "etat": "ORPHELIN",
                            "voies": []}]},
               {"app/m.py": {"regulation": "CABLE",
                             "regulation_why": "importe par 2 module(s)"}})
    p = w.pourquoi()
    assert p[0]["nature"] == "CONFLIT_A_INSTRUIRE"
    assert p[0]["qui_a_raison"] is None
    assert "ecart_artefacts_h" in p[0], (
        "l'ecart d'age est un CANDIDAT stale a fournir, jamais une conclusion")


def test_un_motif_inconnu_reste_indetermine(tmp_path, monkeypatch) -> None:
    """Ne jamais ranger l'inattendu du cote explique : liste BLANCHE, pas noire."""
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [{"module": "m", "chemin": "app/m.py", "etat": "ORPHELIN",
                            "voies": []}]},
               {"app/m.py": {"regulation": "OUTIL", "regulation_why": "motif jamais vu"}})
    p = w.pourquoi()
    assert p[0]["nature"] == "INDETERMINE"
    assert "non reconnu" in p[0]["motif"]


# --- couverture : ABSENT et NON_COUVERT ne se confondent jamais -------------------

def test_la_couverture_est_derivee_de_l_artefact(tmp_path, monkeypatch) -> None:
    """Une couverture ANNONCEE est une intention ; celle-ci est DERIVEE du contenu.

    Mesure du 2026-09-07 : `forge_body_regulation_audit` DECLARE cinq repertoires et
    huit extensions (SCAN_DIRS / CODE_EXT), et son artefact publie ne contient que du
    `.py` de app/ et tools/. Perimetre DECLARE != perimetre OBSERVE — meme famille que
    capacite declaree != capacite prouvee."""
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [{"module": "a", "chemin": "app/a.py", "etat": "BRANCHE",
                            "voies": ["importe par 1 module(s)"]}]},
               {"app/a.py": {"regulation": "CABLE", "organ": "x"}})
    c = w.couverture()["module_wiring"]
    assert c["etat"] == "LU"
    assert c["dossiers"] == ["app"], "les dossiers viennent du contenu, pas d'une table"
    assert c["extensions"] == [".py"]


def test_couche_non_couverte_n_est_pas_un_module_absent(tmp_path, monkeypatch) -> None:
    """LE cas TypeScript. Aucune source ne lit le `.ts` dans son artefact : c'est
    NON_COUVERT, jamais « aucune arete ». J'ai conclu l'inverse le 2026-09-07 et
    annonce que Nokido ne cartographiait pas le TS — c'etait faux."""
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [{"module": "a", "chemin": "app/a.py", "etat": "BRANCHE",
                            "voies": ["importe par 1 module(s)"]}]},
               {"app/a.py": {"regulation": "CABLE", "organ": "x"}})
    d = w.module("proxy_deno/core/nervous_system.ts")
    assert d["aretes"] == []
    for nom, s in d["silences"].items():
        assert s["etat"] == "NON_COUVERT", (
            "%s doit dire qu'il ne LIT PAS cette couche, pas qu'elle est vide" % nom)


def test_fichier_absent_d_une_couche_couverte_est_absent(tmp_path, monkeypatch) -> None:
    """La source a les yeux pour cette couche et n'a pas vu ce fichier : ABSENT."""
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [{"module": "a", "chemin": "app/a.py", "etat": "BRANCHE",
                            "voies": ["importe par 1 module(s)"]}]},
               {"app/a.py": {"regulation": "CABLE", "organ": "x"}})
    d = w.module("app/jamais_vu.py")
    etats = {s["etat"] for s in d["silences"].values()}
    assert etats == {"ABSENT"}, (
        "meme dossier, meme extension : la source POUVAIT le voir. C'est un ABSENT, "
        "pas un trou de couverture — les deux n'appellent pas le meme remede. %s" % etats)


# --- 6. la JOINTURE entre sources ne refait pas la fusion du capteur ---------------

def test_un_basename_ambigu_ne_joint_pas_deux_sources(tmp_path, monkeypatch) -> None:
    """Le defaut corrige dans `forge_module_wiring` le 2026-09-07 pouvait revenir ICI.

    Le capteur ne fusionne plus `agents/core.py` et `netcfg/core.py` ; si la VUE les
    rapproche par basename au moment de joindre deux sources, la fusion est simplement
    deplacee du capteur vers la jointure. On ne joint pas ce qu'on ne sait pas apparier."""
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [{"module": "core", "chemin": "app/agents/core.py",
                            "etat": "ORPHELIN", "voies": [], "defini": True,
                            "teste": False}]},
               {"app/netcfg/core.py": {"regulation": "INVOQUE", "regulation_why": "a",
                                       "organ": "reseau"},
                "app/autre/core.py": {"regulation": "CABLE", "regulation_why": "b",
                                      "organ": "cognition"}})
    assert w.desaccords() == [], (
        "deux fiches partagent le basename 'core.py' : les joindre au premier rencontre "
        "attribuerait a un organe la regulation d'un AUTRE")


def test_un_basename_unique_joint_encore(tmp_path, monkeypatch) -> None:
    """Le garde ne doit pas tout eteindre : une correspondance SANS ambiguite tient."""
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [{"module": "m", "chemin": "app/m.py", "etat": "ORPHELIN",
                            "voies": [], "defini": True, "teste": False}]},
               {"tools/m.py": {"regulation": "INVOQUE", "regulation_why": "cite",
                               "organ": "cognition"}})
    d = w.desaccords()
    assert len(d) == 1, "un basename qui ne designe qu'UNE fiche reste appariable"


def test_un_module_ambigu_n_est_pas_un_desaccord(tmp_path, monkeypatch) -> None:
    """Une source qui S'ABSTIENT ne contredit personne : AMBIGU n'est pas ORPHELIN."""
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [{"module": "core", "chemin": "app/agents/core.py",
                            "etat": "AMBIGU", "voies": [], "defini": True, "teste": False,
                            "ambiguite": {"nom": "core", "candidats":
                                          ["app/agents/core.py", "app/netcfg/core.py"]}}]},
               {"app/agents/core.py": {"regulation": "INVOQUE", "regulation_why": "x",
                                       "organ": "cognition"}})
    assert w.desaccords() == [], "s'abstenir n'est pas contredire"


def test_une_abstention_est_comptee_et_nommee(tmp_path, monkeypatch) -> None:
    """...mais elle n'est pas TUE : un silence non compte se relit comme une absence."""
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [{"module": "core", "chemin": "app/agents/core.py",
                            "etat": "AMBIGU", "voies": [], "defini": True, "teste": False,
                            "ambiguite": {"nom": "core", "candidats":
                                          ["app/agents/core.py", "app/netcfg/core.py"]}}]},
               {"app/agents/core.py": {"regulation": "INVOQUE", "regulation_why": "x",
                                       "organ": "cognition"}})
    a = w.abstentions()
    assert len(a) == 1 and a[0]["module"] == "app/agents/core.py"
    assert a[0]["arbitrage"] is None, "une abstention ne se resout pas non plus"
    assert a[0]["module_wiring"]["ambiguite"]["candidats"] == [
        "app/agents/core.py", "app/netcfg/core.py"], "les candidats sont NOMMES"
    assert a[0]["appariement"] == "chemin"


def test_l_interdiction_de_router_traverse_la_vue(tmp_path, monkeypatch) -> None:
    """Un drapeau qui se perd a l'agregation ne protege rien.

    `routable: False` est porte par l'artefact ; si la vue ne le reporte pas, un
    selecteur de capacite qui lit la VUE (et non l'artefact) choisira un module qu'on
    ne sait pas designer. Trois etats : False, True, None quand la source se tait."""
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [{"module": "core", "chemin": "app/agents/core.py",
                            "etat": "AMBIGU", "voies": [], "defini": True, "teste": False,
                            "routable": False,
                            "ambiguite": {"nom": "core", "candidats":
                                          ["app/agents/core.py", "app/netcfg/core.py"]}}]},
               {"app/agents/core.py": {"regulation": "INVOQUE", "regulation_why": "x",
                                       "organ": "cognition"}})
    assert w.abstentions()[0]["module_wiring"]["routable"] is False


def test_une_source_muette_sur_le_routage_rend_None_pas_True(tmp_path, monkeypatch) -> None:
    """Un artefact ancien n'a pas le champ. L'absence d'interdiction n'est PAS une
    autorisation : on rend None, jamais un True fabrique."""
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [{"module": "core", "chemin": "app/agents/core.py",
                            "etat": "AMBIGU", "voies": [], "defini": True, "teste": False,
                            "ambiguite": {"nom": "core", "candidats":
                                          ["app/agents/core.py", "app/netcfg/core.py"]}}]},
               {"app/agents/core.py": {"regulation": "INVOQUE", "regulation_why": "x",
                                       "organ": "cognition"}})
    assert w.abstentions()[0]["module_wiring"]["routable"] is None


# --- 7. le statut de l'instrument VOYAGE, il ne se reconstitue pas -----------------

def test_la_vue_transporte_le_statut_declare_par_la_source(tmp_path, monkeypatch) -> None:
    """Sans ce report, `NON_CERTIFIANT` meurt a l'agregation et le consommateur
    suivant lit « graphe fiable »."""
    _artefacts(tmp_path, monkeypatch,
               {"fiches": [],
                "certification": {"statut": "NON_CERTIFIANT", "authority": False,
                                  "interdit_pour": ["routage"], "motif": "deux classes"}},
               {})
    c = w.certification()
    assert c["statut"] == "NON_CERTIFIANT"
    assert c["authority"] is False
    assert c["transporte_depuis"] == "wiring.json", "la provenance est nommee"


def test_la_vue_ne_FABRIQUE_aucun_statut() -> None:
    """Verrou de CONCEPTION. Si la vue peut ecrire `CERTIFIANT`, elle peut promouvoir
    une source qui ne l'a jamais declare — et le statut ne veut plus rien dire."""
    import re
    src = SRC.read_text(encoding="utf-8", errors="replace")
    trouve = re.findall(r"""["'](?:NON_)?CERTIFIANT["']""", src)
    assert not trouve, (
        "la vue RELAIE un statut, elle n'en produit aucun. Trouve : %r" % trouve)


def test_une_source_muette_rend_ILLISIBLE_et_JAMAIS_une_autorisation(
        tmp_path, monkeypatch) -> None:
    """Une absence de declaration n'est pas une autorisation.

    Meme piege que `routable` absent lu comme routable, ou qu'un score absent lu comme
    score nul : le repli doit etre le PLUS contraignant, pas le plus permissif."""
    _artefacts(tmp_path, monkeypatch, {"fiches": []}, {})
    c = w.certification()
    assert c["statut"] == "ILLISIBLE"
    assert c["authority"] is False, "un artefact muet ne devient jamais une autorite"
    assert "aucun statut" in c["motif"], "et le motif DIT ce qui manque"


def test_un_artefact_illisible_ne_devient_pas_certifiant(tmp_path, monkeypatch) -> None:
    """Artefact absent du disque : ILLISIBLE, authority False, motif nomme."""
    monkeypatch.setattr(w, "RACINE", tmp_path)
    monkeypatch.setattr(w, "SOURCES", {
        "module_wiring": {"artefact": "absent.json", "producteur": "x", "axe": "cablage"},
    })
    c = w.certification()
    assert (c["statut"], c["authority"]) == ("ILLISIBLE", False)


def test_la_clef_est_le_chemin_pas_le_nom_de_base() -> None:
    """`app/Nokido.py` et `tools/nokido.py` sont deux modules que le systeme de
    fichiers Windows confond. Keyer sur le basename les fusionnerait en silence."""
    assert w._cle("app\\Nokido.py") == "app/Nokido.py"
    assert w._cle("./tools/nokido.py") == "tools/nokido.py"
    assert w._cle("app/Nokido.py") != w._cle("tools/nokido.py")
