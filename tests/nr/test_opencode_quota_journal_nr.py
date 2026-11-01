"""NR : panne fournisseur OpenCode visible seulement dans son journal -> detection en secondes, pas 300 s.
Aucun vrai OpenCode ni reseau : faux journal dans tmp_path, faux client ACP."""
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import forge_opencode_journal as fj  # noqa: E402

RE_QUOTA = re.compile(r"rate limit exceeded|quota exceeded|\b429\b", re.I)


def _ligne(ts, msg='AI_APICallError: Free usage limit reached', sid="ses_abc", niveau="ERROR"):
    return (f'{niveau} {ts.strftime("%Y-%m-%dT%H:%M:%S")} +3ms service=llm providerID=opencode '
            f'modelID=big-pickle session.id={sid} message="stream error" error.error="{msg}"\n')


class FauxClient:
    def __init__(self):
        self.stop = threading.Event()
        self.appels = 0

    def prompt(self, sid, text, timeout=0):
        self.appels += 1
        if not self.stop.wait(30):
            raise TimeoutError("silence 300 s simule")
        return {"text": "ok", "stopReason": "end_turn"}


def _ajouter(log, texte):
    with log.open("a", encoding="utf-8") as f:
        f.write(texte)


def _lancer(client, log, **kw):
    kw.setdefault("intervalle_s", 0.05)
    return fj.prompt_avec_veilleur(client, "ses_abc", "go", timeout=60, chemin=log, quota_re=RE_QUOTA, **kw)


def test_panne_posterieure_interrompt_en_secondes(tmp_path):
    log = tmp_path / "opencode.log"
    log.write_text("INFO debut\n", encoding="utf-8")
    c = FauxClient()
    threading.Timer(0.3, lambda: _ajouter(log, _ligne(datetime.now()))).start()
    t0 = time.time()
    try:
        _lancer(c, log)
        assert False, "doit lever"
    except fj.QuotaJournalOpenCode as exc:
        assert "Free usage limit reached" in str(exc)
        assert RE_QUOTA.search(str(exc)), "le repli existant doit se declencher sur ce message"
    finally:
        c.stop.set()
    assert time.time() - t0 < 5


def test_erreur_anterieure_au_prompt_ignoree(tmp_path):
    log = tmp_path / "opencode.log"
    log.write_text(_ligne(datetime.now() - timedelta(minutes=10)), encoding="utf-8")
    c = FauxClient()
    threading.Timer(0.5, c.stop.set).start()
    assert _lancer(c, log)["text"] == "ok"


def test_autre_session_ignoree(tmp_path):
    log = tmp_path / "opencode.log"
    log.write_text("", encoding="utf-8")
    c = FauxClient()
    threading.Timer(0.2, lambda: _ajouter(log, _ligne(datetime.now(), sid="ses_autre"))).start()
    threading.Timer(0.8, c.stop.set).start()
    assert _lancer(c, log)["text"] == "ok"


def test_journal_absent_comportement_inchange(tmp_path):
    c = FauxClient()
    threading.Timer(0.3, c.stop.set).start()
    assert _lancer(c, tmp_path / "nexiste_pas.log")["text"] == "ok"


def test_exception_du_prompt_propagee(tmp_path):
    class Casse(FauxClient):
        def prompt(self, sid, text, timeout=0):
            raise TimeoutError("SilenceACP simule")
    log = tmp_path / "opencode.log"
    log.write_text("", encoding="utf-8")
    try:
        _lancer(Casse(), log)
        assert False
    except TimeoutError as exc:
        assert "SilenceACP" in str(exc)


def test_lecture_bornee_par_la_fin(tmp_path):
    log = tmp_path / "opencode.log"
    log.write_text("x" * 5_000_000 + "\nFIN\n", encoding="utf-8")
    lignes = fj.lire_fin(log, max_octets=4096)
    assert lignes[-1] == "FIN"
    assert sum(len(l) for l in lignes) <= 4096


def test_caviardage_secret():
    out = fj.caviarder('error sk-ABCDEF1234567890XYZ Bearer abcdef123456 api_key=zzz999')
    assert "sk-ABCDEF" not in out and "abcdef123456" not in out and "zzz999" not in out


def test_chemin_surchargeable_par_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LAFORGE_OPENCODE_LOG", str(tmp_path / "x.log"))
    assert fj.chemin_journal() == tmp_path / "x.log"


def test_executeur_branche_le_veilleur():
    src = (Path(__file__).resolve().parents[2] / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
    assert "prompt_avec_veilleur" in src
