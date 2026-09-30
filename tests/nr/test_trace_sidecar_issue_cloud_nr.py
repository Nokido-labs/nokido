"""NR -- le sidecar trace l'ISSUE d'un appel fournisseur, et ne lit jamais un statut illisible comme un succes.

MESURE 2026-09-25 (8 derniers Mo de logs/mcp_audit.log) : canal CLOUD, groq 178 lignes OUT/CALL et
175 lignes IN/OK ; mistral 20/0, deepseek 10/0, ollama 9/0, claude 4/0. Le sidecar ne tracait que
les lignes OUT : pour les canaux entrants (HUB, STDIO) OUT porte le RESULTAT, mais pour CLOUD le sens
est inverse -- OUT = la requete partie (`log_cloud_out`, CALL), IN = la reponse (`log_cloud_in`).
Resultat : execution_traces ne contenait QUE des CALL pour les fournisseurs, lus « 0 % » par le
capteur d'usage, alors que groq reussissait ~98 %.

Meme mesure, second defaut : `_STATUS_RE` n'acceptait que des lettres ; `ERR:401` (473 lignes) ne
matchait pas et le statut retombait sur « OK » PAR DEFAUT -- un echec lu comme un succes. Latent
(ces lignes etaient des IN hors CLOUD, donc ignorees), mais un defaut qui range l'illisible du cote
sain attend son jour. Un statut illisible est INCONNU ; `ok` en minuscules (sse.open/close) est OK.
"""
from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_T = "2026-09-25T16:19:35"
REQ_CLOUD = (_T + ' | NetworkChannel.CLOUD:groq | {"direction": "Direction.OUT", "trace_id": "system", '
             '"agent": "HUB", "provider": "groq", "model": "m", "in": "resume ce texte | CALL')
REP_CLOUD_OK = (_T + ' | NetworkChannel.CLOUD:groq | {"direction": "Direction.IN", "trace_id": "system", '
                '"agent": "HUB", "latency_ms": "175.6", "provider": "groq", "out": "voici le resume | OK')
REP_CLOUD_ERR = (_T + ' | NetworkChannel.CLOUD:groq | {"direction": "Direction.IN", "trace_id": "system", '
                 '"agent": "HUB", "latency_ms": "30000", "provider": "groq", "out": "ERR: TimeoutError | ERR')
REQ_HUB = (_T + ' | NetworkChannel.HUB:rag | {"direction": "Direction.IN", "trace_id": "system", '
           '"agent": "CLAUDE", "in": "query x | CALL')
RES_HUB = (_T + ' | NetworkChannel.HUB:rag | {"direction": "Direction.OUT", "trace_id": "system", '
           '"agent": "CLAUDE", "out": "3 resultats | OK')
RES_401 = (_T + ' | NetworkChannel.HTTP_DIRECT:UNAUTHORIZED | {"direction": "Direction.OUT", '
           '"trace_id": "system", "agent": "RESCUE", "out": "refus | ERR:401')
RES_ILLISIBLE = (_T + ' | NetworkChannel.HUB:rag | {"direction": "Direction.OUT", "trace_id": "system", '
                 '"agent": "CLAUDE", "out": "x | ???')


@pytest.fixture
def sc():
    m = importlib.import_module("forge_trace_sidecar")
    m._ARGS_CACHE.clear()
    yield m
    m._ARGS_CACHE.clear()


def test_la_requete_cloud_n_est_pas_tracee_la_reponse_l_est_avec_ses_arguments(sc):
    assert sc._parse_line(REQ_CLOUD) is None
    tool, agent, args, out, status, _tid = sc._parse_line(REP_CLOUD_OK)
    assert (tool, agent, status) == ("groq", "HUB", "OK")
    assert args.startswith("resume ce texte")          # apparie depuis la requete
    assert out.startswith("voici le resume")
    assert sc.succes_de(status) is True


def test_l_echec_cloud_est_trace_en_echec(sc):
    sc._parse_line(REQ_CLOUD)
    parsed = sc._parse_line(REP_CLOUD_ERR)
    assert parsed is not None and parsed[4] == "ERR"
    assert sc.succes_de(parsed[4]) is False


def test_les_canaux_entrants_gardent_leur_sens(sc):
    assert sc._parse_line(REQ_HUB) is None
    tool, agent, args, out, status, _tid = sc._parse_line(RES_HUB)
    assert (tool, status) == ("rag", "OK") and args.startswith("query x")


def test_un_statut_avec_code_n_est_pas_un_succes(sc):
    parsed = sc._parse_line(RES_401)
    assert parsed is not None and parsed[4] == "ERR:401"
    assert sc.succes_de(parsed[4]) is False


def test_un_statut_illisible_est_inconnu_jamais_ok(sc):
    parsed = sc._parse_line(RES_ILLISIBLE)
    assert parsed is not None and parsed[4] == "INCONNU"
    assert sc.succes_de(parsed[4]) is False


def test_la_casse_du_statut_ne_fait_pas_un_echec(sc):
    assert sc.succes_de("ok") is True and sc.succes_de("OK") is True
    assert sc.succes_de("CALL") is False and sc.succes_de("") is False


def test_la_boucle_reelle_calcule_le_succes_par_succes_de(sc):
    # Le point d'entree du daemon est `_tail_loop` (boucle infinie sur le journal) : on verifie
    # qu'il emprunte bien la regle testee ci-dessus, pas une comparaison `== "OK"` en dur.
    source = inspect.getsource(sc._tail_loop)
    assert "success=succes_de(status)" in source
    assert 'status == "OK"' not in source
