"""NR — les routes /admin/* reconnaissent le jeton PROPRE d'un organe, et rien de plus.

DEFAUT MESURE le 2026-09-20, de bout en bout :

    POST /admin/run_job  avec FORGE_TOKEN_SUPERVISOR  ->  HTTP 401 unauthorized
    POST /admin/run_job  avec FORGE_MCP_TOKEN         ->  HTTP 200 + job_id

`_admin_tok_ok` compare le porteur au SEUL `FORGE_MCP_TOKEN`. Or `_hubAuthHeaders()`
cote superviseur fait `token = propre || master` : il PREFERE le jeton propre des
qu'il existe. Seme le 2026-09-02, celui-ci a donc remplace un master qui marchait
par un jeton que /admin refuse.

Le journal du superviseur porte la bascule :

    2026-08-23..28  proprioception audit  job=job_xxxx  ok=true
    2026-09-09..17  proprioception audit  job=?         ok=FALSE
    2026-09-09..17  snapshot memoire      job=?         ok=FALSE   (jamais reussi)

Consequence mesuree : `memory_availability_snapshot.json` perime de 14,25 jours,
ce qui bascule l'arbitre en INCONNU et rend `C_consolidation` structurellement
inatteignable -- le code le documente lui-meme.

Le SSoT tranche le sens du correctif, il n'y a pas de choix a faire :
`config/agent_identities.json` declare pour SUPERVISOR « il ne doit PAS emprunter
FORGE_MCP_TOKEN -- le master est le badge du corps entier, et un organe qui le
porte devient indiscernable dans le journal ». Rebrancher le master serait donc
contraire au registre.

CE QUE CE NR GARDE, et surtout CE QU'IL N'OUVRE PAS :

  - le master continue de passer  (aucune regression)
  - un organe de la LISTE BLANCHE admin, porteur de SON jeton propre, passe
  - un NOM sans jeton est refuse   (anti-spoof : nommer n'est pas autoriser)
  - un organe ring 1 HORS liste blanche est REFUSE -- c'est le point critique :
    elargir par le RING seul ouvrirait /admin a CLAUDE et GEMINI, eux aussi
    ring 1. L'autorisation admin ne se deduit pas d'un ring.
  - le 401 porte `WWW-Authenticate: Bearer` (RFC 7235 section 4.1 : le header est
    OBLIGATOIRE sur un 401 ; RFC 6750 section 3 en fixe le schema)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

hub_src = RACINE / "tools" / "nokido_hub.py"


def _source() -> str:
    if not hub_src.exists():
        pytest.skip("nokido_hub.py absent")
    return hub_src.read_text(encoding="utf-8", errors="replace")


def _corps_admin_tok_ok(src: str) -> str:
    """Le corps de `_admin_tok_ok`, borne a la declaration suivante.

    Un motif cherche dans 6 000 lignes finit par se trouver ailleurs et rend un
    faux vert -- defaut paye plusieurs fois aujourd'hui.
    """
    import re
    d = re.search(r"def _admin_tok_ok\s*\(", src)
    assert d, "_admin_tok_ok introuvable : la forme du hub a change"
    suite = re.search(r"\n    def \w+|\n\s{0,4}def \w+", src[d.end():])
    fin = d.end() + (suite.start() if suite else 3000)
    return src[d.start():fin]


def test_une_liste_blanche_admin_existe_et_n_est_PAS_un_ring():
    """L'autorisation admin ne se deduit pas d'un ring : CLAUDE et GEMINI sont
    ring 1 comme SUPERVISOR. Un elargissement par ring ouvrirait /admin a tous
    les clients du corps."""
    corps = _corps_admin_tok_ok(_source())
    assert "_ADMIN_ORGANES" in corps or "ADMIN_ORGANES" in corps, (
        "aucune liste blanche d'organes admin : le jeton propre du superviseur "
        "reste refuse (401 mesure), ou alors l'ouverture se ferait par ring et "
        "donnerait /admin a CLAUDE et GEMINI."
    )


def test_le_jeton_propre_est_compare_en_TEMPS_CONSTANT():
    """Une comparaison naive de secrets fuit leur contenu par le temps."""
    corps = _corps_admin_tok_ok(_source())
    assert "compare_digest" in corps, (
        "la comparaison du jeton propre doit passer par hmac.compare_digest, "
        "comme celle du master juste a cote."
    )


def test_un_NOM_sans_jeton_n_ouvre_rien():
    """« Nommer n'est pas autoriser » -- le plancher anti-spoof du videur.

    On verifie que le porteur est EXIGE : la liste blanche ne doit pas se
    contenter de lire l'en-tete d'identite.
    """
    corps = _corps_admin_tok_ok(_source())
    import re
    # un `if` sur le nom seul, sans exiger `tok`, serait le defaut exact
    assert re.search(r"if\s+not\s+tok|tok\s+and\s|if\s+tok\b", corps), (
        "aucune exigence explicite d'un porteur : un en-tete d'identite nu "
        "pourrait suffire, ce que le videur refuse partout ailleurs."
    )


def test_le_401_porte_WWW_Authenticate_RFC7235():
    """RFC 7235 section 4.1 : un 401 DOIT inclure WWW-Authenticate.

    Le hub rendait `{"ok":false,"error":"unauthorized"}` sans ce header --
    mesure directe du 2026-09-20. Un client conforme ne peut alors pas savoir
    quel schema d'authentification presenter.
    """
    src = _source()
    assert "WWW-Authenticate" in src, (
        "aucun en-tete WWW-Authenticate dans le hub : les 401 ne sont pas "
        "conformes a la RFC 7235 section 4.1."
    )
    assert "Bearer" in src, "le schema Bearer (RFC 6750) doit etre nomme"


def test_le_401_conforme_est_REELLEMENT_APPELE():
    """Un durcissement DEFINI mais jamais appele est une panne en attente.

    Defini seul, `_refus_401` ferait passer le test precedent sans qu'aucune
    reponse reelle ne porte le header. Le defaut est invisible a la relecture ET
    a l'AST -- paye le 2026-09-18 sur deux correctifs de securite sur cinq.
    """
    import re
    src = _source()
    assert re.search(r"def _refus_401\b", src), "_refus_401 n'est pas defini"
    appels = re.findall(r"return _refus_401\s*\(", src)
    assert appels, (
        "`_refus_401` est defini mais JAMAIS appele : aucune reponse 401 reelle "
        "ne porte le WWW-Authenticate, et le test de presence ci-dessus serait "
        "un faux vert."
    )
    # la route qui a produit la mesure doit etre parmi les appelants
    bloc = re.search(r"async def admin_run_job\(request\):(.+?)\n    async def ",
                     src, re.S)
    assert bloc and "_refus_401()" in bloc.group(1), (
        "/admin/run_job — la route ou le 401 a ete MESURE le 2026-09-20 — ne rend "
        "toujours pas un refus conforme."
    )


def test_le_master_passe_TOUJOURS():
    """Pendant obligatoire : on ELARGIT, on ne remplace pas.

    Sans ce garde, un correctif qui casserait l'authentification maitre
    paraitrait reussi -- tous les autres tests porteraient sur le seul chemin
    neuf.
    """
    import re
    corps = _corps_admin_tok_ok(_source())
    assert re.search(r"compare_digest\(tok,\s*expected\)", corps), (
        "la comparaison au master a disparu : l'elargissement est devenu un "
        "remplacement."
    )
    # et elle doit rendre True, pas seulement etre evaluee. Le garde `expected and`
    # (2b-2, 2026-09-28 : maitre lu au guichet) empeche un maitre VIDE de valider un
    # porteur vide ; il ne retire rien au succes du vrai maitre -- le comportement est
    # prouve par tests/nr/test_guichet_seul_2b2_nr.py::test_admin_accepte_le_maitre_du_guichet.
    assert re.search(r"if\s+(?:expected\s+and\s+)?_hmac\.compare_digest\(tok,\s*expected\)\s*:"
                     r"\s*\n\s*return True", corps), (
        "le master est compare mais son succes ne rend plus True."
    )
