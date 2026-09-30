# -*- coding: utf-8 -*-
"""NR — un gate qui n'a pas pu mesurer ne rend pas VERT.

__FORGE_COLOR__ = "qualite/build : non-regression du contrat de verdict des gates"

CONTRAT, trois etats et jamais deux :

    MESURE + sain       -> PASS
    MESURE + probleme   -> WARN (gate warn) / FAIL (gate bloquant)
    PAS MESURE          -> UNKNOWN, inscrit dans `_INCONCLUS`, JAMAIS un succes

CE QUI A ETE PAYE (2026-09-07). `pip-audit` affichait ✅ au resume en **1,3 s** sans
avoir audite un seul paquet : le compte de la CI n'a pas d'egress, `pypi.org` rendait
`WinError 10013`, et le gate etant `warn` son rc non nul passait pour un avertissement
ordinaire. Un domaine declare CRITIQUE (`_DOMAINES_CRITIQUES`) n'avait donc AUCUN
verdict, et l'affichait vert.

🔑 **Le rc ne peut pas discriminer** : `pip-audit` rend `1` pour « CVE trouvee » ET pour
« index injoignable ». Le signal est dans la SORTIE — d'ou `motifs_non_mesure`, qui
etend `rc_non_mesure` (ecrit le 2026-08-19 pour le meme motif sur `archi_lint`) au lieu
d'ouvrir un second mecanisme.

⚠️ Meme signature que la panne du 2026-09-06 (cache absent, 1,4 s) : **une duree
absurde est le temoin qui trahit un gate qui ne mesure rien**.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import ci_local as ci  # noqa: E402

SRC = ROOT / "tools" / "ci_local.py"


class _Faux:
    """Popen minimal : rend les lignes voulues puis le rc voulu."""

    def __init__(self, lignes, rc):
        self.stdout = iter(lignes)
        self._rc = rc

    def wait(self):
        return self._rc


def _jouer(monkeypatch, lignes, rc, **kw):
    monkeypatch.setattr(ci, "_INCONCLUS", [])
    monkeypatch.setattr(ci, "_CHRONO", [])
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _Faux(lignes, rc))
    nom, ok = ci._run("pip-audit", ["x"], blocking=False, **kw)
    return ok, list(ci._INCONCLUS)


MOTIFS = ("NewConnectionError", "Max retries exceeded",
          "Failed to establish a new connection",
          "requests.exceptions.ConnectionError",
          "Failed to read from cache directory")


def test_reseau_injoignable_rend_UNKNOWN_pas_un_vert(monkeypatch) -> None:
    """La sortie REELLE mesuree le 2026-09-07, telle quelle."""
    lignes = [
        "urllib3.exceptions.NewConnectionError: HTTPSConnection(host='pypi.org', "
        "port=443): Failed to establish a new connection: [WinError 10013]\n",
    ]
    ok, inconclus = _jouer(monkeypatch, lignes, 1, motifs_non_mesure=MOTIFS)
    assert inconclus, "le gate doit etre inscrit comme NON MESURE"
    assert inconclus[0][0] == "pip-audit"
    assert inconclus[0][1] is True, (
        "pip-audit est un domaine CRITIQUE sans suppleant : son absence de mesure "
        "doit etre bloquante, pas decorative")


def test_une_CVE_TROUVEE_n_est_PAS_un_non_mesure(monkeypatch) -> None:
    """Le meme rc=1. Confondre les deux ferait taire une vraie vulnerabilite."""
    lignes = ["Found 4 known vulnerabilities in 4 packages\n"]
    ok, inconclus = _jouer(monkeypatch, lignes, 1, motifs_non_mesure=MOTIFS)
    assert not inconclus, "un audit qui a MESURE et trouve doit rester un verdict"
    assert ok is True, "gate warn : il ne bloque pas, mais il a conclu"


def test_un_audit_sain_reste_un_PASS(monkeypatch) -> None:
    lignes = ["No known vulnerabilities found\n"]
    ok, inconclus = _jouer(monkeypatch, lignes, 0, motifs_non_mesure=MOTIFS)
    assert not inconclus and ok is True


def test_sans_motifs_declares_le_comportement_est_INCHANGE(monkeypatch) -> None:
    """Le mecanisme est opt-in : aucun gate existant ne change de verdict."""
    lignes = ["NewConnectionError: pypi.org\n"]
    ok, inconclus = _jouer(monkeypatch, lignes, 1)
    assert not inconclus, "sans `motifs_non_mesure`, rien ne bouge"


def test_le_cache_illisible_est_AUSSI_un_non_mesure(monkeypatch) -> None:
    """Panne du 2026-09-06, meme famille : sans cache, pip-audit meurt avant le
    premier paquet. Elle doit rester attrapee par le meme filet."""
    lignes = ["WARNING:pip_audit._cache:Failed to read from cache directory\n"]
    _ok, inconclus = _jouer(monkeypatch, lignes, 1, motifs_non_mesure=MOTIFS)
    assert inconclus, "le cache absent avait deja rendu ce gate aveugle une fois"


def test_le_site_d_appel_de_pip_audit_declare_ses_motifs() -> None:
    """Le mecanisme ne sert a rien s'il n'est pas CABLE — c'est le defaut qu'on
    passe la semaine a corriger ailleurs."""
    src = SRC.read_text(encoding="utf-8", errors="replace")
    i = src.find('_run("pip-audit"')
    assert i > 0, "site d'appel introuvable"
    bloc = src[i:i + 900]
    assert "motifs_non_mesure=" in bloc, "pip-audit doit declarer ses motifs"
    for m in ("NewConnectionError", "Failed to read from cache directory"):
        assert m in bloc, "motif %r absent du site d'appel" % m


# --- la mesure DEPORTEE : le gate juge ce qu'un autre compte a mesure -------------

def test_aucun_rapport_deporte_reste_un_NON_MESURE(monkeypatch, tmp_path) -> None:
    """Absence de rapport ≠ dependances saines."""
    monkeypatch.setattr(ci, "rapport_courant", lambda: None, raising=False)
    import forge_deps_reconcilier as dr
    monkeypatch.setattr(dr, "rapport_courant", lambda: None)
    frais, detail = ci._mesure_pip_audit_deportee()
    assert frais is False
    assert "aucun rapport" in detail and "run_job online=true" in detail, (
        "le motif doit dire QUOI FAIRE, et en entier : %r" % detail)


def test_un_rapport_PERIME_n_est_pas_un_suppleant(monkeypatch, tmp_path) -> None:
    """« perime, pas absent » — les avis OSV bougent chaque jour."""
    import forge_deps_reconcilier as dr
    import os as _os
    f = tmp_path / "pip_audit_vieux.json"
    f.write_text("{}", encoding="utf-8")
    vieux = time.time() - (ci._AUDIT_FRAICHEUR_J + 3) * 86400
    _os.utime(f, (vieux, vieux))
    monkeypatch.setattr(dr, "rapport_courant", lambda: f)
    frais, detail = ci._mesure_pip_audit_deportee()
    assert frais is False
    assert "perime, pas absent" in detail and "vieux de" in detail, (
        "l'age doit etre DIT, pas seulement le verdict : %r" % detail)


def test_un_rapport_FRAIS_est_un_suppleant_NOMME_et_DATE(monkeypatch, tmp_path) -> None:
    """La date du rapport est RELATIVE a aujourd'hui, jamais absolue.

    Elle etait ecrite en dur (`pip_audit_2026-09-07.json`) contre un seuil de
    sept jours : le test passait, puis a commence a echouer le 14/09 sans qu'une
    seule ligne de code ait bouge. Il ne verifiait plus qu'un rapport recent est
    accepte -- il verifiait que nous etions avant une certaine date.

    Un test qui depend de l'horloge sans la figer ne tombe pas quand le code
    casse : il tombe quand le temps passe, et il fait chercher une regression la
    ou il n'y en a aucune.
    """
    import forge_deps_reconcilier as dr
    from datetime import date, timedelta

    recent = date.today() - timedelta(days=2)
    f = tmp_path / ("pip_audit_%s.json" % recent.isoformat())
    f.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(dr, "rapport_courant", lambda: f)
    frais, detail = ci._mesure_pip_audit_deportee()
    assert frais is True
    assert f.name in detail and "j (<" in detail, (
        "un suppleant se NOMME avec sa date : %r" % detail)


def test_le_producteur_n_ecrit_RIEN_quand_il_n_a_pas_mesure() -> None:
    """🔑 La regle qui empeche de fabriquer un faux calme date.

    Un rapport frais et vide se relirait comme « aucune vulnerabilite ». Le producteur
    ecrit sous `.partiel` et ne publie le nom attendu qu'apres verification."""
    src = (ROOT / "tools" / "forge_pip_audit_mesure.py").read_text(
        encoding="utf-8", errors="replace")
    assert ".partiel" in src, "le rapport n'est publie qu'apres verification"
    assert "provisoire.replace(cible)" in src, "publication atomique du nom attendu"
    assert "0 paquet audite" in src, (
        "zero paquet n'est pas un depot sain, c'est un instrument aveugle")
    assert src.count("unlink(missing_ok=True)") >= 3, (
        "chaque chemin de non-mesure doit RETIRER le fichier partiel")


# ---------------------------------------------------------------------------
# LE MEME CONTRAT, MAIS DANS LE WORKFLOW (mesure 2026-09-16)
#
# Ce fichier protege « PAS MESURE -> jamais un succes » DANS ci_local. Le
# workflow GitHub, lui, ne le respectait pas : le step << Contrat d'acceptation
# UI >> est conditionne par un filtre de chemins, et quand le filtre ne voit
# rien le step sort `skipped` -- donc le job `ui-acceptance` sort `success`.
#
# MESURE, run 35132625459 sur le sha 14004af91 : job `ui-acceptance: success`,
# et le detail des steps dit `4. Contrat d'acceptation UI: skipped`. Le gate
# n'avait RIEN mesure ; j'ai failli lire ce vert comme la validation du coffre.
#
# Le filtre est LEGITIME (la campagne coute ~929 s, sept runs avaient ete tues
# a 15 min pour cette raison). Ce qui ne l'est pas, c'est qu'un domaine
# declare CRITIQUE sorte vert SANS LE DIRE. On ne fait donc pas echouer le
# job -- on exige qu'il NOMME son absence de mesure, dans l'annotation et dans
# le resume du run.
# ---------------------------------------------------------------------------

WORKFLOW = ROOT / ".github" / "workflows" / "ci-selfhosted.yml"


def test_un_gate_UI_saute_par_le_filtre_NOMME_son_absence_de_mesure() -> None:
    yml = WORKFLOW.read_text(encoding="utf-8")
    assert "NON MESURE" in yml, (
        "le workflow ne nomme nulle part l'absence de mesure du gate UI : un "
        "job vert par saut se lit comme un job vert par succes"
    )
    assert "GITHUB_STEP_SUMMARY" in yml, (
        "l'avertissement doit atterrir dans le RESUME du run : une annotation "
        "seule se perd dans les journaux, et c'est le resume qu'on lit"
    )


def test_le_filtre_de_chemins_reste_en_place() -> None:
    """On ne supprime pas le filtre : il evite 929 s de campagne inutile. Le
    defaut n'etait pas de sauter, c'etait de sauter EN SILENCE."""
    yml = WORKFLOW.read_text(encoding="utf-8")
    assert "steps.filter.outputs.run" in yml


def test_pip_audit_reste_un_domaine_CRITIQUE_sans_suppleant() -> None:
    """Mesure 2026-09-07 : `ci-selfhosted.yml` INSTALLE pip-audit (`pip install`)
    et ne le LANCE jamais. Il n'existe donc AUCUN suppleant, et en declarer un
    serait un garde branche sur un emetteur inexistant."""
    assert "pip-audit" in ci._DOMAINES_CRITIQUES
    assert "pip-audit" not in ci._SUPPLEANTS, (
        "ne declarer un suppleant que s'il MESURE reellement")
