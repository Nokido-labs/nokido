# -*- coding: utf-8 -*-
"""NR — la PORTEE du poste « descriptions de skills » dans forge_context_budget.

POURQUOI (2026-09-20). Le module etait honnete sur ce qu'il ne pouvait pas LIRE
(`RESIDENT_TOTAL = INDETERMINE` des que le profil owner refuse), et c'est ce qui
l'a sauve. Mais il etait muet sur ce qu'il ne REGARDAIT pas : `SKILLS_DIR` ne
designe qu'UNE racine, alors que les descriptions residentes viennent d'au moins
trois (le profil, le cache de plugins, les skills du depot). Mesure du jour :
367 `SKILL.md` sur disque, dont des doublons `cache/` + `marketplaces/`.

C'est exactement le defaut du 2026-09-19 — « un controle vrai ne couvre que ce
qu'il mesure » : un poste lu sur une racine sur trois aurait pu ressortir `ok` et
sous plafond, en ayant ignore la majorite de ce qu'il pretend decrire. Un chiffre
partiel servi comme total est pire qu'un INDETERMINE.

Ce que ce NR verrouille :
  1. plusieurs racines sont lues, pas une ;
  2. un meme skill vu dans deux racines ne compte qu'une fois (sinon le cache de
     plugins double la facture et on « reduit » un chiffre qui n'existait pas) ;
  3. une racine ILLISIBLE (refus) interdit l'etat `ok` et se NOMME — tandis
     qu'une racine dont l'absence est PROUVEE est un vide certain, sans quoi le
     poste resterait INDETERMINE pour toujours et ne fermerait jamais rien ;
  4. un releve depose par un exécuteur privilegie n'est servi que s'il est FRAIS ;
  5. le point d'entree reel (`main(["--releve"])`) fonctionne — un drapeau CLI se
     teste en le traversant, pas en appelant la fonction sous-jacente (defaut
     paye le 2026-09-06 : `check()` vert pendant que `--check` mourait).
"""

import importlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _mod():
    return importlib.import_module("forge_context_budget")


def _skill(racine: Path, nom: str, description: str) -> None:
    d = racine / nom
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        "---\nname: %s\ndescription: %s\nmetadata: x\n---\n\n# corps\n%s\n"
        % (nom, description, "x" * 5000),
        encoding="utf-8",
    )


def _racine_illisible(tmp_path: Path, nom: str) -> Path:
    """Une racine qui REFUSE, pas une racine ABSENTE — la distinction compte.

    Une racine dont on peut PROUVER l'absence (son parent est lisible et ne la
    contient pas) est un vide CERTAIN : la compter comme inconnue fabriquerait un
    INDETERMINE permanent, donc un poste qui ne se fermerait jamais. Ce qui doit
    interdire l'etat `ok`, c'est le REFUS — celui que le compte sandbox recolte
    sur le profil owner. On le simule par un chemin qui existe mais n'est pas un
    dossier : le parcours y leve `NotADirectoryError`.
    """
    p = tmp_path / nom
    p.write_text("ceci n'est pas un dossier", encoding="utf-8")
    return p


def _isoler(monkeypatch, racines, releve=None):
    """Coupe le module de la machine : ses racines et son releve sont a nous."""
    mod = _mod()
    monkeypatch.setattr(mod, "RACINES_SKILLS", racines, raising=False)
    monkeypatch.setattr(mod, "SKILLS_DIR", Path(racines[0][1]), raising=False)
    if releve is not None:
        monkeypatch.setattr(mod, "RELEVE_SKILLS", releve, raising=False)
    return mod


def test_plusieurs_racines_de_skills_sont_lues(monkeypatch, tmp_path):
    """ROUGE ATTENDU : le module ne connait qu'une racine.

    Deux racines, un skill distinct dans chacune -> le poste doit en compter 2.
    S'il n'en compte qu'un, il decrit un tiers du resident en se croyant complet.
    """
    a, b = tmp_path / "profil", tmp_path / "plugins"
    _skill(a, "alpha", "description alpha")
    _skill(b, "beta", "description beta")
    mod = _isoler(monkeypatch, [("profil", a), ("plugins", b)])

    r = mod.descriptions_skills()
    assert r["n"] == 2, (
        "deux racines lisibles portent deux skills ; le poste en a compte %r — "
        "une racine sur deux est hors de portee du controle" % (r.get("n"),)
    )
    assert r["octets"] >= len("description alpha") + len("description beta")


def test_un_skill_vu_dans_deux_racines_ne_compte_qu_une_fois(monkeypatch, tmp_path):
    """Le cache de plugins REPLIQUE les skills (`cache/` et `marketplaces/`).

    Sans dedoublonnage le poste gonfle d'un facteur 2 a 3, et toute « reduction »
    mesuree ensuite serait la disparition d'un doublon, pas un gain reel.
    """
    a, b = tmp_path / "cache", tmp_path / "marketplaces"
    _skill(a, "caveman", "mode de communication compresse")
    _skill(b, "caveman", "mode de communication compresse")
    mod = _isoler(monkeypatch, [("cache", a), ("marketplaces", b)])

    r = mod.descriptions_skills()
    assert r["n"] == 1, (
        "le meme skill present dans deux racines a ete compte %r fois" % (r.get("n"),)
    )


def test_une_racine_illisible_interdit_l_etat_ok(monkeypatch, tmp_path):
    """Trois etats et jamais deux : lu · illisible · absent.

    Une racine qui refuse ne doit pas disparaitre du rapport en silence — sinon
    on retombe exactement sur `UNKNOWN` range du cote sain.
    """
    a = tmp_path / "profil"
    _skill(a, "alpha", "description alpha")
    refus = _racine_illisible(tmp_path, "plugins")
    mod = _isoler(monkeypatch, [("profil", a), ("plugins", refus)])

    r = mod.descriptions_skills()
    assert r["etat"] != "ok", (
        "une racine n'a pas pu etre lue et le poste se declare quand meme `ok`"
    )
    assert any("plugins" in str(x) for x in r.get("racines_illisibles") or []), (
        "la racine illisible doit etre NOMMEE, pas seulement comptee : %r"
        % (r.get("racines_illisibles"),)
    )
    assert r.get("octets") is not None, (
        "un partiel garde son PLANCHER mesure — l'ignorer perd l'information"
    )


def test_un_releve_perime_n_est_pas_servi_comme_mesure(monkeypatch, tmp_path):
    """Un releve depose par un exécuteur privilegie vieillit.

    `STALE` n'est pas une mesure : servir un chiffre de la semaine derniere pour
    un poste qu'on ne sait pas lire aujourd'hui fabrique un faux calme.
    """
    refus = _racine_illisible(tmp_path, "profil")
    releve = tmp_path / "releve.json"
    releve.write_text(json.dumps({
        "mesure_le": time.time() - 30 * 24 * 3600,
        "octets": 14273, "n": 90,
    }), encoding="utf-8")
    mod = _isoler(monkeypatch, [("profil", refus)], releve=releve)

    r = mod.descriptions_skills()
    assert r["etat"] != "ok", "un releve perime ne vaut pas une mesure"
    assert "perim" in (r.get("raison") or "").lower(), (
        "la peremption doit etre DITE : %r" % (r.get("raison"),)
    )


def test_un_releve_frais_est_servi_et_se_declare_comme_tel(monkeypatch, tmp_path):
    """Contre-epreuve : un relais qui refuse toujours ne relaie rien."""
    refus = _racine_illisible(tmp_path, "profil")
    releve = tmp_path / "releve.json"
    releve.write_text(json.dumps({
        "mesure_le": time.time() - 60, "octets": 14273, "n": 90,
    }), encoding="utf-8")
    mod = _isoler(monkeypatch, [("profil", refus)], releve=releve)

    r = mod.descriptions_skills()
    assert r["octets"] == 14273 and r["n"] == 90
    assert r["etat"] == "RELEVE", (
        "un chiffre relaye ne se confond pas avec une lecture directe : %r"
        % (r.get("etat"),)
    )


def test_le_point_d_entree_releve_ecrit_le_fichier(monkeypatch, tmp_path, capsys):
    """Le drapeau CLI est traverse pour de vrai, pas contourne.

    Defaut paye le 2026-09-06 : `check()` passait ses tests pendant que `--check`
    mourait en NameError, faute d'un test empruntant le chemin reel.
    """
    a = tmp_path / "profil"
    _skill(a, "alpha", "description alpha")
    releve = tmp_path / "releve.json"
    mod = _isoler(monkeypatch, [("profil", a)], releve=releve)

    assert mod.main(["--releve"]) == 0
    assert releve.is_file(), "`--releve` n'a rien ecrit"
    depose = json.loads(releve.read_text(encoding="utf-8"))
    assert depose["n"] == 1 and depose["octets"] > 0
    assert "mesure_le" in depose, (
        "sans horodatage le releve ne peut pas etre juge frais ou perime"
    )


def test_un_releve_frais_n_est_pas_reecrit_a_chaque_demarrage(monkeypatch, tmp_path):
    """Le releve est pose par un hook de SessionStart : son cout est recurrent.

    Le parcours traverse plusieurs centaines de `SKILL.md` pour une valeur qui
    bouge a peine. Un hook qui le refait a chaque ouverture paie ce scan pour
    rien. Le seuil de reecriture est le MEME que celui qui decide si le releve
    est servable — deux definitions de la fraicheur dans un seul module, c'est le
    piege de relecture paye le 2026-09-05 (hub 15 s / module 60 s).
    """
    a = tmp_path / "profil"
    _skill(a, "alpha", "description alpha")
    releve = tmp_path / "releve.json"
    mod = _isoler(monkeypatch, [("profil", a)], releve=releve)
    monkeypatch.setattr(mod, "RELEVE_SKILLS", releve, raising=False)

    premier = mod.ecrire_releve()
    assert premier["reecrit"] is True
    second = mod.ecrire_releve()
    assert second["reecrit"] is False, (
        "un releve frais a ete reecrit : le scan est paye a chaque demarrage"
    )
    assert mod.ecrire_releve(force=True)["reecrit"] is True, (
        "`--force` doit pouvoir passer outre, sinon le releve ne se rafraichit "
        "jamais a la demande"
    )


def test_le_total_reste_indetermine_quand_le_poste_est_partiel(monkeypatch, tmp_path):
    """Le plancher ne devient jamais un total.

    C'est l'invariant que le module portait deja ; on verifie qu'etendre la
    portee ne l'a pas casse — un partiel NOMME reste un INDETERMINE.
    """
    a = tmp_path / "profil"
    _skill(a, "alpha", "description alpha")
    refus = _racine_illisible(tmp_path, "plugins")
    mod = _isoler(monkeypatch, [("profil", a), ("plugins", refus)])

    m = mod.mesurer()
    assert m["RESIDENT_TOTAL"] is None
    assert m["RESIDENT_TOTAL_etat"] == "INDETERMINE"
    assert any("skills" in x for x in m["RESIDENT_UNKNOWN"])
