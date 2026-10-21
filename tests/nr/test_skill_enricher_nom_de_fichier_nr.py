"""NR -- skill_enricher ecrit sa proposition meme quand le domaine porte des caracteres interdits sous Windows.

Mesure 20/10 (logs/supervisor/NokidoHomeostasis.log, a CHAQUE passage horaire : 21:58, 23:07, 00:14...) :
« KO skills: OSError: [Errno 22] Invalid argument: '...\\sandbox\\skill_proposals\\_new_syste... » -- le slug d'un
nouveau skill vaut f"_new_{domain}" et le domaine vient des lecons (texte libre) ; un « : » ou un « / » rend le nom de
fichier invalide, run_cycle meurt AVANT son _heartbeat : skill_enricher muet depuis le 30/04, accuse « silencieux cense
tourner » par le diagnostic.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_skill_enricher as SE  # noqa: E402


def test_un_domaine_aux_caracteres_interdits_donne_une_proposition_ecrite(tmp_path, monkeypatch):
    monkeypatch.setattr(SE, "PROPOSALS_DIR", tmp_path / "skill_proposals")
    out = SE.propose_skill_update('_new_systeme: hub/ci?*"<>|', [], [])
    assert out.exists() and out.parent == tmp_path / "skill_proposals"
    assert not any(c in out.name for c in ':/?*"<>|\\')


def test_un_slug_ordinaire_garde_son_nom(tmp_path, monkeypatch):
    monkeypatch.setattr(SE, "PROPOSALS_DIR", tmp_path / "skill_proposals")
    assert SE.propose_skill_update("_new_securite", [], []).name == "_new_securite.md"
