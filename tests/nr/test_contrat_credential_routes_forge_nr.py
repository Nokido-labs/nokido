# -*- coding: utf-8 -*-
"""NR — P1-A : le CONTRAT D'ENTREE de `/api/recon/run` et `/api/ctf/run`.

MANDAT : DEMONTRER, NE RIEN MODIFIER. Ce fichier n'arme aucune garde et ne
change aucune autorite. Il fige ce qui a ete MESURE, pour qu'une modification
future parte d'un contrat etabli et non d'une intuition.

    CAPABILITY_TOKEN_PROUVE != CAPABILITY_TOKEN_ACCEPTE_PAR_LA_ROUTE

LA CHAINE, MAILLON PAR MAILLON (mesure 2026-09-22)

    PAGE                 `app/web_hub/recon_demo.html`
    credential dispo     <meta name="laforge-bearer" content="__LAFORGE_BEARER__">
                         substitue cote serveur par _AGENT_TOKENS["CLAUDE"] ou HUB_TOKEN
    appel JS reel        L129 fetch("/api/recon/run", ...)
    emission de l'entete L131 ...(TOK ? {"Authorization": "Bearer " + TOK} : {})
                         -> SI LE JETON MANQUE, AUCUN EN-TETE N'EST ENVOYE
    verification route   tok in set(_AGENT_TOKENS.values() + [HUB_TOKEN])
    decision             401 UNIQUEMENT hors loopback

CE QUE LA MESURE ETABLIT, ET QUI DECIDE DE LA SUITE

 1. La route ne lit NI `sub` NI `scopes`. Elle compare le jeton a un ENSEMBLE
    DE CHAINES. Un CapabilityToken (`payload.signature[.tpm]`) n'appartient pas
    a cet ensemble : il serait REFUSE hors loopback.

 2. `login_agent` ne sait pas emettre une portee reduite : `scopes =
    ring.default_scopes()`, une fonction du RING du role. Aucun parametre de
    scope n'existe dans sa signature.

 3. La primitive de VALIDATION existe pourtant : `_resolve_ring` decode et
    verifie les CapabilityToken (`is_cap` -> `CapabilityToken.decode` ->
    `(ring, sub)`), et `/mcp` s'en sert. Ces deux routes ne l'appellent pas.

        LA CAPACITE EXISTE ; CES ROUTES NE LA CONSOMMENT PAS.
        Le manque n'est pas une primitive : c'est un CABLAGE aux deux bouts.

 4. La garde ne mord QUE hors loopback, et `client == ""` figure parmi les
    exemptes : un `request.client` absent range un UNKNOWN du cote sain.

        GARDE PRESENTE != GARDE ATTEINTE != CREDENTIAL ACCEPTE != DECISION

CE QU'IL NE FAUT PAS DEDUIRE DE CE FICHIER : qu'il faut remplacer le credential
parce qu'un CapabilityToken serait « plus propre ». Tant que (1) et (2) tiennent,
la substitution CASSE les appelants sans rien prouver de plus.
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob tests + lecture (l.241)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

_RACINE = Path(__file__).resolve().parents[2]
for _p in (_RACINE, _RACINE / "app", _RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_HUB = _RACINE / "tools" / "nokido_hub.py"
_PAGE = _RACINE / "app" / "web_hub" / "recon_demo.html"
_ROUTES = ("recon_run", "ctf_run")


def _corps(nom: str) -> str:
    src = _HUB.read_text(encoding="utf-8", errors="replace")
    lignes = src.splitlines()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return "\n".join(lignes[n.lineno - 1:getattr(n, "end_lineno", n.lineno + 80)])
    raise AssertionError("handler %s introuvable -- re-mesurer la chaine" % nom)


# ── MAILLON « verification effectuee par la route » ──────────────────────

@pytest.mark.parametrize("route", _ROUTES)
def test_la_route_compare_des_CHAINES_et_ne_lit_aucune_portee(route):
    """PROUVE. Tant que c'est vrai, un credential de portee reduite ne sert a
    rien ici : la route ne saurait pas lire sa portee."""
    c = _corps(route)
    assert "_AGENT_TOKENS" in c and "HUB_TOKEN" in c, (
        "%s ne compare plus a l'ensemble des jetons statiques : le contrat "
        "d'entree a change, re-etablir la chaine" % route)
    for lu in ("scopes", "cap_token.scopes", "needed_ring"):
        assert lu not in c, (
            "%s lit desormais `%s` : la route consomme une PORTEE, le contrat "
            "a change" % (route, lu))


@pytest.mark.parametrize("route", _ROUTES)
def test_la_route_n_appelle_aucun_validateur_de_capability(route):
    """PROUVE. La primitive existe (`_resolve_ring` accepte les CapabilityToken,
    `/mcp` s'en sert) mais ces routes ne la consultent pas.

        EXISTS != CALLED — une capacite non consommee n'est pas une protection.
    """
    c = _corps(route)
    for validateur in ("_resolve_ring", "CapabilityToken", "authorize("):
        assert validateur not in c, (
            "%s appelle desormais `%s` : elle peut accepter un CapabilityToken, "
            "le contrat d'entree a change et A peut avancer" % (route, validateur))


@pytest.mark.parametrize("route", _ROUTES)
def test_la_garde_ne_mord_QUE_hors_loopback_et_un_client_vide_est_exempte(route):
    """PROUVE, et c'est le point le plus important pour la suite.

    `LOCAL_ONLY != TRUSTED` : en loopback, AUCUN credential n'est exige. Et
    `client == ""` (request.client absent) figure parmi les exemptes -- un
    UNKNOWN range du cote sain, ce que la constitution du corps interdit.
    """
    c = _corps(route)
    assert "localhost" in c and 'client not in' in c, (
        "%s n'exempte plus par l'origine : le contrat a change" % route)
    assert '""' in c.split("client not in")[1][:120], (
        "%s : l'exemption du client VIDE a disparu -- tant mieux, mettre a jour "
        "ce test et dire ce que devient un `request.client` absent" % route)


# ── MAILLON « construction / emission du credential » ────────────────────

def test_login_agent_SAIT_emettre_une_portee_reduite_depuis_A1():
    """RETOURNE le 2026-09-22 (phase A1).

    Ce test figeait « la portee est une fonction du RING, jamais un parametre ».
    A1 a leve la moitie EMISSION du contrat : `scopes_demandes` existe et
    delegue a `attenuer_ou_refuser`.

    QUATRIEME FAUX VERT DU MEME MOTIF CE JOUR-LA, attrape avant qu'il ne
    trompe : la version precedente cherchait les cles exactes `scopes`/`scope`
    dans la signature. Le parametre s'appelle `scopes_demandes` -- le test
    serait reste VERT en affirmant le contraire de ce qui est vrai.

        UN TEST QUI CHERCHE UN NOM CONNU D'AVANCE NE VOIT PAS LA CAPACITE QUI ARRIVE.

    On lit donc la PROPRIETE : existe-t-il un parametre par lequel une portee
    se demande, quel que soit son nom ?
    """
    import forge_auth_tokens as jetons  # noqa: PLC0415 — livrable, jamais d'importorskip
    params = inspect.signature(jetons.login_agent).parameters
    portee = [n for n in params if "scope" in n.lower() or "portee" in n.lower()]
    assert portee, (
        "aucun parametre de portee dans `login_agent` : A1 a ete retire, et un "
        "credential reduit redevient inemettable")
    src = inspect.getsource(jetons.login_agent)
    assert "attenuer_ou_refuser" in src, (
        "`login_agent` n'appelle plus `attenuer_ou_refuser` : la reduction "
        "serait refaite ailleurs, ou pire, appliquee en silence")
    assert "ring.default_scopes()" in src, (
        "le DEFAUT ne derive plus du ring : un appelant qui ne demande aucune "
        "portee doit obtenir exactement ce qu'il obtenait avant A1")


def test_la_chaine_A1_atteint_desormais_une_decision_de_route():
    """RETOURNE le 2026-09-22 (A2 prouve).

    Ce test figeait « A1 s'arrete a l'EMETTEUR ». C'etait vrai, et ca ne l'est
    plus : `/api/recon/run` consulte la portee et refuse avant tout effet.

    SIXIEME FAUX VERT DU MEME MOTIF CE JOUR-LA. La version precedente cherchait
    `"scopes"` et `"has_scope"` dans le corps des routes. Le cablage s'appelle
    `_portee_suffisante` et la methode `can(` : le test serait reste VERT en
    affirmant qu'aucune route ne consulte de portee.

        UN TEST QUI ENUMERE DES NOMS CONNUS D'AVANCE NE VOIT PAS CELUI QUI ARRIVE.
        Six fois en une journee, sur six fichiers differents.

    On lit la PROPRIETE : la chaine d'emission a-t-elle AU MOINS un
    consommateur cote decision ? Sans cela, A1 redevient un jeton mieux decrit
    et rien de plus.
    """
    consommateurs = [r for r in _ROUTES if "_portee_suffisante" in _corps(r)]
    assert consommateurs, (
        "aucune des routes ne consulte plus de portee : le cablage A2 a ete "
        "retire, et la chaine A1 redevient sans effet sur les decisions")
    assert "recon_run" in consommateurs, (
        "le consommateur attendu est `recon_run` ; trouve : %s" % consommateurs)


# ── MAILLON « credential disponible cote page » ──────────────────────────

def test_la_page_n_envoie_AUCUN_entete_si_le_jeton_manque():
    """PROUVE. `...(TOK ? {Authorization} : {})` -- l'absence de jeton ne
    produit pas un appel refuse, elle produit un appel SANS credential, que la
    route accepte en loopback.

        CREDENTIAL DISPONIBLE != CREDENTIAL CONSOMME
    """
    if not _PAGE.exists():
        pytest.skip("recon_demo.html absent de ce depot -- UNKNOWN, pas absent")
    t = _PAGE.read_text(encoding="utf-8", errors="replace")
    assert "laforge-bearer" in t, "la page ne porte plus le meta du credential"
    i = t.find("/api/recon/run")
    assert i > 0, "la page n'appelle plus /api/recon/run : re-mesurer l'appelant"
    voisinage = t[i:i + 400]
    assert "TOK ?" in voisinage or "TOK?" in voisinage, (
        "l'emission de l'en-tete n'est plus conditionnelle : tant mieux, "
        "mettre a jour ce test -- la page exige desormais un credential")


# ── A2 : GAP DE MESURE, fige le 2026-09-22 ──────────────────────────────
#
# A2 n'est ni PASS ni FAIL : il est INDETERMINE. Le cablage du scope serait
# faisable ; c'est sa PREUVE D'ABSENCE D'EFFET qui ne l'est pas au niveau exige.
#
#     Pour B, `inbox_stream` est module-level : on l'importe, on substitue
#     `INBOX`, on COMPTE les `pop()`. `DENY -> 0 pop` est une mesure.
#
#     Pour `recon_run`, le handler est une CLOTURE de `async _build_app()`.
#     Il n'existe pas au niveau module, aucun test ne construit l'app du hub,
#     et son effet (`_emit` sur le bus, puis `_tool_call("research_agent")`)
#     n'est atteignable qu'en montant l'application entiere.
#
# Ce qui reste atteignable sans nouvel instrument -- `DENY -> 403` et l'ORDRE
# decision-avant-effet par AST -- est precisement le niveau de preuve REFUSE
# pour B : « une reponse correcte ne prouve pas que `pop()` n'a pas eu lieu ».
# L'ecrire vert serait un faux calme.
#
# Instruments existants examines, AUCUN ne couvre ce cas sans effet de
# production : `forge_effet_reel_audit` (familles de mecanismes, 0 mention),
# `forge_capability_execution_trace` (transitions d'un provider LLM, 0),
# `app/forge_execution_tracer` (0), `forge_effect_surface` (fermeture d'une
# surface, 2 mentions sans rapport).
#
# CES TESTS ROUGISSENT QUAND LE GAP SE REFERME. C'est leur seule raison d'etre :
# rendre la transition OBSERVABLE au lieu d'une convention de memoire.


def test_A2_un_harnais_monte_l_app_du_hub():
    """RETOURNE. La condition du gap est LEVEE : un test monte l'app.

    Mesure du 2026-09-22 : `_build_app()` rend 91 routes en 0,1 s, sans effet
    de demarrage. `recon_run` reste une cloture -- et ce n'est plus un
    obstacle : on l'atteint PAR SA ROUTE.

        L'obstacle n'etait pas la structure du handler, c'etait l'absence de
        harnais. Extraire `recon_run` aurait ete une fausse necessite.
    """
    appelants = []
    for chemin in (_RACINE / "tests").rglob("test_*.py"):
        if chemin.name == Path(__file__).name:
            continue          # un instrument ne lit jamais son propre vocabulaire
        try:
            t = chemin.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue          # illisible != absent
        if any("_build_app(" in l and not l.strip().startswith("#")
               for l in t.splitlines()):
            appelants.append(chemin.name)
    assert appelants, (
        "plus aucun test ne monte l'app du hub : la preuve d'effet d'A2 n'est "
        "plus reproductible, le gap de mesure se rouvre")


def test_A2_la_verification_de_portee_A_un_consommateur():
    """RETOURNE. `EXISTS != CALLED` est LEVE pour cette primitive.

    CINQUIEME FAUX VERT DU MEME MOTIF CE JOUR-LA. La version precedente
    cherchait `has_scope(` et `_scope_allows(`. La methode s'appelle `can(` :
    le cablage l'a appelee, et ce test serait reste VERT en affirmant qu'aucun
    consommateur n'existe.

        J'AVAIS DEDUIT LE NOM DE LA METHODE AU LIEU DE LE MESURER.
        Un test qui cherche un nom suppose ne voit pas l'appel qui arrive.

    On lit donc la PROPRIETE : une decision de route consulte-t-elle une
    portee, quel que soit le nom de la methode ?
    """
    vus = []
    for sous in ("app", "tools"):
        base = _RACINE / sous
        if not base.is_dir():
            continue
        for chemin in base.glob("*.py"):
            if chemin.name == "forge_integrity.py":
                continue      # le proprietaire de la primitive, pas un consommateur
            try:
                t = chemin.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, ligne in enumerate(t.splitlines(), 1):
                nu = ligne.strip()
                if nu.startswith("#"):
                    continue
                if any(m in nu for m in ("_scope_allows(", ".can(", "has_scope(")):
                    vus.append("%s:%d" % (chemin.name, i))
    assert vus, (
        "plus AUCUN consommateur de la verification de portee : le cablage A2 "
        "a ete retire, et un CapabilityToken restreint redevient sans effet "
        "sur les routes")
    assert any("nokido_hub" in v for v in vus), (
        "le consommateur attendu (`_portee_suffisante` dans `nokido_hub`) a "
        "disparu ; restent : %s" % vus)


def test_A2_recon_exige_la_portee_AVANT_tout_effet():
    """La position compte autant que la presence.

    Le premier effet de `recon_run` est `_emit("recon_start")`. Si le controle
    de portee venait APRES, le refus serait un commentaire sur un effet deja
    produit -- ce que le NR runtime mesure, et que cette vigie statique garde.
    """
    c = _corps("recon_run")
    i_portee = c.find("_portee_suffisante")
    i_effet = c.find('_emit("recon_start"')
    assert i_portee >= 0, (
        "`recon_run` ne consulte plus de portee : le durcissement A2 a disparu")
    assert i_effet > 0, "le premier effet est introuvable : re-mesurer la chaine"
    assert i_portee < i_effet, (
        "la portee est consultee APRES le premier effet : le refus ne peut "
        "plus l'empecher")


def test_A2_ctf_run_reste_INTACT():
    """Le mandat bornait A2 a UNE route. Ce test garde cette frontiere."""
    c = _corps("ctf_run")
    assert "_portee_suffisante" not in c, (
        "`/api/ctf/run` consulte desormais une portee : hors du perimetre A2 "
        "arrete par l'owner. Si c'est voulu, il faut sa propre mesure -- rien "
        "ne prouve qu'elle partage le contrat de `recon`")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
