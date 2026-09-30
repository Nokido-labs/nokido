"""NR — le relais reçoit sa clé par le COFFRE, jamais par un fichier versionné.

POURQUOI CE LANCEUR EXISTE. `services.toml` est lu par le superviseur Deno et son
bloc `env` est STATIQUE : y écrire `CONTROL_PLANE_API_KEY` reviendrait à versionner
un secret dans un dépôt qui passe en public. Et `tunnel-client.exe` est un binaire
TIERS : il ne sait pas lire le coffre DPAPI de Nokido, il attend la valeur dans son
environnement (`env:CONTROL_PLANE_API_KEY`, forme déclarée par son profil).

Le lanceur comble exactement cet écart : il lit le coffre, pose la valeur dans
l'environnement du SOUS-PROCESSUS, et exécute le binaire. C'est le patron déjà
prouvé pour le jeton GitHub (`forge_push_sovereign`) — « le jeton vient du coffre
et transite par l'ENVIRONNEMENT du sous-processus, jamais par la ligne de
commande : une cmdline se lit, un env non ».

CE QUE CES TESTS VERROUILLENT :
  - la clé n'apparaît JAMAIS dans la ligne de commande construite ;
  - une clé absente REFUSE le démarrage en le disant — un relais sans identité ne
    doit pas tourner, et un démarrage silencieux qui échoue plus tard côté OpenAI
    serait une panne illisible de plus ;
  - le binaire est résolu depuis `NOKIDO_BIN`, donc portable : le dépôt passe en
    public et ne doit pas porter le chemin d'un poste.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_tunnel_client_launch as L  # noqa: E402


def test_la_cle_n_est_jamais_dans_la_ligne_de_commande():
    """Une cmdline se lit (tasklist, journaux, inventaire de process) ; un env non."""
    cmd = L.commande(binaire="X:/tc.exe", config="X:/p.yaml", port=8792)
    joint = " ".join(cmd)
    assert "CONTROL_PLANE_API_KEY" not in joint
    assert "--control-plane.api-key" not in joint, (
        "la clé passerait en argument : lisible par tout process du poste"
    )
    assert "run" in cmd and "--config" in cmd


def test_la_cle_absente_refuse_le_demarrage_en_le_disant():
    """Un relais sans identité ne doit pas tourner.

    Le démarrer quand même donnerait un échec distant, plus tard, sans rapport
    visible avec la cause — exactement la panne illisible qu'on vient de payer
    avec le registre DCR non persisté.
    """
    ok, motif = L.decider_lancement(cle=None)
    assert ok is False
    assert "coffre" in motif.lower(), f"le motif doit dire OÙ chercher : {motif!r}"
    assert "CONTROL_PLANE_API_KEY" in motif, "le motif doit NOMMER le secret attendu"


def test_une_cle_vide_vaut_une_cle_absente():
    """Une chaîne vide n'est pas une clé — sinon on démarre avec une identité nulle."""
    ok, _motif = L.decider_lancement(cle="   ")
    assert ok is False


def test_une_cle_presente_autorise_et_ne_fuite_pas():
    """Le motif de succès ne doit pas contenir la valeur, même tronquée."""
    ok, motif = L.decider_lancement(cle="sk-secret-ABCDEF123456")
    assert ok is True
    assert "ABCDEF" not in motif and "sk-secret" not in motif, (
        f"la clé fuite dans le motif journalisé : {motif!r}"
    )


def test_l_environnement_du_sous_processus_porte_la_cle():
    """C'est le seul canal admis : ni argument, ni fichier sur disque."""
    env = L.environnement(cle="valeur-test", base={"PATH": "/x"})
    assert env["CONTROL_PLANE_API_KEY"] == "valeur-test"
    assert env["PATH"] == "/x", "l'environnement de base doit être conservé"


def test_le_binaire_est_resolu_depuis_le_magasin(monkeypatch):
    """Portabilité : le dépôt passe en public, il ne porte pas le chemin d'un poste."""
    monkeypatch.setenv("NOKIDO_BIN", "D:/ailleurs")
    chemin = L.binaire_par_defaut()
    assert str(chemin).replace("\\", "/").startswith("D:/ailleurs"), chemin


def test_aucun_chemin_de_profil_en_dur_dans_le_module():
    """Un chemin de home versionné fuite la disposition du poste de dev."""
    source = (ROOT / "tools" / "forge_tunnel_client_launch.py").read_text(encoding="utf-8")
    assert "Users\\user" not in source and "Users/user" not in source


def test_le_module_ne_lance_rien_a_l_import():
    """Leçon du même jour : `deploy_hub_bundle` deployait A L'IMPORT.

    Un module qui agit quand on le lit est une arme qui part toute seule.
    """
    import ast
    source = (ROOT / "tools" / "forge_tunnel_client_launch.py").read_text(encoding="utf-8")
    for noeud in ast.parse(source).body:
        if isinstance(noeud, ast.Expr) and isinstance(noeud.value, ast.Call):
            pytest.fail("appel au niveau module : ce fichier agirait a l'import")
