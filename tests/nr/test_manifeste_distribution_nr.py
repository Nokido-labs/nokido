"""NR -- manifeste de distribution : schema versionne, validateur FAIL-CLOSED, lot verifie.

Chantier owner « installation complete par un debutant en une commande » (P0, 2026-10-02),
mission distribution-manifeste. Ce NR fige :
  * le manifeste LIVRE est valide, et les packs non prouvables ne se composent pas ;
  * un manifeste invalide est REFUSE en entier (schema, champ, somme, source, orphelin...) ;
  * une somme manquante est un refus -- y compris pour un composant construit, au lot ;
  * aucun chemin absolu dans le manifeste, aucun chemin du CHECKOUT dans un artefact ;
  * un manifeste refuse empeche la construction (rien n'est archive).
"""
from __future__ import annotations

import importlib.util
import io
import json
import shutil
import sys
import tarfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("forge_release_assets_nr",
                                                  RACINE / "tools" / "forge_release_assets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fra = _module()


@pytest.fixture
def copie(tmp_path):
    d = tmp_path / "distribution"
    shutil.copytree(RACINE / "distribution", d)
    return d


def _editer(fichier: Path, avant: str, apres: str, compte: int = 1):
    t = fichier.read_text(encoding="utf-8")
    assert avant in t, avant
    fichier.write_text(t.replace(avant, apres, compte), encoding="utf-8")


def _refus(copie, motif):
    r = fra.valider_manifeste(copie, RACINE)
    assert r["ok"] is False, "aurait du etre REFUSE"
    assert any(motif in e for e in r["erreurs"]), r["erreurs"]
    return r


# ── le manifeste livre ────────────────────────────────────────────────────────────────
def test_le_manifeste_livre_est_valide_et_honnete():
    r = fra.valider_manifeste()
    assert r["ok"] is True, r["erreurs"]
    assert set(r["plateformes"]) == {"windows-x64", "linux-x64"}
    assert r["packs"]["knowledge"]["composable"] and r["packs"]["ml"]["composable"]
    # ce qu'on ne sait pas prouver ne se compose pas
    assert not r["packs"]["local-llm"]["composable"] and not r["packs"]["netcfg"]["composable"]


# ── fail-closed : chaque defaut refuse TOUT le manifeste ──────────────────────────────
def test_schema_inconnu(copie):
    _editer(copie / "manifest.toml", "version_schema = 1", "version_schema = 2")
    _refus(copie, "inconnu")


def test_toml_illisible(copie):
    (copie / "packs" / "ml.toml").write_text("statut = \n", encoding="utf-8")
    _refus(copie, "illisible")


@pytest.mark.parametrize("cle", ["sha256", "taille", "licence", "obligatoire"])
def test_champ_requis_manquant(copie, cle):
    f = copie / "packs" / "ml.toml"
    lignes = [l for l in f.read_text(encoding="utf-8").splitlines() if not l.startswith(cle + " =")]
    f.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    _refus(copie, cle)


def test_somme_manquante_sur_une_url(copie):
    (copie / "packs" / "ml.toml").write_text((copie / "packs" / "ml.toml").read_text(
        encoding="utf-8") + '''
[[composant]]
id = "roue"
source = "url"
url = "https://exemple.invalid/roue.whl"
sha256 = ""
taille = 10
licence = "MIT"
obligatoire = false
''', encoding="utf-8")
    _refus(copie, "sha256")


def test_un_construit_ne_triche_pas_sur_la_somme(copie):
    _editer(copie / "platforms" / "linux-x64.toml", 'sha256 = "au_build"', 'sha256 = "%s"' % ("a" * 64))
    _refus(copie, "au_build")


def test_source_cle_constructeur_hors_liste_blanche(copie):
    _editer(copie / "packs" / "ml.toml", 'source = "depot"', 'source = "ftp"')
    _refus(copie, "liste blanche")
    _editer(copie / "packs" / "ml.toml", 'source = "ftp"', 'source = "depot"')
    _editer(copie / "packs" / "ml.toml", 'obligatoire = true', 'obligatoire = true\ncomplement = 1')
    _refus(copie, "hors schema")


def test_fichier_orphelin_et_prerequis_inconnu(copie):
    shutil.copy(copie / "packs" / "ml.toml", copie / "packs" / "fantome.toml")
    _refus(copie, "non declare")
    (copie / "packs" / "fantome.toml").unlink()
    _editer(copie / "platforms" / "linux-x64.toml", '"netcfg_agent"]', '"netcfg_agent", "kubernetes"]')
    _refus(copie, "kubernetes")


def test_pack_pret_sans_composant_ou_a_epingler_muet(copie):
    _editer(copie / "packs" / "local-llm.toml", 'statut = "A_EPINGLER"', 'statut = "PRET"')
    _refus(copie, "PRET")


def test_fichier_de_depot_modifie(copie, tmp_path):
    racine = tmp_path / "racine"
    racine.mkdir()
    for rel in ("install.sh", "install.ps1", "requirements.txt", "environment.yml", "LICENSE",
                "NOTICE", "requirements-ml.txt"):
        shutil.copy(RACINE / rel, racine / rel)
    assert fra.valider_manifeste(copie, racine)["ok"] is True
    (racine / "install.sh").write_text("echo pirate\n", encoding="utf-8")
    r = fra.valider_manifeste(copie, racine)
    assert r["ok"] is False and any("install.sh a change" in e for e in r["erreurs"])
    # CRLF n'est PAS un changement : la somme porte sur le texte normalise LF
    shutil.copy(RACINE / "install.sh", racine / "install.sh")
    (racine / "LICENSE").write_bytes((RACINE / "LICENSE").read_bytes().replace(b"\n", b"\r\n"))
    assert fra.valider_manifeste(copie, racine)["ok"] is True


# ── aucun chemin absolu, aucun chemin du checkout ─────────────────────────────────────
@pytest.mark.parametrize("chemin", ["C:\\\\Users\\\\owner\\\\nokido\\\\install.sh", "C:/tmp/x",
                                    "/home/user/nokido/install.sh", "\\\\\\\\serveur\\\\partage"])
def test_chemin_absolu_interdit_dans_le_manifeste(copie, chemin):
    _editer(copie / "packs" / "ml.toml", 'description = "', 'description = "voir %s ' % chemin)
    _refus(copie, "chemin absolu")


def test_chemin_de_depot_absolu_ou_remontant(copie):
    _editer(copie / "packs" / "ml.toml", 'chemin = "requirements-ml.txt"', 'chemin = "../secret.txt"')
    _refus(copie, "relatif")


def _lot(tmp_path, version="9.9.9"):
    lot = tmp_path / "lot"
    lot.mkdir()
    (lot / ("nokido-%s-src.tar.gz" % version)).write_bytes(_tar({"nokido-9.9.9/README.md": b"x"}))
    (lot / "vendor.lock").write_text('{"vendored": []}\n', encoding="utf-8")
    sums = "".join("%s  %s\n" % (fra.sha256_file(f), f.name) for f in sorted(lot.iterdir()))
    (lot / "SHA256SUMS").write_text(sums, encoding="utf-8")
    return lot


def _tar(membres: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for nom, data in membres.items():
            ti = tarfile.TarInfo(nom)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def test_lot_conforme(tmp_path):
    assert fra.verifier_lot(_lot(tmp_path), "9.9.9")["ok"] is True


def test_lot_somme_construite_manquante(tmp_path):
    lot = _lot(tmp_path)
    (lot / "SHA256SUMS").write_text("", encoding="utf-8")
    r = fra.verifier_lot(lot, "9.9.9")
    assert r["ok"] is False and any("SHA256SUMS" in e for e in r["erreurs"])


def test_lot_porte_le_chemin_du_checkout(tmp_path):
    lot = _lot(tmp_path)
    (lot / "RELEASE_MANIFEST.json").write_text(json.dumps({"racine": str(RACINE)}), encoding="utf-8")
    r = fra.verifier_lot(lot, "9.9.9")
    assert r["ok"] is False and any("RELEASE_MANIFEST.json" in e for e in r["erreurs"])


def test_archive_dont_un_membre_porte_le_checkout(tmp_path):
    lot = _lot(tmp_path)
    nom = "nokido-9.9.9-src.tar.gz"
    (lot / nom).write_bytes(_tar({RACINE.as_posix().lstrip("/") + "/fuite.txt": b"x"}))
    sums = "".join("%s  %s\n" % (fra.sha256_file(f), f.name) for f in sorted(lot.iterdir())
                   if f.name != "SHA256SUMS")
    (lot / "SHA256SUMS").write_text(sums, encoding="utf-8")
    r = fra.verifier_lot(lot, "9.9.9")
    assert r["ok"] is False and any(nom in e for e in r["erreurs"])


# ── un manifeste refuse empeche la construction ───────────────────────────────────────
def test_manifeste_refuse_aucune_construction(copie, monkeypatch, tmp_path):
    _editer(copie / "manifest.toml", "version_schema = 1", "version_schema = 7")
    monkeypatch.setattr(fra, "DISTRIBUTION", copie)
    construits = []
    monkeypatch.setattr(fra, "build_code_tarball", lambda *a, **k: construits.append(a))
    monkeypatch.setattr(sys, "argv", ["forge_release_assets.py", "--skip-pack",
                                      "--out", str(tmp_path / "out")])
    assert fra.main() == 1 and construits == []
    monkeypatch.setattr(sys, "argv", ["forge_release_assets.py", "--verifier-manifeste"])
    assert fra.main() == 1


# ── le scellement ne touche que les sources depot ─────────────────────────────────────
def test_sceller_recalcule_les_depots_et_garde_le_reste(copie):
    f = copie / "packs" / "ml.toml"
    _editer(f, "taille = ", "taille = 1 # ")    # taille fausse : doit etre resommee
    avant = f.read_text(encoding="utf-8")
    assert fra.valider_manifeste(copie, RACINE)["ok"] is False
    r = fra.sceller_manifeste(copie, RACINE)
    assert any("requirements-ml.txt taille" in c for c in r["changes"])
    apres = f.read_text(encoding="utf-8")
    assert apres.splitlines()[0] == avant.splitlines()[0]      # commentaires conserves
    assert fra.valider_manifeste(copie, RACINE)["ok"] is True
