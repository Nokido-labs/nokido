"""NR -- vagues de roadmap : items EN COURS et subsomption `remplace:` (owner 21/10, suite de 08a41dce5).

Mesure du 21/10 ~20 h sur la roadmap reelle (`--plan`, 59 jouables, 47 prets) : le PUCT attribuait
`P1_roadmap_chronologie_20261021` a MISTRAL alors qu'AGY y travaillait deja (job_f4359b8c). Le plan savait qu'un
REPONDEUR est occupe, pas qu'un ITEM l'est : en resolution parallele multipartite, c'est deux agents sur le meme
chantier, donc deux branches qui se heurtent a l'integration.
Decision owner (choix multiple 21/10) : etiquette `remplace:` -- fermer un chantier ferme aussi ceux qu'il subsume --
dans ce lot, declarative, jamais de cloture silencieuse.

Contrats :
  1. items_en_cours(taches) : {cle: agent} pour chaque tache pending|claimed|running dont la description cite
     `bb:<cle>` ; une tache completed/failed n'occupe rien ;
  2. vagues(items, contexte={'en_cours': {...}}) : un item en cours n'est jamais pret, motif `en_cours:<agent>` ;
     plan_puct ne l'attribue a personne ;
  3. contraintes_item lit `remplace:` (liste) ; un item ouvert remplace par un autre item OUVERT attend avec le
     motif `remplace_par:<cle>` (le faire a part serait du travail jete) ; `subsomptions` = [{par, items}] ;
  4. quand le remplacant est CLOS, l'item remplace encore ouvert est `cloturables` = [{cle, par}] : propose avec sa
     preuve, jamais ferme par le planificateur ;
  5. arbre() : une arete EXPLICITE de la carte (de -> vers) prime sur une citation INVERSE dans le texte (vers cite
     de) ; la citation ecartee est DITE (`carte_conflits` = [{item, cite, carte}]), jamais un cycle fabrique. Mesure
     21/10 : `p1_racine_donnees_hors_paquet_2026-10-13` dit « lie a roadmap_installation_complete_noob » (association)
     alors que la carte pose racine -> noob (dependance reelle) : le plan reel affichait un CYCLE entre les deux.
"""
import json
import sys
import types
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_roadmap_keeper as K  # noqa: E402

CTX = {"maintenant": "2026-10-21", "go_owner": [], "ressources_occupees": [], "quotas": {"S": True, "M": True,
                                                                                        "L": True}}


def _it(cle, reste="cabler", etat="PARTIEL", prio="P1", cite=()):
    return {"cle": cle, "etat": etat, "priorite": prio, "reste": reste, "cite": list(cite)}


def test_items_en_cours_depuis_les_taches():
    taches = [{"agent": "ANTIGRAVITY", "statut": "running", "description": '{"pointer_ref":"bb:chrono"} GREEN ...'},
              {"agent": "OPENCODE_GPTOSS", "statut": "pending", "description": "recette bb:pack sur le livrable"},
              {"agent": "MISTRAL", "statut": "completed", "description": "bb:vieux fini"},
              {"agent": "GLM", "statut": "failed", "description": "bb:rate"}]
    assert K.items_en_cours(taches) == {"chrono": "ANTIGRAVITY", "pack": "OPENCODE_GPTOSS"}


def test_un_item_en_cours_n_est_jamais_pret_ni_attribue():
    items = [_it("chrono", "RED puis GREEN dans tools/x.py", prio="P1"), _it("autre", "RED puis GREEN dans app/y.py")]
    ctx = dict(CTX, en_cours={"chrono": "ANTIGRAVITY"})
    v = K.vagues(items, ctx)
    assert "chrono" not in v["prets"]
    assert "en_cours:ANTIGRAVITY" in v["attente"]["chrono"]
    p = K.plan_puct(items, ["MISTRAL", "OPENCODE_GPTOSS"], [], contexte=ctx)
    assert "chrono" not in {a["cle"] for a in p["attributions"]}


def test_remplace_met_en_attente_le_subsume_et_le_dit():
    assert K.contraintes_item(_it("m", "unifier le middleware remplace: fix_a, fix_b"))["remplace"] == ["fix_a",
                                                                                                         "fix_b"]
    items = [_it("m", "unifier le middleware remplace: fix_a, fix_b", prio="P1"),
             _it("fix_a", prio="P0"), _it("fix_b", prio="P2"), _it("libre")]
    v = K.vagues(items, CTX)
    assert "remplace_par:m" in v["attente"]["fix_a"] and "remplace_par:m" in v["attente"]["fix_b"]
    assert v["subsomptions"] == [{"par": "m", "items": ["fix_a", "fix_b"]}]
    assert sorted(v["prets"]) == ["libre", "m"]


def test_la_carte_prime_sur_une_citation_inverse_sans_fabriquer_de_cycle(tmp_path, monkeypatch):
    faits = [{"key": "p1_racine", "value": "[PARTIEL 2026-10-21 : reste = constater ; lie a p1_noob]",
              "trust": 0.9, "updated_at": 1},
             {"key": "p1_noob", "value": "[PARTIEL 2026-10-21 : reste = installation complete]", "trust": 0.9,
              "updated_at": 2}]
    faux = types.ModuleType("nokido_agent.app.forge_swarm_blackboard")
    faux.read_zone = lambda zone, *, category=None, min_trust=None, limit=200: list(faits)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_swarm_blackboard", faux)
    carte = tmp_path / "deps.json"
    carte.write_text(json.dumps({"aretes": [{"de": "p1_racine", "vers": "p1_noob", "raison": "pip ecrit sinon"}]}),
                     encoding="utf-8")
    monkeypatch.setattr(K, "CARTE_DEPENDANCES", carte)
    doc = K.arbre(out=tmp_path / "a.json")
    par = {i["cle"]: i for i in doc["items"]}
    assert par["p1_noob"]["cite"] == ["p1_racine"]
    assert par["p1_racine"]["cite"] == []
    assert doc["carte_conflits"] == [{"item": "p1_racine", "cite": "p1_noob", "carte": "p1_racine->p1_noob"}]
    v = K.vagues(doc["items"], CTX)
    assert v["cycles"] == []


def test_remplacant_clos_rend_le_subsume_cloturable_sans_le_fermer():
    items = [_it("m", "unifier remplace: fix_a", etat="CLOS"), _it("fix_a", prio="P0")]
    v = K.vagues(items, CTX)
    assert v["cloturables"] == [{"cle": "fix_a", "par": "m"}]
    assert "fix_a" not in v["prets"]
    assert items[1]["etat"] == "PARTIEL"
