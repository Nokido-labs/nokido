"""NR — un mode d'exécution INCONNU ne doit jamais valoir FullLanguage.

Mesure du 2026-09-12, `app/forge_ps_sandbox.PowerShellSandbox.run` :

    if   self.mode == "JEA" and self.jea_config : wrapper JEA
    elif self.mode in ("CLM", "JEA")            : wrapper CLM
    else                                        : -ExecutionPolicy Bypass -File
                                                  (AUCUNE reduction de langage)

Et le mode vient des ARGUMENTS pour deux points d'entrée (`handle_ps_run`
L7635, `handle_ps_agent` L7662) : `mode = args.get("mode", "CLM")`. Le défaut
est sûr, mais une valeur **fournie et non reconnue** tombe dans la branche
`else` — donc la voie la MOINS restreinte.

C'est le motif `UNKNOWN → ALLOW` appliqué au niveau de restriction du langage :
une valeur qu'on ne comprend pas donne plus de pouvoir qu'une valeur valide.
Même famille que le `sandbox=<inconnu>` fermé le 2026-09-01, où une entrée
invalide obtenait davantage de privilèges qu'une entrée valide.

ÉTAT ATTENDU : rouge tant que `modes_autorises` / `mode_valide` n'existent pas
et que `run()` n'oppose pas un refus explicite.

⚠️ Ce NR ne lance AUCUN PowerShell : le refus doit intervenir AVANT la création
du fichier temporaire, donc il est observable sans exécuter quoi que ce soit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app"), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Import DIRECT, sans importorskip : ce module DOIT exister. Un skip ici
# produirait un vert sans rien vérifier.
import forge_ps_sandbox as PS  # noqa: E402


def test_la_liste_des_modes_autorises_est_declaree():
    """ROUGE ATTENDU d'abord. Sans liste explicite, « inconnu » n'a pas de sens :
    tout ce qui n'est pas reconnu tombe dans la branche permissive."""
    assert hasattr(PS, "MODES_AUTORISES"), (
        "aucune liste de modes autorises : le module ne peut pas distinguer "
        "un mode INVALIDE d'un mode moins restrictif")
    assert "CLM" in PS.MODES_AUTORISES


def test_mode_valide_reconnait_les_modes_legitimes():
    """Contrôle positif : le garde ne doit pas tout refuser.

    CORRECTION du 2026-09-12, imposée par la mesure : `PREFLIGHT` n'est PAS une
    valeur inconnue. Elle est documentée dans le module (L116) ET publiée dans
    le contrat du tool (`forge_mcp_registry` L7632 : `mode=CLM|preflight|JEA`).
    La refuser casserait un contrat exposé — c'est la surcorrection qu'on veut
    éviter. L'invariant porte sur les valeurs HORS contrat, pas sur les modes
    moins restrictifs qui ont été délibérément publiés.

    Que `PREFLIGHT` soit atteignable par un client normal est une question
    d'architecture (périmètre des capacités), pas un défaut de validation :
    elle se tranche ailleurs, pas en cassant l'interface ici.
    """
    assert hasattr(PS, "mode_valide"), "fonction de validation absente"
    for legitime in ("CLM", "JEA", "PREFLIGHT", "clm", " jea "):
        assert PS.mode_valide(legitime) is True, (
            "mode documente %r refuse : regression d'interface" % (legitime,))


def test_un_mode_hors_contrat_est_refuse():
    """ROUGE ATTENDU. Une valeur qui n'appartient à aucun mode déclaré ne doit
    pas tomber dans la branche la MOINS restrictive."""
    assert hasattr(PS, "mode_valide"), "fonction de validation absente"
    for inconnu in ("FULL", "FULLLANGUAGE", "BYPASS", "", "??", None):
        assert PS.mode_valide(inconnu) is False, (
            "mode %r accepte : un inconnu ne doit jamais valoir un mode declare"
            % (inconnu,))


def test_run_refuse_un_mode_inconnu_sans_rien_executer():
    """ROUGE ATTENDU. Le refus doit précéder la création du script : aucun
    fichier ne doit être écrit, aucun PowerShell lancé."""
    sb = PS.PowerShellSandbox(mode="FULL", timeout=5)
    res = sb.run("Get-Date")
    assert res.ok is False, "un mode inconnu a ete execute"
    assert "mode" in (res.stderr or "").lower(), (
        "le refus ne nomme pas le mode : un garde muet ne se diagnostique pas "
        "(stderr=%r)" % (res.stderr,))


def test_le_refus_est_anterieur_a_l_ecriture(tmp_path, monkeypatch):
    """Le mode inconnu doit être écarté AVANT `mkstemp` : sinon un script
    client est matérialisé sur disque avant même la décision."""
    appels = {"n": 0}
    vrai_mkstemp = PS.tempfile.mkstemp

    def _espion(*a, **k):
        appels["n"] += 1
        return vrai_mkstemp(*a, **k)

    monkeypatch.setattr(PS.tempfile, "mkstemp", _espion)
    PS.PowerShellSandbox(mode="FULL", timeout=5).run("Get-Date")
    assert appels["n"] == 0, (
        "un script a ete materialise malgre un mode invalide : la decision "
        "arrive apres l'ecriture")
