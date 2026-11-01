"""NR -- `forge_dev_mode arm` en console NON administrateur dit la vraie cause et l'etat du jeton (owner 21/10).

Owner, 21/10 ~23 h 50 : « il ne faut pas que ce soit bloque pour le mode dev ». Mesure : son `arm` en console normale a
rendu « un jeton PROTEGE subsiste et ce compte n'a pas autorite dessus » -- alors que le jeton avait 37 min (TTL 30 :
EXPIRE) et qu'en console ADMINISTRATEUR l'armement l'ecrase sans encombre. La vraie cause etait la console non admin
(l'armement exige un admin par construction : lui seul protege le jeton contre les comptes du bac a sable). Le message
faisait chercher une panne qui n'existait pas.

Contrats :
  1. sans droits admin, arm refuse en NOMMANT la cause : « console ADMINISTRATEUR » -- avant tout diagnostic de jeton ;
  2. le message dit l'etat du jeton lu par sa date (stat, sans lire son contenu) : EXPIRE depuis N min, ou ACTIF ;
  3. rien n'est ecrit (aucun residu).
"""
import os
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_dev_mode as D  # noqa: E402


def test_non_admin_cause_nommee_et_jeton_expire(tmp_path, monkeypatch):
    jeton = tmp_path / ".dev_mode_token"
    jeton.write_text("x", encoding="utf-8")
    vieux = time.time() - 37 * 60
    os.utime(jeton, (vieux, vieux))
    monkeypatch.setattr(D, "TOKEN_FILE", jeton)
    monkeypatch.setattr(D, "_est_admin", lambda: False)
    monkeypatch.setattr(D, "_diagnostic_jeton", lambda: "un jeton PROTEGE subsiste (ne doit pas etre la cause dite)")
    with pytest.raises(SystemExit) as e:
        D.arm()
    msg = str(e.value)
    assert "ADMINISTRATEUR" in msg
    assert "PROTEGE subsiste" not in msg
    assert "EXPIRE" in msg
    assert jeton.read_text(encoding="utf-8") == "x"


def test_non_admin_jeton_actif_dit_actif(tmp_path, monkeypatch):
    jeton = tmp_path / ".dev_mode_token"
    jeton.write_text("x", encoding="utf-8")
    monkeypatch.setattr(D, "TOKEN_FILE", jeton)
    monkeypatch.setattr(D, "_est_admin", lambda: False)
    with pytest.raises(SystemExit) as e:
        D.arm()
    assert "ACTIF" in str(e.value)
