"""NR — un rapport d'audit DIT de quel environnement il est la propriete.

Defaut mesure le 2026-09-20. `forge_pip_audit_mesure.py` lance
`sys.executable -m pip_audit`, et les `run_job` s'executent sous
`miniforge3/envs/laforge_py314` (preuve : le wrapper genere du job). Le rapport
produit decrit donc l'environnement de la CI — pas celui du hub, qui tourne sous
`miniforge3` (base).

    laforge_py314 (CI)   226 paquets audites,  1 a 5 touches
    miniforge3    (hub)  835 paquets audites, 66 touches

609 paquets de l'environnement qui fait tourner le corps ne sont audites par
personne. Et le gate de la CI accepte ce rapport comme suppleant en jugeant sa
FRAICHEUR, jamais sa PORTEE : il affiche « supplee ... 3.6 j (< 7 j) ».

⚠️ CE QUE CE TEST FERME : `OBSERVED(X) != PROPERTY_OF(X)`. Un rapport anonyme se
lit comme « l'environnement », alors qu'il ne decrit qu'UN environnement. Le
nommer ne corrige pas la portee — mais il rend la portee LISIBLE, ce qui est le
prealable pour qu'un consommateur puisse la juger.

Pur : on inspecte la forme du rapport, aucun reseau, aucun service.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))


def _mod():
    import forge_pip_audit_mesure  # type: ignore

    return forge_pip_audit_mesure


def test_le_module_expose_une_enveloppe_nommant_l_interpreteur():
    """La fonction doit exister et rendre l'identite de ce qui a ete audite."""
    m = _mod()
    assert hasattr(m, "enveloppe_meta"), (
        "aucune enveloppe : le rapport reste anonyme et se lira comme « "
        "l'environnement » alors qu'il n'en decrit qu'un"
    )
    meta = m.enveloppe_meta([])
    for cle in ("interpreteur", "n_paquets_audites", "n_paquets_touches"):
        assert cle in meta, "l'enveloppe ne porte pas « %s » : %s" % (cle, sorted(meta))


def test_l_interpreteur_est_celui_qui_a_REELLEMENT_audite():
    """Pas un chemin ecrit a la main : celui de l'execution en cours."""
    m = _mod()
    assert m.enveloppe_meta([])["interpreteur"] == sys.executable, (
        "l'enveloppe annonce un interpreteur qui n'est pas celui qui mesure"
    )


def test_les_comptes_sont_ceux_des_donnees_et_non_declares():
    """Un compte ecrit a cote des donnees derive ; celui-ci se calcule."""
    m = _mod()
    deps = [
        {"name": "a", "vulns": [{"id": "X"}, {"id": "Y"}]},
        {"name": "b", "vulns": []},
        {"name": "c", "vulns": [{"id": "Z"}]},
    ]
    meta = m.enveloppe_meta(deps)
    assert meta["n_paquets_audites"] == 3, meta
    assert meta["n_paquets_touches"] == 2, meta
    assert meta["n_avis"] == 3, meta


def test_un_perimetre_vide_ne_se_lit_pas_comme_un_depot_sain():
    """Zero paquet audite n'est pas « rien a signaler » : c'est un instrument
    aveugle. Le module le refusait deja ; l'enveloppe ne doit pas le rattraper
    en rendant un chiffre rassurant."""
    m = _mod()
    meta = m.enveloppe_meta([])
    assert meta["n_paquets_audites"] == 0
    assert meta.get("portee") == "AUCUNE", (
        "un perimetre vide doit etre NOMME comme tel : %s" % meta
    )
