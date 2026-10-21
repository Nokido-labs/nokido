"""NR -- une session ACP MUETTE est coupee tot ; une session qui donne des signes de vie ne l'est pas.

Mesure 19/10 : OPENCODE_GPTOSS (job_0f007541) et d'autres ont attendu 25 min (`OPENCODE_TIMEOUT_S` = 1500) une
reponse `session/prompt` qui ne venait pas -- « timeout en attente id=3 ». La pompe ne regardait que la reponse
finale : les notifications `session/update` (pensee, outil, texte) n'etaient pas comptees comme signes de vie, et le
silence n'etait pas distingue d'un long travail. Decision owner 19/10 (principe « flux inspecte, pas bufferise ») :
veille de silence, levee comme TimeoutError (le repli de modele existant reste declenche) et nommee « silence ».
"""
from __future__ import annotations

import re
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_acp_client as A  # noqa: E402


class _Proc:
    def poll(self):
        return None


def _client():
    c = A.ACPClient(cmd=["inexistant"], agent="opencode")
    c.proc = _Proc()
    return c


def test_une_session_muette_est_coupee_par_la_veille():
    c = _client()
    t0 = time.monotonic()
    with pytest.raises(A.SilenceACP) as e:
        c._pump_until(3, timeout=20, silence_max=0.5)
    assert time.monotonic() - t0 < 5
    assert isinstance(e.value, TimeoutError) and "silence" in str(e.value)


def test_les_signes_de_vie_repoussent_la_veille():
    c = _client()

    def agent():
        for _ in range(8):
            c._inbox.put({"jsonrpc": "2.0", "method": "session/update",
                          "params": {"update": {"sessionUpdate": "agent_thought_chunk"}}})
            time.sleep(0.2)
        c._inbox.put({"jsonrpc": "2.0", "id": 3, "result": {"stopReason": "end_turn"}})

    threading.Thread(target=agent, daemon=True).start()
    assert c._pump_until(3, timeout=20, silence_max=0.6)["id"] == 3


def test_sans_veille_le_comportement_reste_celui_d_avant():
    c = _client()
    with pytest.raises(TimeoutError) as e:
        c._pump_until(3, timeout=0.5)
    assert not isinstance(e.value, A.SilenceACP)


def test_l_executeur_arme_la_veille_sur_opencode():
    src = (ROOT / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
    assert re.search(r"client\.silence_max\s*=\s*OPENCODE_SILENCE_S", src)


def test_la_veille_ne_vaut_que_pour_les_prompts():
    """initialize / session/new gardent leur borne seule ; seul session/prompt est veille."""
    c = _client()
    c.silence_max = 0.4
    vus = []
    c._send = lambda obj: None
    c._pump_until = lambda rid, timeout, silence_max=None: vus.append(silence_max) or {"id": rid, "result": {}}
    c.request("session/new", {})
    c.request("session/prompt", {})
    assert vus == [None, 0.4]
