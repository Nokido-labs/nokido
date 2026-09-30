# -*- coding: utf-8 -*-
"""NR — l'instrument d'auto-amelioration doit pouvoir dire s'il s'ameliore.

CE QUI A ETE PAYE (2026-09-18). L'owner demande : « est-ce que l'auto-amelioration a
enfin servi a quelque chose ? ». Reponse impossible a donner avec l'instrument en
place, pour deux raisons mesurees :

1. `sandbox/introspect_trace.json` ne porte que des CUMULS et UNE seule date
   (`derniere`). Un cumul ne peut pas repondre a « est-ce que ca s'ameliore » : il
   dilue le present dans le passe. Il a fallu aller chercher A LA MAIN le chiffre du
   2026-09-13 dans une fiche memoire pour obtenir un point de comparaison -- 13,2 %
   contre 19,7 % cumules, soit **46,8 % sur la periode**, un ecart que l'instrument
   etait structurellement incapable de montrer.

2. L'autre source, `rag_chunks WHERE domain='mcp_result'`, ne peut pas non plus :
   ses 16 447 lignes ont `created_at` a **NULL**, et 16 334 d'entre elles viennent du
   daemon POST_COMMIT -- des commits indexes, pas des appels d'outil. D'ou le
   `delta_appels: 0` de `bilan()`, qui ne veut pas dire « rien n'a bouge » mais
   « je compare deux nombres qui ne portent aucune date ».

Un instrument sans serie temporelle ne mesure pas une evolution : il mesure un etat.
C'est la meme famille que les gardes branches sur un signal que personne n'emet, sauf
qu'ici c'est l'outil d'auto-amelioration lui-meme qui est aveugle.

CE QUE CE NR VERROUILLE :
- la serie s'ecrit (un instantane par jour et par agent, en append) ;
- elle ne se reecrit pas deux fois le meme jour ;
- la tendance rend un taux MARGINAL, et le cumul reste A COTE, jamais a la place ;
- l'absence de tendance ne se replie JAMAIS sur « 0 % » (trois etats) ;
- MORSURE : sur des donnees ou marginal et cumul DIVERGENT, l'instrument doit
  rendre le marginal -- sinon il ne sert a rien, puisque c'est precisement cette
  divergence qu'on n'arrivait pas a voir.

Hermetique : serie fabriquee en tmp_path, aucune lecture de la serie reelle.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_introspect as FI  # noqa: E402


def _serie(tmp_path, points) -> Path:
    """Serie JSONL fabriquee : (jour, agent, editions, editions_avec, age_jours)."""
    f = tmp_path / "serie.jsonl"
    lignes = []
    for jour, agent, ed, av, age in points:
        lignes.append(json.dumps({
            "jour": jour, "ts": time.time() - age * 86400, "agent": agent,
            "editions": ed, "editions_avec": av, "editions_sans": ed - av,
            "consultations": av, "reutilisations": 0, "divergences": 0,
        }))
    f.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return f


def test_le_marginal_est_rendu_quand_il_diverge_du_cumul(tmp_path):
    """MORSURE — c'est CE cas qui a motive le chantier, il doit etre visible.

    Chiffres calques sur la mesure reelle : 2886 editions dont 381 avec consultation
    au depart, 3583 dont 707 a l'arrivee. Le cumul bouge a peine (13,2 -> 19,7) alors
    que la periode est a 46,8 %. Un instrument qui ne rendrait que le cumul ferait
    conclure « ca ne change presque pas », ce qui est FAUX.
    """
    f = _serie(tmp_path, [("2026-09-13", "CLAUDE", 2886, 381, 5),
                          ("2026-09-18", "CLAUDE", 3583, 707, 0)])
    t = FI.tendance(30, serie=f)
    assert t["mesure"] == "OK", t
    a = t["agents"]["CLAUDE"]
    assert a["editions"] == 697 and a["avec_consultation"] == 326
    assert a["taux_marginal_pct"] == 46.8, a
    assert a["taux_cumule_pct"] == 19.7, "le cumul doit rester expose A COTE"
    assert a["taux_marginal_pct"] > 2 * a["taux_cumule_pct"], (
        "sur ces donnees le marginal et le cumul DOIVENT diverger : si le NR passe "
        "avec des valeurs proches, il ne mord pas sur le defaut qui l'a motive")


def test_une_serie_trop_courte_ne_rend_pas_zero(tmp_path):
    """Un seul point n'est pas une tendance nulle : c'est une tendance ABSENTE."""
    f = _serie(tmp_path, [("2026-09-18", "CLAUDE", 10, 5, 0)])
    t = FI.tendance(7, serie=f)
    assert t["mesure"] == "PAS_ASSEZ_DE_POINTS", t
    assert "taux_marginal_pct" not in t


def test_une_serie_illisible_ne_rend_pas_zero(tmp_path):
    """ILLISIBLE n'est pas VIDE — sinon un fichier absent se lit « aucune adoption »."""
    t = FI.tendance(7, serie=tmp_path / "jamais_ecrite.jsonl")
    assert t["mesure"] == "INCONNU", t
    assert "raison" in t and t["raison"]


def test_aucune_edition_dans_l_intervalle_nest_pas_zero_pour_cent(tmp_path):
    """Deux instantanes identiques = rien ne s'est passe, pas « 0 % de consultation »."""
    f = _serie(tmp_path, [("2026-09-17", "CLAUDE", 100, 40, 1),
                          ("2026-09-18", "CLAUDE", 100, 40, 0)])
    a = FI.tendance(7, serie=f)["agents"]["CLAUDE"]
    assert a["mesure"] == "RIEN_A_MESURER", a
    assert "taux_marginal_pct" not in a


def test_les_lignes_illisibles_sont_COMPTEES(tmp_path):
    """Un filtre qui ecarte des donnees le DIT, sinon la couverture est surestimee."""
    f = _serie(tmp_path, [("2026-09-17", "CLAUDE", 10, 2, 1),
                          ("2026-09-18", "CLAUDE", 20, 12, 0)])
    with f.open("a", encoding="utf-8") as h:
        h.write("{ceci n est pas du json}\n")
    t = FI.tendance(7, serie=f)
    assert t["lignes_illisibles"] == 1, t
    assert t["agents"]["CLAUDE"]["taux_marginal_pct"] == 100.0


def test_l_instantane_ne_se_pose_qu_une_fois_par_jour(tmp_path, monkeypatch):
    """Sinon chaque ecriture de trace ajouterait une ligne : la serie exploserait."""
    monkeypatch.setattr(FI, "SERIE", tmp_path / "s.jsonl")
    data = {"CLAUDE": {"editions_avec": 3, "editions_sans": 7, "consultations": 3}}
    for _ in range(5):
        FI._poser_instantane(data)
    lignes = [l for l in (tmp_path / "s.jsonl").read_text(encoding="utf-8").split("\n") if l.strip()]
    assert len(lignes) == 1, "un instantane par jour et par agent, pas un par ecriture"
    assert json.loads(lignes[0])["editions"] == 10


def test_l_ecrivain_ne_leve_jamais(tmp_path, monkeypatch):
    """Un instrument qui casse ce qu'il mesure est pire que pas d'instrument."""
    monkeypatch.setattr(FI, "SERIE", tmp_path / "s.jsonl")
    FI._poser_instantane({"CLAUDE": "pas un dict", "X": None})   # entrees hostiles
    FI._poser_instantane({})                                      # rien a ecrire


def test_la_serie_est_branchee_sur_l_ecriture_de_trace():
    """Une dette de cablage : la serie pourrait exister sans que rien ne l'alimente."""
    import inspect
    src = inspect.getsource(FI._ecrire_trace)
    assert "_poser_instantane" in src, (
        "la serie n'est appelee par personne : mecanisme present, effet nul")
