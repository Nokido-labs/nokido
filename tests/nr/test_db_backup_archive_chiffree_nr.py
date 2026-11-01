# -*- coding: utf-8 -*-
"""NR — la sauvegarde de embeddings.db sort en ARCHIVE CHIFFRÉE ; la copie en clair ne survit pas à l'opération.

__FORGE_COLOR__ = "immunitaire/guard : non-regression de l'archive chiffree des sauvegardes"

DÉCISION OWNER (21/10). Les sauvegardes du RAG (~50 Go) quittaient le volume chiffré V: en CLAIR (E:, disque externe).
Choix : copie cohérente transitoire sur E:, puis zstd + chiffrement par une clé DÉDIÉE du coffre, puis effacement
aussitôt de la copie en clair. Fernet (forge_encrypt) charge tout le message en mémoire : impossible à 50 Go. D'où
un flux par blocs AES-256-GCM, chaque bloc authentifié avec son index et un drapeau de fin dans les données
associées : un bloc tronqué, permuté ou retouché, ou une mauvaise clé, est REFUSÉ, jamais restauré à moitié.

Contrat (tools/forge_db_backup.py) :
  archiver_chiffre(src, dst, cle: bytes, level=9) -> dict   (src_bytes, dst_bytes, blocs, sha256_clair)
  restaurer_archive(src, dst, cle: bytes) -> dict           (octets, sha256_clair) ; ArchiveInvalide(ValueError) sinon
  cle_archive() -> bytes | None                             clé NOKIDO_BACKUP_KEY du coffre (32 octets, base64 urlsafe),
                                                            JAMAIS de clé dérivée du maître
  main --chiffrer : sans clé -> rc 4 AVANT toute copie ; sinon seule l'archive `*.nkbk` reste dans le dossier.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _zstd_present() -> bool:
    return any(importlib.util.find_spec(n) is not None for n in ("compression.zstd", "zstandard")) \
        if sys.version_info >= (3, 14) else importlib.util.find_spec("zstandard") is not None


pytestmark = [
    pytest.mark.skipif(importlib.util.find_spec("cryptography") is None, reason="cryptography absent"),
    pytest.mark.skipif(not _zstd_present(), reason="ni compression.zstd ni zstandard"),
]


def _mod(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "app"))
    spec = importlib.util.spec_from_file_location("forge_db_backup_nr", ROOT / "tools" / "forge_db_backup.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "forge_db_backup_nr", mod)
    spec.loader.exec_module(mod)
    return mod


CLE = bytes(range(32))
MARQUEUR = b"TEMOIN-EN-CLAIR-0123456789"


def _clair(tmp_path, taille=3 * 1024 * 1024 + 17) -> Path:
    p = tmp_path / "clair.db"
    bloc = (MARQUEUR + os.urandom(64)) * (taille // 90 + 1)
    p.write_bytes(bloc[:taille])
    return p


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_aller_retour_identique_et_rien_en_clair(monkeypatch, tmp_path):
    m = _mod(monkeypatch)
    src = _clair(tmp_path)
    arch = tmp_path / "a.db.zst.nkbk"
    r = m.archiver_chiffre(src, arch, CLE)
    assert r["sha256_clair"] == _sha(src) and r["blocs"] >= 1, r
    assert MARQUEUR not in arch.read_bytes(), "le contenu en clair se lit dans l'archive"
    out = tmp_path / "restaure.db"
    r2 = m.restaurer_archive(arch, out, CLE)
    assert _sha(out) == _sha(src) == r2["sha256_clair"]


def test_mauvaise_cle_refusee(monkeypatch, tmp_path):
    m = _mod(monkeypatch)
    arch = tmp_path / "a.nkbk"
    m.archiver_chiffre(_clair(tmp_path), arch, CLE)
    with pytest.raises(m.ArchiveInvalide):
        m.restaurer_archive(arch, tmp_path / "x.db", bytes(32))


def test_archive_tronquee_refusee(monkeypatch, tmp_path):
    m = _mod(monkeypatch)
    arch = tmp_path / "a.nkbk"
    m.archiver_chiffre(_clair(tmp_path, taille=12 * 1024 * 1024), arch, CLE)
    data = arch.read_bytes()
    arch.write_bytes(data[: len(data) // 2])
    with pytest.raises(m.ArchiveInvalide):
        m.restaurer_archive(arch, tmp_path / "x.db", CLE)


def test_octet_retouche_refuse(monkeypatch, tmp_path):
    m = _mod(monkeypatch)
    arch = tmp_path / "a.nkbk"
    m.archiver_chiffre(_clair(tmp_path), arch, CLE)
    data = bytearray(arch.read_bytes())
    data[len(data) // 2] ^= 0x01
    arch.write_bytes(bytes(data))
    with pytest.raises(m.ArchiveInvalide):
        m.restaurer_archive(arch, tmp_path / "x.db", CLE)


def _base(tmp_path) -> Path:
    db = tmp_path / "src" / "embeddings.db"
    db.parent.mkdir()
    c = sqlite3.connect(db)
    c.execute("create table t(x text)")
    c.executemany("insert into t values (?)", [(MARQUEUR.decode() + str(i),) for i in range(2000)])
    c.commit()
    c.close()
    return db


def test_sans_cle_refus_avant_toute_copie(monkeypatch, tmp_path):
    m = _mod(monkeypatch)
    monkeypatch.setattr(m, "DB", _base(tmp_path))
    monkeypatch.setattr(m, "cle_archive", lambda: None)
    appels = []
    monkeypatch.setattr(m, "online_backup", lambda *a, **k: appels.append(a))
    dest = tmp_path / "dest"
    monkeypatch.setattr(sys, "argv", ["forge_db_backup.py", "--dir", str(dest), "--chiffrer"])
    assert m.main() == 4
    assert not appels, "la copie en clair a ete faite alors que la cle manquait"


def test_chiffrer_ne_laisse_que_l_archive(monkeypatch, tmp_path):
    m = _mod(monkeypatch)
    db = _base(tmp_path)
    monkeypatch.setattr(m, "DB", db)
    monkeypatch.setattr(m, "cle_archive", lambda: CLE)
    dest = tmp_path / "dest"
    monkeypatch.setattr(sys, "argv", ["forge_db_backup.py", "--dir", str(dest), "--chiffrer"])
    assert m.main() == 0
    restes = sorted(p.name for p in dest.iterdir())
    assert len(restes) == 1 and restes[0].endswith(".nkbk"), restes
    out = tmp_path / "restaure.db"
    m.restaurer_archive(dest / restes[0], out, CLE)
    c = sqlite3.connect(out)
    assert c.execute("pragma integrity_check").fetchone()[0] == "ok"
    assert c.execute("select count(*) from t").fetchone()[0] == 2000
    c.close()


def test_cle_archive_lit_la_cle_dediee_et_rien_d_autre(monkeypatch):
    m = _mod(monkeypatch)
    vue = []
    valeur = base64.urlsafe_b64encode(CLE).decode()
    monkeypatch.setattr(m, "get_secret", lambda nom: (vue.append(nom), valeur if nom == "NOKIDO_BACKUP_KEY" else None)[1],
                        raising=False)
    assert m.cle_archive() == CLE
    assert vue == ["NOKIDO_BACKUP_KEY"], vue
    monkeypatch.setattr(m, "get_secret", lambda nom: None, raising=False)
    assert m.cle_archive() is None
