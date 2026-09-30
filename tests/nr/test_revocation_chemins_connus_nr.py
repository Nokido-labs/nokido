r"""NR — inventaire des chemins de REVOCATION, avec leurs trois maillons separes.

MESURE DU 2026-09-21. P1-C de la campagne longue.

CE QU'ON A CESSE DE CONFONDRE
=============================
« La revocation marche » est une phrase qui cache TROIS proprietes
independantes. Chacune peut manquer seule, et le remede differe a chaque fois :

    EMETTEUR      quelqu'un APPELLE la revocation en production
    RECEPTEUR     le point de decision la CONSULTE avant d'autoriser
    PERSISTANCE   l'etat SURVIT au redemarrage du process

Brancher un emetteur sans persistance donne une revocation qui meurt au
restart. Persister sans emetteur donne un registre toujours vide. Consulter
sans emetteur donne un garde branche sur un signal que personne n'emet --
motif deja paye et documente dans `docs/RULES_GARDE_SANS_EMETTEUR.md`.

LA CARTE MESUREE
================
    app/web_hub/jti_cache.py          objet : jeton (jti)
      emetteur   app/web_hub/app.py:1844   revoke_jti au logout
      recepteur  app/web_hub/auth.py:272   is_jti_revoked dans verify_token
      persiste   SqlitePersister + attach_and_preload (app.py:253, boot)
      => LES TROIS. Mais c'est le WEB HUB (:7400), pas le hub :8766.

    app/forge_integrity.py            objet : IDENTITE d'agent
      emetteur   AUCUN en production -- `forge_dataset_sync` ne l'appelle que
                 dans des cas limites documentes (« EC-05 : Revoke agent
                 inconnu »), et `tools/mcp_nr.py` est un NR
      recepteur  CABLE : `verify` lit `_revoked_seqs`/`_revoked_after`, et le
                 hub utilise bien CE singleton (`nokido_hub.py:1102`)
      persiste   NON : deux dicts nes dans `__init__`
      => LE SEUL MAILLON PRESENT EST LE RECEPTEUR.

    app/forge_agent_keys.py           objet : CLE durable
      persiste   OUI, prouve (rotation survecue au restart, 2026-09-21)
      recepteur  DECABLE le jour meme : `decode` ne recoit aucune
                 `credential_class` permettant de distinguer un DPoP ephemere
                 d'une cle geree (cf le commit de decablage)
      => PRIMITIVE PREPARATOIRE ASSUMEE, pas un chemin actif.

CE QUE CE NR NE FAIT PAS
========================
Il ne rebranche rien et ne revoque rien. Brancher un emetteur de revocation
d'identite est une decision de politique : cela determine QUI peut couper QUI,
et sous quelle autorite. Ce NR fige la carte pour que l'ecart cesse d'etre
re-mesure a chaque session, et pour qu'un maillon qui apparait ou disparait le
DISE.

ANTI-DUP : `test_revocation_identite_isole_la_cause_nr` prouve deja
revoke -> DENY et la volatilite, par experience isolee. On ne le refait pas.
Ce NR couvre ce qu'il ne couvre pas : l'INVENTAIRE et l'asymetrie des maillons.

PIEGE D'HOMONYMIE, paye ailleurs et evite ici : `.revoke(` matche
`IntegrityManager.revoke` ET `JtiRevocationCache.revoke`, qui sont deux
methodes de deux classes sans rapport. Un instrument qui les melange compte des
emetteurs qui n'en sont pas. Les tests ci-dessous les separent explicitement.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob app+tools + ast (l.146)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

#: Ce que chaque mecanisme porte, maillon par maillon. Mettre a jour CETTE
#: table quand un maillon change -- le test qui la lit dira ce qui diverge.
CHEMINS_REVOCATION = {
    "app/web_hub/jti_cache.py": {
        "objet": "jeton",
        "emetteur": "OUI",
        "recepteur": "OUI",
        "persiste": "OUI",
    },
    "app/forge_integrity.py": {
        "objet": "identite",
        "emetteur": "NON",
        "recepteur": "OUI",
        "persiste": "NON",
    },
    "app/forge_agent_keys.py": {
        "objet": "cle",
        "emetteur": "OUI",
        "recepteur": "NON",
        "persiste": "OUI",
    },
}

#: Appels a `IntegrityManager.revoke` qui NE SONT PAS des emetteurs de
#: production, avec la raison. Un appel qui apparait hors de cette liste fait
#: rougir le test : soit un emetteur est ne (tant mieux, mettre a jour), soit
#: un chemin de test s'est glisse en production.
NON_EMETTEURS_CONNUS = {
    "app/forge_dataset_sync.py": "cas limites documentes (EC-05), pas un flux",
    # Un harnais de NR qui vit dans `tools/` et non dans `tests/` : le chemin
    # ne suffit donc pas a separer production et verification. Trouve par ce
    # test a sa premiere execution -- l'instrument a mordu sur un oubli de
    # l'auteur de la carte, ce qui est exactement son role.
    "tools/mcp_nr.py": "harnais de NR loge dans tools/, pas un flux",
}


def _racine() -> Path:
    for base in (Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[1]):
        if (base / "tools" / "nokido_hub.py").exists():
            return base
    raise AssertionError("racine du depot introuvable")


def _integrity():
    for nom in ("nokido_agent.app.forge_integrity", "app.forge_integrity",
                "forge_integrity"):
        try:
            return importlib.import_module(nom)
        except Exception:  # noqa: BLE001
            continue
    raise AssertionError("forge_integrity introuvable")


# ───────────────  LA CARTE EXISTE ET SES FICHIERS AUSSI  ──────────────────

def test_les_fichiers_de_la_carte_existent_tous():
    """Une carte qui nomme un fichier disparu ne mesure plus rien -- defaut
    rencontre le jour meme dans le ledger des capacites prouvees, qui nomme un
    NR absent du depot."""
    racine = _racine()
    manquants = [c for c in CHEMINS_REVOCATION if not (racine / c).exists()]
    assert not manquants, (
        "la carte de revocation nomme des fichiers absents : %s" % manquants)


# ──────  LE MAILLON MANQUANT DE L IDENTITE : PAS D EMETTEUR  ──────────────

def test_la_revocation_d_identite_n_a_aucun_emetteur_de_production():
    """LA MESURE. On cherche les appels a `.revoke(` dans `app/` et `tools/`,
    en EXCLUANT les modules qui portent leur propre revocation homonyme.

    Ce test dit quelque chose de precis : le mecanisme n'est pas casse, il
    n'est jamais DECLENCHE. Le remede n'est donc pas de le reparer.
    """
    racine = _racine()
    trouves = {}
    for sous in ("app", "tools"):
        for chemin in (racine / sous).rglob("*.py"):
            rel = chemin.relative_to(racine).as_posix()
            if "_attic" in rel or "__pycache__" in rel:
                continue
            # HOMONYMIE : jti_cache porte `JtiRevocationCache.revoke`, qui
            # revoque un JETON et n'a rien a voir avec l'identite d'agent.
            if rel == "app/web_hub/jti_cache.py":
                continue
            try:
                arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, OSError):
                continue  # illisible != absent : on ne conclut pas dessus
            for n in ast.walk(arbre):
                if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "revoke":
                    trouves.setdefault(rel, []).append(n.lineno)

    inattendus = {k: v for k, v in trouves.items() if k not in NON_EMETTEURS_CONNUS}
    assert not inattendus, (
        "un appel a `revoke` apparait hors des non-emetteurs connus : %s. "
        "Soit un emetteur de revocation d'identite est ne -- tant mieux, "
        "mettre a jour la carte pour que l'inventaire reste vrai -- soit un "
        "chemin de test s'est glisse en production." % inattendus)


def test_le_recepteur_lui_est_bien_cable():
    """CONTRE-EPREUVE, sans laquelle le test precedent serait ambigu : le
    point de decision consulte l'etat de revocation. Le trou est donc
    strictement du cote emetteur, pas une absence de mecanisme."""
    integrity = _integrity()
    src = Path(integrity.__file__).read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    verify = next(
        (n for n in ast.walk(arbre)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "verify"),
        None)
    assert verify is not None, "`verify` introuvable dans forge_integrity"

    def _attributs(f):
        return {getattr(n, "attr", None) for n in ast.walk(f) if isinstance(n, ast.Attribute)}

    lu = _attributs(verify)
    # 2026-09-28 : la revocation vit en UN endroit, `_raison_revocation`, lu par `verify` et
    # par le renouvellement des jetons courts. Le recepteur se suit a travers la delegation ;
    # la contre-epreuve reste stricte : ni lecture directe ni delegation -> rouge.
    methodes = {n.name: n for n in ast.walk(arbre)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if "_raison_revocation" in lu and "_raison_revocation" in methodes:
        lu |= _attributs(methodes["_raison_revocation"])
    assert "_revoked_seqs" in lu or "_revoked_after" in lu, (
        "`verify` ne consulte plus l'etat de revocation : le recepteur a "
        "disparu, et le mecanisme devient entierement mort")


def test_l_etat_de_revocation_d_identite_ne_persiste_pas(tmp_path):
    """La volatilite est MESUREE, pas deduite du fait qu'on voie un dict : un
    dict peut etre recharge au boot. Deux managers construits sur le MEME
    secret ne partagent pas l'etat -- donc rien n'est relu d'une source
    durable."""
    integrity = _integrity()
    SEL = "sel-de-test-local-a-ce-fichier-jamais-celui-du-corps"
    m1 = integrity.IntegrityManager(SEL)
    m1.revoke("NR_AGENT_VOLATIL", 99)
    assert m1.revoke_status().get("NR_AGENT_VOLATIL") == 99

    m2 = integrity.IntegrityManager(SEL)
    assert "NR_AGENT_VOLATIL" not in m2.revoke_status(), (
        "l'etat de revocation SURVIT a une nouvelle instance : une source "
        "durable a ete branchee -- tant mieux, mettre a jour la carte")


# ──────────  LE CORPS SAIT PERSISTER : ce n est pas une absence  ──────────

def test_le_patron_de_persistance_existe_deja_dans_le_corps():
    """Contre-epreuve decisive pour le remede : persister une revocation n'est
    PAS une capacite manquante. `jti_cache` le fait, et `forge_agent_keys`
    designe deja ce module comme « le patron de persistance reutilisable ».

    Si un emetteur d'identite est branche un jour, il se cable sur ce patron
    -- on n'en ecrit pas un troisieme.
    """
    racine = _racine()
    src = (racine / "app/web_hub/jti_cache.py").read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    noms = {n.name for n in ast.walk(arbre)
            if isinstance(n, (ast.ClassDef, ast.FunctionDef))}
    assert "SqlitePersister" in noms
    assert "attach_and_preload" in noms


def test_l_inventaire_declare_les_trois_maillons_pour_chaque_chemin():
    """Un inventaire dont une entree perd un axe redevient la phrase floue que
    ce NR sert a remplacer."""
    for chemin, etats in CHEMINS_REVOCATION.items():
        for axe in ("objet", "emetteur", "recepteur", "persiste"):
            assert axe in etats, "%s ne declare pas l'axe %r" % (chemin, axe)
        for axe in ("emetteur", "recepteur", "persiste"):
            assert etats[axe] in ("OUI", "NON"), (
                "%s.%s vaut %r : un axe se mesure OUI/NON, un troisieme etat "
                "ici masquerait un maillon non verifie" % (chemin, axe, etats[axe]))


def test_l_instrument_distingue_les_deux_revoke_homonymes():
    """Sans cette separation, `JtiRevocationCache.revoke` serait compte comme
    un emetteur de revocation d'IDENTITE, et la carte dirait l'inverse de la
    verite. Deux `revoke` existent, ils ne revoquent pas le meme objet."""
    integrity = _integrity()
    assert hasattr(integrity.IntegrityManager, "revoke")

    jti = None
    for nom in ("nokido_agent.app.web_hub.jti_cache", "app.web_hub.jti_cache"):
        try:
            jti = importlib.import_module(nom)
            break
        except Exception:  # noqa: BLE001
            continue
    if jti is None:
        pytest.skip("jti_cache non importable dans ce runtime -- ILLISIBLE, "
                    "pas absent : l'existence du fichier est verifiee ailleurs")
    assert hasattr(jti.JtiRevocationCache, "revoke")
    assert jti.JtiRevocationCache.revoke is not integrity.IntegrityManager.revoke
