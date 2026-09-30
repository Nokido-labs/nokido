"""NR -- l'en-tete de V: se verifie HORS VeraCrypt, en lecture seule (incident du 2026-09-28).

Ce jour-la, V: est reste inaccessible ~2 h. Une etape de l'interface graphique de VeraCrypt
avait reecrit les deux en-tetes avec un verrou inconnu, et `--mount` ne disait que « rc=1 »
(VeraCrypt en /silent). Trois heures de pistes (mot de passe, anciennes copies du coffre,
version de VeraCrypt) avant qu'un dechiffrement de l'en-tete hors VeraCrypt tranche : la cle
ouvrait les en-tetes des cliches VSS du 27/09, plus l'en-tete actuel.

Contrat :
- `_entete_ouvre` rend (prf, taille du pool) avec la bonne cle, None sinon ; plusieurs
  fichiers-cles : l'ordre n'importe pas (VeraCrypt additionne les pools) ;
- `verdict_cle_entete` : OUVRE / NON / ILLISIBLE -- un conteneur illisible n'est PAS « la cle
  ne marche pas » ;
- chemin reel `main(["--mount"])` : un echec DIT si la cle ouvre l'en-tete (verdict hors
  VeraCrypt) ; `main(["--verifier-cle"])` rend 0/1 ; aucune sortie ne contient la cle.

Le dechiffrement a ete valide sur de VRAIS en-tetes VeraCrypt le 2026-09-28 (cliches VSS) ;
ici, iterations reduites pour la vitesse, meme algorithme. Cles de test factices.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = Path(__file__).resolve().parents[2]
CLE = bytes(range(64))
AUTRE = bytes(range(64, 128))
ITER = 1000


def _outil(monkeypatch):
    spec = importlib.util.spec_from_file_location("nr_vc_entete", ROOT / "tools/forge_at_rest_veracrypt.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_ITERATIONS_ENTETE", ITER)
    return mod


def _entete(mod, fichiers, prf="sha512", taille=64):
    """En-tete de volume standard : sel (64) + 448 octets chiffres commencant par VERA."""
    sel = os.urandom(64)
    clair = b"VERA" + os.urandom(444)
    dk = hashlib.pbkdf2_hmac(prf, mod._pool_fichiers_cles(fichiers, taille), sel, ITER, dklen=64)
    enc = Cipher(algorithms.AES(dk), modes.XTS(b"\x00" * 16)).encryptor()
    return sel + enc.update(clair) + enc.finalize()


def _conteneur(mod, tmp_path, cle):
    c = tmp_path / "conteneur.hc"
    c.write_bytes(_entete(mod, [cle]) + os.urandom(mod.ENTETE_GROUPE - 512)
                  + _entete(mod, [cle]) + os.urandom(mod.ENTETE_GROUPE - 512))
    return c


def test_dechiffrement_reconnait_la_bonne_cle_seulement(monkeypatch):
    mod = _outil(monkeypatch)
    h = _entete(mod, [CLE])
    assert mod._entete_ouvre(h, [CLE]) == ("sha512", 64)
    assert mod._entete_ouvre(h, [AUTRE]) is None
    assert mod._entete_ouvre(_entete(mod, [CLE], prf="sha256", taille=128), [CLE]) == ("sha256", 128)


def test_plusieurs_fichiers_cles_l_ordre_n_importe_pas(monkeypatch):
    mod = _outil(monkeypatch)
    assert mod._pool_fichiers_cles([CLE, AUTRE], 64) == mod._pool_fichiers_cles([AUTRE, CLE], 64)
    h = _entete(mod, [CLE, AUTRE])
    assert mod._entete_ouvre(h, [AUTRE, CLE]) and not mod._entete_ouvre(h, [CLE])


def test_verdict_lecture_seule_et_illisible_n_est_pas_non(monkeypatch, tmp_path):
    mod = _outil(monkeypatch)
    monkeypatch.setattr(mod, "_is_mounted", lambda: False)
    c = _conteneur(mod, tmp_path, CLE)
    avant = hashlib.sha256(c.read_bytes()).hexdigest()
    assert mod.verdict_cle_entete(CLE, c) == {"principal": "OUVRE", "secours": "OUVRE", "motif": ""}
    v = mod.verdict_cle_entete(AUTRE, c)
    assert (v["principal"], v["secours"]) == ("NON", "NON")
    assert hashlib.sha256(c.read_bytes()).hexdigest() == avant          # rien n'est ecrit
    v = mod.verdict_cle_entete(CLE, tmp_path / "absent.hc")
    assert (v["principal"], v["secours"]) == ("ILLISIBLE", "ILLISIBLE") and v["motif"]


def _monter(monkeypatch, tmp_path, cle_du_coffre):
    mod = _outil(monkeypatch)
    c = _conteneur(mod, tmp_path, CLE)
    monkeypatch.setattr(mod, "CONTAINER", c)
    monkeypatch.setattr(mod, "IS_WIN", True)
    monkeypatch.setattr(mod, "IS_LINUX", False)
    monkeypatch.setattr(mod, "_is_mounted", lambda: False)
    monkeypatch.setattr(mod, "_vc_main_bin", lambda: "VeraCrypt.exe")
    monkeypatch.setattr(mod, "_vault_get", lambda k: base64.b64encode(cle_du_coffre).decode())
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 1})())
    return mod


def test_mount_rate_dit_si_la_cle_ouvre_l_entete(monkeypatch, tmp_path, capsys):
    mod = _monter(monkeypatch, tmp_path, AUTRE)
    assert mod.main(["--mount"]) == 1
    sortie = capsys.readouterr().out
    assert "N'OUVRE PAS" in sortie and base64.b64encode(AUTRE).decode() not in sortie

    mod = _monter(monkeypatch, tmp_path, CLE)
    assert mod.main(["--mount"]) == 1
    sortie = capsys.readouterr().out
    assert "OUVRE l'en-tete" in sortie and "ailleurs" in sortie
    assert base64.b64encode(CLE).decode() not in sortie


def test_verifier_cle_rend_un_verdict_sans_montrer_la_cle(monkeypatch, tmp_path, capsys):
    mod = _monter(monkeypatch, tmp_path, CLE)
    assert mod.main(["--verifier-cle"]) == 0
    mod = _monter(monkeypatch, tmp_path, AUTRE)
    assert mod.main(["--verifier-cle"]) == 1
    sortie = capsys.readouterr().out
    assert base64.b64encode(CLE).decode() not in sortie and base64.b64encode(AUTRE).decode() not in sortie
