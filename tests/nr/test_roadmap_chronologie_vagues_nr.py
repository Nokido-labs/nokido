"""NR -- la resolution des roadmaps suit une CHRONOLOGIE en plus des liens de causalite (owner 21/10).

Owner, 21/10 ~19 h 30 : « mettre une notion de chronologie a respecter dans la resolution des roadmaps en plus des
liens de causalite pour avancer le plus efficacement possible dans une resolution multipartite, cli et swarm
cloud » ; puis : « et surtout l'ordre logique de resolution a faire, si B depend de A il faut bien le classer. si
je te dis de reprendre le readme, le prevoir avant une publication ».

Existant etendu (pas de systeme parallele) : forge_roadmap_keeper porte deja la CAUSALITE (`cite`, graphe
« debloque », carte des dependances, portes, plan_puct). Decisions owner (choix multiple, 21/10) : etiquettes DANS
le texte de l'item ; quatre familles de contraintes des la v1 (ordres owner, ressources exclusives, quotas,
echeances/circadien) ; calcul en OBSERVATION, la distribution reste manuelle.

Contrats :
  1. contraintes_item lit les etiquettes du reste : `apres:` `pas_avant:` `exclusif:` (listes, separateur virgule),
     `palier:` (S|M|L), `echeance:` (AAAA-MM-JJ) ; absentes = vides, jamais inventees ;
  2. nature_item classe le reste (doc | verif | publication | miroir | autre) ; une reprise du README, d'une doc
     ou du CHANGELOG est `doc`, une publication / release / PyPI / tag public est `publication` ;
  3. ordre logique DEDUIT : une publication ouverte attend tout item `doc` ou `verif` ouvert, un miroir attend la
     publication ; chaque arete deduite est PUBLIEE (`liens_deduits`, raison `nature:<a>-><b>`), jamais cachee ;
  4. causalite : un item n'est pret que si TOUS ses prerequis (`cite` + `apres:` + deduits) sont CLOS ; un
     prerequis inconnu n'est PAS satisfait (UNKNOWN n'est pas NO) : motif `inconnu:<cle>` ;
  5. vagues = couches topologiques des items jouables ; deux items d'une meme ressource exclusive ne partagent
     jamais une vague ; dans une vague : priorite (P0 > P1 > P2), puis echeance la plus proche, puis cle ;
  6. chronologie a l'instant : `pas_avant:GO_owner` attend `contexte.go_owner`, une date attend `maintenant`, une
     ressource occupee bloque (`exclusif:<r>`), un palier sans quota MESURE bloque (`quota:<p>:INCONNU`) ; les
     echeances depassees sont listees (`en_retard`) ;
  7. un cycle est DIT (`cycles`) et ses items ne sont jamais prets ;
  8. plan_puct publie `chronologie` (meme calcul), et le drapeau CLI --plan la rend sur le chemin reel.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_roadmap_keeper as K  # noqa: E402

CTX = {"maintenant": "2026-10-21", "go_owner": [], "ressources_occupees": [], "quotas": {"S": True, "M": True,
                                                                                        "L": True}}


def _it(cle, reste="RED puis GREEN dans app/x.py", etat="PARTIEL", prio="P1", cite=()):
    return {"cle": cle, "etat": etat, "priorite": prio, "reste": reste, "cite": list(cite)}


def test_contraintes_item_lit_les_etiquettes_sans_inventer():
    c = K.contraintes_item(_it("a", "lot 0.20.15 apres: P2_snn, x_readme pas_avant: GO_owner exclusif: poste_ci "
                                    "palier: L echeance: 2026-10-30"))
    assert c["apres"] == ["P2_snn", "x_readme"]
    assert c["pas_avant"] == ["GO_owner"]
    assert c["exclusif"] == ["poste_ci"]
    assert c["palier"] == "L"
    assert c["echeance"] == "2026-10-30"
    vide = K.contraintes_item(_it("b", "cabler forge_x"))
    assert vide["apres"] == [] and vide["pas_avant"] == [] and vide["exclusif"] == []
    assert not vide["palier"] and not vide["echeance"]


def test_nature_item():
    assert K.nature_item(_it("r", "reprendre le README avec la nouvelle install")) == "doc"
    assert K.nature_item(_it("c", "mettre a jour le CHANGELOG")) == "doc"
    assert K.nature_item(_it("p", "publier 0.20.15 sur PyPI (release)")) == "publication"
    assert K.nature_item(_it("m", "propager sur les miroirs GitLab Codeberg")) == "miroir"
    assert K.nature_item(_it("v", "CI de reference sur la tete")) == "verif"
    assert K.nature_item(_it("x", "cabler forge_x dans le hub")) == "autre"


def test_le_readme_passe_avant_la_publication_meme_si_elle_est_p0():
    items = [_it("pub", "publier 0.20.15 sur PyPI", prio="P0"), _it("readme", "reprendre le README", prio="P2"),
             _it("mir", "propager sur les miroirs", prio="P0")]
    v = K.vagues(items, CTX)
    rang = {c: i for i, vague in enumerate(v["vagues"]) for c in vague}
    assert rang["readme"] < rang["pub"] < rang["mir"]
    assert v["prets"] == ["readme"]
    assert any(m == "cause:readme" for m in v["attente"]["pub"])
    assert {"de": "readme", "vers": "pub", "raison": "nature:doc->publication"} in v["liens_deduits"]


def test_causalite_cite_et_apres_un_prerequis_clos_libere():
    items = [_it("a", etat="CLOS"), _it("b", cite=["a"]), _it("c", "suite apres: b"), _it("d", "apres: fantome")]
    v = K.vagues(items, CTX)
    assert "b" in v["prets"]
    assert "c" not in v["prets"] and "cause:b" in v["attente"]["c"]
    assert "d" not in v["prets"] and "inconnu:fantome" in v["attente"]["d"]


def test_ressource_exclusive_jamais_dans_la_meme_vague_et_occupee_bloque():
    items = [_it("x", "CI ref exclusif: poste_ci", prio="P1"), _it("y", "bench lourd exclusif: poste_ci", prio="P0")]
    v = K.vagues(items, CTX)
    assert v["vagues"][0] == ["y"] and v["vagues"][1] == ["x"]
    occ = K.vagues(items, dict(CTX, ressources_occupees=["poste_ci"]))
    assert occ["prets"] == []
    assert "exclusif:poste_ci" in occ["attente"]["y"]


def test_ordre_owner_date_et_quota():
    items = [_it("go", "lot 0.20.15 pas_avant: GO_owner"), _it("date", "rappel pas_avant: 2026-11-01"),
             _it("l", "gros chantier palier: L")]
    v = K.vagues(items, dict(CTX, quotas={}))
    assert v["prets"] == []
    assert "pas_avant:GO_owner" in v["attente"]["go"]
    assert "pas_avant:2026-11-01" in v["attente"]["date"]
    assert "quota:L:INCONNU" in v["attente"]["l"]
    ok = K.vagues(items, dict(CTX, go_owner=["go"], maintenant="2026-11-02"))
    assert sorted(ok["prets"]) == ["date", "go", "l"]


def test_tri_dans_la_vague_et_echeances_depassees():
    items = [_it("p1_tard", "x echeance: 2026-12-01"), _it("p1_tot", "y echeance: 2026-10-25"),
             _it("p0", "z", prio="P0"), _it("p2_retard", "w echeance: 2026-10-01", prio="P2")]
    v = K.vagues(items, CTX)
    assert v["vagues"][0] == ["p0", "p1_tot", "p1_tard", "p2_retard"]
    assert v["en_retard"] == ["p2_retard"]


def test_un_cycle_est_dit_et_jamais_pret():
    items = [_it("a", "apres: b"), _it("b", "apres: a"), _it("c")]
    v = K.vagues(items, CTX)
    assert any(set(cy) == {"a", "b"} for cy in v["cycles"])
    assert v["prets"] == ["c"]


def test_plan_puct_publie_la_chronologie():
    items = [_it("pub", "publier sur PyPI", prio="P0"), _it("readme", "reprendre le README", prio="P2")]
    p = K.plan_puct(items, ["OPENCODE_NEMOTRON"], [])
    assert p["chronologie"]["prets"] == ["readme"]


import pytest  # noqa: E402 -- borne pytest du test au chemin reel (cliquet test_sous_processus_borne_sous_la_suite_nr)


@pytest.mark.timeout(120)
def test_le_drapeau_plan_rend_la_chronologie_sur_le_chemin_reel(tmp_path):
    items = [_it("pub", "publier sur PyPI", prio="P0"), _it("readme", "reprendre le README", prio="P2")]
    (tmp_path / "arbre.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    (tmp_path / "r.jsonl").write_text("", encoding="utf-8")
    env = {**os.environ, "NOKIDO_PLAN_ARBRE": str(tmp_path / "arbre.json"),
           "NOKIDO_MOTIVATION_RESULTATS": str(tmp_path / "r.jsonl"),
           "NOKIDO_PLAN_JOURNAL": str(tmp_path / "plan.jsonl"), "PYTHONNOUSERSITE": "1"}
    r = subprocess.run([sys.executable, str(RACINE / "tools" / "forge_roadmap_keeper.py"), "--plan",
                        "--libres", "OPENCODE_NEMOTRON"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, errors="replace", env=env, timeout=60, cwd=str(RACINE))
    assert r.returncode == 0, r.stderr[-800:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    rang = {c: i for i, vague in enumerate(out["chronologie"]["vagues"]) for c in vague}
    assert rang["readme"] < rang["pub"]
