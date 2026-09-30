"""NR — `sandbox=ps_clm` exige l'attestation DEV, qui existe déjà.

CE QUI EST DÉMONTRÉ (2026-09-12, chantier M0.1) :

    client ring 3 → run → sandbox="ps_clm" → PowerShellSandbox
                  → script dont le CONTENU vient du client (f.write(code), L5)
                  → NT AUTHORITY\\Système

    `console`, qui ne donne que la session UTILISATEUR, est gardé ring-0
    default-deny. `ps_clm`, qui donne SYSTEM, n'était gardé par rien.
    L'asymétrie est inversée par rapport au privilège.

CE QUI REND LA CORRECTION MINIMALE POSSIBLE :

    `tools/forge_dev_mode` existe déjà — `arm()` / `disarm()` / `is_armed()`,
    TTL, et un token `sandbox/.dev_mode_token` dont l'ACL est SYSTEM +
    Administrators. **Le client ne peut pas l'armer lui-même** : c'est une
    attestation par une autorité extérieure, exactement ce qu'un mode dev doit
    être. Il n'y a donc AUCUN second mécanisme à créer — seulement un
    raccordement.

    Et la restriction ne casse aucun usage runtime : mesure du même jour,
    `ps_clm` n'a AUCUN appelant fonctionnel dans le dépôt (les 11 occurrences
    sont des patches déclarant l'enum, un rang d'isolation, un commentaire et
    des tests). Seuls des clients interactifs l'utilisent.

POURQUOI UN TEST STRUCTUREL :
    La décision vit dans `_exec_sandboxed`, méthode d'une classe lourde à
    instancier hors hub. On lit donc le SOURCE RÉEL. Mais on ne se contente pas
    d'une MENTION de `is_armed` dans le fichier — ce serait le piège déjà payé
    (« une mention n'est pas une structure ») : on vérifie que l'appel est dans
    la BRANCHE `ps_clm` et qu'il PRÉCÈDE l'instanciation de l'exécuteur.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
REGISTRE = RACINE / "app" / "forge_mcp_registry.py"


def _branche_ps_clm() -> str:
    """Le corps de la branche `if sandbox == "ps_clm":`, jusqu'à la suivante."""
    if not REGISTRE.is_file():
        pytest.skip(f"registre absent: {REGISTRE}")
    src = REGISTRE.read_text(encoding="utf-8", errors="replace")
    debut = src.find('if sandbox == "ps_clm":')
    assert debut != -1, "la branche de dispatch ps_clm a disparu du registre"
    suite = src.find('if sandbox == "docker":', debut)
    return src[debut: suite if suite != -1 else debut + 4000]


def test_la_branche_de_dispatch_existe_toujours():
    """Contrôle positif : sans elle, tous les tests suivants seraient vides."""
    branche = _branche_ps_clm()
    assert "PowerShellSandbox" in branche, (
        "la branche ps_clm n'instancie plus la sandbox : dispatch modifie, "
        "ce NR doit etre revu")


def test_le_gate_console_reste_en_place():
    """Garde-fou de non-régression : on ajoute une protection, on n'en retire
    aucune."""
    src = REGISTRE.read_text(encoding="utf-8", errors="replace")
    assert "sandbox=console requiert ring=0" in src, (
        "le gate ring-0 de console a disparu")


def test_ps_clm_consulte_l_attestation_dev():
    """ROUGE ATTENDU avant correction."""
    branche = _branche_ps_clm()
    assert "is_armed" in branche, (
        "la branche ps_clm n'interroge PAS l'attestation dev : un client normal "
        "obtient un transfert de code vers un executeur SYSTEM sans qu'aucune "
        "autorite exterieure ne l'ait accorde")


def test_l_attestation_precede_l_executeur():
    """ROUGE ATTENDU. Une vérification postérieure à l'instanciation ne garde
    rien : l'ordre est la propriété, pas la présence."""
    branche = _branche_ps_clm()
    pos_gate = branche.find("is_armed")
    pos_exec = branche.find("PowerShellSandbox(")
    assert pos_gate != -1, "aucune attestation dans la branche"
    assert pos_exec != -1, "aucune instanciation trouvee"
    assert pos_gate < pos_exec, (
        "l'attestation est consultee APRES l'instanciation de l'executeur "
        "(gate=%d, exec=%d)" % (pos_gate, pos_exec))


def test_le_refus_est_explicite_et_nomme_le_motif():
    """Un refus muet ne se diagnostique pas — et un garde qu'on ne comprend pas
    se fait désarmer."""
    branche = _branche_ps_clm()
    assert re.search(r"SECURITY:.*ps_clm", branche), (
        "le refus ne porte pas de message SECURITY nommant ps_clm")


def test_aucun_second_mecanisme_dev_n_est_introduit():
    """Le raccordement doit utiliser `forge_dev_mode`, pas un dev-mode bis."""
    branche = _branche_ps_clm()
    if "is_armed" in branche:
        assert "forge_dev_mode" in branche, (
            "une attestation est consultee mais elle ne vient pas de "
            "forge_dev_mode : un second mecanisme de dev a ete introduit")
