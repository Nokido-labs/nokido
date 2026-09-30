"""NR -- TaskExecutor relit son jeton A CHAQUE APPEL (2026-09-28), prealable a l'injection.

Mesure du jour : `run_loop` lisait son jeton UNE fois (`token = _load_token()`, l.1150) et le
passait a tous les appels ; un jeton court (30 min) injecte par le lanceur y aurait expire.
Tous les appels au hub passent par `_hub_call` : c'est la qu'on relit.

Et le lanceur ne connaissait, en mode `interactive`, qu'une ETIQUETTE (`interactive-sid...`)
et non un compte : l'ACL du jeton projete aurait echoue. Il lit desormais le SID du compte
dans le jeton du processus lance.

Contrats :
  1. `_hub_call` presente le jeton COURANT de TASK_EXECUTOR (`jeton_pour`), relu a chaque
     appel ; sans lui, le jeton passe en argument (repli d'avant) ;
  2. `_load_token` demande d'abord la brique `jeton_pour` ;
  3. le lanceur accorde la lecture au SID reel du compte (`*S-1-...`) ; une etiquette seule
     ne donne AUCUN compte -- pas de projection plutot qu'une ACL fausse.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _charger(rel: str, nom: str):
    spec = importlib.util.spec_from_file_location(nom, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Rep:
    def read(self):
        return json.dumps({"result": {}}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_hub_call_presente_le_jeton_courant_a_chaque_appel(monkeypatch):
    te = _charger("tools/forge_task_executor.py", "nr_task_executor_jeton")
    cred = importlib.import_module("nokido_agent.app.forge_agent_credential")
    jetons = iter(["jeton-courant-1", "jeton-courant-2", ""])
    monkeypatch.setattr(cred, "jeton_pour", lambda agent: next(jetons))
    vus: list = []
    monkeypatch.setattr(te.urllib.request, "urlopen",
                        lambda req, timeout=0: vus.append(req.get_header("Authorization")) or _Rep())
    for _ in range(3):
        te._hub_call("ping", {}, "jeton-du-demarrage", timeout=5)
    assert vus == ["Bearer jeton-courant-1", "Bearer jeton-courant-2", "Bearer jeton-du-demarrage"]


def test_load_token_demande_d_abord_la_brique(monkeypatch):
    te = _charger("tools/forge_task_executor.py", "nr_task_executor_load")
    cred = importlib.import_module("nokido_agent.app.forge_agent_credential")
    demandes: list = []
    monkeypatch.setattr(cred, "jeton_pour", lambda agent: demandes.append(agent) or "jeton-de-la-brique")
    ok = (te._load_token() == "jeton-de-la-brique", demandes)
    assert ok == (True, ["TASK_EXECUTOR"])


def test_le_lanceur_accorde_la_lecture_au_sid_reel_du_compte(monkeypatch):
    m = _charger("tools/forge_runas_launcher.py", "nr_runas_compte")
    monkeypatch.setattr(m, "_sid_du_processus", lambda proc: "S-1-5-21-1-2-3-1001")
    avec_sid = m._compte_du_service(object(), {"sandbox_user": "interactive-sid1"})
    monkeypatch.setattr(m, "_sid_du_processus", lambda proc: "")
    etiquette = m._compte_du_service(object(), {"sandbox_user": "interactive-sid1"})
    nom = m._compte_du_service(object(), {"sandbox_user": "LaForgeSbxOnline"})
    assert (avec_sid, etiquette, nom) == ("*S-1-5-21-1-2-3-1001", None, "LaForgeSbxOnline")
