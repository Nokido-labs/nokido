# -*- coding: utf-8 -*-
"""NR-WIRING-ID-01 — deux fichiers distincts gardent deux identités distinctes.

__FORGE_COLOR__ = "observabilite/audit : non-regression de l identite des noeuds du graphe"

CE QUI A ÉTÉ PAYÉ (2026-09-07). `forge_module_wiring` indexait ses nœuds par
`p.stem` via `setdefault` : **2 415 fichiers pour 1 961 nœuds**, donc 454 fichiers sans
identité propre, et aucune trace de la collision.

Démonstration mesurée sur le témoin `core` :

    app/agents/core.py  publiait  "importe par 43 module(s)"   <- AUCUN import qualifie
    app/netcfg/core.py  n'avait   AUCUN noeud                  <- 1 importeur reel

Les 43 venaient d'`import core` nus, rattachés au gagnant du `setdefault` par hasard
d'ordre de parcours. **Un graphe qui fusionne deux organes attribue une capacité au
mauvais** — et un futur routeur de capacités y sélectionnerait le mauvais module.

⚠️ Ce n'est PAS le problème des collisions d'IMPORT, qui est déjà gaté ailleurs
(`test_aucune_nouvelle_collision_de_nom`, 8 collisions de racine gelées avec leurs
contenus divergents mesurés). Ici Python ne confond rien : `agents.core` et
`netcfg.core` sont deux modules parfaitement distincts. C'est le CAPTEUR qui
confondait.

TROIS PROPRIÉTÉS, et la troisième est celle qui compte pour la suite :

  1. même nom + chemins différents          -> deux nœuds
  2. résolution ambiguë                     -> `AMBIGU`, aucun choix silencieux
  3. arête résolue par nom, plusieurs candidats -> AUCUNE attribution

La 3 est un garde de routage : une ambiguïté d'identité doit **empêcher** la sélection
d'une capacité, pas produire un avertissement décoratif.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_module_wiring as mw  # noqa: E402


def _faux_depot(tmp_path, monkeypatch):
    """Un dépôt minuscule : deux homonymes en sous-dossiers, un module seul, un
    importeur. Hermétique — `scanner()` ne touche jamais le vrai dépôt."""
    (tmp_path / "app" / "agents").mkdir(parents=True)
    (tmp_path / "app" / "netcfg").mkdir(parents=True)
    (tmp_path / "app" / "agents" / "core.py").write_text(
        '"""docstring presente."""\n', encoding="utf-8")
    (tmp_path / "app" / "netcfg" / "core.py").write_text(
        "x = 1\n", encoding="utf-8")            # PAS de docstring : doit differer
    (tmp_path / "app" / "solo.py").write_text(
        '"""seul de son nom."""\n', encoding="utf-8")
    # Trois pointes, trois genres — le fixture EXERCE les trois branches de ID-03 :
    #   `solo`            pointe NUE, nom UNIQUE     -> attribuee
    #   `core`            pointe NUE, nom AMBIGU     -> attribuee a PERSONNE
    #   `app.netcfg.core` pointe POINTEE, un CHEMIN  -> attribuee malgre l'homonyme
    (tmp_path / "app" / "client.py").write_text(
        '"""importe."""\nimport solo\nimport core\nfrom app.netcfg.core import y\n',
        encoding="utf-8")
    fichiers = sorted((tmp_path / "app").glob("**/*.py"))
    monkeypatch.setattr(mw, "ROOT", tmp_path)
    monkeypatch.setattr(mw, "modules", lambda: fichiers)
    monkeypatch.setattr(mw, "_texte_declaratif", lambda *a: "")
    return {f["chemin"]: f for f in mw.scanner()["fiches"]}


def test_deux_fichiers_de_meme_nom_font_deux_noeuds(tmp_path, monkeypatch) -> None:
    """PROPRIETE 1. `setdefault(stem, path)` n'en gardait qu'un, sans trace."""
    f = _faux_depot(tmp_path, monkeypatch)
    assert "app/agents/core.py" in f
    assert "app/netcfg/core.py" in f, (
        "le second homonyme doit EXISTER : sinon un fichier vivant n'a aucune identite")


def test_une_resolution_ambigue_ne_choisit_pas_en_silence(tmp_path, monkeypatch) -> None:
    """PROPRIETE 2. `AMBIGU` est un troisieme etat : ni branche, ni orphelin."""
    f = _faux_depot(tmp_path, monkeypatch)
    assert f["app/agents/core.py"]["etat"] == "AMBIGU", (
        "un nom qui designe deux fichiers ne se tranche pas au premier rencontre")
    for c in ("app/agents/core.py", "app/netcfg/core.py"):
        assert f[c]["ambiguite"]["candidats"] == [
            "app/agents/core.py", "app/netcfg/core.py"], "les candidats sont NOMMES"
        # VISIBLE mais NON ROUTABLE : un selecteur de capacite ne doit jamais choisir
        # un module qu'on ne sait pas designer, meme quand il a des aretes prouvees.
        assert f[c]["routable"] is False, (
            "%s : une identite ambigue ne peut pas etre routee" % c)
    assert f["app/solo.py"]["routable"] is True, "un nom unique reste routable"


def test_une_arete_ambigue_n_est_attribuee_a_personne(tmp_path, monkeypatch) -> None:
    """PROPRIETE 3 — le garde de routage.

    `client.py` fait `import core`. Cette arete ne peut revenir a aucun des deux
    fichiers : elle n'est donnee A AUCUN. C'est ce qui faisait publier 43 importeurs
    sur un fichier qui n'en avait pas."""
    f = _faux_depot(tmp_path, monkeypatch)
    for c in ("app/agents/core.py", "app/netcfg/core.py"):
        assert f[c]["importateurs"] == [], (
            "%s : aucune arete resolue par NOM ne lui est attribuee" % c)
    assert f["app/agents/core.py"]["voies"] == [], (
        "celui qui n'a QUE des aretes nommees ambigues n'en recoit aucune")


def test_ID03_une_arete_qualifiee_atteint_sa_cible_malgre_l_homonyme(
        tmp_path, monkeypatch) -> None:
    """ID-03. Une pointe POINTEE est deja une identite : l'homonyme ne la bloque pas.

    Mesure du 2026-09-07 : `app/netcfg/core.py` a UN importeur qualifie reel, et il
    etait perdu — d'abord credite a `app/agents/core.py` par la collision, puis retenu
    par l'abstention quand la collision a ete corrigee. L'abstention est juste pour les
    aretes NOMMEES ; l'appliquer aux aretes qualifiees, c'est jeter la seule preuve
    disponible."""
    f = _faux_depot(tmp_path, monkeypatch)
    n = f["app/netcfg/core.py"]
    assert n["importateurs_qualifies"] == ["app/client.py"], (
        "l'arete pointee doit atteindre SA cible, pas son homonyme")
    assert n["etat"] == "BRANCHE", "une arete prouvee suffit a le brancher"
    assert f["app/agents/core.py"]["importateurs_qualifies"] == [], (
        "et l'homonyme n'en recoit AUCUNE")


def test_un_nom_unique_reste_attribue_normalement(tmp_path, monkeypatch) -> None:
    """Le garde ne doit pas tout eteindre : sans ambiguite, l'arete est rendue."""
    f = _faux_depot(tmp_path, monkeypatch)
    assert f["app/solo.py"]["etat"] == "BRANCHE"
    assert any("importe par" in v for v in f["app/solo.py"]["voies"]), (
        "un import qualifie vers un nom UNIQUE doit rester une arete")


def test_les_proprietes_du_fichier_ne_deteignent_pas(tmp_path, monkeypatch) -> None:
    """`defini` (docstring) est une propriete DU FICHIER, pas du nom.

    Indexee par `stem`, l'absence de docstring de l'un contaminait l'autre."""
    f = _faux_depot(tmp_path, monkeypatch)
    assert f["app/agents/core.py"]["defini"] is True
    assert f["app/netcfg/core.py"]["defini"] is False, (
        "deux homonymes n'ont pas la meme docstring : la propriete se cle par CHEMIN")


def test_un_fichier_qui_ne_parse_pas_est_NOMME_pas_escamote(tmp_path, monkeypatch) -> None:
    """ILLISIBLE n'est pas ABSENT.

    Un `.py` casse disparaissait du graphe SANS TRACE : l'instrument charge de dire ce
    qui existe repondait « il n'y a rien » la ou il fallait lire « je n'ai pas pu
    voir ». Un denominateur muet surestime la couverture."""
    _faux_depot(tmp_path, monkeypatch)
    (tmp_path / "app" / "casse.py").write_text("def (\n", encoding="utf-8")
    fichiers = sorted((tmp_path / "app").glob("**/*.py"))
    monkeypatch.setattr(mw, "modules", lambda: fichiers)
    r = mw.scanner()
    chemins = [x["chemin"] for x in r["illisibles"]]
    assert chemins == ["app/casse.py"], "le fichier illisible doit etre NOMME"
    assert "SyntaxError" in r["illisibles"][0]["motif"], "avec son motif, pas un booleen"
    f = {x["chemin"]: x for x in r["fiches"]}["app/casse.py"]
    assert f["etat"] == "ILLISIBLE", (
        "ORPHELIN est une affirmation POSITIVE -- « il existe et rien ne l'atteint » -- "
        "sur un fichier dont on ignore tout. UNKNOWN n'est pas NO. Etat rendu : %s"
        % f["etat"])
    assert "SyntaxError" in (f["illisible"] or ""), "la fiche porte son motif"


# ── SECONDE CLASSE : clef de niveau PAQUET (temoin app/web_hub/app.py) ────────────
#
# Disjointe de la premiere, et PLUS dangereuse : le stem `app` est UNIQUE dans tout
# le depot, donc AUCUN signal d'ambiguite ne pouvait l'attraper. Le fichier sortait
# BRANCHE, routable, avec la connectivite la plus forte du depot.
# Mesure 2026-09-07 : 79 importeurs annonces, 3 reels -> 96,2 % fabriques.

def _faux_depot_paquet(tmp_path, monkeypatch):
    (tmp_path / "app" / "web_hub").mkdir(parents=True)
    (tmp_path / "tools").mkdir()
    for rel, contenu in [
        ("app/__init__.py", ""),
        ("app/web_hub/__init__.py", ""),
        ("app/web_hub/app.py", '"""faux central."""\nfrom app.web_hub.auth import v\n'),
        ("app/web_hub/auth.py", '"""vraie cible."""\ndef v(): pass\n'),
        # UN vrai importeur de app.py : le correctif ne doit pas le supprimer aussi.
        ("tools/dump_hub_routes.py", '"""vrai importeur."""\nfrom app.web_hub.app import r\n'),
        # ...et un import qui vise AUTH : il ne doit jamais atterrir sur app.py.
        ("tools/audit_ui.py", '"""vise auth."""\nfrom app.web_hub.auth import v\n'),
    ]:
        (tmp_path / rel).write_text(contenu, encoding="utf-8")
    fichiers = sorted(tmp_path.glob("**/*.py"))
    monkeypatch.setattr(mw, "ROOT", tmp_path)
    monkeypatch.setattr(mw, "modules", lambda: fichiers)
    monkeypatch.setattr(mw, "_texte_declaratif", lambda *a: "")
    return {f["chemin"]: f for f in mw.scanner()["fiches"]}


def test_une_clef_de_paquet_n_absorbe_AUCUNE_arete(tmp_path, monkeypatch) -> None:
    """`from app.web_hub.auth import v` ne doit rien donner a `app/web_hub/app.py`.

    L'ancien capteur creditait les segments `app` puis `web_hub`, resolus par stem ;
    `app` designant un seul fichier, TOUT le depot atterrissait dessus."""
    f = _faux_depot_paquet(tmp_path, monkeypatch)
    assert "tools/audit_ui.py" not in f["app/web_hub/app.py"]["importateurs_qualifies"]
    assert f["app/web_hub/app.py"]["importateurs"] == [], (
        "aucune arete resolue par le NOM `app` ne doit exister")


def test_la_VRAIE_arete_survit_au_correctif(tmp_path, monkeypatch) -> None:
    """Le fixture porte a la fois le faux positif massif ET le vrai positif : un
    correctif qui supprimerait trop serait invisible sans lui."""
    f = _faux_depot_paquet(tmp_path, monkeypatch)
    assert f["app/web_hub/app.py"]["importateurs_qualifies"] == [
        "tools/dump_hub_routes.py"], "l'importeur REEL de app.py reste"


def test_l_arete_va_a_la_FEUILLE_visee(tmp_path, monkeypatch) -> None:
    f = _faux_depot_paquet(tmp_path, monkeypatch)
    assert f["app/web_hub/auth.py"]["importateurs_qualifies"] == [
        "app/web_hub/app.py", "tools/audit_ui.py"]


def test_cette_classe_n_a_AUCUN_signal_d_ambiguite(tmp_path, monkeypatch) -> None:
    """Le point qui rend la classe dangereuse, et la raison du second fixture.

    `app` a UN seul candidat : `routable` reste True et l'etat n'est pas AMBIGU. Le
    garde de la classe `core` ne couvre donc pas celle-ci — deux fixtures, pas un."""
    f = _faux_depot_paquet(tmp_path, monkeypatch)
    assert f["app/web_hub/app.py"]["routable"] is True
    assert f["app/web_hub/app.py"]["etat"] != "AMBIGU"


# ── L'instrument declare son propre statut ────────────────────────────────────────

def test_authority_est_un_LITTERAL_jamais_un_calcul() -> None:
    """`confidence` et `authority` sont orthogonaux.

    Si `authority` pouvait etre affecte depuis une expression, un seuil suffirait a
    promouvoir l'instrument : `confidence 0.99` redeviendrait `authority True`. La
    qualite d'une mesure ne transforme jamais un instrument d'exploration en
    instrument de decision."""
    import ast as _ast
    arbre = _ast.parse((ROOT / "tools" / "forge_module_wiring.py").read_text(
        encoding="utf-8", errors="replace"))
    vus = 0
    for n in _ast.walk(arbre):
        if not isinstance(n, _ast.Dict):
            continue
        for k, v in zip(n.keys, n.values):
            if isinstance(k, _ast.Constant) and k.value == "authority":
                vus += 1
                assert isinstance(v, _ast.Constant), (
                    "`authority` doit etre un litteral, pas %s" % type(v).__name__)
    assert vus >= 1, "l'instrument doit DECLARER son authority"


def test_le_statut_voyage_avec_l_artefact(tmp_path, monkeypatch) -> None:
    """Un statut qui reste dans le module se perd des qu'on lit le json."""
    _faux_depot(tmp_path, monkeypatch)
    c = mw.scanner()["certification"]
    assert c["statut"] == "NON_CERTIFIANT"
    assert c["authority"] is False
    assert len(c["classes_de_defaut_connues"]) == 2, "les DEUX classes sont nommees"
    assert "routage" in " ".join(c["interdit_pour"])
    # Les metriques sont A COTE du statut : une mesure n'ameliore pas une autorite.
    assert "false_edges" not in c and "false_edges" in c["mesures"]["2026-09-07"]


def test_routable_n_est_PAS_une_autorite(tmp_path, monkeypatch) -> None:
    """`routable: True` dit « je sais lequel », pas « c'est prouve ».

    Trois proprietes distinctes, et les confondre est la derniere porte de promotion
    silencieuse :

        IDENTITE   module_id = chemin ; resolution = nom
        RESOLUTION unique -> RESOLVED · plusieurs -> AMBIGUOUS · absente -> ABSENT
        AUTORITE   authority = False tant que l'instrument est NON_CERTIFIANT

    Une fiche ne doit donc porter AUCUNE clef d'autorite : sinon un consommateur la
    lit au niveau du NOEUD et court-circuite le statut de l'INSTRUMENT."""
    _faux_depot(tmp_path, monkeypatch)
    r = mw.scanner()
    interdits = {"authority", "certification", "confidence", "score", "proven", "certifie"}
    for f in r["fiches"]:
        fautives = interdits & set(f)
        assert not fautives, (
            "%s porte %r : l'autorite se lit sur l'INSTRUMENT, jamais sur un noeud"
            % (f["chemin"], sorted(fautives)))
    assert "authority" in r["certification"], "elle vit la, et seulement la"


def test_le_rapport_declare_les_noms_ambigus(tmp_path, monkeypatch) -> None:
    """Une ambiguite qu'on ne compte pas se referme en silence."""
    _faux_depot(tmp_path, monkeypatch)
    r = mw.scanner()
    assert r["noms_ambigus"] == ["core"]
    assert r["total"] == 4, "une fiche PAR FICHIER, pas par nom"
