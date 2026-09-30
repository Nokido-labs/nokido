"""NR -- sauvegarde : cle hors des arguments, cible fixe E:, meme volume ecarte (2026-09-24).

Decision owner : « sauvegarde sur E en attendant la reparation du disque (pb de cable) ».
Mesure en passant : `encrypt_file_7z` passait `-p<cle>` a 7z.exe -- la cle de TOUTES les
sauvegardes lisible dans la liste des processus pendant l'export (~45 Go). Ce NR fige :
  - la cle ne figure dans AUCUN argument de processus (chiffrement en processus, py7zr) ;
  - sans py7zr : REFUS (jamais de repli qui remettrait la cle en argument) ;
  - avec py7zr : l'archive se relit avec la cle, pas sans ;
  - cible fixe : place controlee, source du meme volume ecartee et DITE.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))


@pytest.fixture()
def bk(monkeypatch):
    # Import sans effet de bord disque : le module ouvre un FileHandler a l'import.
    monkeypatch.setattr(logging, "FileHandler", lambda *a, **k: logging.NullHandler())
    sys.modules.pop("forge_backup_hotswap", None)
    import forge_backup_hotswap as m  # noqa: PLC0415
    return m


def test_un_journal_refuse_ne_tue_pas_la_sauvegarde(monkeypatch):
    """Mesure du 24/09 : PermissionError sur logs/hotswap_backup/*.log A L'IMPORT (compte des
    jobs) -> sauvegarde morte avant toute ecriture. Le module doit s'importer quand meme."""
    def _refuse(*a, **k):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(logging, "FileHandler", _refuse)
    logging.getLogger("Nokido.HotswapBackup").handlers.clear()
    sys.modules.pop("forge_backup_hotswap", None)
    import forge_backup_hotswap as m  # noqa: PLC0415
    assert any(isinstance(h, logging.StreamHandler) for h in m.logger.handlers)
    logging.getLogger("Nokido.HotswapBackup").handlers.clear()


def test_la_cle_n_apparait_dans_aucun_argument_de_processus(bk):
    import inspect
    src = inspect.getsource(bk.encrypt_file_7z)
    assert "_run(" not in src and "SEVENZIP" not in src and '"-p' not in src and "f\"-p" not in src


def test_chiffrement_en_processus_ou_refus(bk, tmp_path):
    clair = tmp_path / "base.db"
    clair.write_bytes(b"SQLite format 3\x00" + b"x" * 4096)
    dest = tmp_path / "base.db.7z"
    r = bk.encrypt_file_7z(clair, dest, "cle-de-test-NR")
    if importlib.util.find_spec("py7zr") is None:
        assert r["ok"] is False and "argument" in r["reason"] and not dest.exists()
        return
    assert r["ok"] is True and dest.exists()
    assert b"SQLite format 3" not in dest.read_bytes(), "contenu en clair dans l'archive"
    import py7zr  # noqa: PLC0415
    with py7zr.SevenZipFile(dest, "r", password="cle-de-test-NR") as z:
        lu = z.readall()["base.db"].read()
    assert lu == clair.read_bytes()
    with pytest.raises(Exception):
        with py7zr.SevenZipFile(dest, "r", password="mauvaise") as z:
            z.readall()


def test_cible_fixe_la_preparation_est_sur_la_cible_jamais_sur_c(bk, monkeypatch, tmp_path):
    """Ordre owner du 24/09 : « la sauvegarde doit etre sur E ! pas sur C ! ». Un premier essai
    avait pose 6,4 Go d'export EN CLAIR sous sandbox/hotswap_staging (C:)."""
    src = tmp_path / "src" / "base.db"
    src.parent.mkdir()
    src.write_bytes(b"x")
    cible = tmp_path / "cible"
    monkeypatch.setattr(bk, "SOURCES", {"base": {"kind": "sqlite", "path": src, "dest_subdir": "rag"}})
    monkeypatch.setattr(bk, "_controle_cible_fixe", lambda r: None)
    monkeypatch.setattr(bk, "_lecteur", lambda p: "X:" if "src" in str(p) else "E:")
    monkeypatch.setattr(bk, "STAGING_DIR", tmp_path / "C_staging_interdit")
    monkeypatch.setattr(bk, "emit_event", lambda *a, **k: None)
    vus = []

    def _export(s, d):
        vus.append(Path(d))
        Path(d).write_bytes(b"clair")
        return {"ok": True}

    monkeypatch.setattr(bk, "export_sqlite", _export)
    assert bk.cmd_backup(cible_fixe=str(cible)) == 0
    assert vus and all(cible in p.parents for p in vus), vus
    assert not (tmp_path / "C_staging_interdit").exists(), "la zone de C: a ete utilisee"


def test_cible_fixe_refuse_sans_place(bk, monkeypatch, tmp_path):
    # HERMETIQUE (2026-09-26). Le besoin se calcule sur la taille des bases de SOURCES : le test comptait sur la
    # VRAIE base (45 Go). Dans le worktree detache de la CI elle n'existe pas -> besoin 0 -> jamais « place
    # insuffisante » (rouge en CI de reference 26d1f6b0c, vert dans l'arbre partage). Il porte sa propre base.
    base = tmp_path / "base.db"
    base.write_bytes(b"x" * 2_000_000)
    monkeypatch.setattr(bk, "SOURCES", {"base": {"kind": "sqlite", "path": base, "dest_subdir": "b"}})

    class U:
        free = 1_000_000
    monkeypatch.setattr(bk.shutil, "disk_usage", lambda p: U())
    motif = bk._controle_cible_fixe(Path(str(tmp_path)))
    assert motif and "place insuffisante" in motif


def test_meme_volume_que_la_cible_est_ecarte_et_dit(bk, monkeypatch, tmp_path):
    src = tmp_path / "donnees"
    src.mkdir()
    monkeypatch.setattr(bk, "SOURCES", {"arbre": {"kind": "tree", "path": src, "dest_subdir": "a"}})
    monkeypatch.setattr(bk, "_controle_cible_fixe", lambda r: None)
    monkeypatch.setattr(bk, "STAGING_DIR", tmp_path / "staging")
    monkeypatch.setattr(bk, "emit_event", lambda *a, **k: None)
    copies = []
    monkeypatch.setattr(bk, "copy_tree", lambda s, d: copies.append(s) or {"ok": True})
    rc = bk.cmd_backup(cible_fixe=str(tmp_path / "cible"))
    assert rc == 0 and copies == [], "une source du MEME volume a ete copiee et comptee"
    manifeste = next((tmp_path / "cible").glob("gen_*/manifest.json")).read_text(encoding="utf-8")
    assert "meme volume que la cible" in manifeste
