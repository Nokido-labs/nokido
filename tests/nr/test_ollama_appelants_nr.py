# -*- coding: utf-8 -*-
"""NR : QUI appelle Ollama (:11434) -- journal JSONL des NOUVELLES connexions, attribue par parente prouvee.
Connexions simulees : aucun reseau, aucune base RAG."""
import json
import sys
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import forge_port_callers as P  # noqa: E402

Addr = namedtuple("Addr", "ip port")
Conn = namedtuple("Conn", "laddr raddr status pid")


def _c(pid, lport, rport=11434, status="ESTABLISHED"):
    return Conn(Addr("127.0.0.1", lport), Addr("127.0.0.1", rport), status, pid)


VIVANTS = {
    100: {"nom": "python.exe", "ppid": 50},   # fils d'un service supervise
    200: {"nom": "python.exe", "ppid": 1},    # orphelin sans ancetre identifie
}
PID_SERVICE = {50: "NokidoOpenaiProxy"}


def test_nouvelle_connexion_attribuee_par_parente_pas_par_nom():
    lignes, vus = P.releve_appelants([_c(100, 50001), _c(200, 50002)], VIVANTS, PID_SERVICE, {}, set(), now=1.0)
    par_pid = {r["pid"]: r for r in lignes}
    assert par_pid[100]["service"] == "descendant de NokidoOpenaiProxy"
    assert par_pid[200]["service"] == "ILLISIBLE"          # jamais devine par le nom "python.exe"
    assert par_pid[100]["nom"] == "python.exe" and par_pid[100]["ts"] == 1.0
    assert len(vus) == 2


def test_journal_uniquement_au_changement():
    c = [_c(100, 50001)]
    l1, vus = P.releve_appelants(c, VIVANTS, PID_SERVICE, {}, set(), now=1.0)
    l2, vus = P.releve_appelants(c, VIVANTS, PID_SERVICE, {}, vus, now=6.0)
    assert len(l1) == 1 and l2 == []
    l3, vus = P.releve_appelants(c + [_c(100, 50009)], VIVANTS, PID_SERVICE, {}, vus, now=11.0)
    assert [r["pid"] for r in l3] == [100]


def test_ignore_autres_ports_et_etats_et_borne_les_vus():
    bruit = [_c(100, 1, rport=8099), _c(100, 2, status="TIME_WAIT"), _c(None, 3)]
    l, vus = P.releve_appelants(bruit, VIVANTS, PID_SERVICE, {}, set(), now=1.0)
    assert l == [] and vus == set()
    _, vus = P.releve_appelants([_c(100, 50001)], VIVANTS, PID_SERVICE, {}, set(), now=1.0)
    _, vus = P.releve_appelants([], VIVANTS, PID_SERVICE, {}, vus, now=6.0)
    assert vus == set()


def test_tick_ecrit_jsonl_rotation_bornee_et_cadence(tmp_path):
    chemin = tmp_path / "ollama_appelants.jsonl"
    etat = {"vus": set(), "dernier": 0.0}
    conns = [_c(100, 40000 + i) for i in range(60)]
    n = P.tick_appelants_ollama(etat, chemin=chemin, now=10.0, conns=conns, vivants=VIVANTS,
                                pid_service=PID_SERVICE, max_bytes=2000)
    assert n == 60
    # re-appel < 5 s : aucun releve (cout borne)
    assert P.tick_appelants_ollama(etat, chemin=chemin, now=12.0, conns=conns + [_c(200, 1)],
                                   vivants=VIVANTS, pid_service=PID_SERVICE, max_bytes=2000) == 0
    assert chemin.stat().st_size <= 2000 + 400
    row = json.loads(chemin.read_text(encoding="utf-8").splitlines()[-1])
    assert set(row) >= {"ts", "pid", "nom", "service"}
