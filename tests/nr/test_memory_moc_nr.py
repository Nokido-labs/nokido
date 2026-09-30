# -*- coding: utf-8 -*-
"""NR — la repartition de l'index chaud en cartes thematiques.

Un seul invariant compte : AUCUNE entree ne disparait. Une reecriture d'index
qui perd une ligne fait sortir une memoire de la traversee statique, sans que
rien ne le signale. Les deux defauts figes ici ont tous deux ete attrapes par
cet invariant et par rien d'autre.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))

moc = pytest.importorskip("forge_memory_moc")

# Index d'essai : reproduit les trois formes reelles de l'index owner.
_INDEX = """# MEMORY

- **🔍 THEME AVEC TETE LIEE (21 entrees)** → [index](index_reflexes_et_doctrine.md) : \
[premiere](feedback_une_chose_2026-01-02.md) · [seconde](gotcha_autre_2026-01-03.md)
- **🚦 THEME SIMPLE** : [mesure](mesure_quelconque_2026-01-04.md)
- [entree nue](reference_un_pointeur_2026-01-05.md) — sans tete thematique
"""


def _ecrire(tmp_path: Path) -> Path:
    d = tmp_path / "memory"
    d.mkdir()
    (d / "MEMORY.md").write_text(_INDEX, encoding="utf-8")
    return d


def test_la_repartition_conserve_TOUTES_les_entrees(tmp_path):
    plan = moc.repartir(_ecrire(tmp_path), chaud_jours=0)
    assert plan["conserve"], (
        "%d entrees avant, %d apres" % (plan["entrees_avant"], plan["entrees_apres"])
    )
    # 5 liens : celui de la TETE thematique compte comme les autres.
    assert plan["entrees_avant"] == 5


def test_un_nom_de_fiche_DATE_est_bien_capte_par_l_attrape_tout(tmp_path):
    """Premier defaut : l'attrape-tout s'ecrivait `[a-z0-9_]+\\.md`.

    Aucun nom porteur d'un TIRET n'y entrait — c'est-a-dire aucune fiche datee
    (`..._2026-09-04.md`). Mesure : 17 entrees sur 68 s'evaporaient.
    """
    plan = moc.repartir(_ecrire(tmp_path), chaud_jours=0)
    toutes = [e for v in plan["cartes"].values() for e in v]
    assert any("mesure_quelconque_2026-01-04.md" in e for e in toutes), (
        "une fiche datee doit tomber dans une carte, pas disparaitre"
    )


def test_un_lien_porte_par_la_TETE_n_est_compte_qu_une_fois(tmp_path):
    """Second defaut : la tete etait recopiee devant CHAQUE segment.

    Une ligne « - **X** -> [index](i.md) : a · b » dupliquait donc le lien de
    tete autant de fois qu'il y avait de segments. Mesure : 68 -> 71.
    """
    plan = moc.repartir(_ecrire(tmp_path), chaud_jours=0)
    toutes = [e for v in plan["cartes"].values() for e in v]
    n = sum(e.count("(index_reflexes_et_doctrine.md)") for e in toutes)
    assert n == 1, "le lien de tete apparait %d fois au lieu d'une" % n


def test_une_repartition_non_conservatrice_N_ECRIT_RIEN(tmp_path, monkeypatch):
    """Le garde doit ARRETER, pas corriger silencieusement."""
    d = _ecrire(tmp_path)
    avant = (d / "MEMORY.md").read_text(encoding="utf-8")
    monkeypatch.setattr(
        moc, "repartir",
        lambda *_a, **_k: {"entrees_avant": 68, "entrees_apres": 51, "conserve": False,
                           "routeur_lignes": [], "chaudes": [], "cartes": {},
                           "cutoff_chaud": "2026-01-01", "taille_avant_ko": 21.2},
    )
    res = moc.appliquer(d, dry_run=False)
    assert "ARRET" in res
    assert (d / "MEMORY.md").read_text(encoding="utf-8") == avant, "l'index a ete touche malgre l'arret"


def test_un_index_illisible_rend_NO_VERDICT_pas_un_succes(tmp_path):
    """Absent, vide et illisible sont TROIS etats. Les confondre fabrique un
    succes sur une mesure jamais prise."""
    res = moc.repartir(tmp_path / "nexiste_pas")
    assert "NO_VERDICT" in res


def test_la_fenetre_chaude_garde_le_recent_dans_le_routeur(tmp_path):
    """Rotation : l'index chaud porte l'etat courant, les cartes portent le fond."""
    import datetime

    d = tmp_path / "memory"
    d.mkdir()
    hier = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    (d / "MEMORY.md").write_text(
        "- **T** : [recente](gotcha_du_jour_%s.md) · [vieille](gotcha_ancien_2026-01-01.md)\n" % hier,
        encoding="utf-8",
    )
    plan = moc.repartir(d, chaud_jours=3)
    assert plan["conserve"]
    assert any("gotcha_du_jour" in c for c in plan["chaudes"])
    froides = [e for v in plan["cartes"].values() for e in v]
    assert any("gotcha_ancien_2026-01-01" in e for e in froides)
