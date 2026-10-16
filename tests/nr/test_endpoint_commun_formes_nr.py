"""NR -- le catalogue commun des sondes lit toutes les formes de /models (defaut consigne le 15/10 :
endpoint_commun_catalogue_mono_format ; Cohere rendait « 200 -- 0 modele » depuis le module commun alors que la
matrice l'avait corrige pour elle seule le 03/09)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_endpoint_commun as ec  # noqa: E402


def test_les_formes_connues_sont_toutes_lues():
    assert [m["id"] for m in ec.modeles_de({"data": [{"id": "gpt-oss-20b"}]})] == ["gpt-oss-20b"]
    assert [m["id"] for m in ec.modeles_de({"models": [{"name": "command-r-08-2024"}]})] == ["command-r-08-2024"]
    assert [m["id"] for m in ec.modeles_de({"results": [{"model": "m1"}], "data": "pas une liste"})] == ["m1"]
    assert [m["id"] for m in ec.modeles_de([{"id": "a"}, "b"])] == ["a", "b"]
    assert ec.modeles_de({"models": [{"name": "x", "context_length": 8192}]})[0]["context_length"] == 8192


def test_une_forme_inconnue_rend_vide_sans_planter():
    assert ec.modeles_de({"autre": [1, 2]}) == [] and ec.modeles_de(None) == [] and ec.modeles_de("texte") == []
    assert ec.modeles_de({"data": [{"sans_identifiant": 1}, 3]}) == []


def test_le_catalogue_passe_par_le_parseur_multi_formes(monkeypatch):
    monkeypatch.setattr(ec, "lire", lambda url, cle="", charge=None, timeout=0, taille_max=0:
                        (200, '{"models": [{"name": "command-r"}]}', {"x-ratelimit-remaining": "9"}))
    code, modeles, entetes = ec.catalogue("https://api.exemple/v1", "k")
    assert code == 200 and [m["id"] for m in modeles] == ["command-r"] and entetes["x-ratelimit-remaining"] == "9"
    assert ec.utiles(modeles) == modeles
