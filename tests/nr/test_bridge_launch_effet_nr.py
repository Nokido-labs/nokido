"""NR — le lanceur de la passerelle MCP décide, compose l'environnement et la
commande CORRECTEMENT, testé par EFFET (pas par import).

Réclamé par `test_nr_coverage_ratchet_nr` : `tools/forge_bridge_launch.py` était
livré (chantier pont ChatGPT du 2026-09-14, commit a50398f5e) sans aucun NR. Ce
module porte trois défauts déjà payés cette soirée-là, chacun verrouillé ici :

  1. `NOKIDO_BRIDGE_OAUTH_APPARIEMENT` absente → le consentement est fail-closed
     et refuse TOUT code : le lanceur doit REFUSER avant de démarrer.
  2. un client pré-inscrit PARTIEL (identifiant sans son secret associé) → refus,
     « ensemble ou pas du tout ».
  3. `NOKIDO_BRIDGE_OAUTH_CLIENTS` non posée → les clients inscrits vivaient en
     mémoire ; le lanceur injecte un registre par défaut mais RESPECTE une valeur
     déjà présente.

Hermétique : on appelle les fonctions PURES avec des dictionnaires en argument
(`base={}`), jamais `main()`/`lire()` — aucun coffre, aucun sous-processus,
aucun réseau. Les clés d'identité sont référencées via les constantes du module,
jamais réécrites en littéral (le scan de publication les prendrait pour une fuite).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_bridge_launch as L  # noqa: E402

TEMOIN = "valeur-temoin-a-ne-pas-fuiter-42"


def test_refuse_sans_la_variable_exigee():
    autorise, motif = L.decider_lancement({})
    assert autorise is False
    assert L.EXIGEE in motif
    assert "fail-closed" in motif.lower() or "code" in motif.lower()


def test_le_motif_de_refus_ne_montre_aucune_valeur():
    _autorise, motif = L.decider_lancement({L.EXIGEE: "", "bruit": TEMOIN})
    assert TEMOIN not in motif


def test_autorise_avec_l_appariement_seul():
    autorise, motif = L.decider_lancement({L.EXIGEE: "un-code"})
    assert autorise is True
    assert "appariement" in motif.lower()


def test_refuse_un_client_preinscrit_partiel():
    # un seul des champs optionnels posé → refus (le module les exige ensemble)
    valeurs = {L.EXIGEE: "un-code", L.OPTIONNELLES[0]: TEMOIN}
    autorise, motif = L.decider_lancement(valeurs)
    assert autorise is False
    assert "INCOMPLET" in motif or "ENSEMBLE" in motif


def test_autorise_un_client_preinscrit_complet():
    valeurs = {L.EXIGEE: "un-code"}
    for cle in L.OPTIONNELLES:
        valeurs[cle] = TEMOIN
    autorise, _motif = L.decider_lancement(valeurs)
    assert autorise is True


def test_environnement_injecte_le_registre_par_defaut_quand_absent():
    env = L.environnement({L.EXIGEE: "un-code"}, base={})
    reg = env.get("NOKIDO_BRIDGE_OAUTH_CLIENTS", "")
    assert reg, "le registre des clients OAuth doit être posé par le lanceur"
    assert reg.endswith(L.REGISTRE_PAR_DEFAUT[-1])  # bridge_oauth_clients.json


def test_environnement_respecte_un_registre_deja_pose():
    env = L.environnement({L.EXIGEE: "un-code"},
                          base={"NOKIDO_BRIDGE_OAUTH_CLIENTS": "/chemin/a/moi.json"})
    assert env["NOKIDO_BRIDGE_OAUTH_CLIENTS"] == "/chemin/a/moi.json"


def test_environnement_transfere_les_valeurs_non_vides_et_ignore_les_vides():
    env = L.environnement({L.EXIGEE: "un-code", "VIDE": "", "PLEIN": "x"}, base={})
    assert env[L.EXIGEE] == "un-code"
    assert env["PLEIN"] == "x"
    assert "VIDE" not in env


def test_la_commande_ne_porte_aucune_valeur_sensible():
    # Une cmdline se lit : elle ne contient QUE python, le script et le port.
    cmd = L.commande(8791)
    assert "--port" in cmd and "8791" in cmd
    joint = " ".join(cmd)
    assert TEMOIN not in joint
    assert L.EXIGEE not in joint
    assert len(cmd) == 6
