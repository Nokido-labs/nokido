"""NR — la route de publication d'evenements ne CROIT plus ce qui franchit sa porte.

AUDIT SECURITE 2026-09-18, finding #2 (confirme). `POST /api/events/publish`
figure dans les prefixes PUBLICS du webhub : le middleware d'authentification ne
la voit pas. Le handler refaisait son propre controle et, en boucle locale,
n'exigeait aucun jeton. Jusque-la c'est un CHOIX assume — le proxy Deno publie
depuis la machine, et fermer la route casserait le systeme nerveux.

Ce qui n'etait PAS un choix, et que ce test verrouille :

    trusted=True            <- LITTERAL
    agent=payload["agent"]  <- choisi par l'APPELANT

Un client non authentifie atteignant le loopback publiait donc des evenements
DE CONFIANCE sous l'identite de son choix. Or le compte sandbox atteint le
loopback (mesure du 2026-09-01). C'est l'inverse exact du plancher anti-spoof
`_HEADER_FLOOR_RING = 4`, qui DEGRADE une identite d'en-tete au lieu de la
prendre pour argent comptant.

Ce test mord sur l'EFFET, pas sur une lecture de source : il APPELLE le handler
reel avec un EventBus substitue et lit les arguments qui arrivent a `publish`.
Un NR qui se contenterait de grepper `trusted=True` prouverait `DECLARED`, jamais
`OBSERVED` — c'est la limite nommee pour `test_pont_portee_par_outil_nr`, et on
ne la reproduit pas ici.

Ce qui est SUBSTITUE, et pourquoi c'est licite : le VERDICT d'authentification
(`admin_token_ok`). Le sujet du test est la DERIVATION de l'identite et de la
confiance A PARTIR de ce verdict, pas le verdict lui-meme, qui a ses propres
tests. Le chemin teste reste celui de la production : meme fonction, meme corps,
meme appel a `publish`.
"""

import asyncio
import sys
import types
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

W = pytest.importorskip("app.web_hub.app", reason="webhub non importable dans cet environnement")


class _FausseRequete:
    """Le strict minimum que le handler lit sur une requete."""

    def __init__(self, host, payload):
        self.client = types.SimpleNamespace(host=host)
        self.headers = {}
        self.cookies = {}
        self._payload = payload

    async def json(self):
        return self._payload


@pytest.fixture()
def bus_substitue(monkeypatch):
    """Capture les arguments qui atteignent REELLEMENT `EventBus.publish`."""
    captures = []

    class _FauxBus:
        def __init__(self, *a, **k):
            pass

        def publish(self, **kw):
            captures.append(kw)
            return "evt-nr"

    faux = types.ModuleType("nokido_agent.app.forge_state_manager")
    faux.EventBus = _FauxBus
    faux.get_state_manager = lambda: None
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_state_manager", faux)
    return captures


def _publier(monkeypatch, captures, *, hote, authentifie, payload):
    monkeypatch.setattr(W, "admin_token_ok", lambda *a, **k: authentifie)
    reponse = asyncio.run(W.api_events_publish(_FausseRequete(hote, payload)))
    return reponse, (captures[0] if captures else None)


_CHARGE_HOSTILE = {
    "topic": "system.deno",
    "kind": "info",
    "data": {"x": 1},
    # L'appelant se reclame de l'organe le plus autoritaire du corps.
    "agent": "MASTER_SUPERVISOR",
}


def test_un_appelant_anonyme_ne_choisit_pas_son_nom(monkeypatch, bus_substitue):
    _, publie = _publier(
        monkeypatch, bus_substitue, hote="127.0.0.1", authentifie=False, payload=_CHARGE_HOSTILE
    )
    assert publie is not None, "l'evenement n'a pas ete publie — la fonction est cassee"
    assert publie["agent"] == "LOOPBACK_ANONYME", (
        "un appelant NON authentifie a impose son identite : il demandait "
        f"{_CHARGE_HOSTILE['agent']!r} et a obtenu {publie['agent']!r}. "
        "C'est la forgerie d'autorite du finding #2."
    )


def test_un_appelant_anonyme_ne_publie_pas_de_la_confiance(monkeypatch, bus_substitue):
    _, publie = _publier(
        monkeypatch, bus_substitue, hote="127.0.0.1", authentifie=False, payload=_CHARGE_HOSTILE
    )
    assert publie["trusted"] is False, (
        "un evenement anonyme est arrive marque DE CONFIANCE "
        f"(trusted={publie['trusted']!r}) — `trusted=True` litteral est revenu"
    )


def test_la_route_reste_ouverte_au_systeme_nerveux(monkeypatch, bus_substitue):
    """MORSURE SYMETRIQUE — durcir ne doit pas fermer la porte.

    Le correctif serait un echec s'il rendait la publication impossible : le
    proxy Deno publie depuis le loopback sans jeton, et le systeme nerveux en
    depend. On ne refuse pas l'appel, on refuse de croire son etiquette.
    """
    reponse, publie = _publier(
        monkeypatch, bus_substitue, hote="127.0.0.1", authentifie=False, payload=_CHARGE_HOSTILE
    )
    assert reponse.get("ok") is True and publie is not None, (
        "le durcissement a casse la publication loopback — le systeme nerveux "
        "ne peut plus emettre"
    )


def test_un_appelant_authentifie_garde_son_autorite(monkeypatch, bus_substitue):
    """L'autorite n'est pas supprimee, elle est EXIGEE."""
    _, publie = _publier(
        monkeypatch, bus_substitue, hote="127.0.0.1", authentifie=True, payload=_CHARGE_HOSTILE
    )
    assert publie["agent"] == "MASTER_SUPERVISOR", (
        "un appelant authentifie a perdu son identite : le correctif est trop "
        "large et degrade des emetteurs legitimes"
    )
    assert publie["trusted"] is True, "un appelant authentifie doit rester de confiance"


def test_un_distant_sans_jeton_est_toujours_refuse(monkeypatch, bus_substitue):
    """Le garde preexistant tient — on ne l'a pas dilue en le completant."""
    from fastapi import HTTPException

    monkeypatch.setattr(W, "admin_token_ok", lambda *a, **k: False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(W.api_events_publish(_FausseRequete("localhost", _CHARGE_HOSTILE)))
    assert exc.value.status_code == 401, f"statut inattendu : {exc.value.status_code}"
    assert not bus_substitue, "un appelant distant refuse a tout de meme publie"


# ---------------------------------------------------------------------------
# MEME MOTIF, AUTRE ROUTE : /api/opsec/set (revue defensive du 2026-09-18).
#
# Elle regle le niveau d'alerte opsec du systeme et figure aussi dans les
# prefixes PUBLICS. Sa docstring promettait « Bypass localhost authentication »
# — et le code ne lisait JAMAIS `request.client.host` : le contournement
# n'etait pas reserve au loopback, il etait ABSOLU. Deux autorites etaient des
# litteraux : `set_by="human_ui"`, qui fait passer l'appel pour un geste humain,
# et `force=True`, qui contourne le verrou pose pour empecher le changement.
#
# On teste ici la meme propriete que plus haut — l'autorite se PROUVE — et on la
# teste au meme endroit, parce que c'est un seul motif et non deux defauts.
# ---------------------------------------------------------------------------


@pytest.fixture()
def opsec_substitue(monkeypatch):
    """Capture ce qui atteint REELLEMENT `set_opsec_level`."""
    vus = []
    faux = types.ModuleType("nokido_agent.app.forge_opsec")
    faux.set_opsec_level = lambda level, **kw: (vus.append({"level": level, **kw}), {"ok": True})[1]
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_opsec", faux)
    return vus


class _RequeteOpsec(_FausseRequete):
    def __init__(self, host):
        super().__init__(host, {"level": "CTF", "reason": "nr", "lock": True})


def _regler_opsec(monkeypatch, vus, *, hote, authentifie):
    monkeypatch.setattr(W, "admin_token_ok", lambda *a, **k: authentifie)
    reponse = asyncio.run(W.opsec_set_api(_RequeteOpsec(hote)))
    return reponse, (vus[0] if vus else None)


def test_un_anonyme_ne_force_pas_le_verrou_opsec(monkeypatch, opsec_substitue):
    _, passe = _regler_opsec(monkeypatch, opsec_substitue, hote="127.0.0.1", authentifie=False)
    assert passe is not None, "l'appel n'a pas atteint set_opsec_level"
    assert passe["force"] is False, (
        "`force=True` litteral est revenu : un appelant qui ne prouve rien "
        "contourne le verrou pose pour empecher le changement de niveau"
    )


def test_un_anonyme_ne_se_fait_pas_passer_pour_un_humain(monkeypatch, opsec_substitue):
    _, passe = _regler_opsec(monkeypatch, opsec_substitue, hote="127.0.0.1", authentifie=False)
    assert passe["set_by"] != "human_ui", (
        "le journal opsec porterait « human_ui » devant un appel dont personne "
        "n'a etabli l'origine"
    )


def test_l_interface_locale_authentifiee_garde_son_autorite(monkeypatch, opsec_substitue):
    """MORSURE SYMETRIQUE — durcir ne doit pas retirer la capacite legitime."""
    _, passe = _regler_opsec(monkeypatch, opsec_substitue, hote="127.0.0.1", authentifie=True)
    assert passe["set_by"] == "human_ui" and passe["force"] is True, (
        f"l'interface authentifiee a perdu son autorite : {passe}"
    )


def test_la_restriction_annoncee_est_reellement_appliquee(monkeypatch, opsec_substitue):
    """Le defaut d'origine : une docstring qui promet une restriction que le code
    n'applique pas. Un appelant DISTANT et non authentifie doit etre refuse AVANT
    que le niveau opsec ne soit touche."""
    from fastapi import HTTPException

    monkeypatch.setattr(W, "admin_token_ok", lambda *a, **k: False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(W.opsec_set_api(_RequeteOpsec("localhost")))
    assert exc.value.status_code == 401
    assert not opsec_substitue, (
        "le niveau opsec a ete change malgre le refus — le garde s'execute apres "
        "l'effet, ce qui ne garde rien"
    )


def test_aucun_defaut_de_confiance_litteral_dans_la_source():
    """CONTROLE DE FORME — complement, jamais substitut aux tests d'effet.

    Les tests ci-dessus prouvent le comportement d'aujourd'hui. Celui-ci nomme la
    REGRESSION exacte, pour que son retour soit lisible dans le diff et pas
    seulement dans une trace d'echec.

    Il lit l'AST, jamais le TEXTE. Premiere ecriture de ce test : la recherche
    textuelle de `trusted=True` matchait le COMMENTAIRE qui documente la
    regression, juste au-dessus du code corrige — l'instrument s'accusait
    lui-meme, neuvieme instance du motif en trois semaines. L'AST ne porte pas
    les commentaires ; il porte les docstrings, mais un mot-clef d'appel ne peut
    jamais en etre une.
    """
    import ast

    arbre = ast.parse((RACINE / "app" / "web_hub" / "app.py").read_text(encoding="utf-8"))
    fn = next(
        (
            n
            for n in ast.walk(arbre)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
            and n.name == "api_events_publish"
        ),
        None,
    )
    assert fn is not None, "la route de publication a disparu ou a ete renommee"

    appels = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "publish"
    ]
    assert appels, "aucun appel a `publish` dans la route — la fonction a change de forme"

    for appel in appels:
        mots = {k.arg: k.value for k in appel.keywords if k.arg}
        confiance = mots.get("trusted")
        assert confiance is not None, "`trusted` n'est plus passe : le defaut du bus decide seul"
        assert not (isinstance(confiance, ast.Constant) and confiance.value is True), (
            "`trusted=True` litteral est revenu dans la route de publication : "
            "la confiance ne se derive plus de l'autorite resolue"
        )
