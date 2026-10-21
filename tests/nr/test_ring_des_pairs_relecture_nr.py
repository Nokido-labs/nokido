"""NR -- decision owner 17/10 : ring 2 pour les pairs (claude.ai, ChatGPT web), SEULEMENT pour les annexes de relecture.

« Ring des pairs [...] : ring 2, et seulement pour les annexes de relecture. D'ici la, cette lecture reste fermee a
tous. = OK » (owner). Le pair est un NOM de client OAuth (claude.ai se reinscrit sous un nouvel identifiant a chaque
autorisation : clients_du_meme_pair regroupe deja par nom). La politique vit dans config/pairs_rings.json (versionnee,
sans secret) : nom de pair -> ring. Une capsule n'ouvre ses annexes que si elle declare usage_annexes = "relecture".
Tout le reste reste FERME : nom inconnu, registre illisible, politique absente -> ring INCONNU -> refus.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_pair_mcp as P  # noqa: E402

INSCRITS = [{"client_id": "cid-claude-1", "client_name": "Claude"},
            {"client_id": "cid-claude-2", "client_name": "Claude"},
            {"client_id": "cid-gpt", "client_name": "ChatGPT"},
            {"client_id": "cid-autre", "client_name": "Inconnu"}]


def _politique(tmp_path, monkeypatch, politique=None, registre=INSCRITS):
    reg = tmp_path / "clients.json"
    reg.write_text(json.dumps(registre), encoding="utf-8")
    monkeypatch.setenv("NOKIDO_BRIDGE_OAUTH_CLIENTS", str(reg))
    pol = tmp_path / "pairs_rings.json"
    if politique is not None:
        pol.write_text(json.dumps(politique), encoding="utf-8")
    monkeypatch.setattr(P, "chemin_politique_rings", lambda: pol)


def test_les_pairs_nommes_ont_le_ring_2(tmp_path, monkeypatch):
    _politique(tmp_path, monkeypatch, {"pairs": {"claude": 2, "chatgpt": 2}})
    assert P._ring_du_pair("cid-claude-1") == 2 and P._ring_du_pair("cid-claude-2") == 2
    assert P._ring_du_pair("cid-gpt") == 2


def test_un_pair_hors_politique_reste_ferme(tmp_path, monkeypatch):
    _politique(tmp_path, monkeypatch, {"pairs": {"claude": 2, "chatgpt": 2}})
    assert P._ring_du_pair("cid-autre") is None
    assert P._ring_du_pair("cid-jamais-inscrit") is None


def test_sans_politique_tout_reste_ferme(tmp_path, monkeypatch):
    _politique(tmp_path, monkeypatch, politique=None)
    assert P._ring_du_pair("cid-claude-1") is None


def _capsule(tmp_path, monkeypatch, usage):
    monkeypatch.setattr(P, "dossier_capsules", lambda: tmp_path / "caps")
    (tmp_path / "caps" / "c1" / "annexes").mkdir(parents=True)
    meta = {"ring_annexes": 2}
    if usage is not None:
        meta["usage_annexes"] = usage
    (tmp_path / "caps" / "c1.capsule.json").write_text(json.dumps(meta), encoding="utf-8")
    (tmp_path / "caps" / "c1" / "annexes" / "diff.txt").write_text("diff zorglub " * 50, encoding="utf-8")


def test_une_capsule_de_relecture_s_ouvre_au_ring_2(tmp_path, monkeypatch):
    _politique(tmp_path, monkeypatch, {"pairs": {"claude": 2, "chatgpt": 2}})
    _capsule(tmp_path, monkeypatch, "relecture")
    assert P.lire_annexe("cid-gpt", "annexe:c1/diff.txt", 0)["ok"] is True


def test_une_capsule_qui_n_est_pas_de_relecture_reste_fermee(tmp_path, monkeypatch):
    _politique(tmp_path, monkeypatch, {"pairs": {"claude": 2, "chatgpt": 2}})
    for usage in (None, "mission", "RELECTURE-et-plus"):
        (tmp_path / "caps").exists() and __import__("shutil").rmtree(tmp_path / "caps")
        _capsule(tmp_path, monkeypatch, usage)
        r = P.lire_annexe("cid-claude-1", "annexe:c1/diff.txt", 0)
        assert r["ok"] is False and "relecture" in str(r).lower(), (usage, r)
