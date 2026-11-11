"""NR -- clients Crawl4AI : jeton Bearer du COFFRE (owner 10/11 « fais-le » : mise a jour 0.8.6 -> 0.9.4).

Source primaire (CHANGELOG crawl4ai 0.9.0) : « set CRAWL4AI_API_TOKEN and send Authorization: Bearer <token> on
every request except GET /health ». Deux clients POSTaient /crawl sans en-tete (forge_crawl_tool, forge_dispatchers).
Contrats :
  1. `entetes_crawl4ai()` rend Content-Type + Authorization Bearer si le coffre a CRAWL4AI_API_TOKEN, sinon sans
     Authorization (le serveur 0.8.6 l'ignore, la bascule reste retrocompatible) ;
  2. un coffre illisible ne leve pas : pas d'en-tete, jamais un jeton invente ;
  3. les DEUX clients passent par `entetes_crawl4ai` (plus d'en-tete code en dur sur /crawl).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_crawl_tool as C  # noqa: E402


def test_entetes_avec_et_sans_jeton(monkeypatch):
    monkeypatch.setattr(C, "_jeton_crawl4ai", lambda: "tok-123")
    assert C.entetes_crawl4ai() == {"Content-Type": "application/json", "Authorization": "Bearer tok-123"}
    monkeypatch.setattr(C, "_jeton_crawl4ai", lambda: "")
    assert C.entetes_crawl4ai() == {"Content-Type": "application/json"}


def test_coffre_illisible_ne_leve_pas(monkeypatch):
    def _boum():
        raise RuntimeError("coffre")
    monkeypatch.setattr(C, "_jeton_crawl4ai", _boum)
    assert "Authorization" not in C.entetes_crawl4ai()


def test_les_deux_clients_passent_par_le_helper():
    for rel in ("app/forge_crawl_tool.py", "app/forge_dispatchers.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "entetes_crawl4ai()" in src, rel
        bloc = src.split("/crawl", 1)[1][:400]
        assert 'headers={"Content-Type": "application/json"}' not in bloc, rel
