"""NR -- worker ACP : sessions persistantes en parallele, envoyer non bloquant, pouls pendant un tour long."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import acp_worker_faux as F  # noqa: E402


@pytest.fixture
def env(tmp_path):
    rt = F.routeur(tmp_path)
    yield tmp_path, rt
    F.fermer_tout(rt)


def _ouvrir(tmp_path, wk, agent):
    jid = F.deposer(tmp_path, "ouvrir", agent=agent)
    r = F.attendre(tmp_path, wk, jid)
    assert r["etat"] == "ACHIEVED" and r["resultat"]["ok"], r
    return r["resultat"]["session"]


def test_session_persiste_entre_jobs(env):
    tmp_path, rt = env
    wk = F.worker(tmp_path, rt)
    sid = _ouvrir(tmp_path, wk, "codex")
    for texte in ("un", "deux"):
        jid = F.deposer(tmp_path, "envoyer", session=sid, texte=texte, timeout=20)
        r = F.attendre(tmp_path, wk, jid)
        assert r["resultat"]["reponse"]["text"] == "re:" + texte
    jid = F.deposer(tmp_path, "lister")
    r = F.attendre(tmp_path, wk, jid)
    assert [s["id"] for s in r["resultat"]["sessions"]] == [sid]
    jid = F.deposer(tmp_path, "fermer", session=sid)
    assert F.attendre(tmp_path, wk, jid)["resultat"]["ok"] is True
    assert rt.lister() == []


def test_deux_sessions_en_parallele(env):
    tmp_path, rt = env
    wk = F.worker(tmp_path, rt)
    a = _ouvrir(tmp_path, wk, "codex")
    b = _ouvrir(tmp_path, wk, "claude")
    assert a != b
    ja = F.deposer(tmp_path, "envoyer", session=a, texte="lent", timeout=30)
    jb = F.deposer(tmp_path, "envoyer", session=b, texte="vite", timeout=30)
    wk.scan()
    t0 = time.time()
    rb = F.attendre(tmp_path, wk, jb)
    assert time.time() - t0 < 1.2, "la session B attend la session A"
    assert rb["resultat"]["reponse"]["text"] == "re:vite"
    assert F.resultat(tmp_path, ja)["etat"] == "ACCEPTED"
    ra = F.attendre(tmp_path, wk, ja)
    assert ra["resultat"]["reponse"]["text"] == "re:lent"


def test_envoyer_ne_bloque_pas(env):
    tmp_path, rt = env
    wk = F.worker(tmp_path, rt)
    sid = _ouvrir(tmp_path, wk, "codex")
    t0 = time.time()
    jid = F.deposer(tmp_path, "envoyer", session=sid, texte="lent", timeout=30)
    assert F.resultat(tmp_path, jid)["etat"] == "REQUESTED"
    wk.scan()
    assert time.time() - t0 < 0.8
    assert F.resultat(tmp_path, jid)["etat"] == "ACCEPTED"
    assert wk.en_vol() == 1
    F.attendre(tmp_path, wk, jid)


def test_pouls_pendant_un_tour_long(env):
    tmp_path, rt = env
    battements = []
    wk = F.worker(tmp_path, rt, battre=lambda **k: battements.append(k))
    sid = _ouvrir(tmp_path, wk, "codex")
    stop = threading.Event()
    th = threading.Thread(target=wk.boucle, args=(0.05, stop), daemon=True)
    th.start()
    try:
        jid = F.deposer(tmp_path, "envoyer", session=sid, texte="lent", timeout=30)
        time.sleep(0.4)
        n0 = len(battements)
        assert F.resultat(tmp_path, jid)["etat"] == "ACCEPTED"
        time.sleep(0.5)
        assert len(battements) > n0, "pas de pouls pendant le tour"
        assert any(b.get("jobs_en_vol") for b in battements)
        fin = time.time() + 15
        while F.resultat(tmp_path, jid)["etat"] != "ACHIEVED" and time.time() < fin:
            time.sleep(0.05)
        assert F.resultat(tmp_path, jid)["etat"] == "ACHIEVED"
    finally:
        stop.set()
        th.join(5)


def test_resultat_caviarde(env):
    tmp_path, rt = env
    wk = F.worker(tmp_path, rt)
    sid = _ouvrir(tmp_path, wk, "codex")
    jid = F.deposer(tmp_path, "envoyer", session=sid, texte=F.TEMOIN, timeout=20)
    F.attendre(tmp_path, wk, jid)
    brut = (tmp_path / "jobs" / f"{jid}.result.json").read_text(encoding="utf-8")
    assert F.TEMOIN not in brut


def test_resultat_malforme_est_illisible(env):
    # Decision owner 2026-10-28 : resultats NON signes (le worker n'a plus de secret). Reste : forme valide exigee.
    tmp_path, rt = env
    jid = F.deposer(tmp_path, "lister")
    d = tmp_path / "jobs"
    (d / f"{jid}.started").write_text("1")
    (d / f"{jid}.result.json").write_text("[1]", encoding="utf-8")
    (d / f"{jid}.done").write_text("1")
    assert F.resultat(tmp_path, jid)["etat"] == "ILLISIBLE"


def test_resultat_job_inconnu_est_requested(env):
    tmp_path, rt = env
    assert F.resultat(tmp_path, "f" * 32)["etat"] == "REQUESTED"
