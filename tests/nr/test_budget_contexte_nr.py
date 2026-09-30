"""Non-régression : le contexte RÉSIDENT ne croît pas sans décision.

Le dépôt a des cliquets pour la mutation, la duplication, les règles d'or, la
couverture NR. Aucun ne portait sur la seule ressource dépensée à **chaque tour
de chaque session** : ce qui est rechargé avant le premier mot de l'utilisateur.

Mesure fondatrice (2026-09-12) : ~154 Ko, dont **51,6 % pour `RULES_SHARED.md`**.

⚠️ CE QUE CE TEST VERROUILLE EN PRIORITÉ N'EST PAS LE CHIFFRE, C'EST L'HONNÊTETÉ
DU CHIFFRE. Une partie du résident vit dans le profil de l'owner, que les comptes
de service ne peuvent pas lire — et là-bas `Path.exists()` ne rend pas `False`,
il **lève `PermissionError`**. Mesuré sur l'outil lui-même, au premier lancement :
son garde à trois états mourait avant d'atteindre son propre traitement.

Un budget qui compte `0` ce qu'il n'a pas pu lire s'auto-félicite : il descend
quand on perd l'accès. C'est le défaut que ce fichier interdit.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))


def _mod():
    import forge_context_budget  # type: ignore

    return forge_context_budget


def _forcer_refus(m, monkeypatch, tmp_path, nom="absent"):
    """Fait REFUSER la racine « profil », et rend son chemin.

    Pointer `SKILLS_DIR` vers un chemin inexistant ne suffit PAS : `_lire_racine`
    distingue l'absence PROUVEE (`FileNotFoundError` -> vide certain) du REFUS
    (`OSError`). Une racine absente est donc comptee comme LUE, et le poste sort
    `ok` des qu'une des trois autres racines repond.

    Les NR qui s'en contentaient ne passaient en local que parce que deux racines
    y refusent pour de vrai : ils mesuraient les ACL de la machine, pas le code,
    et sont tombes sur un runner ou tout est lisible (CI GitHub 35508916105).
    """
    chemin = tmp_path / nom
    monkeypatch.setattr(m, "SKILLS_DIR", chemin, raising=False)
    _vrai_lire = m._lire_racine

    def _refuse_le_profil(racine):
        if Path(racine) == Path(chemin):
            return {}, "PermissionError"
        return _vrai_lire(racine)

    monkeypatch.setattr(m, "_lire_racine", _refuse_le_profil, raising=True)
    return chemin


def test_le_resident_du_depot_reste_sous_son_budget():
    """Le cliquet. Croître exige d'abaisser explicitement le plafond, ce qui se
    voit dans le diff — au lieu de dériver sans que personne ne le mesure."""
    m = _mod().mesurer()
    # LE MESSAGE NOMME LA CAUSE. `depasse` agrege trois budgets ; n'imprimer que
    # la ventilation du depot a envoye enqueter du mauvais cote le 2026-09-14
    # (« 124907 o pour 125000 », donc SOUS le plafond, alors que `memoire` debordait).
    assert not m["depasse"], (
        _mod().expliquer(m) + " || "
        "le contexte resident du depot depasse son budget : %d o pour %d — "
        "chaque tour de chaque session le paie. Reduire, ou abaisser le plafond "
        "en le justifiant. Detail : %s"
        % (m["depot_total"], m["budget_depot_octets"], m["depot_octets"])
    )


def test_un_poste_illisible_n_est_jamais_compte_zero():
    """Le cœur. Un budget qui compte 0 ce qu'il n'a pas pu lire BAISSE quand on
    perd l'acces — il recompenserait la cecite."""
    m = _mod().mesurer()
    connus = m["resident_connu_octets"]
    assert connus >= m["depot_total"], (
        "le total connu est inferieur au total du depot : un poste a ete "
        "additionne comme zero (%s)" % m
    )
    for nom, v in m["hors_depot_octets"].items():
        if v is None:
            assert any(nom in x for x in m["INDETERMINES"]), (
                "le poste « %s » est illisible et ne figure PAS dans les "
                "INDETERMINES : il disparait du rapport en silence" % nom
            )


def test_l_outil_survit_a_un_profil_inaccessible(monkeypatch, tmp_path):
    """`Path.exists()` LEVE sous un compte de service, il ne rend pas False.
    L'outil doit rendre INDETERMINE, pas mourir — sinon la CI casse chez le seul
    compte qui n'a pas les droits, et le cliquet devient inutilisable."""
    m = _mod()
    inexistant = tmp_path / "profil_absent" / ".claude" / "skills"
    monkeypatch.setattr(m, "SKILLS_DIR", inexistant, raising=False)
    # ⚠️ ABSENT N'EST PAS ILLISIBLE — et ce test l'avait oublie, alors que le
    # module qu'il garde le dit dans sa propre docstring. Pointer `SKILLS_DIR`
    # vers un chemin inexistant fait rendre `FileNotFoundError` a `_lire_racine`,
    # qui la traite en VIDE CERTAIN et non en refus. Le poste sortait donc `ok`
    # des que l'UNE des trois autres racines repondait.
    #
    # Le test ne passait en local que parce que deux racines y refusent POUR DE
    # VRAI : il mesurait les ACL de la machine, pas le code. Il est tombe sur un
    # runner ou tout est lisible (CI GitHub 35508916105, 2026-09-20 :
    # `{'etat': 'ok', 'racines_illisibles': []}`). C'est exactement le defaut
    # deja paye la veille — « le NR simulait le refus par une ABSENCE ».
    # On SIMULE donc le refus, au point d'injection reel.
    _vrai_lire = m._lire_racine

    def _refuse_le_profil(racine):
        if Path(racine) == Path(inexistant):
            return {}, "PermissionError"
        return _vrai_lire(racine)

    monkeypatch.setattr(m, "_lire_racine", _refuse_le_profil, raising=True)
    r = m.descriptions_skills()
    # CONTRAT ELARGI le 2026-09-20, et il se RENFORCE au lieu de s'assouplir.
    # Le poste ne lisait qu'UNE racine ; il en lit quatre (profil, cache de
    # plugins, projet, depot). Quand une seule refuse, exiger `octets is None`
    # reviendrait a JETER ce qui a ete lu — or un PLANCHER nomme vaut mieux
    # qu'un vide, tant qu'il ne se fait pas passer pour un total.
    #
    # Ce qui reste interdit, et qui est l'objet reel de ce test : qu'un poste
    # incomplet se lise comme complet. On l'exige donc explicitement.
    assert r["etat"] in ("INDETERMINE", "PARTIEL"), r
    assert r["etat"] != "ok", "une racine a refuse et le poste se declare complet"
    if r["octets"] is not None:
        assert r.get("racines_illisibles"), (
            "un chiffre est rendu sans nommer ce qui n'a pas pu etre lu : "
            "c'est un plancher qui se fait passer pour un total (%s)" % r
        )

    complet = m.mesurer()
    assert complet["INDETERMINES"], (
        "aucun poste n'est declare indetermine alors que le profil est "
        "inaccessible : le rapport parait complet sans l'etre"
    )
    assert complet["RESIDENT_TOTAL"] is None, (
        "un TOTAL est annonce alors qu'une racine du poste skills a refuse"
    )


def test_le_drapeau_check_rend_un_code_utilisable():
    """Le chemin REEL : c'est `--check` que la CI appellera, pas `mesurer()`.
    Defaut paye deux fois aujourd'hui — fonction verte, point d'entree mort."""
    m = _mod()
    rc = m.main(["--check"])
    assert rc in (0, 1), "code de retour inexploitable : %r" % rc
    assert rc == (1 if m.mesurer()["depasse"] else 0), (
        "le code de retour ne suit pas le verdict mesure"
    )


def test_un_poste_illisible_interdit_d_annoncer_un_total(monkeypatch, tmp_path):
    """Le durcissement demande par l'owner, et il ferme un faux vert que j'avais
    introduit : la v1 affichait « TOTAL DEPOT 121 674 -> ok » face a une baseline
    de 154 336. Or 154 336 - 18 389 (MEMORY) - 14 273 (descriptions) = 121 674 :
    le denominateur avait change, pas le resident.

    Tant qu'un poste est INDETERMINE, `RESIDENT_TOTAL` doit valoir None. Sinon
    « RULES baisse, CLAUDE.md baisse, skills illisibles » se conclut « gain de
    25 % » en ignorant justement un composant resident."""
    m = _mod()
    _forcer_refus(m, monkeypatch, tmp_path)
    r = m.mesurer()
    assert r["RESIDENT_UNKNOWN"], "aucun poste declare inconnu, le test ne prouve rien"
    assert r["RESIDENT_TOTAL"] is None, (
        "un TOTAL a ete annonce alors qu'un poste resident est illisible : %s"
        % r["RESIDENT_TOTAL"]
    )
    assert r["RESIDENT_TOTAL_etat"] == "INDETERMINE", r["RESIDENT_TOTAL_etat"]
    assert "INDETERMINE" in str(r["comparaison_T0"]["delta_total"]), (
        "un delta contre T0 a ete calcule sur un denominateur ampute : %s"
        % r["comparaison_T0"]
    )


def test_la_baseline_T0_est_figee_et_ventilee():
    """T0 est le temoin. Sans ventilation par poste, une comparaison future ne
    peut pas se faire a denominateur identique — et c'est exactement l'erreur
    qu'on vient de corriger."""
    m = _mod()
    assert m.T0["total"] == 154_336, "la baseline a ete reecrite"
    assert sum(m.T0["par_poste"].values()) == m.T0["total"], (
        "la ventilation de T0 ne somme pas au total : %s" % m.T0
    )
    for poste in ("MEMORY.md", "descriptions de skills"):
        assert poste in m.T0["par_poste"], (
            "le poste « %s » manque a T0 : il pourrait etre retire du "
            "denominateur sans que personne ne le voie" % poste
        )


def test_un_budget_ne_se_declare_pas_tenu_sur_un_poste_illisible(monkeypatch,
                                                                 tmp_path):
    """Le meme faux vert, une couche plus bas. `(None or 0) > 16000` rendait
    False, donc « ok » : un budget se declarait respecte sur un poste qu'il
    n'avait pas mesure. Trois etats ici aussi — depasse / tenu / NON VERIFIE."""
    m = _mod()
    # CIBLE CHANGEE LE 2026-09-20, et l'invariante est INCHANGEE. Ce test faisait
    # refuser le PROFIL et exigeait un verdict `None`. Depuis que le budget porte
    # sur les racines GOUVERNEES par le depot (`RACINES_GOUVERNEES`), un profil
    # illisible ne suspend plus le verdict — c'est le but meme du correctif : le
    # meme commit doit rendre le meme verdict sur toute machine.
    #
    # Ce que ce test protege ne change pas d'un iota : un budget ne se declare
    # pas TENU sur un poste qu'il n'a pas mesure. On fait donc refuser une racine
    # QUE LE DEPOT GOUVERNE, seule situation ou le verdict doit redevenir `None`.
    _vrai_lire = m._lire_racine
    _gouvernee = next(Path(ch) for nom, ch in m.RACINES_SKILLS
                      if nom in m.RACINES_GOUVERNEES)

    def _refuse_une_racine_du_depot(racine):
        if Path(racine) == _gouvernee:
            return {}, "PermissionError"
        return _vrai_lire(racine)

    monkeypatch.setattr(m, "_lire_racine", _refuse_une_racine_du_depot,
                        raising=True)
    # ⚠️ CE QUE CE TEST A ATTRAPE LE 2026-09-20, et pourquoi il ne doit pas
    # bouger : en elargissant la portee du poste, `descriptions_skills` s'est
    # mis a rendre un PLANCHER (12 784 o) la ou il rendait None. Le verdict de
    # budget l'a compare au plafond — `12784 > 16000` -> False -> « ok » — et le
    # budget s'est declare TENU sur un poste qu'il n'avait pas fini de mesurer.
    # Exactement le faux vert decrit dans la docstring, reintroduit par le bas,
    # un mois apres. Le garde etait bon ; c'est le code qui avait regresse.
    # HERMETISME. Ce test porte sur UN poste indetermine, pas sur l'etat reel des
    # deux autres. Sans plafonds neutres il tombait des que `MEMORY.md` debordait
    # -- pour une raison etrangere a ce qu'il verifie (mesure 2026-09-14) -- et un
    # NR qui echoue pour autre chose que son objet fait accuser le mauvais code.
    monkeypatch.setattr(m, "BUDGETS",
                        dict(m.BUDGETS, kernel_depot=10 ** 9, memoire=10 ** 9),
                        raising=False)
    r = m.mesurer()
    assert r["depassements"]["descriptions_skills"] is None, (
        "verdict « %s » sur un poste illisible : le budget s'auto-declare tenu"
        % r["depassements"]["descriptions_skills"]
    )
    assert "descriptions_skills" in r["budgets_NON_VERIFIES"], r
    assert r["depasse"] is False, (
        "un poste indetermine ne doit pas faire echouer le cliquet non plus"
    )


def test_une_racine_HORS_DEPOT_illisible_ne_suspend_PAS_le_verdict(monkeypatch,
                                                                   tmp_path):
    """Le pendant du precedent, et il est tout aussi necessaire.

    Sans lui, on pourrait « reparer » le cliquet en le rendant indetermine des
    qu'une racine de profil refuse — ce qui le ferait taire sur la moitie des
    machines au lieu de le rendre reproductible. Une racine hors depot qui
    refuse doit etre DITE, et ne rien suspendre.
    """
    m = _mod()
    _forcer_refus(m, monkeypatch, tmp_path)   # refuse la racine « profil »
    r = m.mesurer()
    assert r["depassements"]["descriptions_skills"] is not None, (
        "une racine HORS DEPOT illisible a suspendu le verdict : le cliquet se "
        "tait des qu'une machine refuse, au lieu de juger le commit (%s)" % r
    )
    assert r["descriptions_skills_racines_illisibles"], (
        "la racine qui a refuse n'est pas nommee : cesser de la juger n'autorise "
        "pas a cesser de la montrer"
    )


# --------------------------------------------------------------------------
# Le verdict doit NOMMER la cause qui l'a declenche
# --------------------------------------------------------------------------
#
# Paye le 2026-09-14 : `depasse` agrege TROIS budgets, mais le message d'echec
# imprimait la ventilation du seul `kernel_depot`. Le cliquet a donc annonce
# « le contexte resident du depot depasse son budget : 124907 o pour 125000 »
# -- un chiffre SOUS le plafond -- alors que la cause etait `memoire`. Une heure
# d'enquete du mauvais cote, sur un instrument dont le module, lui, etait juste.
#
# Un agregat qui ne dit pas QUI l'a fait basculer renvoie l'enqueteur au hasard.


def _mesure_fictive(depot=100, memoire=None, skills=None,
                    d_depot=False, d_mem=None, d_skills=None):
    """Forme REELLE de `mesurer()`, reduite aux clefs que l'explication lit."""
    return {
        "budgets": {"kernel_depot": 125000, "memoire": 25000,
                    "descriptions_skills": 16000},
        "depot_total": depot,
        "hors_depot_octets": {"MEMORY.md": memoire,
                              "descriptions de skills": skills},
        "depassements": {"kernel_depot": d_depot, "memoire": d_mem,
                         "descriptions_skills": d_skills},
        "budgets_NON_VERIFIES": [k for k, v in
                                 (("kernel_depot", d_depot), ("memoire", d_mem),
                                  ("descriptions_skills", d_skills)) if v is None],
    }


def test_l_explication_nomme_le_poste_qui_a_declenche(ci_budget=None):
    """Le cas exact du 2026-09-14 : c'est `memoire` qui deborde, pas le depot."""
    txt = _mod().expliquer(_mesure_fictive(depot=124907, memoire=25239,
                                           d_depot=False, d_mem=True))
    assert "memoire" in txt
    assert "25239" in txt and "25000" in txt, txt
    # `"239" in txt` passerait deja grace a « 25239 » : c'est l'ECART qu'on exige.
    assert "+239" in txt, "l'ecart au plafond doit etre lisible : %s" % txt
    assert "kernel_depot" not in txt, (
        "le poste QUI TIENT ne doit pas figurer comme cause : %s" % txt)


def test_l_explication_distingue_NON_VERIFIE_d_un_depassement(ci_budget=None):
    """`None` n'est pas une cause. Il ne doit pas non plus disparaitre."""
    txt = _mod().expliquer(_mesure_fictive(memoire=10, d_mem=False,
                                           skills=None, d_skills=None))
    assert "descriptions_skills" in txt
    bas = txt.lower()
    assert "non verifie" in bas or "indetermine" in bas, txt
    # On exige que le poste non mesure n'apparaisse pas du cote des CAUSES.
    # (Chercher « depasse » avant la coupure ne prouvait rien : c'est une
    # sous-chaine de « depassement », present dans « aucun depassement mesure ».)
    avant = bas.split("non verifie")[0]
    assert "descriptions_skills" not in avant, (
        "un poste non mesure est presente comme un depassement : %s" % txt)


def test_sans_depassement_l_explication_le_DIT(ci_budget=None):
    """Une explication vide se relit comme un bug de l'explication."""
    txt = _mod().expliquer(_mesure_fictive(memoire=10, d_mem=False,
                                           skills=10, d_skills=False))
    assert txt.strip(), "explication vide"
    assert "aucun" in txt.lower(), txt


def test_les_budgets_sont_separes_par_nature():
    """Un budget unique laisserait « instructions -30 %, memoire +300 % » passer
    pour une amelioration."""
    m = _mod()
    assert set(m.BUDGETS) >= {"kernel_depot", "memoire", "descriptions_skills"}, (
        "budgets non separes : %s" % sorted(m.BUDGETS)
    )
    r = m.mesurer()
    assert set(r["depassements"]) == set(m.BUDGETS), (
        "un budget n'a pas de verdict de depassement associe"
    )
    for cle, v in r["depassements"].items():
        assert v in (True, False, None), (
            "verdict a deux etats pour « %s » : %r" % (cle, v)
        )


def test_le_budget_est_une_decision_pas_une_estimation():
    """Le plafond doit etre un entier pose explicitement, pas derive a l'execution
    de ce qu'on vient de mesurer — sinon le cliquet se regle sur la derive et ne
    mord jamais."""
    m = _mod()
    assert isinstance(m.BUDGET_DEPOT_OCTETS, int)
    assert m.BUDGET_DEPOT_OCTETS > 0
    mesure = m.mesurer()
    assert m.BUDGET_DEPOT_OCTETS != mesure["depot_total"], (
        "le budget vaut exactement la mesure courante : un cliquet cale sur "
        "l'etat present laisse passer la prochaine croissance"
    )
