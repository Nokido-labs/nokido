"""NR 29/10 -- audit R7 `lecture_sans_borne` : app/web_hub n'avait AUCUNE limite globale de corps de requete (109 routes
`request.json()`/`body()` sans borne, pre-filtre AST sandbox/workspace/audit_r7_prefiltre/r7_candidats.json) -> epuisement memoire
par un appelant. Un middleware ASGI unique borne le corps : Content-Length annonce trop gros -> 413 sans rien lire ;
corps en flux sans longueur -> lu jusqu'au plafond + 1 puis 413 ; sous le plafond -> rejoue A L'IDENTIQUE a l'app.
Appels ASGI bruts (aucune dependance de client HTTP)."""
import ast
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "app")]

from nokido_agent.app.web_hub.taille_corps_middleware import TailleCorpsMiddleware  # noqa: E402

MAX = 100


class _App:
    def __init__(self):
        self.appele, self.corps = False, b""

    async def __call__(self, scope, receive, send):
        self.appele = True
        if scope["type"] == "http" and scope.get("method") != "GET":
            while True:
                m = await receive()
                self.corps += m.get("body", b"")
                if not m.get("more_body"):
                    break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _jouer(morceaux, methode="POST", longueur=None):
    app = _App()
    mw = TailleCorpsMiddleware(app, max_octets=MAX)
    entetes = [(b"content-length", str(longueur).encode())] if longueur is not None else []
    scope = {"type": "http", "method": methode, "path": "/api/x", "headers": entetes}
    file = [{"type": "http.request", "body": m, "more_body": i < len(morceaux) - 1} for i, m in enumerate(morceaux)]
    envoyes = []

    async def receive():
        return file.pop(0) if file else {"type": "http.disconnect"}

    async def send(msg):
        envoyes.append(msg)

    asyncio.run(mw(scope, receive, send))
    statut = next(m["status"] for m in envoyes if m["type"] == "http.response.start")
    return app, statut, envoyes


def test_content_length_annonce_trop_gros_413_sans_appeler_l_app():
    app, statut, envoyes = _jouer([b"x" * 10], longueur=MAX + 1)
    assert statut == 413 and app.appele is False
    corps = b"".join(m.get("body", b"") for m in envoyes if m["type"] == "http.response.body")
    assert json.loads(corps)["max_octets"] == MAX


def test_flux_sans_longueur_au_dela_du_plafond_413():
    app, statut, _ = _jouer([b"a" * 60, b"b" * 60])
    assert statut == 413 and app.appele is False


def test_sous_le_plafond_le_corps_est_rejoue_a_l_identique():
    app, statut, _ = _jouer([b"a" * 40, b"b" * 40], longueur=80)
    assert statut == 200 and app.appele is True and app.corps == b"a" * 40 + b"b" * 40


def test_get_passe_sans_etre_lu():
    app, statut, _ = _jouer([b""], methode="GET")
    assert statut == 200 and app.appele is True


def test_cable_le_plus_externe_du_web_hub():
    """Le DERNIER add_middleware de app/web_hub/app.py est le plus externe (Starlette empile) : c'est lui."""
    arbre = ast.parse((ROOT / "app" / "web_hub" / "app.py").read_text(encoding="utf-8"))
    ajouts = [n for n in ast.walk(arbre) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "add_middleware"]
    dernier = max(ajouts, key=lambda n: n.lineno)
    assert isinstance(dernier.args[0], ast.Name) and dernier.args[0].id == "TailleCorpsMiddleware"
