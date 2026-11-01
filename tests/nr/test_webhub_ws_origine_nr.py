"""NR 29/10 -- audit CS-3 (WebSocket hijacking cross-origin) : app/web_hub/proxy.py `_handle_websocket` n'examinait
AUCUN Origin avant authorize_ws ; SameSite=Lax ne couvre pas une page same-site servie sur un AUTRE PORT local. Une
origine de navigateur differente de l'hote servi (et hors liste LAFORGE_WEBHUB_WS_ORIGINES) est refusee (4403) AVANT
l'authentification ; un client sans Origin (CLI, script) n'est pas un navigateur et passe a l'authentification."""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "app")]

from nokido_agent.app.web_hub.ws_origine import origine_ws_admise  # noqa: E402


def _scope(origine=None, hote="127.0.0.1:7400"):
    h = [(b"host", hote.encode())]
    if origine is not None:
        h.append((b"origin", origine.encode()))
    return {"type": "websocket", "headers": h}


def test_meme_origine_admise():
    assert origine_ws_admise(_scope("http://127.0.0.1:7400")) is True


def test_autre_port_local_refuse():
    assert origine_ws_admise(_scope("http://127.0.0.1:8080")) is False


def test_origine_etrangere_refusee():
    assert origine_ws_admise(_scope("https://evil.example")) is False


def test_sans_origin_client_non_navigateur_admis():
    assert origine_ws_admise(_scope(None)) is True


def test_liste_declaree_admise(monkeypatch):
    monkeypatch.setenv("LAFORGE_WEBHUB_WS_ORIGINES", "http://localhost:5173, https://ui.local")
    assert origine_ws_admise(_scope("http://localhost:5173")) is True


def test_proxy_verifie_l_origine_avant_l_authentification():
    """Chemin reel : dans _handle_websocket, origine_ws_admise est appelee AVANT authorize_ws."""
    src = (ROOT / "app" / "web_hub" / "proxy.py").read_text(encoding="utf-8")
    f = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_handle_websocket")
    appels = [(n.lineno, n.func.id) for n in ast.walk(f) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id in ("origine_ws_admise", "authorize_ws")]
    noms = [nom for _l, nom in sorted(appels)]
    assert noms[:1] == ["origine_ws_admise"] and "authorize_ws" in noms
