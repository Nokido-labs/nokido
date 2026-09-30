r"""NR — aucune I/O SQLite dans la boucle d'evenements du hub.

(Docstring RAW : il contient une accolade ASCII `\` de mise en page, que Python
lit sinon comme une sequence d'echappement invalide -- `SyntaxWarning` emis au
commit meme. Une figure de presentation ne doit pas salir la compilation.)

INCIDENT DU 2026-09-21, reproduit DEUX fois : une sonde GET sans jeton a tue
`:8766`. Cause localisee au lot pres :

    /health/readiness   503                  (repond)
    /api/rag/stats      PAS_DE_STATUT_EN_12S <- LE bloqueur
    /api/rag/stream     PAS_DE_STATUT_EN_12S \  victimes de la FILE, pas
    /forge/network      PAS_DE_STATUT_EN_12S /  coupables : `network_ui` rend
                                                UNE ligne de HTML

puis plus aucun LISTEN sur :8766 (`curl` en refus de connexion, exit 7 -- un
hub GELE aurait accepte la connexion et expire, un hub MORT la refuse ; la
distinction se mesure, elle ne se suppose pas).

`rag_stats` faisait TROIS balayages complets de `RAG/embeddings.db` (25 Go) --
`SUM(LENGTH(text))`, un `COUNT(*)` global, un `COUNT(*) WHERE embedding IS NULL`
sans index -- en `async def`, donc DANS la boucle. Le serveur entier gelait.

CE QUI REND CET INCIDENT INSTRUCTIF
===================================
La lecon etait DEJA ECRITE dans ce meme fichier, 660 lignes plus haut, dans
`health_readiness` :

    « sans COUNT -- un COUNT sur cette base a couche le hub le 2026-09-03 »

Elle tenait UNE porte. `rag_stats` en faisait trois, et personne ne l'avait
rapprochee. Un garde ne vaut que par le nombre de portes qu'il tient.

Et le remede existait : `tools/forge_route_async_bloquante.py`, applique le
2026-08-26 a `app/web_hub/app.py` (47 routes sur 62 en `async def` sans
`await`). `tools/nokido_hub.py` ne l'avait JAMAIS recu -- il en portait 40.

L'INVARIANT VERROUILLE ICI
==========================
Aucune fonction `async def` de `nokido_hub` ne fait d'appel SQLite SANS jamais
rendre la main. En `def`, Starlette route vers un threadpool : la requete reste
aussi lente -- on ne rend pas la base plus petite -- mais elle cesse d'immobiliser
tout le monde. Le cout n'est pas supprime, il cesse d'etre PARTAGE.

CE QUE CE NR NE PROUVE PAS, et c'est ecrit dans l'outil lui-meme :
    « une route async peut etre bloquante meme quand elle attend quelque part :
      la presence d'un `await` prouve que la fonction rend la main, pas qu'elle
      la rend ASSEZ SOUVENT. »
Sept `async def` du hub font du SQLite AVEC `await` (routes d'ingestion,
streams). Elles ne sont PAS jugees ici : les interdire casserait des routes
legitimement asynchrones, et les declarer saines serait une conclusion tiree
d'un critere que sa propre documentation dit incomplet. Leur mesure passe par
le TEMPS DE REPONSE sous charge, pas par l'AST.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

#: Appels qui touchent une base : tous synchrones avec le module `sqlite3`.
_SQLITE = {"connect", "execute", "executemany", "executescript",
           "fetchall", "fetchone"}

#: Corrigees le 2026-09-21. Nommees pour que la REGRESSION se voie, pas pour
#: figer une implementation : l'invariant reel est le test de propriete plus bas.
_CORRIGEES = ("rag_stats", "health_readiness", "loops_status")

# ══════════════════════════════════════════════════════════════════════════
#  DEUXIEME PORTE : L I/O RESEAU — ajoutee le 2026-09-21, le soir.
#
#  Ce fichier porte depuis ce matin la phrase « un garde ne vaut que par le
#  nombre de portes qu'il tient ». Il n'en tenait qu'UNE : SQLite.
#
#  `ui_generate` (tools/nokido_hub.py) est `async def` et atteint, a la
#  PROFONDEUR 2, un appel reseau BLOQUANT :
#
#      ui_generate                       async def, aucun deport
#        -> forge_ui_generator.generate_component(description, save=True)
#        -> _hub_ask(prompt, timeout=120)
#        -> urllib.request.urlopen("http://localhost:8766/mcp", timeout=120)
#
#  LA CIBLE EST LE HUB LUI-MEME. Un handler de la boucle appelle la boucle et
#  l'attend : `/mcp` ne peut pas etre servi tant que `ui_generate` la tient.
#  Deadlock jusqu'au timeout de 120 secondes, pendant lesquelles le serveur
#  entier est muet -- et la route n'exige AUCUN porteur.
#
#  DEUX GARDES EXISTANTS NE POUVAIENT PAS LE VOIR, chacun pour sa raison,
#  toutes deux ECRITES dans leur propre source :
#
#    * `forge_route_async_bloquante` : `CIBLES = ("app/web_hub/app.py",)` --
#      il ne regarde pas `nokido_hub.py` ; et il classe « legitimement async »
#      toute fonction contenant un `await` (ici `await request.json()`). Son
#      docstring le dit : « une route async peut donc etre bloquante ».
#    * le garde SQLite ci-dessus : il ne cherche que `sqlite3`.
#
#  L'invariant s'elargit donc au TRANSPORT, pas a une bibliotheque.
# ══════════════════════════════════════════════════════════════════════════

#: Appels reseau SYNCHRONES. Caracterisation POSITIVE : ce qu'on sait
#: reconnaitre. Un transport absent d'ici reste INCONNU, jamais « non
#: bloquant ».
_RESEAU_BLOQUANT = {"urlopen", "urlretrieve", "getresponse",
                    "get", "post", "put", "delete", "patch", "head", "request"}

#: Modules dont ces noms d'appel indiquent vraiment un transport synchrone.
#: `get`/`post` seuls sont trop communs -- il faut le module qui les porte.
_MODULES_RESEAU = ("urllib", "requests", "httpx", "http.client", "socket",
                   "urllib3", "aiohttp")

#: Formes qui RENDENT la main pendant l'appel bloquant. Leur presence suffit :
#: le cout demeure, il cesse d'etre PARTAGE.
_DEPORTS = ("run_in_threadpool", "to_thread", "run_in_executor",
            "loop.run_in_executor")


def _modules_importes_dans(noeud) -> set:
    """Modules importes DANS le corps -- c'est la forme du hub, qui importe
    au plus pres de l'usage."""
    mods = set()
    for x in ast.walk(noeud):
        if isinstance(x, ast.ImportFrom) and x.module:
            mods.add(x.module)
        elif isinstance(x, ast.Import):
            for a in x.names:
                mods.add(a.name)
    return mods


def _fichier_du_module(mod: str):
    for base in (Path(__file__).resolve().parents[2],
                 Path(__file__).resolve().parents[1]):
        court = mod.split(".")[-1]
        for sous in ("app", "tools", "app/web_hub"):
            p = base / sous / (court + ".py")
            if p.exists():
                return p
    return None


def _appel_reseau_direct(noeud) -> bool:
    """Un appel reseau synchrone ECRIT dans ce noeud."""
    return any(isinstance(x, ast.Call)
               and getattr(x.func, "attr", None) in _RESEAU_BLOQUANT
               and any(m in ast.dump(x) for m in _MODULES_RESEAU)
               for x in ast.walk(noeud))


def _fonctions_du_module(mod: str) -> dict:
    p = _fichier_du_module(mod)
    if p is None:
        return {}
    try:
        src = p.read_text(encoding="utf-8", errors="replace")
        arbre = ast.parse(src)
    except (OSError, SyntaxError):
        return {}
    return {n.name: n for n in ast.walk(arbre)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _fonction_atteint_le_reseau(nom: str, fonctions: dict, vus=None) -> bool:
    """La fonction NOMMEE atteint-elle un appel reseau synchrone ?

    On suit les appels INTRA-MODULE, avec garde contre les cycles.

    POURQUOI CETTE PRECISION. La premiere version de ce test demandait
    seulement « le MODULE importe contient-il du reseau quelque part ». Elle a
    rendu TREIZE coroutines fautives la ou une seule l'etait : un module qui
    sait faire du reseau ne prouve pas que la route l'exerce.

        OBSERVED(module) != PROPERTY_OF(route)

    C'est la faute que ce depot a deja nommee sur un autre inventaire, et un
    garde qui crie a faux se fait desarmer.

    BORNE : les appels sortant du module ne sont pas suivis. Un « non » dit
    que CETTE profondeur n'a rien vu, jamais que la route est sure.
    """
    vus = vus if vus is not None else set()
    if nom in vus or nom not in fonctions:
        return False
    vus.add(nom)
    noeud = fonctions[nom]
    # LE DEPORT PEUT ETRE A UN AUTRE NIVEAU QUE L'APPEL -- mesure du
    # 2026-09-21, sur mon propre correctif. `_handle_netcfg_proxy` enveloppe
    # son `urlopen` dans une fonction imbriquee passee a `run_in_executor` :
    # l'appel bloquant est toujours PRESENT dans l'arbre, et pourtant il ne
    # s'execute plus dans la boucle. Un detecteur qui ne regarde que la
    # presence de `urlopen` accuse un code deja corrige.
    #
    #     CALL_SITE != DECISION_SITE, ici sur le deport plutot que sur l'auth.
    #
    # BORNE ASSUMEE : si une fonction deporte UN appel et pas un autre, ce
    # test la laisse passer entierement. Il verrouille la presence d'un
    # deport, pas sa couverture -- et le dit plutot que de le laisser croire.
    if _deporte(noeud):
        return False
    if _appel_reseau_direct(noeud):
        return True
    for x in ast.walk(noeud):
        if isinstance(x, ast.Call):
            suivant = getattr(x.func, "id", None) or getattr(x.func, "attr", None)
            if suivant and suivant in fonctions and suivant != nom:
                if _fonction_atteint_le_reseau(suivant, fonctions, vus):
                    return True
    return False


def _reseau_atteint_depuis(noeud) -> list:
    """Les fonctions REELLEMENT nommees dans la coroutine qui atteignent un
    appel reseau synchrone. Liste vide = cette profondeur n'a rien vu."""
    appels = {getattr(x.func, "id", None) or getattr(x.func, "attr", None)
              for x in ast.walk(noeud) if isinstance(x, ast.Call)}
    coupables = []
    for mod in _modules_importes_dans(noeud):
        fonctions = _fonctions_du_module(mod)
        if not fonctions:
            continue
        for nom in sorted(appels & set(fonctions)):
            if _fonction_atteint_le_reseau(nom, fonctions):
                coupables.append("%s.%s" % (mod.split(".")[-1], nom))
    return coupables


def _deporte(noeud) -> bool:
    src = ast.dump(noeud)
    return any(d.split(".")[-1] in src for d in _DEPORTS)


def test_aucune_coroutine_n_atteint_un_reseau_bloquant_sans_deport():
    """LA DEUXIEME PORTE. Une `async def` qui atteint un appel reseau
    synchrone -- directement ou par un module qu'elle importe -- doit le
    DEPORTER. Sinon elle gele le serveur entier, et si la cible est le hub
    lui-meme, elle l'attend sans que personne puisse repondre."""
    fautives = []
    for n in ast.walk(_arbre()):
        if not isinstance(n, ast.AsyncFunctionDef):
            continue
        if _deporte(n):
            continue
        direct = _appel_reseau_direct(n)
        # Chaine REELLE : la fonction nommee dans la coroutine, puis ce
        # qu'elle appelle DANS son module. Pas « le module contient ».
        indirect = _reseau_atteint_depuis(n)
        if direct or indirect:
            fautives.append((n.name, n.lineno, "direct" if direct else indirect))
    assert not fautives, (
        "I/O RESEAU bloquante dans la boucle d'evenements : %r. Le serveur "
        "ENTIER gele pendant l'appel. Remede : deporter l'appel "
        "(`run_in_threadpool`), pas seulement passer la route en `def` -- "
        "`await request.json()` exige de rester `async`." % (fautives,))


def test_l_instrument_ne_condamne_pas_une_route_pour_son_module():
    """CONTRE-EPREUVE DE SUR-DETECTION, ajoutee apres 12 faux positifs.

    Un module qui porte a la fois une fonction reseau et une fonction pure ne
    doit condamner que la route qui appelle la PREMIERE.
    """
    fonctions = {
        n.name: n for n in ast.walk(ast.parse(
            "import urllib.request\n"
            "def lit_le_reseau():\n"
            "    return urllib.request.urlopen('http://x').read()\n"
            "def compte(a, b):\n"
            "    return a + b\n"))
        if isinstance(n, ast.FunctionDef)}
    assert _fonction_atteint_le_reseau("lit_le_reseau", fonctions) is True
    assert _fonction_atteint_le_reseau("compte", fonctions) is False

    # Et une fonction qui DEPORTE son appel n'est pas fautive, meme si
    # `urlopen` reste visible dans son arbre.
    deportee = {
        n.name: n for n in ast.walk(ast.parse(
            "import asyncio, urllib.request\n"
            "async def proxy():\n"
            "    def _sync():\n"
            "        return urllib.request.urlopen('http://x').read()\n"
            "    return await asyncio.get_running_loop().run_in_executor(None, _sync)\n"))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert _fonction_atteint_le_reseau("proxy", deportee) is False, (
        "un appel DEPORTE est compte comme bloquant : le detecteur accuse du "
        "code deja corrige")
    # et la chaine INTRA-MODULE est suivie d'un cran
    fonctions2 = {
        n.name: n for n in ast.walk(ast.parse(
            "import urllib.request\n"
            "def bas():\n"
            "    return urllib.request.urlopen('http://x').read()\n"
            "def haut():\n"
            "    return bas()\n"))
        if isinstance(n, ast.FunctionDef)}
    assert _fonction_atteint_le_reseau("haut", fonctions2) is True


def test_l_instrument_voit_une_coroutine_reseau_fautive():
    """CONTRE-EPREUVE. Un detecteur qui ne rend jamais rien est
    indistinguable d'un code sain -- prouve sur deux sources construites."""
    fautive = ast.parse(
        "async def h(request):\n"
        "    import urllib.request\n"
        "    body = await request.json()\n"
        "    return urllib.request.urlopen('http://x/y').read()\n")
    saine = ast.parse(
        "async def h(request):\n"
        "    import urllib.request\n"
        "    body = await request.json()\n"
        "    return await run_in_threadpool(urllib.request.urlopen, 'http://x/y')\n")

    def _juge(mod):
        for n in ast.walk(mod):
            if isinstance(n, ast.AsyncFunctionDef) and not _deporte(n):
                if any(isinstance(x, ast.Call)
                       and getattr(x.func, "attr", None) in _RESEAU_BLOQUANT
                       and any(m in ast.dump(x) for m in _MODULES_RESEAU)
                       for x in ast.walk(n)):
                    return True
        return False

    assert _juge(fautive) is True
    assert _juge(saine) is False


def test_la_presence_d_un_await_ne_vaut_pas_absence_de_blocage():
    """L'angle mort que `forge_route_async_bloquante` DECLARE dans sa propre
    source. Les deux sources du test precedent contiennent un `await` : si
    `_rend_la_main` suffisait a innocenter, aucune des deux ne serait vue."""
    fautive = ast.parse(
        "async def h(request):\n"
        "    import urllib.request\n"
        "    body = await request.json()\n"
        "    return urllib.request.urlopen('http://x/y').read()\n")
    coroutine = next(n for n in ast.walk(fautive)
                     if isinstance(n, ast.AsyncFunctionDef))
    assert _rend_la_main(coroutine) is True, (
        "cette source contient bien un `await` -- c'est tout l'objet")
    assert not _deporte(coroutine), (
        "et pourtant elle ne deporte rien : `await` != non bloquant")


def _hub_source() -> str:
    for base in (Path(__file__).resolve().parents[2],
                 Path(__file__).resolve().parents[1]):
        p = base / "tools" / "nokido_hub.py"
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise AssertionError("tools/nokido_hub.py introuvable depuis ce test")


def _arbre() -> ast.Module:
    return ast.parse(_hub_source())


def _appels_sqlite(noeud) -> set:
    vus = set()
    for x in ast.walk(noeud):
        if isinstance(x, ast.Call):
            nom = getattr(x.func, "attr", None)
            if nom in _SQLITE:
                vus.add(nom)
    return vus


def _rend_la_main(noeud) -> bool:
    return any(isinstance(x, (ast.Await, ast.AsyncFor, ast.AsyncWith))
               for x in ast.walk(noeud))


# ─────────────────────────  L INVARIANT  ──────────────────────────────

def test_aucune_coroutine_ne_fait_de_SQLite_sans_jamais_rendre_la_main():
    """LE GARDE. Une `async def` sans le moindre point de suspension s'execute
    d'un bloc dans la boucle : toute I/O qu'elle contient gele le serveur."""
    fautives = []
    for n in ast.walk(_arbre()):
        if isinstance(n, ast.AsyncFunctionDef):
            appels = _appels_sqlite(n)
            if appels and not _rend_la_main(n):
                fautives.append((n.name, n.lineno, sorted(appels)))
    assert not fautives, (
        "I/O SQLite dans la boucle d'evenements — le serveur ENTIER gele "
        "pendant ces appels, pas seulement la requete : %r. Remede : declarer "
        "la route `def` (Starlette la route vers un threadpool), cf. "
        "tools/forge_route_async_bloquante.py" % (fautives,))


@pytest.mark.parametrize("nom", _CORRIGEES)
def test_les_routes_corrigees_ne_redeviennent_pas_des_coroutines(nom):
    """Cliquet de regression sur les trois cas MESURES de l'incident.

    `rag_stats` est celui qui a tue le hub ; les deux autres sont de la meme
    classe exacte (SQLite, aucun `await`) et l'un d'eux est le capteur de
    sante -- qui, s'il gele, meurt avec le patient qu'il devait ausculter.
    """
    trouvee = [n for n in ast.walk(_arbre())
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == nom]
    assert trouvee, f"{nom} a disparu de nokido_hub : le cliquet ne garde plus rien"
    for n in trouvee:
        assert not isinstance(n, ast.AsyncFunctionDef), (
            f"{nom} est redevenue une coroutine alors qu'elle fait du SQLite : "
            "c'est la forme exacte qui a tue le hub deux fois le 2026-09-21")


def test_rag_stats_ferme_sa_connexion_meme_sur_erreur():
    """Trois scans longs sur une base verrouillee sont precisement la ou une
    exception survient — et la connexion fuyait."""
    for n in ast.walk(_arbre()):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "rag_stats":
            assert any(isinstance(x, ast.Try) and x.finalbody
                       for x in ast.walk(n)), (
                "rag_stats n'a pas de `finally` : la connexion a la base de "
                "25 Go fuit des qu'une requete leve")
            return
    pytest.fail("rag_stats introuvable")


def test_l_instrument_sait_voir_une_coroutine_fautive():
    """Un detecteur qui ne rend jamais rien est indistinguable d'un code sain.

    On lui donne une fautive FABRIQUEE : s'il ne la voit pas, le vert du test
    d'invariant ne prouve rien. Piege paye plusieurs fois dans cette campagne —
    un instrument se mesure avant de mesurer avec.
    """
    faux = ast.parse(
        "async def mauvaise(request):\n"
        "    c = sqlite3.connect('x')\n"
        "    return c.execute('SELECT 1').fetchone()\n")
    n = faux.body[0]
    assert isinstance(n, ast.AsyncFunctionDef)
    assert _appels_sqlite(n) == {"connect", "execute", "fetchone"}
    assert _rend_la_main(n) is False
