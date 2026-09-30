# -*- coding: utf-8 -*-
"""Non-regression — un service eteint est NOMME et orientable, il n'est pas demarre d'office.

HISTOIRE DE CE FICHIER, en deux temps — la garder evite de refaire le premier.

1. 2026-08-26, demande owner : « http://127.0.0.1:7474/ en tuile devrait se lancer et
   start ». Le proxy rendait un 503 sec : la tuile annoncait une panne la ou il suffisait
   d'allumer. On a donc branche un reveil sur le chemin d'erreur du proxy.

2. 2026-09-18, consigne owner : « rien ne doit plus se lancer au clic ». Le reveil
   automatique est revoque. Mesure du jour qui montre pourquoi c'etait aussi un defaut
   technique : Neo4j :7474 et :7687 fermes, la page « Demarrage de graph… » se
   rechargeait toutes les 6 s SANS FIN en promettant un demarrage qui n'arrivait pas,
   et une sonde a 9 s n'y voyait qu'un TimeoutError. Une page qui promet sans fin
   apprend a l'utilisateur a ne plus la croire.

Ce que ce fichier protege DESORMAIS : naviguer n'agit pas, la page dit CE QUI manque,
et le geste explicite existe (le lanceur). Ce qui reste du premier temps et garde toute
sa valeur : le reveil declare doit nommer un service que l'un des deux registres connait,
avec sa FAMILLE, sinon le lien propose serait faux.

DEUX TESTS ONT ETE RETIRES le 2026-09-18 parce qu'ils lisaient le SOURCE BRUT de
`proxy.py` (`"MODULES" in src`) : un simple COMMENTAIRE mentionnant le mot suffisait a
les rendre verts. Une mention n'est pas une structure. Tout ce qui inspecte du code ici
passe desormais par `ast.unparse`, qui rend le code SANS ses commentaires ni docstrings.

Hermetique : AST + registres en memoire, aucun service demarre.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

APP = ROOT / "app" / "web_hub" / "app.py"
PROXY = ROOT / "app" / "web_hub" / "proxy.py"


def _reveils_declares() -> dict:
    """{prefixe_de_mount: nom_du_reveil} lus dans les app.mount(...) du portail."""
    if not APP.exists():
        pytest.skip("app.py absent")
    arbre = ast.parse(APP.read_text(encoding="utf-8", errors="replace"))
    out = {}
    for n in ast.walk(arbre):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "mount" and n.args):
            continue
        prefixe = n.args[0].value if isinstance(n.args[0], ast.Constant) else "?"
        for a in n.args[1:]:
            if isinstance(a, ast.Call):
                for k in a.keywords:
                    if k.arg == "reveil" and isinstance(k.value, ast.Constant):
                        out[prefixe] = k.value.value
    return out


def _code_seul(nom: str) -> str:
    """Code EXECUTABLE d'une fonction de proxy.py, sans commentaires ni docstring.

    `ast.unparse` reconstruit depuis l'arbre : les commentaires n'y survivent pas, et la
    docstring est retiree explicitement. Sans cette precaution, un instrument se fait
    mordre par son propre vocabulaire — paye trois fois le 2026-09-18, dont deux fois
    dans ce fichier meme (un commentaire citant `MODULES` rendait un garde vert).
    """
    src = PROXY.read_text(encoding="utf-8", errors="replace")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            noeud = ast.parse(ast.unparse(n)).body[0]
            corps = noeud.body
            if (corps and isinstance(corps[0], ast.Expr)
                    and isinstance(corps[0].value, ast.Constant)
                    and isinstance(corps[0].value.value, str)):
                noeud.body = corps[1:] or [ast.Pass()]
            return ast.unparse(noeud)
    pytest.fail("fonction %s introuvable dans proxy.py" % nom)


# ── Ce que la consigne du 2026-09-18 impose ────────────────────────────────────

def test_le_chemin_d_erreur_du_proxy_ne_demarre_rien():
    """MORSURE — rebrancher un demarrage ici fait rougir ce test immediatement.

    C'est le test central du fichier : tous les autres decrivent la page, celui-ci
    verrouille le COMPORTEMENT. Sans lui, on pourrait remettre un reveil automatique
    et garder une jolie page « eteint » qui allume quand meme.
    """
    code = _code_seul("_handle_http")
    for interdit in ("_demander_reveil", "launcher.start", "_lanceur.start",
                     "forge_ensure_service", "to_thread"):
        assert interdit not in code, (
            "le chemin HTTP du proxy appelle %r : naviguer vers une page demarrerait "
            "un service, ce que la consigne du 2026-09-18 interdit" % interdit
        )


def test_la_page_eteinte_reste_un_503():
    """Repondre 200 ferait passer un service eteint pour sain aupres d'une sonde."""
    code = _code_seul("_send_service_eteint")
    assert "503" in code, "la page de service eteint doit rester un 503"


def test_la_page_ne_se_recharge_plus_indefiniment():
    """Le rechargement automatique bouclait sans fin quand le service ne venait jamais."""
    code = _code_seul("_send_service_eteint")
    assert "refresh" not in code.lower(), (
        "la page porte encore un rechargement automatique : elle promet un demarrage "
        "que rien ne declenche plus"
    )
    assert "retry-after" not in code.lower(), (
        "Retry-After invite une sonde a repasser en boucle pour un service que "
        "personne ne demarrera d'office"
    )


def test_la_page_dit_ce_qui_manque_et_offre_le_geste():
    """Un refus qui n'indique aucune issue laisse l'utilisateur sans recours."""
    code = _code_seul("_send_service_eteint")
    assert "/launcher" in code, "la page n'oriente pas vers le lanceur"
    assert "target" in code, "la page ne nomme pas la cible attendue"
    assert "service" in code, "la page ne nomme pas le service eteint"


def test_la_page_est_calee_sur_le_design_system():
    """Meme feuille que la page des tuiles : un ecran d'erreur reste un ecran Nokido."""
    code = _code_seul("_send_service_eteint")
    assert "nokido.css" in code, "la page d'erreur n'importe pas la feuille commune"


def test_aucun_cooldown_residuel():
    """Un parametre sans effet se lit comme une securite et n'en est pas une.

    `cooldown_reveil` ne protegeait que d'un empilement de demarrages qui n'a plus lieu.
    """
    import inspect

    from app.web_hub.proxy import ReverseProxy
    assert "cooldown_reveil" not in inspect.signature(ReverseProxy.__init__).parameters


# ── Ce qui reste vrai du premier temps : le nom declare doit etre JUSTE ────────

def test_le_proxy_accepte_un_reveil():
    import inspect

    from app.web_hub.proxy import ReverseProxy
    assert "reveil" in inspect.signature(ReverseProxy.__init__).parameters


def test_les_services_on_demand_declarent_un_reveil():
    """Sans declaration, la page ne saurait meme pas NOMMER ce qui est eteint."""
    reveils = _reveils_declares()
    for prefixe in ("/graph", "/tui"):
        assert prefixe in reveils, (
            "%s pointe un service on-demand sans reveil : la page rendrait un 503 sec, "
            "sans nom ni orientation" % prefixe)


@pytest.mark.parametrize("prefixe", ["/graph", "/tui"])
def test_tout_reveil_declare_est_connu(prefixe):
    """Un nom inconnu des DEUX familles orienterait vers un lanceur qui ne peut rien."""
    valeur = _reveils_declares().get(prefixe)
    if valeur is None:
        pytest.skip("%s ne declare pas de reveil" % prefixe)
    _famille, _, nom = valeur.partition(":")
    nom = nom or valeur

    connu_launcher = False
    try:
        from app.web_hub import launcher as LA
        connu_launcher = nom in LA.MODULES
    except Exception as exc:  # noqa: BLE001
        pytest.skip("launcher illisible (%s)" % type(exc).__name__)

    connu_superviseur = False
    try:
        import inspect as _i

        import forge_ensure_service as ES
        connu_superviseur = nom in _i.getsource(ES.ensure)
    except Exception:  # noqa: BLE001 — registre illisible : traite en INCONNU, pas en absent
        connu_superviseur = False

    assert connu_launcher or connu_superviseur, (
        "reveil %r declare sur %s mais inconnu du launcher ET du superviseur — "
        "la page orienterait vers un geste impossible" % (nom, prefixe))


@pytest.mark.parametrize("prefixe", ["/graph", "/tui"])
def test_la_famille_du_reveil_est_declaree(prefixe):
    """« graph » est connu des DEUX registres : la famille doit etre declaree.

    ⚠ La raison qu'on donnait ici etait FAUSSE, corrigee le 2026-09-18 : on ecrivait
    « launcher sur :7420, superviseur sur :7474 ». `services.toml` dit autre chose —
    `NokidoGraphExplorer` lance `tools/nokido_graph_server.py` avec
    `LAFORGE_GRAPH_PORT = "7420"`, le MEME port que le lanceur. :7474 appartient a un
    SECOND explorateur, `NokidoGraph` (app/forge_graph_explorer.py), coupe au mode
    sauvegarde du 2026-09-05. Le proxy visait ce second-la, que le lanceur ne sait pas
    demarrer — d'ou un /graph/ eteint quel que soit le geste de l'utilisateur.

    Le prefixe reste utile : il dit QUI sait demarrer le module, et le ModuleSpec du
    lanceur declare le port, la ou un nom de service devait etre devine.
    """
    valeur = _reveils_declares().get(prefixe)
    if valeur is None:
        pytest.skip("%s ne declare pas de reveil" % prefixe)
    famille = valeur.partition(":")[0]
    assert famille in ("launcher", "service"), (
        "reveil %r sur %s : la famille doit etre DECLAREE (launcher: ou service:), "
        "sinon elle est devinee" % (valeur, prefixe))


def test_graph_est_bien_le_piege_a_deux_familles():
    """Contre-epreuve : si `graph` cessait d'etre ambigu, ce garde perdrait son sens —
    autant que le test le dise plutot que de passer pour une raison qui n'existe plus."""
    try:
        import inspect as _i

        import forge_ensure_service as ES
        from app.web_hub import launcher as LA
    except Exception as exc:  # noqa: BLE001
        pytest.skip("registres illisibles (%s)" % type(exc).__name__)
    assert "graph" in LA.MODULES and "graph" in _i.getsource(ES.ensure), (
        "`graph` n'est plus ambigu : reevaluer l'utilite du prefixe de famille")
