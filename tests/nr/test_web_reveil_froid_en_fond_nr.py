"""NR -- Docker A FROID : l'organe de recherche ATTEND un boot court, puis seulement lance un reveil de fond (10/11 soir).

Historique : 0d72203cf partait EN FOND des que le daemon etait down, sur la foi de « ~230 s a froid » (commentaire
du keeper, 12/08) presente a tort comme mesure. Mesure reelle (sandbox/docker_boot_samples.jsonl, 200 boots) :
mediane 11,7 s, p90 14,9 s, max 31,7 s. Les echecs du soir venaient de la SUSPENSION du keeper (cd553f996), pas
d'un boot lent : partir en fond payait Tavily pour rien. Contrats de `_reveiller_searxng` :
  1. daemon DOWN -> reveil SYNCHRONE borne LAFORGE_WEB_REVEIL_FROID_S (40 s ; pire cas de l'appel 65 s < 70 s) ;
  2. s'il echoue -> UN reveil de fond lance (les appels suivants en profitent), erreur nommee ;
  3. un seul reveil de fond a la fois ;
  4. daemon UP -> reveil synchrone borne LAFORGE_WEB_REVEIL_S (25 s).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_web_fallback as W  # noqa: E402


def _brancher(monkeypatch, froid, pret):
    lances, synchrones = [], []
    monkeypatch.setattr(W, "_docker_a_froid", lambda: froid)
    monkeypatch.setattr(W, "_demarrer_fond", lambda cible, **kw: lances.append(kw))
    monkeypatch.setattr(W, "_REVEIL_FOND_TS", 0.0)
    monkeypatch.setattr(W, "_ensure_searxng_sync", lambda attente: synchrones.append(attente) or pret)
    return lances, synchrones


def test_a_froid_attente_synchrone_longue_qui_aboutit(monkeypatch):
    lances, synchrones = _brancher(monkeypatch, froid=True, pret=True)
    assert W._reveiller_searxng() == (True, None)
    assert synchrones == [40] and lances == []


def test_a_froid_echec_lance_un_reveil_de_fond(monkeypatch):
    lances, synchrones = _brancher(monkeypatch, froid=True, pret=False)
    ok, err = W._reveiller_searxng()
    assert ok is False and "fond" in err
    assert synchrones == [40] and len(lances) == 1


def test_un_seul_reveil_de_fond(monkeypatch):
    lances, _ = _brancher(monkeypatch, froid=True, pret=False)
    W._reveiller_searxng()
    W._reveiller_searxng()
    assert len(lances) == 1


def test_daemon_up_reveil_synchrone_court(monkeypatch):
    lances, synchrones = _brancher(monkeypatch, froid=False, pret=True)
    assert W._reveiller_searxng() == (True, None)
    assert lances == [] and synchrones == [25]
