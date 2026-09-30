"""NR — E1 : les gardes du corps sont exerces des DEUX cotes.

Chantier E1 de `docs/roadmap_ameliorations_veille.md`, tire de la veille
(`litellm`, tests de circuit breaker). Le patron vit dans `_patron_garde.py`.

POURQUOI CE NR EXISTE. Le depot porte deux preuves datees qu'un garde peut etre
present, correct a la relecture, et n'avoir JAMAIS agi : le frein
`INSULIN_VECTORIZATION > 0.4` n'a jamais tire faute d'emetteur, et le garde
d'intention du reclaimer a laisse recharger 312,94 Go en 7,6 jours parce qu'un
seul reveilleur sur six posait le drapeau. Un test qui verifie qu'un garde
« repond » ne distingue pas ces cas d'un garde vivant.

Le patron exige DEUX assertions symetriques -- il MORD sur ce qui doit etre
refuse, il LAISSE PASSER ce qui doit passer. La premiere seule ne prouve rien
d'un garde qui refuse tout ; la seconde seule ne prouve rien d'un garde inerte.

Ce fichier applique le patron a trois gardes REELS, sans demarrer aucun service.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : glob tests/nr + lecture
#   (l.159)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
for _chemin in (RACINE, RACINE / "app", RACINE / "tools", Path(__file__).parent):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

from _patron_garde import (  # noqa: E402
    GardeInerte,
    GardeParanoiaque,
    prouver_que_le_garde_mord,
)


# ── le patron lui-meme doit mordre ───────────────────────────────────────────
# Un patron qui ne detecte pas un garde inerte serait exactement le defaut qu'il
# pretend combattre. On l'exerce donc sur deux gardes FICTIFS degeneres.

def test_le_patron_detecte_un_garde_inerte():
    with pytest.raises(GardeInerte):
        prouver_que_le_garde_mord(
            nom="fictif tout-permissif",
            exercer=lambda _e: {"ok": True},
            entree_refusee="dangereux",
            entree_admise="benin",
            est_un_refus=lambda v: v.get("ok") is False,
        )


def test_le_patron_detecte_un_garde_paranoiaque():
    with pytest.raises(GardeParanoiaque):
        prouver_que_le_garde_mord(
            nom="fictif tout-refusant",
            exercer=lambda _e: {"ok": False},
            entree_refusee="dangereux",
            entree_admise="benin",
            est_un_refus=lambda v: v.get("ok") is False,
        )


# ── garde 1 : l'admission de ressources ──────────────────────────────────────

def test_le_garde_d_admission_mord(monkeypatch):
    """Refuse une machine saturee, admet une machine saine."""
    m = pytest.importorskip("app.forge_lane_admission")

    def exercer(sante):
        monkeypatch.setattr(m, "_get_system_health", lambda: sante)
        return m.check_ressources(heavy=True)

    prouver_que_le_garde_mord(
        nom="admission de ressources",
        exercer=exercer,
        entree_refusee={"cpu_pct": 99.0, "ram_pct": 40.0, "ram_dispo_gb": 12.0,
                        "degraded": False, "source": "psutil"},
        entree_admise={"cpu_pct": 13.0, "ram_pct": 60.0, "ram_dispo_gb": 9.0,
                       "degraded": False, "source": "inspecteur"},
        est_un_refus=lambda v: v.get("ok") is False,
    )


# ── garde 2 : le validateur de messages inter-agents ─────────────────────────

def test_le_validateur_m2m_mord():
    """Refuse un message sans intent, accepte un message conforme."""
    m = pytest.importorskip("app.forge_m2m_protocol")

    def exercer(charge):
        return m.validate("notify", charge)

    def est_un_refus(verdict) -> bool:
        # `validate` rend un dict de diagnostic ; un code hors des codes OK = refus.
        code = (verdict or {}).get("code", "")
        return code not in ("M2M_OK", "M2M_OK_PROSE")

    prouver_que_le_garde_mord(
        nom="validateur M2M",
        exercer=exercer,
        entree_refusee={"texte": "coucou, peux-tu regarder le fichier stp"},
        entree_admise={"intent": "COLLAB_PING", "pointer_ref": "bb:zone/clef"},
        est_un_refus=est_un_refus,
    )


# ── garde 3 : le dry-run de la purge des temporaires ─────────────────────────

def test_le_dry_run_de_la_purge_mord(monkeypatch, tmp_path):
    """Le dry-run protege : il ne supprime RIEN, l'application supprime.

    Ce test n'est possible que parce que le chemin tmp a un POINT UNIQUE
    honorant `LAFORGE_SANDBOX_TMP` (livre le 2026-09-08) : sans lui, il aurait
    fallu ecrire dans la vraie zone du depot pour exercer le garde.
    """
    retention = pytest.importorskip("forge_log_retention")
    monkeypatch.setenv("LAFORGE_SANDBOX_TMP", str(tmp_path))

    vieux = tmp_path / "vieux.tmp"
    recent = tmp_path / "recent.tmp"

    def semer():
        vieux.write_text("x", encoding="utf-8")
        recent.write_text("y", encoding="utf-8")
        tres_ancien = time.time() - 40 * 86400
        import os as _os
        _os.utime(vieux, (tres_ancien, tres_ancien))

    def exercer(dry: bool):
        semer()
        retention._purge_workspace_tmp(dry=dry)
        return {"vieux_encore_la": vieux.exists(), "recent_encore_la": recent.exists()}

    # MORDANT : en mode applique, le vieux disparait.
    applique = exercer(False)
    assert applique["vieux_encore_la"] is False, (
        "la purge n'a pas supprime un fichier de 40 jours : garde INERTE"
    )
    # PORTEE : elle epargne le recent, dans les deux modes.
    assert applique["recent_encore_la"] is True, (
        "la purge a supprime un fichier RECENT : garde PARANOIAQUE"
    )
    # Et le dry-run ne touche a rien.
    sec = exercer(True)
    assert sec["vieux_encore_la"] is True and sec["recent_encore_la"] is True, (
        "le dry-run a supprime des fichiers : il ne protege plus rien"
    )


# ── le patron doit etre UTILISE, sinon c'est une dette de cablage ────────────

def test_le_patron_a_des_appelants():
    """Un patron ecrit et jamais employe serait le defaut qu'il combat."""
    dossier = Path(__file__).parent
    appelants = [
        p.name for p in dossier.glob("test_*_nr.py")
        if "prouver_que_le_garde_mord" in p.read_text(encoding="utf-8", errors="replace")
    ]
    assert appelants, (
        "le patron E1 n'est appele par aucun NR : un mecanisme present mais non "
        "cable est une dette, jamais une securite"
    )
