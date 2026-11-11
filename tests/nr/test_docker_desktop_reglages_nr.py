"""NR -- Nokido regle Docker Desktop (owner 2026-11-10 : « tu dois etre en capacite de faire tous les reglages dans
docker desktop via le lien mcp » ; choix « ACL pour le hub » : LaForgeTrusted:(M) sur settings-store.json, cmd-5ae504fb4fe5).

Mesure : %APPDATA%\\Docker\\settings-store.json, 24 cles ; illisible des comptes Nokido avant l'ACL. Contrats :
  1. lecture : valeurs des cles de la liste blanche, les autres MASQUEES (default-deny), cles inconnues nommees ;
  2. ecriture : cle hors liste = PARK sans ecriture ; type impose par la liste (« true »/« false » -> bool) ;
  3. sauvegarde AVANT ecriture, hors du dossier Docker (seul le fichier est inscriptible) ; autres cles intactes ;
  4. meme valeur = rien n'est ecrit ; fichier illisible = ILLISIBLE, jamais « absent » ;
  5. le redemarrage de Desktop est DIT requis (l'effet n'est pas atteint par l'ecriture seule).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import forge_docker_agent as D  # noqa: E402

REEL = {"AutoStart": False, "EnableDockerAI": True, "UseResourceSaver": False, "LicenseTermsVersion": 2,
        "IntegratedWslDistros": [], "CleInconnue": "x"}


def _fichier(tmp_path):
    f = tmp_path / "settings-store.json"
    f.write_text(json.dumps(REEL), encoding="utf-8")
    return f


def test_profil_owner_derive_comme_conv_indexer(monkeypatch):
    # trusted_script reel : « ...\Script python IA\AppData\Roaming\Docker\settings-store.json » -- un cran de moins
    import importlib
    monkeypatch.delenv("LAFORGE_OWNER_HOME", raising=False)
    m = importlib.reload(D)
    assert m.SETTINGS_DESKTOP == ROOT.parent.parent / "AppData" / "Roaming" / "Docker" / "settings-store.json"


def test_lecture_liste_blanche_et_masque(tmp_path):
    r = D.desktop_reglages_lire(_fichier(tmp_path))
    assert r["etat"] == "LU"
    assert r["reglages"]["EnableDockerAI"] is True and r["reglages"]["UseResourceSaver"] is False
    assert r["reglages"]["CleInconnue"] == "<masque>" and "CleInconnue" in r["cles_inconnues"]
    assert D.desktop_reglages_lire(tmp_path / "absent.json")["etat"] == "ILLISIBLE"


def test_ecriture_typee_sauvegardee_et_autres_cles_intactes(tmp_path):
    f, sauv = _fichier(tmp_path), tmp_path / "sauvegardes"
    r = D.desktop_reglage_ecrire("UseResourceSaver", "true", f, sauvegardes=sauv)
    assert r["verdict"] == "ECRIT" and r["avant"] is False and r["apres"] is True and r["redemarrage_requis"]
    apres = json.loads(f.read_text(encoding="utf-8"))
    assert apres["UseResourceSaver"] is True and apres["CleInconnue"] == "x" and apres["LicenseTermsVersion"] == 2
    assert len(list(sauv.glob("settings-store.*.json"))) == 1
    assert json.loads(next(sauv.glob("*.json")).read_text(encoding="utf-8"))["UseResourceSaver"] is False


def test_type_reel_different_du_type_declare_refuse(tmp_path, monkeypatch):
    # lecture reelle du 10/11 : DisableHardwareAcceleration = "always" (chaine) -- l'ecrire en booleen casserait Desktop
    f = tmp_path / "settings-store.json"
    f.write_text(json.dumps({"DisableHardwareAcceleration": "always", "AutoStart": "oui"}), encoding="utf-8")
    assert "DisableHardwareAcceleration" not in D.DESKTOP_ECRITURE
    r = D.desktop_reglage_ecrire("AutoStart", "true", f, sauvegardes=tmp_path / "s")
    assert r["verdict"] == "REFUS_TYPE" and "str" in r["motif"]


def test_refus_hors_liste_type_faux_et_idempotence(tmp_path):
    f, sauv = _fichier(tmp_path), tmp_path / "sauvegardes"
    avant = f.read_text(encoding="utf-8")
    assert D.desktop_reglage_ecrire("LicenseTermsVersion", "3", f, sauvegardes=sauv)["verdict"] == "PARK"
    assert D.desktop_reglage_ecrire("CleInconnue", "y", f, sauvegardes=sauv)["verdict"] == "PARK"
    assert D.desktop_reglage_ecrire("EnableDockerAI", "peut-etre", f, sauvegardes=sauv)["verdict"] == "REFUS_TYPE"
    assert f.read_text(encoding="utf-8") == avant
    assert D.desktop_reglage_ecrire("EnableDockerAI", "true", f, sauvegardes=sauv)["verdict"] == "INCHANGE"
    assert not sauv.exists() or not list(sauv.glob("*.json"))
