# -*- coding: utf-8 -*-
"""Non-regression du garde memoire du wrapper de job (forge_job_runner).

Incident 2026-08-02 : un decoupeur en boucle a gonfle a 15 Go par URL, x12 ->
famine RAM, dwm.exe tue (l'iGPU 780M prend sa VRAM dans la RAM systeme), bureau
fige, redemarrage manuel de l'owner. Le wrapper bornait deja la taille du LOG,
mais RIEN ne bornait la RAM.

Le test eprouve le wrapper REELLEMENT genere par `launch_job` ; seul le spawn
privilegie (CreateProcessAsUser, hors de portee d'un compte non-owner) est
neutralise. Sans ce test le garde ne serait que du code charge jamais execute,
et un garde jamais declenche est un garde qu'on croit avoir.
"""
import os
import subprocess
import sys
import time

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (job reel) (l.74)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

# Le garde s'appuie sur psutil ; sans lui il s'annonce INACTIF dans le .err et
# ne borne rien. Un skip est honnete, un test vert ne le serait pas.
pytest.importorskip("psutil")

# La cible doit vivre sous la racine Nokido ou C:/tmp : `launch_job` refuse tout
# autre emplacement (et le tmp de pytest est partage entre comptes, cf. CI).
ZONE = os.path.join(ROOT, "sandbox", "workspace")

CIBLE_GLOUTONNE = """import time
blocs = []
for i in range(10):
    b = bytearray(20 * 1024 * 1024)
    b[::4096] = b"x" * len(b[::4096])   # toucher les pages : sinon pas de RSS
    blocs.append(b)
    time.sleep(1)
"""

CIBLE_SAINE = 'print("job sain")\n'


def _essai(monkeypatch, source, cap_mb, limite_s):
    """Genere le wrapper via launch_job, l'execute, rend (rc, err)."""
    import forge_sandbox_exec

    monkeypatch.setattr(
        forge_sandbox_exec, "spawn_as_sandbox_detached", lambda *a, **k: {"pid": None}
    )
    from forge_job_runner import JOBS_DIR, launch_job

    os.makedirs(ZONE, exist_ok=True)
    cible = os.path.join(ZONE, "_cible_garde_rss_%d.py" % os.getpid())
    with open(cible, "w", encoding="utf-8") as fh:
        fh.write(source)

    jobs = str(JOBS_DIR)
    a_nettoyer = [cible]
    try:
        res = launch_job(cible, online=False, lane="", rss_cap_mb=cap_mb)
        assert res.get("ok"), res
        jid = res["job_id"]
        wrap = os.path.join(jobs, jid + "_wrap.py")
        rc_f = os.path.join(jobs, jid + ".rc")
        err_f = os.path.join(jobs, jid + ".err")
        a_nettoyer += [wrap, rc_f, err_f, os.path.join(jobs, jid + ".log"),
                       os.path.join(jobs, jid + ".json"),
                       os.path.join(jobs, jid + ".fin")]  # cause de fin (dette D, 2026-10-02)

        # Le wrapper est du code GENERE : le hook AST du depot ne le valide pas.
        with open(wrap, encoding="utf-8") as fh:
            compile(fh.read(), wrap, "exec")

        # stderr -> .err, comme le lanceur REEL (spawn_as_sandbox_detached) : sans cette redirection,
        # `_dire` ecrivait le motif dans le stderr de pytest (avec succes) et jamais dans le .err --
        # le test echouait sur un montage qui n'existe pas en production (2026-10-02).
        _err_h = open(err_f, "w", encoding="utf-8")
        proc = subprocess.Popen([sys.executable, wrap], stderr=_err_h)
        t0 = time.time()
        rc = None
        while time.time() - t0 < limite_s:
            if os.path.exists(rc_f):
                with open(rc_f) as fh:
                    rc = fh.read().strip()
                break
            time.sleep(0.5)
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        _err_h.close()
        err = ""
        if os.path.exists(err_f):
            with open(err_f, encoding="utf-8", errors="replace") as fh:
                err = fh.read()
        return rc, err
    finally:
        for f in a_nettoyer:
            try:
                os.remove(f)
            except OSError:
                pass


def test_garde_tue_le_job_qui_gonfle(monkeypatch):
    """Cap 60 Mo, cible qui monte a 200 Mo : le job doit etre TUE, pas subi."""
    rc, err = _essai(monkeypatch, CIBLE_GLOUTONNE, cap_mb=60, limite_s=45)
    assert rc == "137", "job non tue (rc=%r) -- la RAM n'est plus bornee" % rc
    assert "TUE : RSS" in err, "kill sans motif dans le .err : illisible pour l'enquete"


def test_chemin_nominal_ecrit_toujours_son_code_de_sortie(monkeypatch):
    """Le garde ne doit pas priver un job sain de son rc (regression possible du
    drapeau _tue qui protege le 137)."""
    rc, _ = _essai(monkeypatch, CIBLE_SAINE, cap_mb=None, limite_s=25)
    assert rc == "0", "job sain sans rc exploitable (rc=%r)" % rc
