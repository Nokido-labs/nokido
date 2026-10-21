# -*- coding: utf-8 -*-
"""NR -- un depot de pair coupe a la borne le DIT au pair, et les outils annoncent borne et format (owner 19/10 :
« donner des instructions a chatgpt web pour que ce ne soit pas tronque et qu'il te donne juste des pointeurs »).

Mesure du 19/10 : le plan en 6 vagues de ChatGPT web (pair_b3fbc1221ef5395e) est arrive coupe a 4 000 caracteres
(MAX_TEXTE, tools/forge_pair_mcp._nettoyer) EN SILENCE : sa vague 5 perdue, le pair n'en savait rien, et rien dans
la description de proposer_fait ne disait la borne. Une borne doit dire combien.
Contrat :
  1. `deposer` coupe toujours a MAX_TEXTE mais rend `tronque = {recu, garde}` et une note qui demande des pointeurs ;
     la charge stockee porte la meme marque ; un texte court ne porte aucune marque ;
  2. les descriptions de proposer_fait, envoyer_message, soumettre_tache annoncent la borne et le format POINTEURS.
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_pair_mcp as pm  # noqa: E402

pytestmark = pytest.mark.timeout(60)


@pytest.fixture()
def boite(tmp_path, monkeypatch):
    db = tmp_path / "m2m.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, "
              "correlation_id TEXT, method TEXT, payload TEXT, status TEXT, created_at TEXT)")
    c.commit()
    c.close()
    monkeypatch.setattr(pm, "chemin_m2m", lambda: str(db))
    return db


def _charge(db, ident):
    c = sqlite3.connect(str(db))
    p = c.execute("SELECT payload FROM agent_messages WHERE id=?", (ident,)).fetchone()[0]
    c.close()
    return json.loads(p)


def test_un_depot_coupe_le_dit_au_pair_et_le_garde(boite):
    r = pm.deposer_fait("chatgpt-web", "x" * (pm.MAX_TEXTE + 1000))
    assert r["ok"] and r["tronque"] == {"recu": pm.MAX_TEXTE + 1000, "garde": pm.MAX_TEXTE}
    assert "TRONQUE" in r["note"] and "pointeur" in r["note"].lower()
    ch = _charge(boite, r["id"])
    assert ch["tronque"] == r["tronque"] and len(ch["texte"]) == pm.MAX_TEXTE


def test_un_depot_court_ne_porte_aucune_marque(boite):
    r = pm.deposer_fait("chatgpt-web", "V0: bb:P1_executeurs_preservation_et_arbre_partage_20261019")
    assert r["ok"] and "tronque" not in r and "tronque" not in _charge(boite, r["id"])


@pytest.mark.parametrize("outil", ["proposer_fait", "envoyer_message", "soumettre_tache"])
def test_les_outils_annoncent_borne_et_format(outil):
    src = (RACINE / "tools" / "forge_pair_mcp.py").read_text(encoding="utf-8")
    i = src.find('name="%s"' % outil)
    assert i >= 0
    desc = src[i:i + 900]
    assert "POINTEURS" in desc and "MAX_TEXTE" in desc, "la description de %s doit dire borne et format" % outil
