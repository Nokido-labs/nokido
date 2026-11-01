"""NR -- revue d'integration du veilleur OpenCode (CLAUDE 28/10) : le FORMAT REEL du journal.

Le vrai ~/.local/share/opencode/log/opencode.log ecrit (28/10 13:40:39, UTC) :
  timestamp=2026-10-28T13:40:39.798Z level=ERROR run=d24274b4 message="stream error" providerID=opencode
  modelID=big-pickle session.id=ses_... error.error="AI_APICallError: Free usage limit reached. ..."
Les NR de la livraison fabriquaient « ERROR <heure LOCALE> » : en reel, l'heure UTC (Z) comparee a un debut de
prompt en heure LOCALE (UTC+1) passait pour ANTERIEURE -> la panne n'etait jamais vue. Le veilleur doit lire Z
comme UTC, et une erreur vieille de 10 min reste ignoree.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_opencode_journal as fj  # noqa: E402


def _reelle(ts_utc: datetime, sid="ses_e7d423da3ffeDkIyiupcv0ABij"):
    horo = ts_utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts_utc.microsecond // 1000:03d}Z"
    return (f'timestamp={horo} level=ERROR run=d24274b4 message="stream error" providerID=opencode '
            f'modelID=big-pickle session.id={sid} small=false agent=build mode=primary '
            f'error.error="AI_APICallError: Free usage limit reached. Free models work in OpenCode"\n')


def test_erreur_utc_posterieure_au_prompt_est_vue(tmp_path):
    log = tmp_path / "opencode.log"
    debut = datetime.now(timezone.utc)
    log.write_text(_reelle(debut + timedelta(seconds=4)), encoding="utf-8")
    ligne = fj.chercher_panne(log, debut, "ses_e7d423da3ffeDkIyiupcv0ABij", None)
    assert ligne and "Free usage limit reached" in ligne


def test_erreur_utc_anterieure_au_prompt_ignoree(tmp_path):
    log = tmp_path / "opencode.log"
    debut = datetime.now(timezone.utc)
    log.write_text(_reelle(debut - timedelta(minutes=10)), encoding="utf-8")
    assert fj.chercher_panne(log, debut, "ses_e7d423da3ffeDkIyiupcv0ABij", None) is None


def test_debut_local_naif_compare_juste_a_une_heure_utc(tmp_path):
    """L'appelant reel passe datetime.now() (local, naif) : la comparaison doit rester juste."""
    log = tmp_path / "opencode.log"
    debut_local = datetime.now()
    log.write_text(_reelle(datetime.now(timezone.utc) + timedelta(seconds=4)), encoding="utf-8")
    assert fj.chercher_panne(log, debut_local, "ses_e7d423da3ffeDkIyiupcv0ABij", None)
