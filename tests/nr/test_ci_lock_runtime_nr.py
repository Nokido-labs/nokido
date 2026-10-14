# -*- coding: utf-8 -*-
"""NR -- `forge_ci_lock --runtime` fige TOUT le runtime certifiant, et ne ment pas sur les doublons.

2026-10-13 : le lock du runtime, ecrit a la main le 22/05, ne decrivait plus l'env (18 versions differentes,
104 paquets absents, ResolutionImpossible dans un env neuf) ; la CI disait deja « NON CERTIFIANT ». L'env
portait 14 paires de dist-info (restes de montees) : pip freeze lisait l'ANCIENNE version, le code charge
etait la RECENTE. Ce que ces tests tiennent :
- une installation editable (PEP 610) est EXCLUE et dite, sans chemin de la machine (le lock part au public) ;
- un doublon se tranche par PREUVE : la copie dont le RECORD correspond au disque ;
- sans copie prouvee, AUCUN lock ne s'ecrit (rc 2) -- un lock au hasard serait pire qu'aucun.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("forge_ci_lock_runtime_nr", ROOT / "tools" / "forge_ci_lock.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Dist:
    def __init__(self, nom, version, base, fichiers=None, direct=None, record=None):
        self.metadata = {"Name": nom}
        self.version = version
        self._base, self._direct, self._record = Path(base), direct, record

    def read_text(self, nom):
        if nom == "direct_url.json":
            return json.dumps(self._direct) if self._direct else None
        if nom == "RECORD":
            return self._record
        return None

    def locate_file(self, _p):
        return self._base


def _ligne_record(rel, contenu: bytes) -> str:
    dig = base64.urlsafe_b64encode(hashlib.sha256(contenu).digest()).rstrip(b"=").decode()
    return "%s,sha256=%s,%d" % (rel, dig, len(contenu))


def test_une_installation_editable_est_exclue_sans_chemin_machine(tmp_path):
    m = _module()
    d = _Dist("forge_bm25", "0.1", tmp_path, direct={"url": "file:///C:/Users/x/rust_ext", "dir_info": {"editable": True}})
    r = m.runtime([d, _Dist("requests", "2.33.1", tmp_path)])
    assert "forge-bm25" not in r["paquets"] and r["paquets"]["requests"] == "2.33.1"
    texte = m.rendu_runtime(r, str(tmp_path / "envs" / "laforge_py314" / "python.exe"))
    assert "EXCLU forge-bm25" in texte and "C:/Users" not in texte and str(tmp_path) not in texte


def test_un_doublon_se_tranche_par_le_record_conforme_au_disque(tmp_path):
    m = _module()
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_bytes(b"VERSION = 2\n")
    vieux = _Dist("pkg", "1.0", tmp_path, record=_ligne_record("pkg/__init__.py", b"VERSION = 1\n"))
    neuf = _Dist("pkg", "2.0", tmp_path, record=_ligne_record("pkg/__init__.py", b"VERSION = 2\n"))
    r = m.runtime([vieux, neuf])
    assert r["paquets"]["pkg"] == "2.0", "la version du lock doit etre celle du code REELLEMENT installe"
    assert r["doublons"] == [("pkg", "2.0", ["1.0"])] and not r["douteux"]
    assert "DOUBLON pkg : 2.0 garde" in m.rendu_runtime(r, "x/laforge_py314/python.exe")


def test_sans_copie_prouvee_aucun_lock_ne_s_ecrit(tmp_path, monkeypatch):
    m = _module()
    r = m.runtime([_Dist("pkg", "1.0", tmp_path), _Dist("pkg", "2.0", tmp_path)])  # RECORD illisibles
    assert r["douteux"] and "pkg" not in r["paquets"]
    monkeypatch.setattr(m, "runtime", lambda dists=None: r)
    cible = tmp_path / "lock.txt"
    assert m._main(["--runtime", "--ecrire", "--fichier", str(cible)]) == 2
    assert not cible.exists(), "un lock ecrit sur un doublon douteux mentirait sur l'env"
