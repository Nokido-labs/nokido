"""NR -- la garde anti-sawtooth de _ensure_docker ne juge plus sur un battement ANTERIEUR a la demande (10/11 soir).

Mesure : 17:35:10 un reveil pose docker.wanted ; 17:35:14 `forge_ensure_service._ensure_docker` lit le battement du
keeper (jusqu'a 30 s de retard) qui dit encore `monitor_only` -- l'etat NOMINAL d'avant la demande -- conclut que
le keeper « ignore le flag », EFFACE docker.wanted sans trace et refuse ; le keeper ne voit plus de demande, reste
idle : SearXNG non releve, reveil rate a 40 s. STALE != preuve. Contrats :
  1. battement ANTERIEUR (ou egal) au drapeau frais -> pas de conclusion : la demande reste, on attend le daemon ;
  2. battement POSTERIEUR au drapeau et toujours monitor_only/daemon down -> refus (contrat anterieur), et
     l'effacement est JOURNALISE (forge_docker_audit) ;
"""
# pylint: disable=import-error,wrong-import-position,protected-access
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_ensure_service as ES  # noqa: E402
from nokido_agent.tools import forge_searxng_keeper as SK  # noqa: E402


def _monter(monkeypatch, tmp_path, decalage_battement_s):
    """Drapeau frais pose a t ; battement du keeper a t + decalage (negatif = anterieur)."""
    sb = tmp_path / "sandbox"
    sb.mkdir()
    flag = sb / "docker.wanted"
    flag.write_text(str(time.time()), encoding="utf-8")
    t_flag = time.time() - 5
    os.utime(flag, (t_flag, t_flag))
    (sb / "docker_keeper.heartbeat").write_text(json.dumps(
        {"ts": t_flag + decalage_battement_s, "stats": {"monitor_only": True, "daemon_up": False}}), encoding="utf-8")
    audits = []
    monkeypatch.setattr(ES, "ROOT", tmp_path)
    monkeypatch.setattr(ES.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(SK, "_docker_daemon_up", lambda: True)
    monkeypatch.setattr(ES, "_audit_effacement_demande", lambda motif: audits.append(motif))
    return flag, audits


def test_battement_anterieur_ne_juge_pas(monkeypatch, tmp_path):
    """Battement plus vieux que la demande : on la garde et on attend le daemon."""
    flag, audits = _monter(monkeypatch, tmp_path, -20)
    assert ES._ensure_docker(timeout_s=8) is True
    assert flag.exists() and audits == []


def test_battement_posterieur_refuse_et_journalise(monkeypatch, tmp_path):
    """Le keeper a vu la demande et reste monitor_only : refus, effacement journalise."""
    flag, audits = _monter(monkeypatch, tmp_path, +3)
    assert ES._ensure_docker(timeout_s=8) is False
    assert not flag.exists() and len(audits) == 1
