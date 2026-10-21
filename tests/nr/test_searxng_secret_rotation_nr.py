"""NR -- la secret_key de SearXNG se fait tourner par le keeper, sans jamais s'afficher (owner 18/10 : « oui
systematiquement si ca fuite tu fais tourner ! »).

Fuite du 18/10 : sandbox/searxng/settings.yml lu en entier dans une session agent (cle en clair dans le contexte).
Le keeper ne savait que GENERER la cle si le fichier etait absent ; un script jetable de rotation a ete refuse par le
garde d'infra (« gestion d'infra par script jetable refusee ») -- la rotation vit donc DANS le keeper.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import forge_searxng_keeper as k  # noqa: E402

ANCIENNE = "a" * 64
MODELE = ('use_default_settings: true\nserver:\n  secret_key: "%s"\n  limiter: false\nsearch:\n  formats:\n'
          "    - json\n")


def test_rotation_change_la_cle_garde_le_reste_et_ne_l_affiche_pas(tmp_path, monkeypatch, capsys):
    f = tmp_path / "settings.yml"
    f.write_text(MODELE % ANCIENNE, encoding="utf-8")
    monkeypatch.setattr(k, "SETTINGS_FILE", f)
    r = k.rotate_secret()
    neuf = re.search(r'secret_key:\s*"([0-9a-f]+)"', f.read_text(encoding="utf-8")).group(1)
    assert r["ok"] is True and len(neuf) == 64 and neuf != ANCIENNE
    assert f.read_text(encoding="utf-8").replace(neuf, ANCIENNE) == MODELE % ANCIENNE, "seule la cle change"
    sortie = capsys.readouterr()
    assert neuf not in sortie.out + sortie.err and neuf not in str(r) and ANCIENNE not in str(r)


def test_rotation_sans_cle_reconnue_ne_touche_a_rien(tmp_path, monkeypatch):
    f = tmp_path / "settings.yml"
    f.write_text("server:\n  limiter: false\n", encoding="utf-8")
    monkeypatch.setattr(k, "SETTINGS_FILE", f)
    assert k.rotate_secret()["ok"] is False
    assert f.read_text(encoding="utf-8") == "server:\n  limiter: false\n"
