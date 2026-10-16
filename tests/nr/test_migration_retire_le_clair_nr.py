# -*- coding: utf-8 -*-
"""NR -- un secret migre et RELU identique au coffre ne reste pas en clair dans Nokido.env (owner 15/10).

Owner : « tu dois le faire toi systematiquement si present au coffre ». Contrat de
`tools/forge_migrate_env_secret.retirer_du_clair` (sur un faux fichier, valeurs factices) :
  1. la ligne `source=<valeur migree>` devient un commentaire SANS la valeur (nom, cible, date) ;
  2. toutes les autres lignes restent identiques A L'OCTET, y compris une ligne a l'encodage atypique ;
  3. une ligne commentee, ou portant une AUTRE valeur, n'est pas touchee ;
  4. rien a retirer -> fichier inchange ;
  5. creation du voisin temporaire REFUSEE (LaForgeTrusted, mesure 15/10) -> reecriture en place, relue,
     et aucun voisin temporaire laisse derriere (il porterait les autres secrets en clair).
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_migrate_env_secret as mig  # noqa: E402

VAL = "valeur-factice-0001"


def test_ligne_retiree_le_reste_intact_a_l_octet(tmp_path):
    env = tmp_path / "Nokido.env"
    contenu = (b"AUTRE_CLEF=garde\r\n"
               b"cloud.exemple_API_KEY=" + VAL.encode() + b"\r\n"
               b"# cloud.exemple_API_KEY=" + VAL.encode() + b"\r\n"
               b"cloud.exemple_API_KEY=une-autre-valeur\r\n"
               b"LATIN=caf\xe9\r\n")
    env.write_bytes(contenu)
    n = mig.retirer_du_clair(env, "cloud.exemple_API_KEY", VAL, "EXEMPLE_API_KEY")
    apres = env.read_bytes().split(b"\r\n")
    assert n == 1
    assert apres[0] == b"AUTRE_CLEF=garde" and apres[4] == b"LATIN=caf\xe9"
    assert apres[1].startswith(b"# cloud.exemple_API_KEY -> migre au coffre EXEMPLE_API_KEY le ")
    assert VAL.encode() not in apres[1]
    assert apres[2] == b"# cloud.exemple_API_KEY=" + VAL.encode()      # commentee : intacte
    assert apres[3] == b"cloud.exemple_API_KEY=une-autre-valeur"        # autre valeur : intacte


def test_rien_a_retirer_fichier_inchange(tmp_path):
    env = tmp_path / "Nokido.env"
    env.write_bytes(b"A=1\nB=2\n")
    assert mig.retirer_du_clair(env, "C", "3", "C_KEY") == 0
    assert env.read_bytes() == b"A=1\nB=2\n"


def test_creation_refusee_reecrit_en_place(tmp_path, monkeypatch):
    env = tmp_path / "Nokido.env"
    env.write_bytes(b"A=1\r\nS=" + VAL.encode() + b"\r\n")
    vrai = Path.write_bytes

    def refuse_le_voisin(self, data):
        if self.name.endswith(".env.tmp"):
            raise PermissionError(13, "Permission denied", str(self))
        return vrai(self, data)

    monkeypatch.setattr(Path, "write_bytes", refuse_le_voisin)
    assert mig.retirer_du_clair(env, "S", VAL, "S_KEY") == 1
    apres = env.read_bytes()
    assert VAL.encode() not in apres and apres.startswith(b"A=1\r\n# S -> migre au coffre S_KEY le ")
    assert not (tmp_path / "Nokido.env.tmp").exists()


def test_lire_source_ignore_les_commentees_par_defaut(tmp_path):
    env = tmp_path / "Nokido.env"
    env.write_text("# X=morte\nX=vive\n", encoding="utf-8")
    assert mig.lire_source(env, "X")[0] == "vive"
    env.write_text("# X=morte\n", encoding="utf-8")
    assert mig.lire_source(env, "X") == (None, "") and mig.lire_source(env, "X", commentee_ok=True)[0] == "morte"
