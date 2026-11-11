# -*- coding: utf-8 -*-
"""NR -- non-regression scanner de secrets et caviardage pour le depot long de pair (owner 24/10, revue 09/11).

Contrat :
- deposer_fragment refuse un fragment contenant une clef a casse mixte
  ("sk-ant-api03-" + "AbCdEfGhIjKlMnOpQrSt") des l'etape 1 regex, et rien n'est ecrit sur disque ;
- un fragment propre passe ;
- lire_document caviarde un secret factice deja stocke en quarantaine (champ caviarde=True).
Fixtures FACTICES construites par concatenation (jamais une clef reelle).
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_pair_mcp as pm  # noqa: E402
import forge_pair_depot_long as dl  # noqa: E402

pytestmark = pytest.mark.timeout(60)

PAIR = "f07699ff-58dc-44c3-8693-650bbd470dc2"
DOC = "rapport_audit_20261024"
FAUSSE_CLE_ANTHROPIC = "sk-ant-api03-" + "AbCdEfGhIjKlMnOpQrSt"


def _sha(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


@pytest.fixture()
def monde(tmp_path, monkeypatch):
    db = tmp_path / "m2m.db"
    c = sqlite3.connect(str(db))
    c.execute(
        "CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, "
        "correlation_id TEXT, method TEXT, payload TEXT, status TEXT, created_at TEXT)"
    )
    c.commit()
    c.close()
    monkeypatch.setattr(pm, "chemin_m2m", lambda: str(db))
    depot = tmp_path / "sandbox" / "pair_quarantaine"
    monkeypatch.setattr(dl, "racine_depot", lambda: depot)
    return db, depot, tmp_path


def test_deposer_fragment_refuse_secret_casse_mixte_et_rien_n_est_ecrit(monde):
    """deposer_fragment refuse un fragment contenant une clef a casse mixte et rien n'est ecrit."""
    _db, depot, _ = monde
    texte = "# Rapport\nVoici le jeton : " + FAUSSE_CLE_ANTHROPIC + "\nsuite\n"
    sha_f = _sha(texte)
    r = dl.deposer_fragment(PAIR, DOC, 1, 1, texte, sha_f, sha_f)
    assert not r["ok"]
    assert r.get("etat") == "INVALIDE"
    assert "secret" in (r.get("erreur") or r.get("motif") or "").lower()
    # Rien n'est ecrit dans la quarantaine
    assert not depot.exists() or not any(depot.rglob("*"))


def test_deposer_fragment_propre_passe(monde):
    """Un fragment propre passe sans encombre."""
    _db, _depot, _ = monde
    texte = "# Rapport sain\nTout est propre et conforme, sans secrets.\n"
    sha_f = _sha(texte)
    r = dl.deposer_fragment(
        PAIR,
        DOC,
        1,
        1,
        texte,
        sha_f,
        sha_f,
        deposer=lambda client, *a, **k: {"ok": True, "id": "msg_001"},
    )
    assert r["ok"]
    assert r.get("etat") == "ASSEMBLE"


def test_lire_document_caviarde_secret_factice_deja_stocke(monde):
    """lire_document caviarde un secret factice deja stocke (champ caviarde=True)."""
    _db, depot, _ = monde
    texte = "# Rapport ancien\nclef_api = " + FAUSSE_CLE_ANTHROPIC + "\nfin du rapport\n"
    d = depot / dl.dossier_pair(PAIR) / DOC
    d.mkdir(parents=True, exist_ok=True)
    octets = texte.encode("utf-8")
    sha_doc = _sha(texte)
    (d / "assemble.md").write_bytes(octets)
    meta = {
        "doc_id": DOC,
        "total": 1,
        "sha256_document": sha_doc,
        "statut": "ASSEMBLE",
        "provenance": dl.PROVENANCE,
        "client": PAIR,
    }
    dl._ecrire_meta(d, meta)

    rep = dl.lire_document(PAIR, "pairdoc:" + DOC, 0)
    assert rep["ok"]
    assert rep.get("caviarde") is True
    assert FAUSSE_CLE_ANTHROPIC not in rep["contenu"]
    assert "[ANTHROPIC_KEY_REDIGE]" in rep["contenu"]
