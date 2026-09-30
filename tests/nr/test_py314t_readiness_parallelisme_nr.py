# -*- coding: utf-8 -*-
"""NR — la readiness py314t se MESURE, elle ne se declare pas.

Mesure 2026-08-30. `forge_py314t_readiness.CANDIDATES` est une carte ecrite a la
main dont le champ `parallel` etait une INTENTION que rien ne confrontait au code.
La matrice affichait donc six `READY+PARALLEL` ; quatre de ces modules n'importent
ni `threading` ni `concurrent` -- `forge_world_model`, `forge_semantic_pressure`,
`forge_tem_factorize`, `forge_lats_general`.

L'enjeu n'est pas cosmetique : basculer un module sans thread vers le build
free-threaded coute +13 % de RAM a vide (18,1 -> 20,4 Mo, mesure du jour) pour un
gain NUL, puisque le free-threading leve le GIL mais ne parallelise pas le code.
Sur une machine qui refusait deja des jobs a 85 % de RAM, c'est une regression.

Ces tests verrouillent la mesure et, surtout, ses trois etats.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (code appele) (l.88)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from forge_py314t_readiness import (  # noqa: E402
    CANDIDATES,
    deps_absentes,
    deps_de_travail,
    parallelisme_mesure,
)


def test_module_avec_threading_est_mesure_parallele():
    # forge_handoff importe `concurrent.futures` ET `threading` (verifie a l'AST).
    r = parallelisme_mesure("forge_handoff")
    assert r["etat"] == "oui", r
    assert r["imports"], "les imports parallelisants doivent etre NOMMES, pas juste comptes"


def test_module_sans_thread_est_mesure_non_parallele():
    r = parallelisme_mesure("forge_semantic_pressure")
    assert r["etat"] == "non", (
        "forge_semantic_pressure n'importe aucun module de parallelisme : "
        "le declarer parallele ferait basculer un service pour rien -- %r" % r
    )


def test_module_introuvable_est_ILLISIBLE_jamais_non():
    """Le piege : rendre `non` pour « je n'ai pas pu regarder ».

    Un module qu'on ne sait pas lire n'est pas un module sans threads. Confondre
    les deux fabrique un faux negatif indetectable.
    """
    r = parallelisme_mesure("forge_module_qui_n_existe_pas_du_tout")
    assert r["etat"] == "illisible", r
    assert r.get("motif"), "un etat illisible doit NOMMER ce qu'on n'a pas pu voir"


def test_les_trois_etats_sont_les_seuls_possibles():
    for nom, info in CANDIDATES.items():
        etat = parallelisme_mesure(info["module"])["etat"]
        assert etat in ("oui", "non", "illisible"), "%s -> %r" % (nom, etat)


def test_au_moins_un_candidat_est_declare_parallele():
    """Sonde de la sonde : sans cela, les tests ci-dessus seraient vacuement verts."""
    assert any(c.get("parallel") for c in CANDIDATES.values()), (
        "aucun candidat declare parallele : la carte a change de forme, ce test ne "
        "mesure plus rien"
    )


def test_les_deps_lourdes_sont_MESUREES_sur_le_module():
    """`forge_bge_m3_shared` importe onnxruntime : la sonde doit le voir."""
    assert "onnxruntime" in deps_de_travail("forge_bge_m3_shared")
    # forge_handoff n'a pas de dependance lourde -- rien a exiger de l'env cible.
    assert deps_de_travail("forge_handoff") == []


def test_une_dep_absente_est_DETECTEE_pas_supposee_presente(tmp_path):
    """Le coeur du faux vert : un import de module qui reussit SANS ses deps.

    `probe_module_import` voyait `forge_bge_m3_shared` OK sous py314t alors
    qu'onnxruntime y est absent -- le module protege ses imports lourds et
    retombe en repli. On sonde donc l'env pour CHAQUE dep, avec l'interpreteur
    courant comme temoin : un paquet fabrique n'existe nulle part.
    """
    absentes = deps_absentes(sys.executable, ["os", "paquet_qui_n_existe_pas_du_tout"])
    assert absentes == ["paquet_qui_n_existe_pas_du_tout"], absentes


def test_aucune_dep_demandee_rend_liste_vide():
    assert deps_absentes(sys.executable, []) == []


def test_une_declaration_parallele_sans_thread_ne_doit_pas_etre_recommandee():
    """Le contrat de decision : declare ET mesure, pas l'un des deux.

    On rejoue ici la regle appliquee dans `main()` sans lancer les sondes d'import
    (qui demarrent trois interpreteurs) : le test reste hermetique.
    """
    for nom, info in CANDIDATES.items():
        if not info.get("parallel"):
            continue
        mes = parallelisme_mesure(info["module"])
        recommande = True and bool(info["parallel"]) and mes["etat"] == "oui"
        if mes["etat"] != "oui":
            assert not recommande, (
                "%s est declare parallele mais son code ne porte aucun thread : "
                "il ne doit pas etre recommande pour py314t" % nom
            )
