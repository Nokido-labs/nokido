# -*- coding: utf-8 -*-
"""NR — le GRAPHE entier lecteurs+ecrivains partage le meme point de bascule.

Reformulation du contrat par l'owner le 2026-09-22, apres que la validation
d'avant-bascule eut refuse de basculer :

    pas « les ecrivains sont cables »
    mais « l'ensemble du graphe lecteurs + ecrivains partage effectivement
           le meme point de bascule »

CE QUE LA VALIDATION A TROUVE, ET QUI A EMPECHE LA BASCULE
==========================================================
1. `forge_token_monitor` ne creait PAS `token_usage` : `migrer()` fait
   `ALTER TABLE`, jamais `CREATE`. Sur base neuve, l'ALTER levait `no such
   table`, son appelant AVALAIT l'exception, et les 6 720 ecritures de ce
   journal seraient parties dans le vide SANS BRUIT.

       UNE ECRITURE AVALEE RESSEMBLE A UN SYSTEME CALME. UN CRASH SE VOIT.

2. ONZE lecteurs resolvaient leur base par une constante figee a l'import.
   Apres bascule, les ecrivains auraient ecrit dans `sandbox/*.db` pendant que
   ces onze lisaient `%NOKIDO_DATA%\embeddings.db`, devenue figee — exactement ce que la
   regle du depot interdit : « un site qui bascule seul fait ecrire d'un cote
   et lire de l'autre ».

LE DOUTE STRUCTUREL A ETE LEVE PAR MESURE
=========================================
Sur 2 467 modules, **ZERO** requete ne melange un journal et une autre table.
Aucun JOIN a reecrire, aucune denormalisation : deux bases distinctes ne se
joignent pas sans ATTACH, et la question devait etre tranchee AVANT de promettre
que la migration etait faisable.

POURQUOI CE NR DECOUVRE AU LIEU DE LISTER
=========================================
Une liste de fichiers ecrite a la main se perime en silence : un module ajoute
demain n'y figure pas, et le garde se relit comme une couverture. Ce fichier
RECENSE les acces par analyse du SQL, et confronte chaque module trouve a
l'accesseur. Motif deja paye sur l'allowlist de `forge_dep_manager` : une liste
figee autorise ce que personne n'a declare.

CE QU'IL ATTRAPE
================
  * un LECTEUR qui resout sa base hors de l'accesseur ;
  * un ECRIVAIN dans le meme cas ;
  * `token_usage` sans schema creable sur une base neuve ;
  * un echec de schema qui n'emet AUCUN signal observable.

Le plafond est pose a la mesure du jour et non a zero : un test rouge des sa
naissance se fait desarmer dans la semaine. Il interdit la PROPAGATION pendant
que les huit lecteurs restants sont cables un par un.
"""

import logging
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture de app/ et tools/ (2
#   niveaux) (l.170)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_db_path as D  # noqa: E402

JOURNAUX = ("conversation_log", "inspector_log", "token_usage")

# Marqueurs d'un module qui resout sa base par l'accesseur, sous l'une des formes
# que le depot emploie reellement.
#
# 🪤 CE MEME FICHIER A REPAYE LE MOTIF QU'IL CITE. La liste ne contenait que
# `journal_path` et `CheminJournal` ; le dernier site cable l'a ete via
# `lecteur_journal`, un TROISIEME nom, et le detecteur a continue de compter ce
# module comme non cable alors qu'il venait de l'etre. Troisieme occurrence du
# 2026-09-22, apres les six faux verts du matin et la delegation de
# `forge_souverainete_reelle`.
#
#     UN VOCABULAIRE FIGE D'AVANCE NE VOIT PAS LA GARDE QUI ARRIVE.
#
# Toute primitive de resolution de journal ajoutee a `forge_db_path` doit donc
# etre ajoutee ICI dans le meme geste -- sinon le garde se relit comme une
# couverture tout en ratant precisement le travail qu'on vient de faire.
_CABLE = ("journal_path", "CheminJournal", "lecteur_journal")

# Plafond MESURE le 2026-09-22 apres le cablage des dix lecteurs : il en reste
# DEUX, et pour des raisons DIFFERENTES qui sont nommees ici plutot que
# confondues dans un chiffre.
PLAFOND_NON_CABLES = 1

# Exemptions NOMMEES, avec leur raison. Jamais implicites : une liste noire
# laisserait tomber du cote sain tout module inattendu.
#
# `forge_souverainete_reelle` ne cite aucun marqueur parce qu'il DELEGUE :
# `_chemin_db()` rend `forge_provider_quota.DB`, lui-meme cable. Sa docstring le
# dit -- « on lit la ou le PRODUCTEUR ecrit, jamais redecouvert ». Le detecteur
# textuel produit donc un FAUX POSITIF : CALL_SITE != DECISION_SITE, le meme
# motif qui avait fait ranger `/api/login` parmi les routes nues alors qu'elle
# delegue a `login_agent`.
#
# L'exemption n'est PAS une tolerance : `test_la_delegation_suit_vraiment_la_bascule`
# l'exerce au RUNTIME. Un module exempte qui cesserait de suivre l'interrupteur
# ferait rougir ce fichier.
_DELEGATIONS = {
    "app/forge_souverainete_reelle.py": (
        "delegue a forge_provider_quota.DB, cable — verifie au runtime plus bas"
    ),
}

# Plus aucun module bloque : `forge_mcp_registry` a ete cable le 2026-09-22 sur
# AUTORISATION OWNER EXPLICITE (`allow_critical=true`, tracee), apres que le
# garde eut d'abord REFUSE l'ecriture. Le garde a joue son role ; il n'a pas ete
# contourne, il a ete leve.
#
# La premiere tentative, un bloc de 35 lignes, a fait TOMBER LE HUB : validation
# AST, scan secret et tree_lock sur 9 241 lignes, in-process. La seconde a tenu
# parce que la logique est partie dans `forge_db_path.lecteur_journal` et que le
# bloc s'est reduit a trois lignes.
#
#     DANS UN CRITICAL_FILE, LA TAILLE DE L'EDITION EST UN PARAMETRE DE SURETE.
_BLOQUE_PAR_GARDE: dict = {}

_ECRIT = re.compile(r"\b(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)\s+(%s)\b"
                    % "|".join(JOURNAUX), re.I)
_LIT = re.compile(r"\b(?:FROM|JOIN)\s+(%s)\b" % "|".join(JOURNAUX), re.I)


def recenser(racine=None) -> dict:
    """Rend {module: {"tables": {...}, "ecrit": bool, "cable": bool}} par ANALYSE.

    `tests/` est exclu : un instrument ne lit jamais son propre vocabulaire, et ce
    fichier contient les motifs qu'il cherche (cinq fois paye en trois jours).
    `_attic` et `__pycache__` aussi, et c'est DIT plutot que taire.
    """
    racine = Path(racine or ROOT)
    trouves, lus, illisibles = {}, 0, 0
    for zone in ("app", "tools"):
        base = racine / zone
        if not base.is_dir():
            continue
        fichiers = list(base.glob("*.py"))
        for sous in (p for p in base.iterdir() if p.is_dir()
                     and not p.name.startswith(("__", "_attic"))):
            fichiers += list(sous.glob("*.py")) + list(sous.glob("*/*.py"))
        for p in sorted(set(fichiers)):
            try:
                texte = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                illisibles += 1
                continue
            lus += 1
            tables = {m.group(1).lower() for m in _ECRIT.finditer(texte)}
            ecrit = bool(tables)
            tables |= {m.group(1).lower() for m in _LIT.finditer(texte)}
            if not tables:
                continue
            rel = str(p.relative_to(racine)).replace("\\", "/")
            trouves[rel] = {
                "tables": sorted(tables),
                "ecrit": ecrit,
                "cable": any(marqueur in texte for marqueur in _CABLE),
            }
    return {"modules": trouves, "lus": lus, "illisibles": illisibles}


def test_le_recensement_voit_quelque_chose():
    """CONTRE-ÉPREUVE : un recenseur aveugle respecterait tous les plafonds."""
    res = recenser()
    assert res["lus"] > 1000, f"seulement {res['lus']} modules lus — le balayage est casse"
    assert res["modules"], "aucun acces aux journaux trouve : le detecteur ne voit rien"
    ecrivains = [m for m, v in res["modules"].items() if v["ecrit"]]
    assert len(ecrivains) >= 4, f"moins de 4 ecrivains trouves : {ecrivains}"
    print(
        f"[graphe] {res['lus']} modules lus, {res['illisibles']} illisible(s) · "
        f"{len(res['modules'])} module(s) touchent un journal · {len(ecrivains)} ecrivain(s)"
    )


def test_TOUS_les_ecrivains_partagent_le_point_de_bascule():
    """Zero tolerance cote ecriture : un ecrivain hors accesseur continuerait
    d'alimenter la base de 26 Go le jour de la bascule, et la migration se
    relirait comme faite. C'est le contrat « ancien emplacement interdit »."""
    res = recenser()
    hors = sorted(m for m, v in res["modules"].items() if v["ecrit"] and not v["cable"])
    assert not hors, (
        f"ecrivain(s) de journal resolvant leur base HORS de l'accesseur : {hors}. "
        "Rappel : `inspector_log` a DEUX ecrivains, l'inserteur ET le rotateur."
    )


def test_le_nombre_de_lecteurs_non_cables_ne_croit_pas():
    """Plafond decroissant, pas exigence de zero : huit lecteurs melangent un
    journal et d'autres tables de la meme base, et se traitent un par un."""
    res = recenser()
    hors = sorted(m for m, v in res["modules"].items() if not v["ecrit"] and not v["cable"])
    print(f"[graphe] {len(hors)} lecteur(s) non cable(s) (plafond {PLAFOND_NON_CABLES}) : {hors}")
    assert len(hors) <= PLAFOND_NON_CABLES, (
        f"{len(hors)} lecteurs hors accesseur, plafond {PLAFOND_NON_CABLES} "
        f"(mesure 2026-09-22) : {hors}"
    )


def test_la_delegation_suit_vraiment_la_bascule(monkeypatch, tmp_path):
    """Une exemption se PROUVE, elle ne se declare pas.

    `forge_souverainete_reelle` ne cite aucun marqueur de cablage : il delegue.
    Ce test le verifie au RUNTIME en posant un interrupteur temporaire et en
    constatant que le chemin resolu CHANGE. Si la delegation etait rompue -- par
    exemple parce que le module amont revient a une constante figee -- ce test
    tombe, et l'exemption cesse avec lui.
    """
    import importlib
    import tempfile

    import sys

    import forge_souverainete_reelle as SR

    # « Sans interrupteur » doit etre VRAI pendant le test : isoler de l'interrupteur
    # REEL sandbox/journaux.switch (pose le 2026-09-23), sur toutes les formes
    # d'import du module, sans toucher au mecanisme reel.
    absent = tmp_path / "absent.switch"
    for nom in ("forge_db_path", "nokido_agent.app.forge_db_path", "app.forge_db_path"):
        m = sys.modules.get(nom)
        if m is not None and hasattr(m, "_JOURNAUX_SWITCH"):
            monkeypatch.setattr(m, "_JOURNAUX_SWITCH", absent)
    importlib.reload(SR)
    avant = SR._chemin_db()
    assert avant == D.db_path(), (
        "sans interrupteur, la delegation ne rend plus la base historique : "
        "le cablage a change un comportement, ce qu'il ne doit pas faire"
    )
    with tempfile.TemporaryDirectory() as d:
        interrupteur = Path(d) / "journaux.switch"
        interrupteur.write_text("test", encoding="utf-8")
        ancien = D._JOURNAUX_SWITCH
        D._JOURNAUX_SWITCH = interrupteur
        try:
            apres = SR._chemin_db()
        finally:
            D._JOURNAUX_SWITCH = ancien
    assert apres != avant, (
        "la delegation NE SUIT PAS la bascule : ce module lirait la base figee "
        "pendant que les ecrivains partent ailleurs. L'exemption doit tomber."
    )
    print(f"[graphe] delegation verifiee : {avant} -> {apres}")
    assert SR._chemin_db() == avant, "l'etat n'a pas ete restaure apres le test"


def test_les_non_cables_restants_sont_TOUS_expliques():
    """Un chiffre sans noms se lit comme une dette anonyme. Chaque module encore
    hors accesseur doit etre soit une delegation prouvee, soit un travail bloque
    par un garde — et jamais un oubli silencieux."""
    res = recenser()
    hors = {m for m, v in res["modules"].items() if not v["ecrit"] and not v["cable"]}
    inexpliques = sorted(hors - set(_DELEGATIONS) - set(_BLOQUE_PAR_GARDE))
    assert not inexpliques, (
        f"module(s) hors accesseur sans explication : {inexpliques}. "
        "Ajouter le cablage, ou nommer la raison — pas laisser le chiffre parler seul."
    )
    for m, raison in sorted(_DELEGATIONS.items()):
        print(f"[graphe] exempte  {m} — {raison}")
    for m, raison in sorted(_BLOQUE_PAR_GARDE.items()):
        print(f"[graphe] BLOQUE   {m} — {raison}")


def test_token_usage_a_un_schema_CREABLE_sur_une_base_neuve():
    """Le defaut qui a empeche la bascule, exerce sur le CHEMIN REEL.

    Sans cela : ALTER sur table absente -> `no such table` -> exception avalee ->
    6 720 ecritures perdues en silence.
    """
    import forge_token_monitor as TM

    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "neuve.db"
        conn = sqlite3.connect(str(base))
        try:
            assert not conn.execute(
                "SELECT name FROM sqlite_master WHERE name='token_usage'").fetchone()
            TM.migrer(conn)
            assert conn.execute(
                "SELECT name FROM sqlite_master WHERE name='token_usage'").fetchone(), (
                "migrer() n'a pas cree la table sur une base neuve")
            cols = {r[1] for r in conn.execute("PRAGMA table_info(token_usage)")}
            # Les colonnes que l'INSERT de production nomme : si l'une manque, la
            # ligne part en erreur au lieu d'etre ecrite.
            for attendue in ("id", "agent_id", "provider", "total_tokens", "provenance",
                             "execution_id", "writer_component"):
                assert attendue in cols, f"colonne {attendue!r} absente du schema cree"
            conn.execute(
                "INSERT OR IGNORE INTO token_usage (id,agent_id,total_tokens) VALUES ('t','a',1)")
            conn.commit()
            assert conn.execute("SELECT COUNT(*) FROM token_usage").fetchone()[0] == 1, (
                "le schema est cree mais l'ecriture ne passe pas")
        finally:
            conn.close()


def test_un_echec_de_schema_EMET_un_signal_et_ne_se_lit_pas_comme_un_succes(caplog):
    """Le chemin d'erreur EMET-IL vraiment ?

    Sa premiere version appelait `logger.error` dans un module qui n'importait
    meme pas `logging` : un `NameError` LEVE DEPUIS UN GESTIONNAIRE D'EXCEPTION,
    qui aurait masque la cause qu'il pretendait reveler. Piege deja paye
    (`forge_web_fetch` n'avait aucun logger), invisible a l'AST comme a la
    relecture, et visible en UNE execution.

        VERIFIER QUI EMET LE SIGNAL, PAS SEULEMENT QUE LE GARDE EXISTE.
    """
    import forge_token_monitor as TM

    assert hasattr(TM, "logger"), (
        "le module n'a pas de logger : son chemin d'erreur leverait un NameError"
    )
    with caplog.at_level(logging.ERROR, logger="Nokido.TokenMonitor"):
        TM.logger.error("[token_monitor] sonde de NR — le canal emet-il ?")
    assert caplog.records, "le logger du module n'emet RIEN : le signal est mort"
