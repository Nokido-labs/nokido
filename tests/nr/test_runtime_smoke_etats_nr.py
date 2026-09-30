"""NR — le smoke de demarrage distingue QUATRE issues, et n'en confond aucune.

Mesure du 2026-09-19 sur le hub reel : `/health` rend 200, `tools/list` rend
**401**. La premiere version comptait ce 401 comme un ECHEC — ce qui aurait
rendu le workflow rouge alors que le hub fonctionnait *et* appliquait son
controle d'acces. Un smoke qui echoue sur la securite qu'on a voulue est un
smoke qu'on desarme a la premiere occasion.

    200 + outils   PASS        la capacite est prouvee
    401 / 403      GOUVERNE    le hub repond ET refuse : sain, mais la liste
                               d'outils n'est pas prouvee
    autre HTTP     HTTP_<n>    il repond, mal
    rien           SANS_REPONSE

Le test ne demarre aucun hub : il substitue les deux seules fonctions qui
touchent le reseau, et pose un garde de morsure avant toute assertion.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tools import forge_runtime_smoke as S  # noqa: E402


def _cabler(monkeypatch, code_mcp: int, corps_mcp: str, port_ouvert: bool = True):
    """Substitue le reseau. Rend un temoin pour verifier que la substitution mord."""
    appels: list[str] = []

    def faux_http(url, corps=None, delai=10.0):
        appels.append(url)
        if url.endswith("/health"):
            return 200, '{"status":"ok"}'
        return code_mcp, corps_mcp

    monkeypatch.setattr(S, "_http", faux_http)
    monkeypatch.setattr(S, "_port_ouvert", lambda h, p, delai=1.0: port_ouvert)
    return appels


def _etats(r):
    return {e["etape"]: e["etat"] for e in r["etapes"]}


def test_un_401_est_GOUVERNE_et_non_un_echec(monkeypatch):
    appels = _cabler(monkeypatch, 401, '{"error":"Unauthorized"}')
    r = S.smoke(demarrer=False)
    assert appels, "la substitution n'a pas mordu : aucun appel HTTP intercepte"
    assert _etats(r)["mcp tools/list"] == "GOUVERNE"
    assert r["verdict"] == "PASS_GOUVERNE"


def test_un_403_aussi(monkeypatch):
    _cabler(monkeypatch, 403, "")
    assert S.smoke(demarrer=False)["verdict"] == "PASS_GOUVERNE"


def test_une_liste_d_outils_servie_est_un_PASS_franc(monkeypatch):
    appels = _cabler(monkeypatch, 200,
                     '{"result": {"tools": [{"name": "a"}, {"name": "b"}]}}')
    r = S.smoke(demarrer=False)
    assert appels, "substitution sans effet"
    assert _etats(r)["mcp tools/list"] == "PASS"
    assert r["verdict"] == "PASS"


def test_une_reponse_en_flux_SSE_est_lue(monkeypatch):
    """Le hub peut repondre en text/event-stream : le parseur doit suivre."""
    _cabler(monkeypatch, 200,
            'event: message\ndata: {"result": {"tools": [{"name": "x"}]}}\n\n')
    assert S.smoke(demarrer=False)["verdict"] == "PASS"


def test_une_erreur_serveur_reste_un_echec(monkeypatch):
    _cabler(monkeypatch, 500, "boom")
    r = S.smoke(demarrer=False)
    assert _etats(r)["mcp tools/list"] == "HTTP_500"
    assert r["verdict"] == "ECHEC"


def test_aucune_reponse_est_distincte_d_un_refus(monkeypatch):
    _cabler(monkeypatch, 0, "ConnectionRefusedError")
    r = S.smoke(demarrer=False)
    assert _etats(r)["mcp tools/list"] == "SANS_REPONSE"
    assert r["verdict"] == "ECHEC"


def test_sans_demarrage_sur_port_ferme_ne_crie_pas_TIMEOUT(monkeypatch):
    """Piege du `while ... else` : sa clause s'execute AUSSI quand la boucle ne
    tourne jamais. La premiere version criait TIMEOUT sur un hub vivant."""
    _cabler(monkeypatch, 200, '{"result": {"tools": []}}', port_ouvert=False)
    r = S.smoke(demarrer=False)
    etats = _etats(r)
    assert etats.get("port initial") == "FERME"
    assert "attente port" not in etats, (
        "aucune attente n'a eu lieu : en parler serait inventer une mesure")
    assert r["verdict"] == "ECHEC"


def test_un_port_deja_pris_est_INDETERMINE_pas_un_echec(monkeypatch):
    """On jugerait quelqu'un d'autre : c'est une mesure impossible, pas une panne."""
    _cabler(monkeypatch, 200, "{}", port_ouvert=True)
    r = S.smoke(demarrer=True)
    assert r["verdict"] == "INDETERMINE"
    assert _etats(r)["port initial"] == "DEJA_OUVERT"


def test_le_code_de_retour_ne_punit_pas_un_INDETERMINE(monkeypatch, capsys):
    monkeypatch.setattr(S, "smoke", lambda **kw: {
        "verdict": "INDETERMINE", "etapes": [], "journal": "", "port": 8766})
    assert S.main([]) == 0
    monkeypatch.setattr(S, "smoke", lambda **kw: {
        "verdict": "ECHEC", "etapes": [], "journal": "", "port": 8766})
    assert S.main([]) == 1


def test_le_journal_est_imprime_dans_tous_les_cas(monkeypatch, capsys):
    """Sans journal, « le hub n'a pas repondu » ne se diagnostique pas."""
    monkeypatch.setattr(S, "smoke", lambda **kw: {
        "verdict": "ECHEC", "etapes": [], "journal": "TRACE-TEMOIN-42", "port": 8766})
    S.main([])
    assert "TRACE-TEMOIN-42" in capsys.readouterr().out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
