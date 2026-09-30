"""NR — les réponses d'ERREUR du webhub sortent rédigées, par les DEUX portes.

Mesure du 2026-09-19 : le rédacteur du firewall est câblé sur le canal MCP et
sur **aucun** des 27 fichiers de `app/web_hub/` (AST, 0 illisible). 34 sites y
laissent partir le message complet d'une exception.

Le point que ce test verrouille, et que le réflexe rate :

    raise HTTPException(..., detail=str(e))   11 sites
    return JSONResponse({"error": str(e)})    23 sites   <- invisibles à un
                                                            exception_handler

Un `app.exception_handler(...)` aurait couvert 11 sur 34 en se relisant comme
une protection générale. Les deux formes finissent en réponse ASGI, donc c'est
la réponse SORTANTE qu'on inspecte — et c'est cela qu'on teste ici, sans monter
l'application réelle.

Aucun secret réel n'apparaît : uniquement des marqueurs fabriqués.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from app.web_hub.redaction_middleware import RedactionMiddleware  # noqa: E402

# Chemin FABRIQUÉ : il n'existe pas, et il porte la forme que le rédacteur
# d'infrastructure remplace. On n'affirme jamais sur une valeur réelle.
CHEMIN_TEMOIN = r"C:\Users\CompteFabrique\secrets\jeton_temoin.txt"


def _repondre(statut: int, corps: bytes, ctype: bytes = b"application/json"):
    """Exerce le middleware sur une réponse ASGI et rend ce qui sort vraiment."""
    async def appli(scope, receive, send):
        await send({"type": "http.response.start", "status": statut,
                    "headers": [(b"content-type", ctype),
                                (b"content-length", str(len(corps)).encode())]})
        await send({"type": "http.response.body", "body": corps, "more_body": False})

    sorti: list = []

    async def send(message):
        sorti.append(message)

    async def receive():
        return {"type": "http.request"}

    async def run():
        await RedactionMiddleware(appli)({"type": "http"}, receive, send)

    asyncio.run(run())
    debut = next(m for m in sorti if m["type"] == "http.response.start")
    corps_final = b"".join(m.get("body", b"") for m in sorti
                           if m["type"] == "http.response.body")
    return debut, corps_final


def test_un_return_JSONResponse_est_redige():
    """La porte que l'exception_handler ne voit PAS — 23 sites sur 34."""
    brut = ('{"ok": false, "error": "FileNotFoundError: %s"}'
            % CHEMIN_TEMOIN.replace("\\", "\\\\")).encode()
    _, sorti = _repondre(502, brut)
    txt = sorti.decode("utf-8")
    assert CHEMIN_TEMOIN not in txt, (
        "le chemin absolu est sorti tel quel : le middleware ne mord pas")
    assert CHEMIN_TEMOIN.replace("\\", "\\\\") not in txt, (
        "forme ECHAPPEE encore presente : rediger le TEXTE d'un JSON rate les "
        "chemins Windows, il faut rediger ses VALEURS")
    assert "PATH_WIN" in txt, "le marqueur de redaction est attendu dans la sortie"


def test_un_raise_HTTPException_est_redige_aussi():
    """⚠️ L'assertion porte sur la forme ÉCHAPPÉE, celle qui existe réellement.

    Version initiale de ce test : elle cherchait `CHEMIN_TEMOIN` avec des
    backslashes simples dans un corps JSON qui les double. Elle passait donc
    sans rien prouver — un faux vert, pendant que le middleware ne rédigeait
    RIEN. On vérifie ici les deux formes.
    """
    brut = ('{"detail": "OperationalError: %s"}'
            % CHEMIN_TEMOIN.replace("\\", "\\\\")).encode()
    _, sorti = _repondre(422, brut)
    txt = sorti.decode("utf-8")
    assert CHEMIN_TEMOIN not in txt
    assert CHEMIN_TEMOIN.replace("\\", "\\\\") not in txt, (
        "la forme ECHAPPEE est celle qui circule dans du JSON : c'est elle qui "
        "doit disparaitre")
    assert "CompteFabrique" not in txt, "aucun fragment du chemin ne doit subsister"


def test_une_reponse_de_SUCCES_n_est_PAS_touchee():
    """Portée étroite assumée : un filtre sur tout le trafic finit désarmé.

    C'est le contrôle négatif : sans lui, un middleware qui rédige tout
    passerait les deux tests précédents sans qu'on sache ce qu'il coûte.
    """
    brut = ('{"chemin": "%s"}' % CHEMIN_TEMOIN.replace("\\", "\\\\")).encode()
    debut, sorti = _repondre(200, brut)
    assert sorti == brut, "une reponse 200 ne doit pas etre modifiee par ce garde"
    assert debut["status"] == 200


def test_un_corps_non_JSON_n_est_pas_touche():
    brut = b"<html>" + CHEMIN_TEMOIN.encode() + b"</html>"
    _, sorti = _repondre(500, brut, ctype=b"text/html; charset=utf-8")
    assert sorti == brut, "hors JSON, le middleware laisse passer sans copier"


def test_le_content_length_est_RECALCULE():
    """La rédaction change la longueur : un content-length périmé casse la réponse."""
    brut = ('{"error": "%s"}' % CHEMIN_TEMOIN.replace("\\", "\\\\")).encode()
    debut, sorti = _repondre(500, brut)
    entetes = {k.lower(): v for k, v in debut["headers"]}
    assert b"content-length" in entetes
    assert int(entetes[b"content-length"]) == len(sorti), (
        "content-length=%s mais corps=%d octets" % (entetes[b"content-length"], len(sorti)))


def test_un_corps_indecodable_est_laisse_INTACT_pas_corrompu():
    """Illisible n'autorise pas à casser : on préfère ne rien faire, et le dire."""
    brut = b'{"x": "' + bytes([0xFF, 0xFE, 0xFD]) + b'"}'
    _, sorti = _repondre(500, brut)
    assert sorti == brut


def test_le_corps_arrive_en_PLUSIEURS_morceaux_est_recolle():
    """Un corps fragmenté ne doit pas échapper au filtre par ses coutures."""
    moitie = CHEMIN_TEMOIN.replace("\\", "\\\\")
    a = ('{"error": "' + moitie[:20]).encode()
    b = (moitie[20:] + '"}').encode()

    async def appli(scope, receive, send):
        await send({"type": "http.response.start", "status": 500,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": a, "more_body": True})
        await send({"type": "http.response.body", "body": b, "more_body": False})

    sorti: list = []

    async def send(m):
        sorti.append(m)

    async def receive():
        return {"type": "http.request"}

    asyncio.run(RedactionMiddleware(appli)({"type": "http"}, receive, send))
    corps = b"".join(m.get("body", b"") for m in sorti if m["type"] == "http.response.body")
    assert CHEMIN_TEMOIN not in corps.decode("utf-8", "replace")


def test_le_middleware_est_REELLEMENT_enregistre_dans_l_application():
    """Un garde écrit et non câblé est une dette, jamais une sécurité.

    Lecture AST : `app.add_middleware(RedactionMiddleware)` doit exister, et
    venir APRÈS `AuthMiddleware` pour être le plus externe.
    """
    import ast

    src = (RACINE / "app" / "web_hub" / "app.py").read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    ordre = []
    for n in ast.walk(arbre):
        if isinstance(n, ast.Call):
            f = n.func
            nom = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if nom == "add_middleware" and n.args:
                a = n.args[0]
                if isinstance(a, ast.Name):
                    ordre.append((n.lineno, a.id))
    noms = [x[1] for x in ordre]
    assert "RedactionMiddleware" in noms, (
        "le middleware existe mais n'est pas enregistre : dette de cablage")
    assert "AuthMiddleware" in noms
    assert noms.index("RedactionMiddleware") > noms.index("AuthMiddleware"), (
        "il doit etre inscrit APRES l'authentification pour etre le plus EXTERNE "
        "et voir aussi les reponses qu'elle produit")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
