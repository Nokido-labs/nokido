"""NR — le journal d'audit opsec se borne par VOLUME, et la table d'etat ne se purge JAMAIS.

Signale par le garde anti-firehose au commit `cffd0fb05` : `opsec_state` et
`opsec_audit_log` n'etaient referencees dans aucune purge. Les deux tables ont
ete nommees ensemble, mais elles ne se traitent PAS pareil -- et se tromper de
traitement coute bien plus cher que l'absence de purge.

1. **`opsec_state` ne doit JAMAIS etre purgee.** Trois lignes cle/valeur qui
   portent le kill-switch humain. Ce n'est pas un journal : la purger
   n'effacerait pas des logs, elle effacerait l'AUTORITE. Meme famille que
   `vault_entries` / `vault_meta`, deja exemptees ici avec la note « un garde
   qui compte les tables sans distinguer JOURNAL et DONNEE pousse a effacer le
   coffre ».

2. **`opsec_audit_log` se borne par VOLUME, pas par anciennete.** Mesure du
   2026-09-13 : 21 lignes couvrant plusieurs mois. A `COLD_DAYS=30`, une purge
   par age en effacerait 21 sur 21 -- tout l'historique du kill-switch, pour
   gagner quelques kilo-octets. Le risque que nomme le garde est la CROISSANCE.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 sur la VRAIE base (code
#   appele) (l.38)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_log_retention as flr  # noqa: E402


def test_opsec_state_est_exemptee():
    """Purger la table d'etat effacerait le kill-switch, pas un journal."""
    out = flr._purge_journaux_securite(dry=True)
    assert "opsec_state" in out.get("exemptees", []), (
        "opsec_state n'est pas declaree exemptee : une purge future l'effacerait "
        "en croyant nettoyer un journal"
    )
    assert "opsec_state" not in [k for k in out if k != "exemptees"], (
        "opsec_state apparait comme cible de purge"
    )


def test_le_journal_opsec_se_borne_par_volume_pas_par_age():
    """A COLD_DAYS=30, une purge par age effacerait 21 lignes sur 21."""
    src = Path(flr.__file__).read_text(encoding="utf-8", errors="replace")
    assert "OPSEC_AUDIT_MAX_LIGNES" in src
    bloc = src.split("Journaux d'AUTORITE")[-1][:2500]
    assert "ORDER BY id DESC LIMIT" in bloc, "le bornage n'est pas par volume"

    # Ne lire QUE le code : le commentaire du bloc cite `COLD_DAYS` pour
    # expliquer pourquoi on ne s'en sert PAS ici. Premiere version de ce test
    # rouge sur sa propre prose -- « un instrument ne lit jamais son propre
    # vocabulaire », paye plusieurs fois dans le corps.
    code = "\n".join(l for l in bloc.splitlines() if not l.lstrip().startswith("#"))
    assert "COLD_DAYS" not in code, (
        "le journal opsec est borne par anciennete : a 30 jours il perdrait tout "
        "son historique, qui est precisement ce qu'un audit doit garder"
    )


def test_le_plafond_ne_mord_pas_sur_le_regime_observe():
    """Un plafond pose SOUS le volume courant effacerait a chaque passage."""
    out = flr._purge_journaux_securite(dry=True)
    vu = out.get("opsec_audit_log")
    if not isinstance(vu, dict):
        pytest.skip("journal illisible sur ce poste (%r) — non observable ici" % (vu,))
    assert vu["supprimees"] == 0, (
        "le plafond mord deja sur le volume courant : il est trop bas, ou le "
        "journal s'est emballe — les deux se regardent avant d'effacer"
    )
    assert vu["plafond"] > vu["lignes"]
    assert vu["mode"] == "volume (pas anciennete)"


def test_un_journal_illisible_se_dit_au_lieu_de_passer_pour_vide():
    """« je n'ai pas pu ouvrir » ne doit jamais se lire « rien a purger »."""
    out = flr._purge_journaux_securite(dry=True)
    for cle, val in out.items():
        if cle == "exemptees" or cle == "dry_run":
            continue
        if isinstance(val, str):
            assert ("non purgeable" in val or "absente" in val or "irresolue" in val), (
                f"{cle} rend une chaine qui ne dit pas pourquoi : {val!r}"
            )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
