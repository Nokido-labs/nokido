# -*- coding: utf-8 -*-
"""NR — la souverainete affichee est une MESURE, et ce qu'on ignore ne compte pas comme local.

Demande owner du 2026-09-18 : l'ecran doit « representer le reel des actions effectuees
[...] afficher le pourcentage selon le fonctionnement reel de Nokido ».

Ce qui etait affiche avant : `PREF.get("power", 68)` -- une valeur REGLEE par
l'utilisateur au curseur, rendue comme « 68% local ». Une preference presentee comme une
mesure. La premiere mesure reelle, sur `token_usage` (23 140 appels) : **4,5 % de local
tous temps confondus, et 0,0 % sur les 7 derniers jours**. L'ecart n'etait pas un detail
d'affichage.

TROIS MORSURES, une par facon de rendre ce chiffre malhonnete :

1. `test_l_indetermine_ne_compte_jamais_comme_local` — classer par liste NOIRE ferait
   tomber tout provider inconnu du cote favorable. C'est le corollaire ecrit dans la
   constitution semantique du depot : n'est sain que ce qui est PROUVE sain.
2. `test_une_base_illisible_ne_rend_pas_zero` — ILLISIBLE n'est pas ZERO. Un journal
   qu'on ne peut pas lire donnerait « 0 % local », c'est-a-dire une accusation fausse.
3. `test_une_fenetre_vide_ne_rend_pas_zero` — aucune activite n'est pas « 0 % local »,
   c'est « rien a mesurer ». Les deux se corrigent a des endroits differents.

Hermetique : base SQLite fabriquee en tmp_path, aucun acces au journal reel.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_souverainete_reelle as SR  # noqa: E402


def _base(tmp_path, lignes):
    """Journal d'usage minimal : (provider, ts, total_tokens)."""
    f = tmp_path / "usage.db"
    con = sqlite3.connect(str(f))
    con.execute("CREATE TABLE token_usage (id INTEGER PRIMARY KEY, ts TEXT, "
                "provider TEXT, total_tokens INT)")
    con.executemany("INSERT INTO token_usage (ts, provider, total_tokens) VALUES (?,?,?)",
                    lignes)
    con.commit()
    con.close()
    SR._CACHE.clear()          # le cache ne doit pas faire fuiter un test dans l'autre
    return str(f)


def test_une_base_illisible_ne_rend_pas_zero(tmp_path):
    """MORSURE — un journal illisible rendrait « 0 % local », une accusation fausse."""
    SR._CACHE.clear()
    r = SR.parts("total", db_path=str(tmp_path / "absente.db"))
    assert r["mesure"] == "INCONNU", r
    assert r["part_locale_pct"] is None, "un pourcentage a ete fabrique sur du vide"
    assert "raison" in r and r["raison"], "le refus ne dit pas ce qui manque"


def test_une_fenetre_vide_ne_rend_pas_zero(tmp_path):
    """MORSURE — aucune activite n'est pas « 0 % local », c'est « rien a mesurer »."""
    db = _base(tmp_path, [])
    r = SR.parts("total", db_path=db)
    assert r["mesure"] == "RIEN_A_MESURER", r
    assert r["part_locale_pct"] is None
    assert r["denominateur"] == 0


def test_l_indetermine_ne_compte_jamais_comme_local(tmp_path, monkeypatch):
    """MORSURE PRINCIPALE — liste BLANCHE : n'est local que ce qui est prouve local."""
    monkeypatch.setattr(SR, "_classe_par_provider",
                        lambda: {"ollama_local": "local", "groq": "free"})
    db = _base(tmp_path, [
        ("2026-09-18 10:00:00", "ollama_local", 10),
        ("2026-09-18 10:00:00", "groq", 10),
        ("2026-09-18 10:00:00", "un_truc_jamais_vu", 10),
        ("2026-09-18 10:00:00", "encore_un_autre", 10),
    ])
    r = SR.parts("total", db_path=db)
    assert r["mesure"] == "OK", r
    assert r["denominateur"] == 4
    assert r["part_locale_pct"] == 25.0, (
        "les providers inconnus ont ete absorbes quelque part : %s" % r["classes"]
    )
    assert r["indetermine_pct"] == 50.0, "l'indetermine n'est pas expose tel quel"
    assert r["classes"]["indetermine"]["appels"] == 2


def test_le_denominateur_est_toujours_dit(tmp_path, monkeypatch):
    """Un pourcentage sans son nombre d'appels ne se juge pas."""
    monkeypatch.setattr(SR, "_classe_par_provider", lambda: {"ollama_local": "local"})
    db = _base(tmp_path, [("2026-09-18 10:00:00", "ollama_local", 5)])
    r = SR.parts("total", db_path=db)
    assert r["denominateur"] == 1
    assert r["part_locale_pct"] == 100.0
    assert "duree_ms" in r, "le cout de la mesure n'est pas rendu"


def test_un_catalogue_illisible_rend_tout_indetermine(tmp_path, monkeypatch):
    """Sans table de classement, on ne DEVINE pas : tout devient indetermine, et on le dit."""
    def _casse():
        raise RuntimeError("temoin")
    monkeypatch.setattr(SR, "_classe_par_provider", _casse)
    db = _base(tmp_path, [("2026-09-18 10:00:00", "ollama_local", 5)])
    r = SR.parts("total", db_path=db)
    assert r["indetermine_pct"] == 100.0
    assert r["part_locale_pct"] == 0.0
    assert r.get("avertissement"), "la perte du catalogue n'est pas signalee"


def test_les_fenetres_sont_declarees():
    """Une tendance se lit mal sur un seul point : 24h, 7j, 30j, total."""
    for f in ("24h", "7j", "30j", "total"):
        assert f in SR.FENETRES
    assert SR.FENETRES["total"] is None, "la fenetre totale ne doit pas etre bornee"


def test_la_route_de_souverainete_n_est_pas_publique():
    """Exposer la part cloud/local sans session renseigne sur la posture de la machine."""
    pytest.importorskip("fastapi")
    from app.web_hub.auth import is_public_path
    assert not is_public_path("/api/souverainete")
