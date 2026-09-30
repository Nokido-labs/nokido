"""NR — aucune decision ne se prend sur `request.url.path` (CVE-2026-48710, veille lot_B_33).

MESURE du 2026-09-24 (C:/tmp/corrections/cve_starlette.json) : sous ${PYTHON} (Starlette 0.52.1),
un en-tete `Host: 127.0.0.1:7400/ping?x=` fait lire `/ping` a `request.url.path` alors que la
requete va reellement a `/admin` (`scope["path"]`). Le hub (Starlette 1.3.1) n'y est pas sensible.
Trois decisions y etaient exposees : l'authentification du webhub (`is_public_path(path)`), celle
du graph explorer (`/ping` exempte) et le chemin relaye par le proxy a la demande.

Cliquet : `request.url.path` / `req.url.path` sont INTERDITS dans app/, app/web_hub/ et tools/,
sauf aux sites de pure JOURNALISATION nommes ci-dessous. La correction est dans le CODE : elle
tient quelle que soit la version de Starlette installee.
"""
from __future__ import annotations

import re
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture de tous les .py de
#   app/, app/web_hub, tools/ (l.32)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
# (fichier, extrait de ligne) : journalisation seule, jamais une decision — chaque exception est NOMMEE.
EXCEPTIONS = {
    ("tools/nokido_mcp_proxy.py", "log_line = f"),
    ("tools/nokido_hub.py", "la ROUTE manquait a la signature"),
    ("tools/nokido_hub.py", "et non `request.url.path`"),
    ("tools/forge_bridge_oauth.py", "plutot que `url.path`"),
}
MOTIF = re.compile(r"\b(request|req|requete)\.url\.path\b")


def test_aucune_decision_sur_url_path():
    fautes = []
    for d in ("app", "app/web_hub", "tools"):
        for p in sorted((RACINE / d).glob("*.py")):
            rel = p.relative_to(RACINE).as_posix()
            for i, ligne in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if MOTIF.search(ligne) and not any(rel == f and ext in ligne for f, ext in EXCEPTIONS):
                    fautes.append("%s:%d %s" % (rel, i, ligne.strip()[:100]))
    assert not fautes, "decision(s) sur request.url.path (lire scope['path']) :\n" + "\n".join(fautes)


def test_les_exceptions_existent_encore():
    """Une exception qui ne correspond plus a rien doit disparaitre de la liste (pas de trou dormant)."""
    for f, ext in EXCEPTIONS:
        assert ext in (RACINE / f).read_text(encoding="utf-8", errors="replace"), (f, ext)


def test_le_superviseur_refuse_un_host_forge_avant_de_construire_la_route():
    """Meme classe, cote Deno (mesure du 2026-09-24, sonde_host_superviseur.py) : `req.url` est
    construit avec l'en-tete Host, et un Host forge reecrivait la route servie par :8765.
    `handleCtrl` doit valider Host AVANT la premiere construction de l'URL."""
    src = (RACINE / "proxy_deno" / "core" / "supervisor.ts").read_text(encoding="utf-8")
    debut = src.index("async function handleCtrl(")
    corps = src[debut:debut + 4000]
    assert "bad_host" in corps, "handleCtrl ne valide plus l'en-tete Host"
    assert corps.index("bad_host") < corps.index("new URL(req.url)"), (
        "l'URL est construite AVANT la validation du Host : la route depend encore du client")
    for hote in ("127.0.0.1:${CTRL_PORT}", "localhost:${CTRL_PORT}", "[::1]:${CTRL_PORT}"):
        assert hote in corps, hote
