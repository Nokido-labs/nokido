"""NR -- handle_hub transmet a forge_ordres_bureau la PREUVE d'identite deja posee pour la requete.

Carte AGY job_04ab2eb5 : nokido_hub.py:3139 pose `forge_recon_breaker.IDENTITE_PROUVEE` (resolve_identity(nom, jeton) :
le nom declare est PROUVE par son jeton) pour CETTE requete ; forge_mcp_registry.handle_hub ne la lisait pas et
n'appelait redemarrer_stack / demander_ordre qu'avec une chaine. Sans elle, b21fd1de5 et 1b800095a restent INERTES :
la demande admin du CLI pilote passe encore par le dialogue qui expire (owner 17/10).
Meme patron que test_demander_ordre_nr::test_le_registre_route_demander_ordre (le registre se lit au source).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _bloc_ordres_bureau():
    src = (ROOT / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")
    debut = src.index("from nokido_agent.app import forge_ordres_bureau as _ob")
    return src[debut:src.index("return _json.dumps(r, ensure_ascii=False)", debut)]


def test_la_preuve_de_la_requete_est_lue():
    assert "IDENTITE_PROUVEE" in _bloc_ordres_bureau()


def test_les_deux_portes_recoivent_la_preuve():
    bloc = _bloc_ordres_bureau()
    for porte in ("redemarrer_stack", "demander_ordre"):
        appel = re.search(r"_ob\.%s\((.*?)\)\n" % porte, bloc, re.S)
        assert appel and "demandeur_prouve=" in appel.group(1), porte
