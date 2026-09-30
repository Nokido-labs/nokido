"""NR -- le fichier-cle VeraCrypt de V: devient un nom RESERVE (coffre, 2026-09-28).

Mesure du jour : `LAFORGE_VC_KEYFILE_B64` (fichier-cle du conteneur `C:\\LaForge_data\\
rag_secure_50g.hc`, monte en V:) vivait au coffre machine, hors des noms reserves, LISIBLE par
LaForgeSbxOffline ; et le conteneur lui-meme etait lisible par tout compte authentifie --
dechiffrement hors ligne possible depuis un compte bac a sable.

Lecteurs mesures : `tools/forge_at_rest_veracrypt.py` seul (tache de demarrage
`LaForge-VC-Boot`, sous SYSTEM ; et l'owner, pour un montage manuel ou `--status`, sous son
compte -- lecteur RARE, que le journal ne verrait pas : la fermeture attend sa voie propre).

Fermeture (meme jour) : copie au coffre reserve sous SYSTEM (tache de demarrage) et au
magasin PERSONNEL de l'owner (montage manuel), relues identiques -- chaque lecteur legitime
a sa voie ; hors SYSTEM, le guichet ne sert plus le fichier-cle par le coffre machine.

Contrats :
  1. le nom est reserve (coffre reserve lu d'abord, sous SYSTEM) et FERME hors SYSTEM ;
  2. l'outil de provisionnement le copie au coffre reserve (il couvre tous les noms reserves) ;
  3. forge_at_rest_veracrypt le lit AU GUICHET, jamais en direct au coffre machine.
"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOM = "LAFORGE_VC_KEYFILE_B64"


def test_le_fichier_cle_est_reserve_et_ferme():
    s = importlib.import_module("nokido_agent.app.forge_secrets")
    ok = (NOM in s.NOMS_RESERVES, NOM in s.RESERVES_EN_TRANSITION)
    assert ok == (True, False)


def test_l_outil_de_provisionnement_le_copie():
    spec = importlib.util.spec_from_file_location("nr_provision_vc", ROOT / "tools/forge_coffre_reserve_provision.py")
    o = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(o)
    assert NOM in o.COPIES


def test_veracrypt_lit_le_fichier_cle_au_guichet(monkeypatch):
    spec = importlib.util.spec_from_file_location("nr_vc_guichet", ROOT / "tools/forge_at_rest_veracrypt.py")
    vc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vc)
    s = importlib.import_module("nokido_agent.app.forge_secrets")
    mv = importlib.import_module("nokido_agent.app.forge_machine_vault")
    guichet: list = []
    direct: list = []
    monkeypatch.setattr(s, "get_secret", lambda k, required=False: guichet.append(k) or "valeur-de-test")
    monkeypatch.setattr(mv, "vault_get", lambda k: direct.append(k) or "valeur-directe")
    ok = (vc._vault_get(NOM) == "valeur-de-test", guichet, direct)
    assert ok == (True, [NOM], [])
