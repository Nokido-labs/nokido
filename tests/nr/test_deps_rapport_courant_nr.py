# -*- coding: utf-8 -*-
"""NR — le réconciliateur de dépendances lit le rapport le PLUS RÉCENT, et le DIT.

__FORGE_COLOR__ = "qualite/gate : non-regression du choix de source des mesures"

CE QUI A ÉTÉ PAYÉ (2026-09-07). `forge_deps_reconcilier` lisait `sandbox/pip_audit.json`,
un nom codé en dur — l'état d'AVANT la campagne de montée — alors que
`sandbox/pip_audit_apres.json` était juste à côté. Il a donc annoncé **135 CVE quand il en
restait 45**, et proposé de monter des paquets DÉJÀ montés (`starlette 1.0.0` alors qu'il
était en 1.3.1). Ce plan a été remis à l'owner, qui allait agir dessus.

**Un instrument qui choisit sa source par un nom figé finit toujours par décrire un passé.**
Et un plan périmé ne se distingue pas d'un plan juste : il a la même forme, les mêmes
colonnes, la même assurance. D'où la seconde exigence, testée ici aussi : la source retenue
doit être IMPRIMÉE avec sa date, sans quoi la mesure n'est pas vérifiable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

SRC = ROOT / "tools" / "forge_deps_reconcilier.py"


def _module():
    import forge_deps_reconcilier as m  # noqa: PLC0415

    return m


def test_le_rapport_le_plus_recent_gagne(tmp_path, monkeypatch):
    m = _module()
    sb = tmp_path / "sandbox"
    sb.mkdir()
    vieux = sb / "pip_audit.json"
    neuf = sb / "pip_audit_apres.json"
    vieux.write_text("[]", encoding="utf-8")
    neuf.write_text("[]", encoding="utf-8")
    os.utime(vieux, (1_000_000, 1_000_000))
    os.utime(neuf, (2_000_000, 2_000_000))
    monkeypatch.setattr(m, "ROOT", tmp_path)
    assert m.rapport_courant().name == "pip_audit_apres.json"


def test_le_nom_fige_ne_gagne_pas_parce_qu_il_est_le_defaut(tmp_path, monkeypatch):
    """Le piège exact : le rapport historique porte le nom par défaut. S'il est le plus
    ANCIEN, il ne doit PAS être choisi."""
    m = _module()
    sb = tmp_path / "sandbox"
    sb.mkdir()
    defaut = sb / "pip_audit.json"
    autre = sb / "pip_audit_2026.json"
    defaut.write_text("[]", encoding="utf-8")
    autre.write_text("[]", encoding="utf-8")
    os.utime(defaut, (1_000_000, 1_000_000))
    os.utime(autre, (3_000_000, 3_000_000))
    monkeypatch.setattr(m, "ROOT", tmp_path)
    assert m.rapport_courant().name == "pip_audit_2026.json"


def test_aucun_rapport_rend_None_et_non_un_chemin_inexistant(tmp_path, monkeypatch):
    """Rien à lire se DIT. Rendre un chemin qui n'existe pas ferait échouer plus loin,
    avec un message sans rapport avec la cause."""
    m = _module()
    (tmp_path / "sandbox").mkdir()
    monkeypatch.setattr(m, "ROOT", tmp_path)
    assert m.rapport_courant() is None


def test_la_source_retenue_est_imprimee_avec_sa_date():
    """Une mesure sans sa source ne se vérifie pas."""
    src = SRC.read_text(encoding="utf-8", errors="replace")
    assert "[deps] source" in src, "le chemin du rapport doit etre affiche"
    assert "st_mtime" in src, "la date du rapport doit etre affichee"


def test_la_portee_de_la_nature_du_paquet_reste_ecrite():
    """`a_des_binaires` décrit la version INSTALLÉE, pas la cible : `litellm` 1.83 est pur
    Python, 1.93 est mixte Python/Rust. Retirer cet avertissement, c'est re-promettre une
    montée « à chaud » qui exigera une toolchain."""
    src = SRC.read_text(encoding="utf-8", errors="replace")
    assert "INSTALLEE, pas la" in src or "INSTALLEE, pas la CIBLE" in src, (
        "la portee de a_des_binaires doit rester documentee")
    assert "sdist" in src, "le cas « pas de wheel pour l'ABI » doit rester nomme"
