"""NR — negociation de version MCP et consignes serveur (veilles lot_B_20 / lot_B_15, 24/09).

Avant : le hub renvoyait en ECHO la `protocolVersion` du client, quelle qu'elle soit, et
`initialize` n'avait pas de champ `instructions`. Contrat :
  - version supportee -> echo ; version inconnue -> la plus recente supportee + avertissement ;
  - aucune demande -> comportement historique (2025-03-26) ;
  - consignes serveur COURTES (elles entrent dans le prompt de chaque session cliente) ;
  - le hub (fichier critique) passe REELLEMENT par ce module et decide sur `scope["path"]`.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))

import forge_mcp_protocole as mp  # noqa: E402  (import strict)


def test_version_supportee_rendue_telle_quelle():
    for v in mp.VERSIONS_SUPPORTEES:
        assert mp.negocier_version(v) == (v, None)


def test_version_inconnue_rend_la_plus_recente_et_le_dit():
    v, avert = mp.negocier_version("1999-01-01")
    assert v == mp.VERSIONS_SUPPORTEES[0] and avert and "1999-01-01" in avert


def test_sans_demande_comportement_historique():
    assert mp.negocier_version(None) == ("2025-03-26", None)
    assert mp.negocier_version("") == ("2025-03-26", None)


def test_consignes_serveur_courtes_et_pointant_la_doctrine():
    assert len(mp.INSTRUCTIONS_SERVEUR) <= 400, (
        "les consignes entrent dans le prompt de CHAQUE session : %d caracteres"
        % len(mp.INSTRUCTIONS_SERVEUR))
    assert "governed_edit" in mp.INSTRUCTIONS_SERVEUR and "RULES_SHARED" in mp.INSTRUCTIONS_SERVEUR


def _hub():
    return (RACINE / "tools" / "nokido_hub.py").read_text(encoding="utf-8", errors="replace")


def test_le_hub_passe_par_la_negociation_et_publie_les_consignes():
    src = _hub()
    i = src.find('if method == "initialize":')
    assert i > 0
    bloc = src[i:i + 4000]
    # Le hub importe la fonction sous un alias : on verifie l'import ET l'appel.
    assert "forge_mcp_protocole" in bloc and "negocier_version as _negocier" in bloc \
        and "_negocier(" in bloc, "le hub renvoie encore la version en echo"
    assert '"instructions"' in bloc, "initialize ne publie pas les consignes serveur"


def test_les_decisions_de_chemin_lisent_scope_path():
    """CVE-2026-48710 : `request.url` est fabrique avec l'en-tete Host. Une decision
    (delestage, autorisation) doit lire `scope["path"]`, jamais `request.url.path`."""
    src = _hub()
    assert "_az.decider(request.url.path" not in src
    assert "path = request.url.path" not in src
    assert src.count('request.scope["path"]') >= 2


def test_x_session_lu_une_seule_fois():
    """Les en-tetes Starlette sont insensibles a la casse : la seconde lecture etait morte."""
    assert 'get("X-Session-ID"' not in _hub()
