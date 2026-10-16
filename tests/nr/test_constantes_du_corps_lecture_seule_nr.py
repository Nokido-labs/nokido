# -*- coding: utf-8 -*-
"""NR -- les constantes du corps s'exposent au MCP en LECTURE SEULE (decision owner du 15/10).

Owner : « oui, lecture seule ». Outil dynamique `constantes_du_corps` (registre app/forge_tools_dynamic) : reglages
DECLARES (PARAMS_L1 : bornes, defaut, valeur du magasin, qui peut changer) a cote des constantes OBSERVEES
(forge_physiology). Un outil qui pourrait aussi ecrire mettrait l'interrupteur a portee de ce qu'il contraint.

Contrat, sur le CHEMIN REEL (`forge_call_dynamic`, garde-fous denylist + SecretGuard compris) :
  1. l'outil passe les garde-fous et rend les reglages declares avec leurs bornes ;
  2. il n'ecrit RIEN : le magasin L1 est relu a l'identique, octet pour octet ;
  3. un magasin ILLISIBLE donne `effective=None` et le dit -- jamais le defaut en silence ;
  4. une section inconnue est refusee en le disant.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_proposal_applier as fpa  # noqa: E402
from nokido_agent.app.forge_tool_forger import forge_call_dynamic  # noqa: E402


def _appel(**kw):
    r = forge_call_dynamic("constantes_du_corps", sandboxed=False, **kw)
    assert "error" not in r, r
    return r["result"]


def test_passe_les_garde_fous_et_rend_les_bornes_declarees(tmp_path, monkeypatch):
    monkeypatch.setattr(fpa, "PARAMS_L1_FICHIER", tmp_path / "parametres_l1.json")
    vue = _appel(section="declare")
    assert vue["lecture_seule"] is True
    b = vue["declare"]["embed.batch_size"]
    assert (b["min"], b["max"], b["defaut"]) == (8, 128, 32)
    assert b["magasin"] == "LU" and b["effective"] == 32 and "owner" in b["qui_change"]


def test_n_ecrit_rien_et_lit_la_valeur_du_magasin(tmp_path, monkeypatch):
    magasin = tmp_path / "parametres_l1.json"
    magasin.write_text('{"embed.batch_size": {"valeur": 40, "precedente": 32}}', encoding="utf-8")
    avant = magasin.read_bytes()
    monkeypatch.setattr(fpa, "PARAMS_L1_FICHIER", magasin)
    b = _appel(section="declare")["declare"]["embed.batch_size"]
    assert b["effective"] == 40 and b["valeur_magasin"] == 40
    assert magasin.read_bytes() == avant and sorted(p.name for p in tmp_path.iterdir()) == ["parametres_l1.json"]


def test_magasin_illisible_n_est_jamais_le_defaut(tmp_path, monkeypatch):
    magasin = tmp_path / "parametres_l1.json"
    magasin.write_text("{illisible", encoding="utf-8")
    monkeypatch.setattr(fpa, "PARAMS_L1_FICHIER", magasin)
    b = _appel(section="declare")["declare"]["embed.batch_size"]
    assert b["effective"] is None and b["magasin"].startswith("ILLISIBLE")


def test_section_inconnue_refusee():
    assert "erreur" in _appel(section="ecrire")
