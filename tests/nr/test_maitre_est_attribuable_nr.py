r"""NR — le porteur du MAITRE est attribuable, meme quand il declare un autre nom.

MESURE DU 2026-09-21 sur la base certifiee `e77c304cf`, reproduite ici.

CE QUI A ETE MESURE
===================
`forge_videur.resolve_identity` traite quatre provenances. Deux d'entre elles
prennent le nom d'agent dans l'EN-TETE, qui n'est pas authentifie :

    via = "header"        nom declare, AUCUNE preuve
    via = "master_token"  nom declare, preuve de possession du secret DU HUB

Le plancher anti-spoof ne teste QUE la premiere :

    if via == "header" and int(ring) < _HEADER_FLOOR_RING:
        ring = _HEADER_FLOOR_RING

Donc un porteur du maitre qui declare `X-Agent-Name: <N>` obtient le ring
REGISTRE de <N>, et le journal l'attribue a <N>. Rien, dans l'entree, ne dit
qu'un porteur du maitre etait derriere -- sauf `via`, une chaine de trace.

C'est la MEME confusion que la constitution semantique nomme ailleurs :

    preuve de POSSESSION  !=  preuve d'IDENTITE

Presenter le maitre prouve qu'on detient le secret du hub. Cela ne prouve
RIEN sur le nom qu'on declare a cote.

CE QUE CE NR FAIT, ET CE QU'IL NE FAIT PAS
==========================================
Il ne REFERME PAS ce chemin. Le maitre est le canal des lanceurs de l'owner et
du hub lui-meme : le plafonner est une decision de politique, pas une deduction
du contrat, et un 401 inattendu sur un lanceur legitime serait une regression.

Il rend le chemin ATTRIBUABLE : le journal doit porter que l'acteur est un
porteur du maitre NON RESOLU, et que le sujet est un nom DECLARE. Un lecteur du
journal cesse alors de confondre « <N> a agi avec son propre jeton » et
« quelqu'un a presente le maitre en se disant <N> ».

    UNKNOWN != NO -- on ne sait pas QUI porte le maitre ; on l'ecrit, on ne
    fabrique pas une identite pour combler le trou.

OU EST LE CORRECTIF, ET POURQUOI PAS DANS LE VIDEUR
===================================================
`app/forge_videur.py` porte au moment de ce commit des modifications NON
COMMITEES d'une AUTRE SURFACE (anti-spoof, +42 lignes, dont
`_VIAS_PROUVEES`). Les toucher ferait entrer leur travail dans ce commit.

Le correctif est donc au SITE D'APPEL du hub, via le parametre `extra` que
`capture` expose deja. Mesure qui rend cette dette faible : sur 28 mentions de
`resolve_identity` au depot, un seul site appelle `capture` derriere --
`tools/nokido_hub.py`. Les autres sont `authorize` (0 appelant depuis le hub,
mesure du 2026-09-21), le hook `forge_tool_gate`, une demo et l'autotest.

A RAPATRIER dans `resolve_identity` quand l'arbre sera propre. C'est nomme ici
pour que la dette ne se perde pas.

DETTE REMBOURSEE LE 2026-09-21, mandat owner « durcir master token oui ».
`resolve_identity` pose desormais `acteur`/`sujet` sur le chemin maitre, a la
SOURCE UNIQUE et non plus au seul site d'appel. Le test correspondant a donc
CHANGE DE SENS : il verifiait l'absence, il verifie la presence. Ce n'est pas
un declassement -- c'est l'echeance que ce fichier s'etait fixee.

Ce qui N'A PAS bouge, et qui est verrouille par `test_le_ring_n_a_pas_bouge`
dans `test_maitre_porte_acteur_et_sujet_nr.py` : le RING. Appliquer le
plancher anti-spoof au maitre ferait chuter 7 112 appels sur 21 647 (33 %),
dont le superviseur et le webhub. L'ecart est EXPOSE (`ring_si_borne`) pour
etre compte sur trafic reel ; l'armer est une decision d'autorite, donc owner.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob app+tools + lecture
#   (l.650)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

# Valeurs de test. Aucune n'est un secret : elles sont construites par
# concatenation et portent leur role dans leur nom, pour ne pas armer le
# scanner de secrets sur un litteral qui RESSEMBLE a un jeton (recidive
# payee deux fois : P4.3.2 puis le 2026-09-21).
_MAITRE_NR = "nr-" + "valeur-factice-du-maitre"
_DERIVE_NR = "nr-" + "valeur-factice-derivee"
_PRIVILEGIE = "AGENT_PRIVILEGIE_NR"


def _racine() -> Path:
    for base in (Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[1]):
        if (base / "tools" / "nokido_hub.py").exists():
            return base
    raise AssertionError("racine du depot introuvable")


def _videur():
    for nom in ("nokido_agent.app.forge_videur", "app.forge_videur", "forge_videur"):
        try:
            return __import__(nom, fromlist=["resolve_identity"])
        except Exception:  # noqa: BLE001
            continue
    raise AssertionError("forge_videur introuvable")


@pytest.fixture()
def videur_avec_registre(monkeypatch):
    """Registre CONTROLE : le ring de l'agent de test ne depend pas de la
    machine. Sans ca, ce NR mesurerait la configuration locale et non le code
    (`OBSERVED(X) != PROPERTY_OF(X)`)."""
    v = _videur()
    monkeypatch.setattr(v, "_load_store", lambda: {_PRIVILEGIE: 1})
    return v


# ──────────────  L ETAT MESURE : l asymetrie existe  ──────────────────────

def test_le_nom_declare_sans_preuve_est_plafonne(videur_avec_registre):
    """Controle POSITIF de l'instrument : l'anti-spoof mord bien sur `header`.
    Sans ce test, le suivant serait indistinguable d'un registre mal charge."""
    v = videur_avec_registre
    ident = v.resolve_identity(_PRIVILEGIE, "", local=True, agent_tokens={})
    assert ident["via"] == "header"
    assert int(ident["ring"]) == 4, (
        "l'anti-spoof ne mord plus sur `header` : ce NR ne mesure plus rien "
        "(%r)" % (ident,))


def test_le_maitre_ne_plafonne_pas_le_nom_declare(videur_avec_registre):
    """LA MESURE. Meme nom declare, meme absence de preuve d'identite -- mais
    le ring registre est accorde parce que `via` n'est plus `header`."""
    v = videur_avec_registre
    ident = v.resolve_identity(_PRIVILEGIE, _MAITRE_NR, local=True,
                               agent_tokens={}, hub_token=_MAITRE_NR)
    assert ident["via"] == "master_token"
    assert int(ident["ring"]) == 1, (
        "le maitre ne rend plus le ring du nom declare : l'asymetrie a ete "
        "traitee ailleurs, re-mesurer avant de supprimer ce NR (%r)" % (ident,))


def test_le_maitre_produit_desormais_un_acteur(videur_avec_registre):
    """DETTE REMBOURSEE. Ce test verifiait l'ABSENCE d'acteur sur le chemin
    maitre, en nommant explicitement le rapatriement a venir. Il verifie
    maintenant sa PRESENCE.

    Mesure qui a declenche le rapatriement : 21 647 appels `master_token`,
    `as_master` = 0, IMPERSONATION 100 %. Le porteur ne s'annonce jamais comme
    MASTER -- il prend le nom d'un organe et recoit le ring de cet organe.

    Le ring n'est PAS touche ici : l'attribution et l'autorite sont deux
    chantiers, et les melanger ferait passer une decision d'autorite dans un
    correctif d'observabilite.
    """
    v = videur_avec_registre
    ident = v.resolve_identity(_PRIVILEGIE, _MAITRE_NR, local=True,
                               agent_tokens={}, hub_token=_MAITRE_NR)
    assert ident.get("acteur") == "classe:porteur_maitre", (
        "le videur ne nomme plus le porteur du maitre : la dette rapatriee le "
        "2026-09-21 a ete perdue (%r)" % (ident,))
    assert ident.get("sujet") == _PRIVILEGIE
    assert ident.get("sujet_prouve") is False, (
        "le nom vient d'un EN-TETE : le declarer prouve serait pire que de ne "
        "rien dire")


def test_la_delegation_elle_produit_bien_un_acteur(videur_avec_registre, monkeypatch):
    """Contre-epreuve : le videur SAIT poser acteur/sujet. Le trou du chemin
    maitre n'est donc pas une capacite absente, c'est une provenance non
    traitee -- distinction qui change entierement le remede."""
    v = videur_avec_registre
    monkeypatch.setattr(v, "_delegation_de",
                        lambda nom: {"ring_min_delegue": 1, "hors_local": True})
    ident = v.resolve_identity(_PRIVILEGIE, _DERIVE_NR, local=True,
                               agent_tokens={"PASSERELLE_NR": _DERIVE_NR})
    assert ident["via"].startswith("delegated:")
    assert ident.get("acteur") == "PASSERELLE_NR"
    assert ident.get("sujet") == _PRIVILEGIE


# ──────────────  LE CABLAGE : le hub compense au journal  ─────────────────

def test_le_hub_attribue_le_porteur_du_maitre_au_journal():
    """LE COEUR, et un test de CABLAGE dit comme tel : il verifie que le site
    d'appel traite la provenance `master_token`, pas que le journal soit relu.

    Le journal est chiffre en DPAPI USER scope et appartient au compte owner
    (mesure 2026-09-02) : le compte de service ne peut pas le dechiffrer.
    Conserver un champ n'est pas le rendre exploitable.
    """
    src = (_racine() / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    t = ast.parse(src)

    # On cherche une comparaison a la chaine "master_token" DANS la fonction
    # qui appelle `capture` -- pas n'importe ou dans le fichier : une mention
    # en commentaire ou dans une route sans rapport ne prouverait rien.
    porteurs = []
    for fn in ast.walk(t):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        appelle_capture = any(
            isinstance(n, ast.Call)
            and (getattr(n.func, "id", None) or getattr(n.func, "attr", None))
            in ("_vcapture", "capture")
            for n in ast.walk(fn)
        )
        if not appelle_capture:
            continue
        cite_maitre = any(
            isinstance(n, ast.Constant) and n.value == "master_token"
            for n in ast.walk(fn)
        )
        porteurs.append(cite_maitre)

    assert porteurs, "aucune fonction du hub n'appelle capture : re-mesurer"
    assert any(porteurs), (
        "le site d'appel de `capture` ne traite pas la provenance "
        "`master_token` : un porteur du maitre declarant un autre nom est "
        "journalise sous CE nom, sans qu'aucun champ ne dise qu'il etait "
        "derriere -- le passe-partout d'identite reste non attribuable")


# ══════════════════════════════════════════════════════════════════════════
#  P1-L — LA PROVENANCE DU MAITRE : TROIS CHEMINS, UN SEUL ATTRIBUE
#  Mesure du 2026-09-21, au soir.
#
#  Le maitre est compare en TROIS endroits, et ils ne se valent pas :
#
#    1. `_resolve_ring` nominal (videur)   -> via="master_token", puis
#                                             acteur/sujet poses au journal
#                                             (correctif du matin). ATTRIBUE.
#    2. `_resolve_ring` FALLBACK LEGACY    -> `return` place HORS du `try` qui
#                                             porte `_vcapture`. MUET.
#    3. `_admin_tok_ok`                    -> aucun journal du tout. MUET.
#
#  LE CAS 2 EST LE PLUS INSTRUCTIF. Il ne se declenche que si le videur tombe
#  -- « videur indispo -> fallback legacy ». C'est donc exactement le moment ou
#  l'on voudrait savoir QUI est passe, et c'est le seul moment ou personne ne
#  l'ecrit. Le seul signal est un `logger.warning`, qui n'est ni chaine, ni
#  signe, ni porteur d'identite.
#
#      LE CHEMIN DEGRADE EST CELUI QU'ON N'INSTRUMENTE JAMAIS
#
#  Et il accorde la meme chose : `agent_id = agent_hdr ... else "MASTER_TOKEN"`
#  -- le nom du header est conserve, comme sur le chemin nominal.
#
#  SECONDE MESURE, ET ELLE PORTE SUR MON PROPRE TRAVAIL. Les champs
#  `acteur`/`sujet` que j'ai poses au journal ce matin n'ont AUCUN
#  consommateur. Une recherche dans `app/`, `tools/` et `proxy_deno/` rend 21
#  sites -- dont la quasi-totalite lisent le SUJET D'UN COMMIT GIT
#  (`c["sujet"]`, `g["depot"]["sujet"]`), homonymie complete. Les seules
#  occurrences reelles sont les deux ECRITURES dans `forge_videur`.
#
#      PRODUCED != CONSUMED
#
#  C'est le motif « emettre reussit toujours, meme sans personne en face »
#  applique a mon propre correctif. Le journal est de surcroit chiffre en
#  DPAPI USER scope : le corps ne peut pas le relire. La chaine s'arrete a
#  l'ecriture.
#
#  CE NR N'AJOUTE AUCUNE ATTRIBUTION. Instrumenter le chemin degrade engage
#  une decision : y appeler `capture` au moment meme ou le videur est declare
#  indisponible demande de savoir si `capture` reste utilisable -- or les deux
#  vivent dans le meme module. Cela s'arbitre.
# ══════════════════════════════════════════════════════════════════════════

def _hub_lignes() -> list:
    return (_racine() / "tools" / "nokido_hub.py").read_text(
        encoding="utf-8", errors="replace").splitlines()


def test_le_fallback_legacy_compare_bien_le_maitre():
    """CONTROLE POSITIF : si ce chemin disparaissait, le test suivant
    deviendrait vert sans que rien n'ait ete corrige."""
    import ast as _ast
    src = "\n".join(_hub_lignes())
    resolve = next(
        (n for n in _ast.walk(_ast.parse(src))
         if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
         and n.name == "_resolve_ring"), None)
    assert resolve is not None, "`_resolve_ring` introuvable : re-mesurer"
    corps = "\n".join(_hub_lignes()[resolve.lineno - 1:
                                    getattr(resolve, "end_lineno", resolve.lineno + 130)])
    assert "fallback legacy" in corps.lower(), (
        "le repli legacy a disparu de `_resolve_ring` -- si le chemin a ete "
        "supprime, tant mieux : retirer ce test en le disant")
    assert "MASTER_TOKEN" in corps, (
        "le repli ne nomme plus MASTER_TOKEN : re-mesurer avant de conclure")


def test_le_chemin_degrade_n_est_pas_attribue():
    """LE FAIT DE P1-L, fige. Le `return` du repli est HORS du `try` qui porte
    `_vcapture` : quand le videur tombe, plus rien n'ecrit QUI est passe.

    Ce test ENREGISTRE. Le jour ou une capture y sera branchee, il rougira --
    et ce sera le bon moment pour verifier que `capture` est encore utilisable
    alors meme que le videur vient d'etre declare indisponible (les deux
    vivent dans le MEME module).
    """
    import ast as _ast
    src = "\n".join(_hub_lignes())
    resolve = next(
        n for n in _ast.walk(_ast.parse(src))
        if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
        and n.name == "_resolve_ring")

    # Le repli commence apres le dernier `ast.Try` du corps.
    essais = [x for x in _ast.walk(resolve) if isinstance(x, _ast.Try)]
    assert essais, "plus aucun `try` dans `_resolve_ring` : re-mesurer"
    fin_du_try = max(getattr(t, "end_lineno", t.lineno) for t in essais)

    captures_apres = [
        x.lineno for x in _ast.walk(resolve)
        if isinstance(x, _ast.Call)
        and (getattr(x.func, "id", None) or getattr(x.func, "attr", None))
        in ("capture", "_vcapture")
        and x.lineno > fin_du_try
    ]
    assert not captures_apres, (
        "une capture est apparue dans le repli legacy (lignes %s) -- tant "
        "mieux. Verifier alors : (1) qu'elle ne s'execute pas alors que le "
        "videur vient d'etre declare indisponible, (2) qu'elle distingue le "
        "repli du chemin nominal, sinon les deux deviennent indiscernables."
        % captures_apres)


# ══════════════════════════════════════════════════════════════════════════
#  P1-O — LE FALLBACK ACCEPTE SANS TRACE
#  Mesure du 2026-09-21 : comparaison PRIMAIRE / FALLBACK, champ par champ.
#
#      propriete        PRIMAIRE                    FALLBACK
#      ---------------  --------------------------  -------------------
#      decision site    resolve_identity (videur)   comparaisons locales
#      via              token/master_token/deleg.   AUCUN
#      acteur / sujet   poses si delegation         AUCUN
#      ring AU registre du registre                 DU REGISTRE (identique)
#      ring HORS regis. defaut 4 (_UNTRUSTED_RING)  defaut 3
#      capture ALLOW    oui (L1164)                 NON
#      capture DENY     oui (L1164)                 NON
#
#  CORRECTION D'UNE AFFIRMATION FAUSSE DE MA PREMIERE PASSE. J'avais ecrit
#  « FALLBACK : plancher 3 », en lisant l'APPEL `_agent_ring(agent_hdr, 3)`
#  sans lire la FONCTION :
#
#      def _agent_ring(agent, default):
#          return _agent_ring_map().get(agent.upper(),
#                                       _AGENT_RING.get(agent, default))
#
#  Le `3` est un DEFAUT DE DERNIER RECOURS, pas une valeur imposee. Le repli
#  lit le MEME registre que le chemin nominal. L'ecart reel est bien plus
#  petit -- et donc bien plus precis : il ne porte QUE sur les identites HORS
#  registre, ou le repli accorde 3 la ou le nominal accorde 4.
#
#      LE SYMBOLE N'EST PAS CE QU'IL DESIGNE -- septieme fois ce jour-la.
#
#  Et le `3` est DOCUMENTE comme un durcissement, pas comme une approximation :
#  « FAIL-CLOSED : une identite hors registre retombe sur 3 (isolee), JAMAIS
#  0. Ce repli defaultait a SYSTEM des lors que l'appel venait de la machine
#  locale. » Le ring du repli a donc DEJA ete durci une fois.
#
#  RESTE INDETERMINE, et ce n'est pas tranche ici : pourquoi 3 et non 4 ?
#  Le commentaire justifie « pas 0 », il ne justifie pas « 3 plutot que 4 ».
#  C'est une question d'AUTORITE, distincte de l'OBSERVABILITE que P1-O
#  traite -- une correction, une causalite.
#
#  TROIS RETOURS dans la zone fallback, DEUX SONT DES ACCEPTATIONS :
#      (_agent_ring(agent_hdr, 3), agent_hdr)   ALLOW
#      (_agent_ring(agent_id, 3), agent_id)     ALLOW  <- le maitre
#      (-1, 'bad_token')                        DENY
#
#  Un ALLOW non trace est plus grave qu'un DENY non trace : le refus laisse au
#  moins un 401 visible du client, l'acceptation ne laisse rien du tout.
#
#  DEUX CAUSES D'ENTREE, ET ELLES N'ONT PAS LES MEMES CONSEQUENCES -- c'est
#  ce que la mesure a rendu, et ce qui decide du remede :
#
#      l'IMPORT de forge_videur echoue   -> `capture` INDISPONIBLE
#      `resolve_identity` LEVE           -> `capture` DISPONIBLE
#
#  Le remede n'est donc pas « tracer toujours » (impossible dans le premier
#  cas) mais « tracer quand c'est possible ». C'est la nuance qui separe un
#  correctif juste d'un correctif qui transforme une panne en DOUBLE panne.
#
#  CE QUE CE TEST NE FAIT PAS : provoquer l'indisponibilite reelle du videur.
#  Aucune panne globale n'est fabriquee pour obtenir une preuve. La mesure est
#  STRUCTURELLE, et la borne est dite.
# ══════════════════════════════════════════════════════════════════════════

def _zones_de_resolve_ring():
    """(noeud, frontiere) -- la ligne ou finit le chemin NOMINAL.

    LA FRONTIERE EST LE `try` QUI CONTIENT `resolve_identity`, pas le dernier
    `try` du corps. Mesure du 2026-09-21 : en ajoutant un `try` dans une
    fonction imbriquee du repli (`_capturer_repli`), « le dernier try »
    designait soudain une ligne PLUS BASSE, et toute la zone repli
    disparaissait de la mesure.

        ast.walk DESCEND DANS LES FONCTIONS FILLES -- meme motif que le
        double comptage de P1-M (145 refus annonces, 75 reels).

    On identifie donc le try par son CONTENU, jamais par sa position.
    """
    import ast as _ast
    src = "\n".join(_hub_lignes())
    fn = next(n for n in _ast.walk(_ast.parse(src))
              if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
              and n.name == "_resolve_ring")
    essais = [x for x in _ast.walk(fn) if isinstance(x, _ast.Try)]
    assert essais, "plus aucun `try` dans `_resolve_ring` : re-mesurer"
    nominaux = [t for t in essais
                if "resolve_identity" in _ast.dump(t) or "_vresolve" in _ast.dump(t)]
    assert nominaux, (
        "aucun `try` ne contient `resolve_identity` : la frontiere "
        "nominal/repli n'est plus identifiable, re-mesurer")
    principal = max(nominaux, key=lambda t: getattr(t, "end_lineno", t.lineno))
    return fn, getattr(principal, "end_lineno", principal.lineno)


def _zone_du_repli() -> str:
    """Le TEXTE de la zone repli.

    LIRE LA ZONE, PAS LE `return`. Quatre tests ont rougi le 2026-09-21 parce
    qu'ils cherchaient `_agent_ring(` DANS les retours -- et un refactoring
    legitime venait de le sortir une ligne plus haut :

        _ring = _agent_ring(agent_hdr, 3)
        return _ring, agent_hdr

    Le plancher n'avait pas saute : il avait CHANGE DE LIGNE.

        un test qui lit le SYMBOLE casse au refactoring,
        un test qui lit la PROPRIETE tient.
    """
    fn, frontiere = _zones_de_resolve_ring()
    lignes_src = _hub_lignes()
    return "\n".join(lignes_src[frontiere:getattr(fn, "end_lineno", frontiere + 60)])


def test_le_repli_contient_bien_des_acceptations():
    """CONTROLE POSITIF. Si le repli ne rendait que des refus, le test suivant
    serait vert pour une raison sans rapport avec ce qu'on mesure."""
    import ast as _ast
    fn, frontiere = _zones_de_resolve_ring()
    # Une ACCEPTATION = un retour dont le ring n'est pas le refus (-1).
    # On juge la VALEUR rendue, pas le nom de la fonction qui l'a calculee.
    allow = []
    for n in _ast.walk(fn):
        if not (isinstance(n, _ast.Return) and n.lineno > frontiere and n.value):
            continue
        rendu = _ast.unparse(n.value)
        if not rendu.startswith("(-1"):
            allow.append(n.lineno)
    assert len(allow) >= 2, (
        "le repli legacy ne rend plus au moins deux acceptations (L%s) : "
        "re-mesurer la frontiere avant de conclure" % allow)


def test_le_repli_capture_son_resultat_quand_c_est_possible():
    """L'INVARIANT DE P1-O, desormais tenu :

        tout resultat produit par le repli doit etre observable LORSQUE
        l'infrastructure de capture est disponible, sans que l'indisponibilite
        du videur devienne elle-meme bloquante.

    Le repli s'active quand le videur tombe -- le moment ou l'on voudrait le
    plus savoir qui est passe. C'etait le seul ou rien n'etait ecrit.
    """
    import ast as _ast
    fn, frontiere = _zones_de_resolve_ring()
    captures = [n.lineno for n in _ast.walk(fn)
                if isinstance(n, _ast.Call)
                and (getattr(n.func, "id", None) or getattr(n.func, "attr", None))
                in ("capture", "_vcapture", "_capturer_repli")
                and n.lineno > frontiere]
    assert captures, (
        "le repli legacy ne capture toujours rien : ses trois retours -- dont "
        "DEUX acceptations -- restent invisibles. Un ALLOW non trace est plus "
        "grave qu'un DENY non trace : le refus laisse au moins un 401 visible "
        "du client, l'acceptation ne laisse rien.")


def test_la_capture_du_repli_ne_peut_pas_creer_une_SECONDE_panne():
    """LA FRONTIERE, et c'est elle le coeur du correctif.

    DEUX CAUSES d'entree dans le repli, aux consequences OPPOSEES :

        l'IMPORT de forge_videur echoue  -> `capture` INDISPONIBLE
        `resolve_identity` LEVE          -> `capture` DISPONIBLE

    Poser une capture sans distinguer les deux reviendrait a appeler le module
    que le repli vient de declarer indisponible -- la forme exacte qui
    transforme une panne en DOUBLE panne.

    Le nom doit donc etre LIE AVANT le `try`, pour qu'un import echoue laisse
    une valeur testable au lieu d'un `NameError`.
    """
    import ast as _ast
    src = "\n".join(_hub_lignes())
    fn = next(n for n in _ast.walk(_ast.parse(src))
              if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
              and n.name == "_resolve_ring")
    essais = [x for x in _ast.walk(fn) if isinstance(x, _ast.Try)]
    dernier = max(essais, key=lambda t: getattr(t, "end_lineno", t.lineno))

    # une liaison `_vcapture = None` (ou equivalent) AVANT le try
    liaisons = [n.lineno for n in _ast.walk(fn)
                if isinstance(n, _ast.Assign)
                and any(getattr(c, "id", None) == "_vcapture" for c in n.targets)
                and n.lineno < dernier.lineno]
    assert liaisons, (
        "`_vcapture` n'est pas lie AVANT le `try` : si l'import echoue, le "
        "repli leverait `NameError` en tentant de capturer -- une seconde "
        "panne causee par la trace elle-meme")

    # et la capture du repli doit etre GARDEE par une condition
    fn2, frontiere = _zones_de_resolve_ring()
    gardes = [n.lineno for n in _ast.walk(fn2)
              if isinstance(n, _ast.If) and n.lineno > frontiere
              and "_vcapture" in _ast.unparse(n.test)]
    assert gardes, (
        "la capture du repli n'est pas gardee par un test de disponibilite : "
        "elle s'executerait meme quand l'infrastructure est absente")


def test_la_capture_du_repli_marque_le_chemin_DEGRADE():
    """Sans marqueur, repli et nominal deviennent indiscernables au journal --
    et l'on perdrait precisement l'information qui a motive ce chantier."""
    import ast as _ast
    fn, frontiere = _zones_de_resolve_ring()
    src = "\n".join(_hub_lignes())
    zone = "\n".join(src.splitlines()[frontiere:getattr(fn, "end_lineno", frontiere + 40)])
    assert "repli" in zone or "fallback" in zone.lower() or "legacy" in zone.lower(), (
        "la capture du repli ne porte aucun marqueur de chemin degrade")


def test_le_repli_ne_fabrique_pas_de_provenance():
    """ABSENCE_DE_DONNEE != DONNEE_RECONSTRUITE.

    Le repli n'a ni `via`, ni `acteur`, ni `sujet` -- il ne les a jamais
    calcules. Les inventer pour « completer » la trace produirait une
    provenance FAUSSE, ce qui est pire que son absence : une absence se voit,
    une invention se croit.
    """
    import ast as _ast
    fn, frontiere = _zones_de_resolve_ring()
    src = "\n".join(_hub_lignes())
    zone = "\n".join(src.splitlines()[frontiere:getattr(fn, "end_lineno", frontiere + 40)])
    for invente in ("'acteur'", '"acteur"', "'sujet'", '"sujet"'):
        assert invente not in zone, (
            "le repli pose %s alors qu'il ne l'a jamais resolu : une "
            "provenance fabriquee se croit, une provenance absente se voit"
            % invente)


def test_le_repli_attrape_TOUTE_exception():
    """PORTEE DE LA BASCULE. Le handler est `Exception` nu : une `KeyError`
    sur `_ident['ring']` bascule autant qu'un import manquant. Ce n'est pas
    un defaut en soi -- c'est une PORTEE, et elle doit etre visible."""
    import ast as _ast
    src = "\n".join(_hub_lignes())
    fn = next(n for n in _ast.walk(_ast.parse(src))
              if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
              and n.name == "_resolve_ring")
    essais = [x for x in _ast.walk(fn) if isinstance(x, _ast.Try)]
    dernier = max(essais, key=lambda t: getattr(t, "end_lineno", t.lineno))
    types = [_ast.unparse(h.type) if h.type else "bare" for h in dernier.handlers]
    assert "Exception" in types or "bare" in types, (
        "le repli n'attrape plus `Exception` : sa portee a change (%s)" % types)


def test_le_repli_garde_un_plancher_de_ring():
    """CONTRE-EPREUVE. Le repli perd la provenance, mais il ne doit pas perdre
    le PLANCHER : une identite hors registre retombe sur 3, jamais 0. Cette
    propriete est deja tenue par `test_fail_closed_sur_le_privilege_nr` ; on
    la re-verifie ici parce que ce fichier touche la meme zone et qu'un
    correctif de trace ne doit pas la deplacer."""
    zone = _zone_du_repli()
    assert "_agent_ring(" in zone, (
        "le repli n'appelle plus `_agent_ring` : son plancher fail-closed a "
        "saute")
    assert not re.search(r"_agent_ring\([^,]+,\s*0\s*\)", zone), (
        "le repli accorde le ring 0 par defaut")


def test_le_repli_lit_le_MEME_registre_que_le_chemin_nominal():
    """LA PROPRIETE QUE MA PREMIERE PASSE AVAIT MAL LUE.

    `_agent_ring(agent, 3)` ne rend PAS 3 : il consulte le store puis les
    seeds, et ne retombe sur son deuxieme argument que pour une identite
    inconnue. Le repli n'attribue donc pas un ring arbitraire -- il lit la
    meme source que le chemin nominal.

    Ce test fige la lecture correcte, pour que l'erreur ne se repaie pas.
    """
    import ast as _ast
    src = "\n".join(_hub_lignes())
    fn = next(n for n in _ast.walk(_ast.parse(src))
              if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
              and n.name == "_agent_ring")
    corps = _ast.unparse(fn)
    assert "_agent_ring_map()" in corps, (
        "`_agent_ring` ne consulte plus le store : le repli attribuerait "
        "alors vraiment un ring fixe, ce qui n'etait pas le cas")
    assert "_AGENT_RING" in corps, "`_agent_ring` ne consulte plus les seeds"
    # le deuxieme argument est bien un DEFAUT, pas une valeur rendue telle quelle
    assert "default" in corps, (
        "le deuxieme parametre n'est plus utilise comme defaut : re-mesurer")


def test_l_ecart_de_defaut_entre_les_deux_chemins_est_enregistre():
    """L'ECART REEL, et il ne porte QUE sur les identites hors registre :

        nominal  -> `_UNTRUSTED_RING` (4)
        repli    -> 3

    Un cran plus permissif. Le commentaire du repli justifie « pas 0 », il ne
    justifie pas « 3 plutot que 4 ». Ce test ENREGISTRE l'ecart ; il ne le
    corrige pas -- c'est une question d'AUTORITE, pas d'observabilite, et les
    deux ne se traitent pas dans le meme correctif.
    """
    defauts = set(re.findall(r"_agent_ring\([^,]+,\s*(\d+)\)", _zone_du_repli()))
    assert defauts == {"3"}, (
        "le defaut du repli a change : %s. Si c'est un alignement sur "
        "`_UNTRUSTED_RING`, tant mieux -- le prouver par un NR d'autorite, "
        "pas par un correctif d'observabilite." % sorted(defauts))

    videur = None
    for base in (_racine() / "app" / "forge_videur.py",):
        if base.exists():
            videur = base.read_text(encoding="utf-8", errors="replace")
    assert videur is not None, "forge_videur introuvable : re-mesurer"
    assert "_UNTRUSTED_RING = 4" in videur, (
        "le defaut du chemin nominal n'est plus 4 : l'ecart mesure ici n'a "
        "plus le meme sens, re-mesurer avant de conclure")


def test_les_champs_d_attribution_n_ont_pas_de_consommateur():
    """PRODUCED != CONSUMED, mesure sur mon propre correctif du matin.

    PIEGE D'HOMONYMIE, la raison d'etre de ce test : `sujet` designe AUSSI le
    sujet d'un commit git dans une dizaine d'outils. Compter les occurrences
    brutes rendrait « 21 consommateurs » la ou il n'y en a aucun. On exige
    donc que le nom apparaisse a cote d'un vocabulaire d'IDENTITE.
    """
    import re as _re
    racine = _racine()
    contexte = _re.compile(r"acteur|sujet")
    identite = _re.compile(r"\bring\b|\bvia\b|token_h|identity|videur|capture")
    lecteurs = []
    for sous in ("app", "tools"):
        base = racine / sous
        if not base.is_dir():
            continue
        for chemin in base.rglob("*.py"):
            if {"__pycache__", "_attic"} & set(chemin.parts):
                continue
            try:
                lignes = chemin.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue          # illisible != absent
            for i, ligne in enumerate(lignes):
                if not _re.search(r"""(get\(\s*["'](acteur|sujet)|\[\s*["'](acteur|sujet))""", ligne):
                    continue
                voisinage = "\n".join(lignes[max(0, i - 4):i + 5])
                if identite.search(voisinage) and "forge_videur" not in chemin.name:
                    lecteurs.append("%s:%d" % (chemin.relative_to(racine).as_posix(), i + 1))
    # RETOURNE le 2026-09-22 : le consommateur est arrive.
    #
    # Ce test disait « tant mieux, mettre a jour ce test » le jour ou un lecteur
    # apparaitrait. `/inbox/{agent_id}` est desormais gouverne par l'ownership :
    # `_identite_inbox` LIT `sujet_prouve` et la decision en DEPEND. L'attribution
    # a cesse d'etre ecrite sans etre lue.
    #
    #     PRODUCED -> CONSUMED, et c'est la propriete qu'on verrouille maintenant.
    #
    # Le laisser en « aucun consommateur » en aurait fait un garde qui certifie
    # le contraire de ce qui est vrai -- le faux vert qu'on vient de payer deux
    # fois dans la journee.
    assert lecteurs, (
        "plus AUCUN consommateur de l'attribution : `acteur`/`sujet` sont "
        "redevenus ECRITS sans etre LUS. Le durcissement de `/inbox/` a-t-il "
        "ete retire ?")
    assert any("nokido_hub" in ref for ref in lecteurs), (
        "le consommateur attendu (`_identite_inbox` dans `nokido_hub`) a "
        "disparu ; lecteurs restants : %s" % lecteurs)


def test_l_instrument_ne_confond_pas_une_mention_et_un_traitement():
    """Un detecteur qui rend vrai sur n'importe quel fichier citant
    `master_token` serait non discriminant. On le prouve sur deux sources."""
    sans = ast.parse(
        "def f():\n    capture(i, 'x')\n")
    avec = ast.parse(
        "def f():\n"
        "    if i.get('via') == 'master_token':\n"
        "        pass\n"
        "    capture(i, 'x', {})\n")

    def _traite(mod):
        for fn in ast.walk(mod):
            if isinstance(fn, ast.FunctionDef):
                if any(isinstance(n, ast.Constant) and n.value == "master_token"
                       for n in ast.walk(fn)):
                    return True
        return False

    assert _traite(sans) is False
    assert _traite(avec) is True
