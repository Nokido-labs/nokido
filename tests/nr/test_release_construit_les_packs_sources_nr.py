"""NR -- la release CONSTRUIT et VERIFIE chaque pack par source declare (etape 2 du pack, decisions owner 20/10).

Mesure du 20/10 : `forge_release_assets` ne construisait que le pack essentiel (`build_rag_pack`, natif). Les
composants `rag_pack_source` du manifeste (docsets, RFC, physiologie) n'avaient AUCUNE etape de construction, et
`verifier_lot` ne regardait que les composants des PLATEFORMES : une release serait sortie sans aucun d'eux, sans
erreur. Decisions owner : un pack par source = par licence ; tout telecharge par defaut.

Contrat :
  * `build_rag_packs_sources(out_dir, version, man, base)` construit en UN passage (exporter_sources) chaque composant
    `rag_pack_source` OBLIGATOIRE du pack knowledge, nomme par BUILDERS (`nokido_pack_<slug>_v<version>.tar`) ;
    un pack a 0 fragment REFUSE la release (SystemExit) : une source declaree et vide n'est pas livree en silence ;
  * `verifier_lot` exige chacun de ces tars dans le lot ET dans SHA256SUMS ;
  * `main` les construit par defaut ; `--skip-packs-sources` les saute (repetition).
"""
from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
PHYSIO = "github:openstax/osbooks-anatomy-physiology"
TEXTE = "Le systeme respiratoire assure les echanges gazeux ; les chemorecepteurs reglent la ventilation, section "


def _ra():
    spec = importlib.util.spec_from_file_location("release_packs_sources_nr", RACINE / "tools" / "forge_release_assets.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _vec(i):
    v = np.zeros(1024, dtype=np.float32)
    v[i] = 1.0
    return v.tobytes()


def _base(tmp_path, avec_flask=True):
    p = tmp_path / "rag.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, domain TEXT, text TEXT, "
                "embedding BLOB, active INTEGER)")
    lignes = [("p1", PHYSIO + "/modules/m1/index.cnxml", "physiologie", TEXTE + "un", _vec(1), 1)]
    if avec_flask:
        lignes.append(("f1", "docset:Flask#Quickstart", "reference",
                       "Flask est un micro-cadre web ecrit en Python, section un de la documentation", _vec(2), 1))
    con.executemany("INSERT INTO rag_chunks VALUES (?,?,?,?,?,?)", lignes)
    con.commit()
    con.close()
    return p


def _comp(cid, famille, domaine=None, licence="CC-BY-4.0", obligatoire=True):
    c = {"id": cid, "description": "x", "source": "construit", "construit": "rag_pack_source", "sha256": "au_build",
         "taille": "au_build", "licence": licence, "obligatoire": obligatoire, "famille": famille,
         "conditions": "attribution", "preuve": "https://exemple.org/licence"}
    if domaine:
        c["domaine"] = domaine
    return c


def _man(*comps):
    return {"ok": True, "plateformes": {}, "packs": {"knowledge": {"composants": list(comps), "composable": True}}}


def test_chaque_pack_source_obligatoire_est_construit(tmp_path):
    ra = _ra()
    man = _man(_comp("k-physio", PHYSIO, "physiologie"), _comp("k-flask", "docset:Flask", licence="BSD-3-Clause"),
               _comp("k-option", "docset:Django", obligatoire=False))
    tars = ra.build_rag_packs_sources(tmp_path / "lot", "9.9.9", man, base=_base(tmp_path))
    noms = sorted(Path(t).name for t in tars)
    assert noms == ["nokido_pack_docset-flask_v9.9.9.tar", "nokido_pack_github-openstax-osbooks-anatomy-physiology"
                    "_v9.9.9.tar"], noms


def test_un_pack_source_vide_refuse_la_release(tmp_path):
    ra = _ra()
    man = _man(_comp("k-physio", PHYSIO, "physiologie"), _comp("k-flask", "docset:Flask", licence="BSD-3-Clause"))
    with pytest.raises(SystemExit):
        ra.build_rag_packs_sources(tmp_path / "lot", "9.9.9", man, base=_base(tmp_path, avec_flask=False))


def test_le_lot_exige_les_packs_sources_et_leurs_sommes(tmp_path):
    ra = _ra()
    man = _man(_comp("k-physio", PHYSIO, "physiologie"))
    lot = tmp_path / "lot"
    lot.mkdir()
    (lot / "SHA256SUMS").write_text("", encoding="utf-8")
    v = ra.verifier_lot(lot, "9.9.9", man)
    assert not v["ok"] and any("k-physio" in e for e in v["erreurs"]), v
    tar = lot / "nokido_pack_github-openstax-osbooks-anatomy-physiology_v9.9.9.tar"
    tar.write_bytes(b"x")
    (lot / "SHA256SUMS").write_text("%s  %s\n" % (hashlib.sha256(b"x").hexdigest(), tar.name), encoding="utf-8")
    v = ra.verifier_lot(lot, "9.9.9", man)
    assert not any("k-physio" in e for e in v["erreurs"]), v["erreurs"]


def test_le_point_d_entree_construit_les_packs_sources_par_defaut(monkeypatch, tmp_path):
    ra = _ra()
    appels = []

    def _faux(nom):
        def f(out_dir, *a, **k):
            p = Path(out_dir) / nom
            p.write_bytes(b"x")
            return p
        return f

    monkeypatch.setattr(ra, "build_code_tarball", _faux("code.tar.gz"))
    monkeypatch.setattr(ra, "write_vendor_lock", lambda dest=None: (Path(dest).write_text("{}"), Path(dest))[1])
    monkeypatch.setattr(ra, "build_rag_pack", _faux("pack.npz"))
    monkeypatch.setattr(ra, "build_rag_packs_sources",
                        lambda out_dir, version, man, base=None: appels.append(version) or [])
    monkeypatch.setattr(ra, "verifier_lot", lambda *a, **k: {"ok": True, "erreurs": []})
    monkeypatch.setattr(ra, "print_upload_help", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["forge_release_assets.py", "--version", "9.9.9", "--out", str(tmp_path / "o")])
    assert ra.main() == 0 and appels == ["9.9.9"], appels
    appels.clear()
    monkeypatch.setattr(sys, "argv", ["forge_release_assets.py", "--version", "9.9.9", "--out", str(tmp_path / "o2"),
                                      "--skip-packs-sources"])
    assert ra.main() == 0 and appels == [], "repetition : packs par source sautes"


def test_une_repetition_sans_packs_sources_ne_les_exige_pas_au_lot(tmp_path):
    """Livraison GPTOSS 53f28d7f2 : le controle se taisait quand le manifeste n'etait pas passe EXPLICITEMENT -- un
    garde qui depend de la forme de l'appel ne garde rien. Il ne s'eteint que DIT (`packs_sources=False`)."""
    ra = _ra()
    man = _man(_comp("k-physio", PHYSIO, "physiologie"))
    lot = tmp_path / "lot"
    lot.mkdir()
    (lot / "SHA256SUMS").write_text("", encoding="utf-8")
    assert not any("k-physio" in e for e in ra.verifier_lot(lot, "9.9.9", man, packs_sources=False)["erreurs"])
