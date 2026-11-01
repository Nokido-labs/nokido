"""NR -- vagues de roadmap : chemin critique herite, empreinte fichiers, fusions (owner 21/10, suite de 6d816bf6a).

Owner, 21/10 : « inspire-toi de ces methodes suggerees par gemini web » (RCPSP, backward pass CPM, footprint
locking, batch coalescing, lookahead MCTS, ROI homeostatique). Tri MESURE contre l'existant avant adoption :
  - DEJA LA : masse aval ponderee (`gestes_groupes` : aval, poids, 19/10) ; PUCT sur force MESUREE (`plan_puct`) ;
  - ADOPTE ici : heritage de priorite ET d'echeance du descendant le plus urgent (un README P2 qui bloque une
    publication P0 passe devant un P1 isole) ; empreinte fichiers (deux items qui touchent le meme fichier ne
    partent jamais ensemble : incident paye le 19/10, un executeur a ecrase deux modules dans l'arbre partage) ;
    fusions (items prets sur le meme fichier -> un lot pour un seul agent) ;
  - ECARTE tant que non mesure : multiplicateurs de strate et gains de « vitalite » inventes, simulateur a couts
    supposes, solveur CP-SAT.

Contrats (s'ajoutent a ceux de test_roadmap_chronologie_vagues_nr) :
  1. `heritage` : pour chaque item dont la priorite ou l'echeance EFFECTIVE differe de la sienne,
     {priorite, echeance, de} -- `de` = l'item aval qui impose l'urgence ; le tri des vagues suit l'effective ;
  2. `aval` : nombre d'items ouverts distincts en aval (fermeture transitive, un diamant ne compte pas double) ;
     a priorite et echeance effectives egales, le plus grand aval passe devant ;
  3. empreinte_item : chemins du depot cites (avec un `/` ou une extension connue), README -> readme.md,
     CHANGELOG -> changelog.md, en minuscules ; collision = meme chemin ou dossier parent (`app/web_hub/`) ;
  4. deux items en collision ne partagent jamais une vague ; le second attend avec le motif `fichier:<chemin>` ;
     `prets` est toujours un sous-ensemble de la premiere vague ;
  5. `fusions` : groupes d'au moins deux items causalement libres et chronologiquement ouverts qui touchent un
     meme fichier -> {fichier, cles} (cles dans l'ordre du tri) ; un item bloque par `pas_avant` n'y entre pas.
"""
import sys
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


def test_le_readme_herite_l_urgence_de_la_publication_et_passe_devant_un_p1_isole():
    items = [_it("readme", "reprendre le README exclusif: poste_ci", prio="P2"),
             _it("bench", "bench lourd exclusif: poste_ci", prio="P1"),
             _it("pub", "publier sur PyPI echeance: 2026-10-25", prio="P0")]
    v = K.vagues(items, CTX)
    assert v["heritage"]["readme"] == {"priorite": "P0", "echeance": "2026-10-25", "de": "pub"}
    assert "bench" not in v["heritage"]
    assert v["vagues"][0] == ["readme"]
    assert "bench" in v["vagues"][1]
    assert v["prets"] == ["readme"]


def test_diamant_aval_sans_double_compte_et_bris_d_egalite():
    items = [_it("a", prio="P2"), _it("b", prio="P2", cite=["a"]), _it("c", prio="P2", cite=["a"]),
             _it("d", prio="P0", cite=["b", "c"]), _it("e", prio="P0")]
    v = K.vagues(items, CTX)
    assert v["aval"]["a"] == 3
    assert v["aval"]["e"] == 0
    assert v["heritage"]["a"]["priorite"] == "P0" and v["heritage"]["a"]["de"] == "d"
    assert v["vagues"][0] == ["a", "e"]


def test_empreinte_et_collision():
    assert K.empreinte_item(_it("x", "corriger tools/forge_roadmap_keeper.py et le README")) == \
        {"tools/forge_roadmap_keeper.py", "readme.md"}
    assert K.empreinte_item(_it("y", "mettre a jour le CHANGELOG")) == {"changelog.md"}
    assert K.empreinte_item(_it("z", "cabler la boucle")) == set()
    assert K.empreintes_collision({"app/web_hub/"}, {"app/web_hub/routes.py"})
    assert K.empreintes_collision({"readme.md"}, {"readme.md"})
    assert not K.empreintes_collision({"app/forge_a.py"}, {"app/forge_b.py"})


def test_meme_fichier_jamais_dans_la_meme_vague():
    items = [_it("p1", "trier dans tools/forge_roadmap_keeper.py", prio="P1"),
             _it("p0", "cycles dans tools/forge_roadmap_keeper.py", prio="P0"),
             _it("ailleurs", "router dans app/forge_router.py", prio="P2")]
    v = K.vagues(items, CTX)
    assert v["vagues"][0] == ["p0", "ailleurs"]
    assert v["vagues"][1] == ["p1"]
    assert sorted(v["prets"]) == ["ailleurs", "p0"]
    assert "fichier:tools/forge_roadmap_keeper.py" in v["attente"]["p1"]
    assert set(v["prets"]) <= set(v["vagues"][0])


def test_fusions_d_items_prets_sur_le_meme_fichier_hors_bloques():
    items = [_it("k1", "parser dans tools/forge_roadmap_keeper.py", prio="P0"),
             _it("k2", "cycles dans tools/forge_roadmap_keeper.py", prio="P1"),
             _it("k3", "liens dans tools/forge_roadmap_keeper.py", prio="P2"),
             _it("k4", "hotfix tools/forge_roadmap_keeper.py pas_avant: GO_owner", prio="P0"),
             _it("seul", "ailleurs dans app/forge_x.py", prio="P1")]
    v = K.vagues(items, CTX)
    assert v["fusions"] == [{"fichier": "tools/forge_roadmap_keeper.py", "cles": ["k1", "k2", "k3"]}]
