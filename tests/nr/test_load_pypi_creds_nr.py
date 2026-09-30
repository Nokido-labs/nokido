"""NR : forge_load_pypi_creds — isole le bloc pypirc + charge les tokens au coffre.

Effets PURS : aucun vrai coffre (forge_secrets mocké), aucun réseau, Nokido.env
factice en tmp_path.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
import forge_secrets
import forge_load_pypi_creds as rl


def test_pypirc_block_isole_les_sections():
    lines = ["FOO=bar", "[testpypi]", "username = __token__", "password = tok-A",
             "", "[pypi]", "username = __token__", "password = tok-B", "BAZ=qux"]
    blk = rl._pypirc_block(lines)
    assert "[testpypi]" in blk and "[pypi]" in blk
    assert "FOO=bar" not in blk and "BAZ=qux" not in blk


def test_load_stocke_les_deux_tokens(monkeypatch, tmp_path):
    env = tmp_path / "Nokido.env"
    env.write_text(
        "A=1\n[testpypi]\nusername = __token__\npassword = tok-A\n"
        "[pypi]\nusername = __token__\npassword = tok-B\nB=2\n", encoding="utf-8")
    saved = {}
    monkeypatch.setattr(forge_secrets, "set_secret",
                        lambda k, v: (saved.__setitem__(k, v), True)[1])
    monkeypatch.setattr(forge_secrets, "get_secret", lambda k: saved.get(k))
    stored = rl.load(env)
    assert set(stored) == {"TESTPYPI_TOKEN", "PYPI_TOKEN"}
    assert saved["TESTPYPI_TOKEN"] == "tok-A"
    assert saved["PYPI_TOKEN"] == "tok-B"


def test_load_source_vide_ne_stocke_rien(monkeypatch, tmp_path):
    env = tmp_path / "Nokido.env"
    env.write_text("A=1\n[testpypi]\nusername = __token__\n", encoding="utf-8")
    monkeypatch.setattr(forge_secrets, "set_secret", lambda k, v: True)
    monkeypatch.setattr(forge_secrets, "get_secret", lambda k: None)
    assert rl.load(env) == []
