"""NR — chaque fichier tiers servi par le portail est déclaré, épinglé et licencié.

Owner 2026-09-29 : « pourquoi un projet comme odysseus cite les licences des produits le
constituant ? ». Mesure du jour : 22 fichiers tiers dans `app/web_hub/static` (14 JS, une
feuille de style, 7 polices), `vendor.lock` n'en déclarait que 2, sans licence ni version ;
aucun texte de licence n'était livré, alors que MIT, ISC, BSD-3 et Apache-2.0 exigent la
reproduction de leur notice. Le garde de licences ne voyait que les paquets Python.

Ce que ces tests verrouillent :
- le dépôt RÉEL est conforme (`--embarques` rend 0) et `vendor.lock` concorde avec VENDORED ;
- un fichier non déclaré, un bundle remplacé sans lock, un texte absent, une licence
  interdite sont REFUSÉS et nommés ;
- la licence jugée est l'identifiant SPDX déclaré, jamais le texte (le BSD-3 de Vega porte
  « All rights reserved », qui est dans DENY).
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_license_guard as G  # noqa: E402
import forge_release_assets as RA  # noqa: E402

S = "app/web_hub/static/"


def _arbre(tmp_path, fichiers, entrees, propres=(S + "nokido*.js",)):
    """Faux depot : fichiers {chemin: octets}, vendor.lock avec `entrees` (sha calcules)."""
    for rel, octets in fichiers.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(octets)
    vendored = []
    for e in entrees:
        e = dict(e)
        fp = tmp_path / e["path"]
        e.setdefault("sha256", hashlib.sha256(fp.read_bytes()).hexdigest() if fp.exists() else "0")
        vendored.append(e)
    (tmp_path / "vendor.lock").write_text(json.dumps({"vendored": vendored, "propres": list(propres)}),
                                          encoding="utf-8")
    return tmp_path


def _base(tmp_path, licence="MIT", texte=b"MIT License\n", extra=None):
    fichiers = {S + "lib.min.js": b"/*! lib */", S + "nokido.js": b"// maison",
                "licenses/lib/LICENSE": texte}
    fichiers.update(extra or {})
    return _arbre(tmp_path, fichiers, [{"path": S + "lib.min.js", "composant": "lib", "licence": licence,
                                        "licence_texte": ["licenses/lib/LICENSE"]}])


def test_un_arbre_declare_et_licencie_passe(tmp_path, capsys):
    assert G.verifier_embarques(_base(tmp_path)) == 0
    assert "0 à corriger" in capsys.readouterr().out


def test_un_fichier_tiers_non_declare_est_refuse(tmp_path, capsys):
    racine = _base(tmp_path, extra={S + "intrus.min.js": b"/*! intrus */"})
    assert G.verifier_embarques(racine) == 1
    assert "NON DÉCLARÉ" in capsys.readouterr().out


def test_un_bundle_remplace_sans_lock_est_refuse(tmp_path, capsys):
    racine = _base(tmp_path)
    (racine / S / "lib.min.js").write_bytes(b"/*! lib v2 */")
    assert G.verifier_embarques(racine) == 1
    assert "REMPLACÉ SANS LOCK" in capsys.readouterr().out


def test_un_texte_de_licence_absent_est_refuse(tmp_path, capsys):
    racine = _base(tmp_path)
    (racine / "licenses/lib/LICENSE").unlink()
    assert G.verifier_embarques(racine) == 1
    assert "TEXTE ABSENT" in capsys.readouterr().out


def test_une_licence_interdite_est_refusee(tmp_path, capsys):
    assert G.verifier_embarques(_base(tmp_path, licence="SSPL-1.0")) == 1
    assert "LICENCE DENY" in capsys.readouterr().out


def test_la_licence_jugee_est_le_spdx_pas_le_texte(tmp_path):
    texte = b"Copyright (c) 2015, Lab\nAll rights reserved.\n\nRedistribution and use ...\n"
    assert G.verifier_embarques(_base(tmp_path, licence="BSD-3-Clause", texte=texte)) == 0


def test_les_polices_ofl_sont_acceptees():
    assert G.classify("inter", "ofl-1.1") == "ok"


def test_un_lock_illisible_n_est_pas_un_succes(tmp_path):
    assert G.verifier_embarques(tmp_path) == 1


def test_le_point_d_entree_embarques(tmp_path, monkeypatch):
    """Le chemin reel : `main()` avec le drapeau CLI, pas seulement la fonction."""
    monkeypatch.setattr(G, "ROOT", _base(tmp_path))
    monkeypatch.setattr(sys, "argv", ["forge_license_guard.py", "--embarques"])
    assert G.main() == 0


def test_vendor_lock_concorde_avec_VENDORED():
    """Le lock versionne est celui que VENDORED produit : ni entree oubliee, ni licence
    divergente (sinon regenerer `forge_release_assets.py --vendor-lock-only`)."""
    lock = json.loads((ROOT / "vendor.lock").read_text(encoding="utf-8"))
    par_chemin = {e["path"]: e for e in lock["vendored"]}
    assert set(par_chemin) == set(RA.VENDORED)
    for rel, meta in RA.VENDORED.items():
        for cle in ("composant", "version", "licence", "source", "licence_texte"):
            assert par_chemin[rel].get(cle) == meta[cle], (rel, cle)
    assert lock.get("propres") == list(RA.PROPRES_STATIC)


def test_le_depot_reel_est_conforme(capsys):
    rc = G.verifier_embarques(ROOT)
    assert rc == 0, capsys.readouterr().out
