"""NR -- changement du fichier-cle de V: SANS interface graphique (suite de l'incident du 2026-09-28).

La voie graphique a reecrit les en-tetes avec un verrou inconnu ; elle est retiree. Le
remplacement rechiffre les DEUX en-tetes : meme clair (donc meme cle maitresse, memes donnees),
nouveau sel, nouveau fichier-cle. Ordre qui ne peut pas perdre l'acces :

  1. preuve que la cle rangee ouvre les deux en-tetes -- sinon rien ;
  2. sauvegarde des deux groupes d'en-tetes, RELUE ;
  3. la nouvelle cle existe sur disque AVANT toute ecriture d'en-tete ;
  4. ecriture, relecture : la nouvelle ouvre les deux, l'ancienne n'ouvre plus -- sinon les
     en-tetes sauvegardes sont REMIS ;
  5. rangement au coffre reserve (SYSTEM), relu ; copie du coffre machine retiree.

Sans --appliquer : preuves seules, AUCUNE ecriture. Hors SYSTEM : refus. Aucune sortie ne contient
une cle. Iterations reduites pour la vitesse, meme algorithme. Cles de test factices.
"""
from __future__ import annotations

import base64
import hashlib
import importlib
import importlib.util
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = Path(__file__).resolve().parents[2]
ANCIENNE = bytes(range(64))
ITER = 1000


def _entete(mod, cle):
    sel = os.urandom(64)
    clair = b"VERA" + os.urandom(444)
    dk = hashlib.pbkdf2_hmac("sha512", mod._pool_fichiers_cles([cle], 64), sel, ITER, dklen=64)
    enc = Cipher(algorithms.AES(dk), modes.XTS(b"\x00" * 16)).encryptor()
    return sel + enc.update(clair) + enc.finalize()


@pytest.fixture
def vc(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("nr_vc_rekey_scripte", ROOT / "tools/forge_at_rest_veracrypt.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "_ITERATIONS_ENTETE", ITER)
    g = m.ENTETE_GROUPE
    c = tmp_path / "conteneur.hc"
    c.write_bytes(_entete(m, ANCIENNE) + os.urandom(g - 512) + os.urandom(3 * g)
                  + _entete(m, ANCIENNE) + os.urandom(g - 512))
    monkeypatch.setattr(m, "CONTAINER", c)
    monkeypatch.setattr(m, "REKEY_DIR", tmp_path / "vc_rekey")
    monkeypatch.setattr(m, "_is_mounted", lambda: False)
    monkeypatch.setattr(m, "_vault_get", lambda k: base64.b64encode(ANCIENNE).decode())
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 0})())
    mv = importlib.import_module("nokido_agent.app.forge_machine_vault")
    coffre = {"reserve": {}, "retire": []}
    monkeypatch.setattr(mv, "reserve_set", lambda k, v: coffre["reserve"].__setitem__(k, v) or True)
    # CONTRAT REEL : (valeur, etat). La premiere version de ce NR simulait une chaine seule ;
    # le code comparait donc un tuple a une chaine sans que le NR le voie -- fausse alerte
    # « cle NON rangee » en production le 2026-09-28 alors que la cle ETAIT rangee.
    monkeypatch.setattr(mv, "reserve_lire", lambda k: ((coffre["reserve"][k], mv.RESERVE_TROUVE)
                                                       if k in coffre["reserve"]
                                                       else (None, mv.RESERVE_CLE_ABSENTE)))
    monkeypatch.setattr(mv, "vault_delete", lambda k: coffre["retire"].append(k) or True)
    monkeypatch.setattr(mv, "_sid_courant", lambda: mv.RESERVE_COMPTE_SID)
    return m, c, mv, coffre


def _donnees(m, c):
    b = c.read_bytes()
    return b[m.ENTETE_GROUPE:len(b) - m.ENTETE_GROUPE]


def test_sans_appliquer_rien_n_est_ecrit(vc, capsys):
    m, c, _mv, coffre = vc
    avant = hashlib.sha256(c.read_bytes()).hexdigest()
    assert m.cmd_rekey(appliquer=False) == 0
    capsys.readouterr()
    assert hashlib.sha256(c.read_bytes()).hexdigest() == avant
    assert not m.REKEY_DIR.exists() and coffre["reserve"] == {}


def test_hors_system_refus_sans_ecriture(vc, monkeypatch, capsys):
    m, c, mv, _coffre = vc
    monkeypatch.setattr(mv, "_sid_courant", lambda: "S-1-5-21-1-2-3-1001")
    avant = hashlib.sha256(c.read_bytes()).hexdigest()
    assert m.cmd_rekey(appliquer=True) == 1
    capsys.readouterr()
    assert hashlib.sha256(c.read_bytes()).hexdigest() == avant and not m.REKEY_DIR.exists()


def test_cle_rangee_qui_n_ouvre_pas_rien_n_est_fait(vc, monkeypatch, capsys):
    m, c, _mv, _coffre = vc
    monkeypatch.setattr(m, "_vault_get", lambda k: base64.b64encode(b"X" * 64).decode())
    avant = hashlib.sha256(c.read_bytes()).hexdigest()
    assert m.cmd_rekey(appliquer=True) == 1
    capsys.readouterr()
    assert hashlib.sha256(c.read_bytes()).hexdigest() == avant and not m.REKEY_DIR.exists()


def test_rechiffrement_complet_et_donnees_intactes(vc, capsys):
    m, c, _mv, coffre = vc
    donnees = _donnees(m, c)
    clair_avant = m._entete_clair(c.read_bytes()[:512], [ANCIENNE])[2]
    assert m.cmd_rekey(appliquer=True) == 0
    sortie = capsys.readouterr().out
    nouvelle = (m.REKEY_DIR / "nouveau.kf").read_bytes()
    b = c.read_bytes()
    principal, secours = b[:512], b[len(b) - m.ENTETE_GROUPE:len(b) - m.ENTETE_GROUPE + 512]
    assert m._entete_ouvre(principal, [nouvelle]) and m._entete_ouvre(secours, [nouvelle])
    assert not m._entete_ouvre(principal, [ANCIENNE]) and not m._entete_ouvre(secours, [ANCIENNE])
    assert m._entete_clair(principal, [nouvelle])[2] == clair_avant      # meme cle maitresse
    assert _donnees(m, c) == donnees                                     # donnees intactes
    assert (m.REKEY_DIR / "entete_avant_principal.bin").read_bytes()[:512] != principal
    assert coffre["reserve"].get(m.VAULT_KEY) == base64.b64encode(nouvelle).decode()
    assert coffre["retire"] == [m.VAULT_KEY]
    for cle in (ANCIENNE, nouvelle):
        assert base64.b64encode(cle).decode() not in sortie


def test_relecture_differente_du_coffre_reserve_reste_une_alerte(vc, monkeypatch, capsys):
    m, _c, mv, coffre = vc
    monkeypatch.setattr(mv, "reserve_set", lambda k, v: coffre["reserve"].__setitem__(k, "autre") or True)
    assert m.cmd_rekey(appliquer=True) == 1
    sortie = capsys.readouterr().out
    assert "NON rangee" in sortie and m._rekey_etat().get("phase") == "ecrit_non_range"
    assert coffre["retire"] == []                 # rien n'est retire tant que la cle n'est pas rangee


def test_restaurer_remet_les_en_tetes_d_avant(vc, capsys):
    m, c, _mv, _coffre = vc
    assert m.cmd_rekey(appliquer=True) == 0
    assert m.cmd_rekey_restaurer() == 0
    capsys.readouterr()
    b = c.read_bytes()
    assert m._entete_ouvre(b[:512], [ANCIENNE])
    assert m._entete_ouvre(b[len(b) - m.ENTETE_GROUPE:len(b) - m.ENTETE_GROUPE + 512], [ANCIENNE])


def test_clore_efface_seulement_si_verifie_et_range(vc, monkeypatch, capsys):
    """Les sauvegardes (anciens en-tetes + ancienne cle = acces a la cle maitresse) et la copie de
    la nouvelle cle ne restent pas : effacees SEULEMENT si phase « verifie » ET coffre reserve =
    nouveau.kf ; sinon rien n'est touche."""
    m, _c, mv, coffre = vc
    assert m.cmd_rekey_clore() == 1                       # rien a clore
    assert m.cmd_rekey(appliquer=True) == 0
    vraie = coffre["reserve"][m.VAULT_KEY]
    coffre["reserve"][m.VAULT_KEY] = "autre"
    assert m.cmd_rekey_clore() == 1 and m.REKEY_DIR.exists()          # coffre != nouveau.kf
    coffre["reserve"][m.VAULT_KEY] = vraie
    m._rekey_ecrire_etat("ecriture")
    assert m.cmd_rekey_clore() == 1 and m.REKEY_DIR.exists()          # pas verifie
    m._rekey_ecrire_etat("verifie")
    assert m.cmd_rekey_clore() == 0 and not m.REKEY_DIR.exists()
    capsys.readouterr()


def test_une_preparation_en_cours_n_est_jamais_ecrasee(vc, capsys):
    m, c, _mv, _coffre = vc
    m.REKEY_DIR.mkdir(parents=True)
    avant = hashlib.sha256(c.read_bytes()).hexdigest()
    assert m.cmd_rekey(appliquer=True) == 1
    capsys.readouterr()
    assert hashlib.sha256(c.read_bytes()).hexdigest() == avant
