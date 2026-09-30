"""NR — le detecteur de duplication.

Ce qu'on mesure ici est la DISCRIMINATION : un detecteur de clones qui repond
« tout se ressemble » est aussi inutile qu'un detecteur muet. Chaque cas vient
du premier passage reel du 2026-08-15 (500 groupes annonces, 402 apres retrait
des archives et du code genere).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def _fn(code: str):
    return ast.parse(code).body[0]


_CORPS = (
    "    total = 0\n"
    "    for element in donnees:\n"
    "        if element > 3:\n"
    "            total += element * 2\n"
    "        else:\n"
    "            total -= 1\n"
    "    resultat = {'somme': total, 'n': len(donnees)}\n"
    "    return resultat\n"
)


def test_le_renommage_ne_cache_pas_un_clone():
    """Le copier-coller s'accompagne presque toujours d'un renommage : une
    empreinte sensible aux noms ne verrait jamais un seul vrai clone."""
    import forge_dup_detector as D

    a = _fn("def calcul(donnees):\n" + _CORPS)
    b = _fn(_CORPS.replace("total", "cumul").replace("element", "x")
            .replace("resultat", "sortie").replace("donnees", "valeurs")
            .join(["def autre_nom(valeurs):\n", ""]))
    assert D.empreinte(a)[0] == D.empreinte(b)[0]


def test_deux_fonctions_differentes_ne_sont_pas_confondues():
    import forge_dup_detector as D

    a = _fn("def calcul(donnees):\n" + _CORPS)
    b = _fn("def autre(donnees):\n    return sorted(donnees, reverse=True)\n")
    assert D.empreinte(a)[0] != D.empreinte(b)[0]


def test_les_appels_distincts_distinguent_deux_fonctions():
    """Attributs CONSERVES : deux fonctions de meme forme qui appellent des
    services differents ne sont pas des clones, sinon tout wrapper d'API
    devient le clone de tous les autres."""
    import forge_dup_detector as D

    a = _fn("def f(x):\n    y = os.path.join(x, 'a')\n    return len(y) + 1\n")
    b = _fn("def g(x):\n    y = shutil.disk_usage(x, 'a')\n    return len(y) + 1\n")
    assert D.empreinte(a)[0] != D.empreinte(b)[0]


def test_la_docstring_ne_fait_pas_la_difference():
    """Documenter une copie ne la rend pas originale."""
    import forge_dup_detector as D

    a = _fn("def f(d):\n" + _CORPS)
    b = _fn('def f(d):\n    """Une doc ajoutee apres coup."""\n' + _CORPS)
    assert D.empreinte(a)[0] == D.empreinte(b)[0]


def test_les_corps_triviaux_sont_ignores(tmp_path):
    """Sous le seuil, les accesseurs noieraient les vrais blocs recopies."""
    import forge_dup_detector as D

    for nom in ("a.py", "b.py"):
        (tmp_path / nom).write_text(
            "class C:\n    def get(self):\n        return self._x\n", encoding="utf-8")
    res = D.scanner([str(tmp_path)])
    assert res["groupes"] == []


def test_un_vrai_clone_est_signale(tmp_path):
    for nom in ("un.py", "deux.py"):
        (tmp_path / nom).write_text("def calcul(donnees):\n" + _CORPS, encoding="utf-8")
    import forge_dup_detector as D

    res = D.scanner([str(tmp_path)])
    assert len(res["groupes"]) == 1
    assert res["fonctions_en_double"] == 1


def test_le_code_genere_est_hors_perimetre(tmp_path):
    """46 formulaires s'annoncent GENERE par forge_ui_sweep : les accuser
    reviendrait a reprocher a la moulinette de faire son travail."""
    import forge_dup_detector as D

    entete = "# GENERE par forge_ui_sweep (moulinette deterministe)\n"
    for nom in ("un.py", "deux.py"):
        (tmp_path / nom).write_text(entete + "def calcul(donnees):\n" + _CORPS,
                                    encoding="utf-8")
    res = D.scanner([str(tmp_path)])
    assert res["fichiers_lus"] == 0 and res["groupes"] == []


def test_la_cle_de_cliquet_ignore_les_lignes():
    """Deplacer une fonction dans son fichier ne cree pas un clone nouveau."""
    import forge_dup_detector as D

    g1 = {"copies": [{"fichier": "app/a.py", "ligne": 10},
                     {"fichier": "app/b.py", "ligne": 20}]}
    g2 = {"copies": [{"fichier": "app/b.py", "ligne": 900},
                     {"fichier": "app/a.py", "ligne": 3}]}
    assert D._cle(g1) == D._cle(g2)


# ── filtres, seuils et sortie : ce que la suite ne protegeait pas ────────────
# MESURE 2026-08-18 : 8 mutants sur 14 survivaient. Les tests couvraient la
# DISCRIMINATION (clone vs non-clone) mais laissaient libres le filtre de
# fichiers, le seuil de taille, la regle « un groupe = au moins deux copies »
# et la sortie machine. Or c'est la que se decide ce que le detecteur REGARDE.

def test_le_filtre_de_fichiers_jetables_ne_mange_pas_les_paquets():
    """`__init__.py` commence par un underscore mais n'est pas un brouillon :
    l'ecarter rendrait invisible tout clone vivant dans un paquet."""
    import forge_dup_detector as D

    assert D._scratch("_essai.py") is True
    assert D._scratch("tmp_passe.py") is True
    assert D._scratch("__init__.py") is False
    assert D._scratch("forge_reel.py") is False


def test_collect_ignore_les_dossiers_exclus_et_les_non_python(tmp_path):
    import forge_dup_detector as D

    (tmp_path / "vrai.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("pas du python\n", encoding="utf-8")
    (tmp_path / "_brouillon.py").write_text("x = 1\n", encoding="utf-8")
    exclu = tmp_path / sorted(D._SKIP_DIRS)[0]
    exclu.mkdir()
    (exclu / "cache.py").write_text("x = 1\n", encoding="utf-8")

    vus = {Path(f).name for f in D.collect([str(tmp_path)])}
    assert vus == {"vrai.py"}


def test_une_fonction_sous_le_seuil_de_taille_est_ignoree(tmp_path):
    """Le seuil est un `<` : au seuil EXACT la fonction compte encore. Le muer
    en `<=` retirerait silencieusement toute une tranche de la surveillance."""
    import forge_dup_detector as D

    src = "def a():\n" + _CORPS + "\n\ndef b():\n" + _CORPS + "\n"
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    _sig, taille = D.empreinte(_fn("def a():\n" + _CORPS))

    assert D.scanner([str(tmp_path)], min_noeuds=taille)["groupes"], "au seuil : compte"
    assert D.scanner([str(tmp_path)], min_noeuds=taille + 1)["groupes"] == []


def test_une_empreinte_unique_ne_fait_pas_un_groupe(tmp_path):
    """Un groupe exige au moins DEUX copies. `> 1` mue en `>= 1` ferait de
    chaque fonction du depot un « clone » — 2000 groupes, gate desarme."""
    import forge_dup_detector as D

    (tmp_path / "seul.py").write_text("def a():\n" + _CORPS, encoding="utf-8")
    res = D.scanner([str(tmp_path)], min_noeuds=1)
    assert res["fichiers_lus"] == 1
    assert res["groupes"] == [] and res["fonctions_en_double"] == 0


def test_l_empreinte_est_stable_et_de_taille_fixe():
    """Le socle du cliquet est indexe PAR EMPREINTE : elle doit etre stable d'un
    appel a l'autre et insensible au nom de la fonction.

    ⚠️ Ne PAS figer ici la valeur litterale de l'empreinte. Essaye le
    2026-08-18 : sous le mutateur, ce test rendait la suite « deja rouge » et la
    surface entiere passait INDETERMINE — donc plus AUCUN mutant mesure, pour
    proteger un seul site. Un test qui empeche la mesure coute plus qu'il ne
    protege. Le site `annotate_fields` reste donc un survivant assume, gele au
    socle de mutation."""
    import forge_dup_detector as D

    sig, taille = D.empreinte(_fn("def a():\n" + _CORPS))
    assert (sig, taille) == D.empreinte(_fn("def autre_nom():\n" + _CORPS))
    assert len(sig) == 16 and taille > 1
    assert sig == D.empreinte(_fn("def a():\n" + _CORPS))[0]


def test_la_sortie_json_scanne_les_chemins_demandes_et_reste_lisible(tmp_path, capsys, monkeypatch):
    """`args.paths or [app, tools]` : passer un chemin doit remplacer le defaut,
    pas s'y ajouter. Et `ensure_ascii=False` garde les accents lisibles — un
    rapport illisible ne se relit pas."""
    import json as _json

    import forge_dup_detector as D

    src = ("def calculé_a():\n" + _CORPS + "\n\ndef calculé_b():\n" + _CORPS + "\n")
    (tmp_path / "accents.py").write_text(src, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["dup", str(tmp_path), "--json", "--min-noeuds", "1"])
    assert D.main() == 0
    sortie = capsys.readouterr().out
    assert "calculé_a" in sortie, "accents echappes : ensure_ascii a saute"
    res = _json.loads(sortie)
    assert res["fichiers_lus"] == 1, "le chemin demande doit remplacer app/tools"
    assert res["fonctions_en_double"] == 1


def test_le_socle_du_depot_est_utilisable():
    import json

    import forge_dup_detector as D

    gele = json.loads(Path(D.SOCLE).read_text(encoding="utf-8"))
    assert gele["groupes"], "socle vide = cliquet sans reference"
    assert gele["min_noeuds"] >= 25


# ── ADAPTATEUR D'ENTREE : le motif structurel admis (2026-09-12) ──────────────
# Ces tests vivent ICI et pas ailleurs : `forge_mutation_ratchet.SURFACES` mappe
# `tools/forge_dup_detector.py` sur CE fichier. Places dans un autre NR, ils
# etaient verts et ne tuaient AUCUN mutant -- mesure du 2026-09-12 : 8/14 tues,
# score inchange, quatre nouvelles faiblesses persistantes. Un test hors de la
# suite declaree ne garde rien, exactement comme un NR hors de `PURE_TESTS`.
#
# Le test de PORTEE sur le depot reel reste dans
# `test_dup_adaptateur_entree_nr.py` : il scanne 2201 fichiers (18 s), et la
# suite de mutation est rejouee UNE FOIS PAR MUTANT.

_BOILERPLATE = (
    "def main():\n"
    "    try:\n"
    "        ev = json.load(sys.stdin)\n"
    "    except Exception:\n"
    "        return 0\n"
    "    return traiter(ev)\n")

# Une entree = une branche de rejet du predicat. Sans elles, les mutations
# booleennes, de comparaison, de negation et de et/ou survivaient toutes.
_REJETS = {
    "corps_a_une_seule_instruction": "def f():\n    return g()\n",
    "corps_a_trois_instructions": (
        "def f():\n    try:\n        v = g()\n    except Exception:\n"
        "        return 0\n    h()\n    return g(v)\n"),
    "premiere_instruction_pas_un_try": "def f():\n    v = g()\n    return g(v)\n",
    "derniere_instruction_pas_un_return": (
        "def f():\n    try:\n        v = g()\n    except Exception:\n"
        "        return 0\n    h(v)\n"),
    "return_final_pas_un_appel": (
        "def f():\n    try:\n        v = g()\n    except Exception:\n"
        "        return 0\n    return 42\n"),
    "try_a_deux_instructions": (
        "def f():\n    try:\n        v = g()\n        w = g()\n"
        "    except Exception:\n        return 0\n    return g(v)\n"),
    "try_sans_affectation": (
        "def f():\n    try:\n        g()\n    except Exception:\n"
        "        return 0\n    return g()\n"),
    "affectation_pas_un_appel": (
        "def f():\n    try:\n        v = 1\n    except Exception:\n"
        "        return 0\n    return g(v)\n"),
    "deux_gestionnaires": (
        "def f():\n    try:\n        v = g()\n    except ValueError:\n"
        "        return 0\n    except Exception:\n        return 1\n"
        "    return g(v)\n"),
    "avec_un_else": (
        "def f():\n    try:\n        v = g()\n    except Exception:\n"
        "        return 0\n    else:\n        v = 2\n    return g(v)\n"),
    "avec_un_finally": (
        "def f():\n    try:\n        v = g()\n    except Exception:\n"
        "        return 0\n    finally:\n        h()\n    return g(v)\n"),
    "gestionnaire_a_deux_instructions": (
        "def f():\n    try:\n        v = g()\n    except Exception:\n"
        "        h()\n        return 0\n    return g(v)\n"),
    "gestionnaire_sans_return": (
        "def f():\n    try:\n        v = g()\n    except Exception:\n"
        "        pass\n    return g(v)\n"),
    "gestionnaire_rend_un_appel": (
        "def f():\n    try:\n        v = g()\n    except Exception:\n"
        "        return h()\n    return g(v)\n"),
}


def _premiere_fonction(src):
    import forge_dup_detector as D

    fn = ast.parse(src).body[0]
    _, taille = D.empreinte(fn)
    return D, fn, taille


def test_l_adaptateur_d_entree_exact_est_admis():
    D, fn, taille = _premiere_fonction(_BOILERPLATE)
    assert D.est_adaptateur_entree(fn, taille) is True


@pytest.mark.parametrize("cas", sorted(_REJETS), ids=sorted(_REJETS))
def test_chaque_branche_de_rejet_de_l_adaptateur(cas):
    D, fn, taille = _premiere_fonction(_REJETS[cas])
    assert D.est_adaptateur_entree(fn, taille) is False, (
        "%s doit etre REFUSE : le predicat reconnait le boilerplate EXACT, "
        "jamais ce qui lui ressemble de loin" % cas)


def test_le_plafond_de_l_adaptateur_est_inclusif():
    """Muter `>` en `>=` couperait le cas reel : le boilerplate pese 25."""
    D, fn, _ = _premiere_fonction(_BOILERPLATE)
    assert D.est_adaptateur_entree(fn, D.PLAFOND_ADAPTATEUR) is True
    assert D.est_adaptateur_entree(fn, D.PLAFOND_ADAPTATEUR + 1) is False


def test_une_fonction_porteuse_de_logique_reste_un_clone_possible():
    """Temoin : le cliquet doit continuer a mordre sur du vrai code."""
    src = ("def calculer(a, b):\n    total = 0\n    for x in range(a):\n"
           "        if x % 2 == 0:\n            total += x * b\n"
           "        else:\n            total -= x\n    return total\n")
    D, fn, taille = _premiere_fonction(src)
    assert taille >= D.MIN_NOEUDS
    assert D.est_adaptateur_entree(fn, taille) is False


def test_un_groupe_retreci_nest_pas_un_groupe_nouveau():
    """Mesure 2026-08-26 : de-cloner `_get_conn` dans un fichier a reduit un groupe
    gele de 4 a 3 membres, et le cliquet a rougi la CI sur les 3 restants. Reduire un
    clone est ce que le cliquet DOIT encourager, pas punir."""
    import forge_dup_detector as D

    gele = {"app/a.py|app/b.py|app/c.py|app/d.py", "tools/x.py|tools/y.py"}
    nouveaux, retrecis = D.groupes_nouveaux(
        ["app/a.py|app/b.py|app/c.py",      # sous-ensemble strict : retreci
         "tools/x.py|tools/y.py",           # identique : gele
         "app/a.py|app/z.py",               # un fichier hors socle : NOUVEAU
         "tools/x.py|tools/y.py|tools/w.py"],  # sur-ensemble : un clone de PLUS = nouveau
        gele)
    assert retrecis == ["app/a.py|app/b.py|app/c.py"]
    assert nouveaux == ["app/a.py|app/z.py", "tools/x.py|tools/y.py|tools/w.py"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
