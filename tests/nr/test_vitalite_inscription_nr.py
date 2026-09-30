# -*- coding: utf-8 -*-
"""NR — l'inscription du cliquet de vitalite FUSIONNE, et n'ecrase jamais l'illisible.

__FORGE_COLOR__ = "qualite/build : non-regression de l inscription du cliquet de vitalite"

CE QUI A ETE PAYE (2026-09-07). `tests/nr/` n'est pas inscriptible par les comptes
sandbox, sous lesquels tourne `run_job` : la CI ne pouvait donc pas faire avancer son
propre cliquet de vitalite. Un cliquet gele n'est pas un cliquet — il finit par
declarer TOUS les gardes anergiques d'un coup, a 14 jours, et a tort.

Patron retenu, identique a la capture de generation : la CI DEPOSE dans
`sandbox/vitalite_en_attente/`, l'inscription dans l'arbre versionne est un geste
GOUVERNE (`trusted_script`).

Trois proprietes, chacune une erreur possible et couteuse :

  1. FUSION par date, jamais ecrasement — un run `--fast` ne mesure qu'une fraction
     des gardes ; une copie brute effacerait la fraicheur des autres, et le registre
     dirait « pas de verdict » pour des gardes qui viennent d'en rendre un.
  2. Une cible ILLISIBLE n'est PAS ecrasee — on ne detruit pas ce qu'on n'a pas lu.
  3. On conclut par RELECTURE, jamais sur l'absence d'erreur.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_vitalite_inscrire as vi  # noqa: E402


def _g(reel=None, unknown=None, etat="PASS", consec=0) -> dict:
    """La forme REELLE d'un garde, relevee dans un depot produit par la CI.

    🪤 Mes premiers fixtures utilisaient des CHAINES de dates. La fusion comparait
    donc `str(v)` et passait — sur un corpus qui n'existe pas. Le depot reel porte un
    DICT, et la comparaison de `repr` se serait retournee des qu'un garde n'a que
    `dernier_unknown`. Un fixture qui ne modele pas le reel valide un code faux.
    """
    d = {"etat": etat, "unknown_consecutifs": consec}
    if reel:
        d["dernier_reel"] = reel
    if unknown:
        d["dernier_unknown"] = unknown
    return d


def _depot_fictif(tmp_path):
    """Un ROOT qui ne contient PAS les fichiers du test : le layout du RUNNER.

    Mesure 2026-09-07 (run GitHub 34138167173, sha 22f7b1ef3) : sur le runner le
    tmp_path de pytest vit HORS du depot (C:/laforge-runner/_work/_temp/...), la
    ou le basetemp local vit DANS le depot (sandbox/). Un `relative_to(ROOT)`
    passait donc en local (3 CI vertes) et levait ValueError sur le runner
    (6 tests rouges). Les fixtures reproduisent le runner ; le local ne peut
    plus etre vert la ou le runner est rouge.
    """
    d = tmp_path / "depot_fictif"
    d.mkdir(exist_ok=True)
    return d


def _monter(monkeypatch, tmp_path, cible=None, depot=None):
    c = tmp_path / "cible.json"
    d = tmp_path / "depot.json"
    if cible is not None:
        c.write_text(cible if isinstance(cible, str)
                     else json.dumps(cible), encoding="utf-8")
    if depot is not None:
        d.write_text(json.dumps(depot), encoding="utf-8")
    monkeypatch.setattr(vi, "CIBLE", c)
    monkeypatch.setattr(vi, "DEPOT", d)
    monkeypatch.setattr(vi, "ROOT", _depot_fictif(tmp_path))
    return c, d


def test_la_fusion_garde_le_verdict_le_PLUS_RECENT(monkeypatch, tmp_path) -> None:
    """PROPRIETE 1. Le depot rafraichit, il n'efface pas."""
    c, _d = _monter(monkeypatch, tmp_path,
                    cible={"gardes": {"bandit": _g("2026-09-01"),
                                      "ruff": _g("2026-09-05")}},
                    depot={"gardes": {"bandit": _g("2026-09-07")}})
    assert vi.main() == 0
    g = json.loads(c.read_text(encoding="utf-8"))["gardes"]
    assert g["bandit"]["dernier_reel"] == "2026-09-07", "le plus recent gagne"
    assert g["ruff"]["dernier_reel"] == "2026-09-05", (
        "un garde ABSENT du depot doit SURVIVRE : un run --fast ne mesure qu'une "
        "fraction, et l'effacer le ferait passer pour sans verdict")


def test_un_depot_PLUS_ANCIEN_ne_regresse_pas_la_cible(monkeypatch, tmp_path) -> None:
    """Le sens de la fusion est la fraicheur, pas l'ordre d'ecriture."""
    c, _d = _monter(monkeypatch, tmp_path,
                    cible={"gardes": {"bandit": _g("2026-09-07")}},
                    depot={"gardes": {"bandit": _g("2026-09-01")}})
    assert vi.main() == 0
    g = json.loads(c.read_text(encoding="utf-8"))["gardes"]
    assert g["bandit"]["dernier_reel"] == "2026-09-07"


def test_une_entree_SANS_verdict_reel_ne_remplace_PAS_une_entree_datee(
        monkeypatch, tmp_path) -> None:
    """LE CAS QUI AURAIT CORROMPU LE REGISTRE (mesure 2026-09-07).

    La fusion comparait `str(dict)`. Avec `sort_keys`, le repr commence par
    `dernier_reel` quand il existe — mais une entree qui n'a QUE `dernier_unknown`
    voit son repr commencer par `dernier_unknown`, et `'dernier_r' < 'dernier_u'` :
    l'entree SANS verdict reel l'aurait emporte, effacant la date du seul verdict
    qu'on possede. Le garde serait alors devenu ANERGIQUE a tort."""
    c, _d = _monter(monkeypatch, tmp_path,
                    cible={"gardes": {"archi-lint": _g("2026-09-06")}},
                    depot={"gardes": {"archi-lint": _g(unknown="2026-09-07",
                                                       etat="UNKNOWN", consec=3)}})
    assert vi.main() == 0
    g = json.loads(c.read_text(encoding="utf-8"))["gardes"]["archi-lint"]
    assert g.get("dernier_reel") == "2026-09-06", (
        "un UNKNOWN plus recent n'efface pas le dernier verdict REEL connu : c'est "
        "lui qui decide de l'anergie")


def test_une_valeur_INATTENDUE_ne_remplace_jamais_une_entree_lisible(
        monkeypatch, tmp_path) -> None:
    """Schema qui derive, entree tronquee : on ne remplace pas ce qu'on sait dater
    par ce qu'on ne sait pas lire."""
    c, _d = _monter(monkeypatch, tmp_path,
                    cible={"gardes": {"bandit": _g("2026-09-07")}},
                    depot={"gardes": {"bandit": "forme inconnue"}})
    assert vi.main() == 0
    g = json.loads(c.read_text(encoding="utf-8"))["gardes"]["bandit"]
    assert isinstance(g, dict) and g["dernier_reel"] == "2026-09-07"


def test_une_cible_ILLISIBLE_n_est_JAMAIS_ecrasee(monkeypatch, tmp_path) -> None:
    """PROPRIETE 2. On ne detruit pas ce qu'on n'a pas su lire."""
    c, _d = _monter(monkeypatch, tmp_path,
                    cible="{ ceci n est pas du json",
                    depot={"gardes": {"bandit": _g("2026-09-07")}})
    avant = c.read_text(encoding="utf-8")
    assert vi.main() == 2, "refus explicite, pas un succes silencieux"
    assert c.read_text(encoding="utf-8") == avant, "la cible est INTACTE"


def test_un_depot_ABSENT_n_est_pas_une_erreur(monkeypatch, tmp_path) -> None:
    """Rien a inscrire n'est pas un echec : la CI n'a simplement pas eu a deposer."""
    c, _d = _monter(monkeypatch, tmp_path,
                    cible={"gardes": {"bandit": _g("2026-09-07")}})
    assert vi.main() == 0
    g = json.loads(c.read_text(encoding="utf-8"))["gardes"]
    assert g["bandit"]["dernier_reel"] == "2026-09-07"


def test_un_depot_ILLISIBLE_refuse_au_lieu_de_vider(monkeypatch, tmp_path) -> None:
    """Un depot corrompu ne doit pas se lire comme « aucun garde mesure »."""
    c, d = _monter(monkeypatch, tmp_path,
                   cible={"gardes": {"bandit": _g("2026-09-07")}})
    d.write_text("{{{", encoding="utf-8")
    assert vi.main() == 2
    g = json.loads(c.read_text(encoding="utf-8"))["gardes"]
    assert g["bandit"]["dernier_reel"] == "2026-09-07"


def test_une_cible_ABSENTE_est_CREEE(monkeypatch, tmp_path) -> None:
    """Premiere inscription : il n'y a pas encore de registre versionne."""
    c, _d = _monter(monkeypatch, tmp_path,
                    depot={"gardes": {"bandit": _g("2026-09-07")}})
    assert vi.main() == 0
    g = json.loads(c.read_text(encoding="utf-8"))["gardes"]
    assert g["bandit"]["dernier_reel"] == "2026-09-07"


# ── SEMANTIQUE DU REGISTRE : deux axes ORTHOGONAUX ────────────────────────────────
#
#   lecture   LU · ABSENT · ILLISIBLE
#   fraicheur FRESH · STALE · INCONNUE
#   perimetre FULL · PARTIAL · UNKNOWN
#
# `FRESH + PARTIAL` est LEGITIME : un run `--fast` peut etre tout recent et ne
# couvrir qu'une fraction des gardes. **FRESH n'est pas COMPLETE.** Les confondre
# ferait lire un registre partiel comme l'etat complet du systeme.

import datetime as _dt  # noqa: E402
import sys as _sys  # noqa: E402

if str(ROOT / "tools") not in _sys.path:
    _sys.path.insert(0, str(ROOT / "tools"))
import ci_local as ci  # noqa: E402


def _registre(monkeypatch, tmp_path, contenu, attente=None):
    v = tmp_path / "vitalite.json"
    a = tmp_path / "attente.json"
    if contenu is not None:
        v.write_text(contenu if isinstance(contenu, str) else json.dumps(contenu),
                     encoding="utf-8")
    if attente is not None:
        a.write_text(json.dumps(attente), encoding="utf-8")
    monkeypatch.setattr(ci, "VITALITE", v)
    monkeypatch.setattr(ci, "VITALITE_ATTENTE", a)
    monkeypatch.setattr(ci, "ROOT", _depot_fictif(tmp_path))
    return ci._charger_vitalite()


def _env(jours=0, perimetre="FULL", gardes=None):
    j = (_dt.date.today() - _dt.timedelta(days=jours)).isoformat()
    return {"observe_le": j, "perimetre": perimetre,
            "gardes": gardes if gardes is not None else {"bandit": _g("2026-09-07")}}


def test_registre_ABSENT_ne_dit_pas_corps_sans_verdict(monkeypatch, tmp_path) -> None:
    g = _registre(monkeypatch, tmp_path, None)
    assert (ci._VITALITE_ETAT, g) == ("ABSENT", {})
    assert ci._VITALITE_FRAICHEUR == "INCONNUE" and ci._VITALITE_PERIMETRE == "UNKNOWN"


def test_registre_ILLISIBLE_est_distinct_d_ABSENT(monkeypatch, tmp_path) -> None:
    """LE defaut d'origine : `except: return {}` confondait les deux, et un registre
    illisible aurait declare TOUS les gardes morts d'un coup."""
    g = _registre(monkeypatch, tmp_path, "{ pas du json")
    assert ci._VITALITE_ETAT == "ILLISIBLE" and g == {}
    assert "JSONDecodeError" in (ci._VITALITE_SOURCE or ""), "le motif est NOMME"


def test_registre_FRESH_et_FULL_est_le_seul_cas_sur(monkeypatch, tmp_path) -> None:
    _registre(monkeypatch, tmp_path, _env(jours=0, perimetre="FULL"))
    assert (ci._VITALITE_ETAT, ci._VITALITE_FRAICHEUR, ci._VITALITE_PERIMETRE) == (
        "LU", "FRESH", "FULL")


def test_registre_STALE_au_dela_de_son_PROPRE_TTL(monkeypatch, tmp_path) -> None:
    """Le TTL de la vitalite n'est PAS celui des capacites : herite, il crierait a
    chaque week-end sans CI."""
    _registre(monkeypatch, tmp_path, _env(jours=ci._VITALITE_TTL_J + 1))
    assert ci._VITALITE_FRAICHEUR == "STALE"
    _registre(monkeypatch, tmp_path, _env(jours=ci._VITALITE_TTL_J))
    assert ci._VITALITE_FRAICHEUR == "FRESH", "la borne elle-meme est fraiche"


def test_FRESH_plus_PARTIAL_est_un_etat_LEGITIME(monkeypatch, tmp_path) -> None:
    """L'orthogonalite, verrouillee : un `--fast` de ce matin est FRAIS et INCOMPLET."""
    _registre(monkeypatch, tmp_path, _env(jours=0, perimetre="PARTIAL"))
    assert (ci._VITALITE_FRAICHEUR, ci._VITALITE_PERIMETRE) == ("FRESH", "PARTIAL")


def test_un_registre_SANS_les_champs_ne_les_INVENTE_pas(monkeypatch, tmp_path) -> None:
    """Registre ecrit avant ce contrat : INCONNUE / UNKNOWN, jamais FRESH / FULL."""
    _registre(monkeypatch, tmp_path, {"gardes": {"bandit": _g("2026-09-07")}})
    assert (ci._VITALITE_FRAICHEUR, ci._VITALITE_PERIMETRE) == ("INCONNUE", "UNKNOWN")


def test_une_date_ILLISIBLE_ne_devient_pas_FRESH(monkeypatch, tmp_path) -> None:
    _registre(monkeypatch, tmp_path,
              {"observe_le": "hier matin", "perimetre": "FULL", "gardes": {}})
    assert ci._VITALITE_FRAICHEUR == "INCONNUE", "on ne devine pas une date"


def test_l_anergie_ne_BLOQUE_que_sur_un_registre_SUR() -> None:
    """Verrou de CONCEPTION : les trois conditions doivent etre exigees ENSEMBLE.

    STALE ne distingue pas « le garde se tait » de « le registre n'a pas ete
    rejoue » ; PARTIAL ne couvre pas tous les gardes, donc une absence n'y prouve
    rien. Bloquer sur l'un ou l'autre fabriquerait des morts."""
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8", errors="replace")
    assert '_VITALITE_ETAT == "LU"' in src
    assert '_VITALITE_FRAICHEUR == "FRESH"' in src
    assert '_VITALITE_PERIMETRE == "FULL"' in src
    i = src.find("anergie_bloquante =")
    assert "_vit_sur" in src[i:i + 200], (
        "la decision de BLOQUER doit dependre de la surete du registre")


def test_un_depot_PARTIAL_ne_DEGRADE_pas_une_cible_FULL(monkeypatch, tmp_path) -> None:
    """Sinon le fichier, aussi complet qu'avant, se declarerait partiel — et
    l'anergie cesserait de bloquer sur un registre pourtant sur."""
    c, _d = _monter(monkeypatch, tmp_path,
                    cible={"perimetre": "FULL", "observe_le": "2026-09-06",
                           "gardes": {"ruff": _g("2026-09-06")}},
                    depot={"perimetre": "PARTIAL", "observe_le": "2026-09-07",
                           "gardes": {"bandit": _g("2026-09-07")}})
    assert vi.main() == 0
    d = json.loads(c.read_text(encoding="utf-8"))
    assert d["perimetre"] == "FULL", "le perimetre decrit le FICHIER, pas le dernier run"
    assert d["observe_le"] == "2026-09-07", "la date la plus recente gagne"
    assert set(d["gardes"]) == {"ruff", "bandit"}


# --- Layout du runner : un chemin d'AFFICHAGE ne leve JAMAIS (2026-09-07) ----
#
# Les fixtures ci-dessus placent desormais le registre HORS du depot, comme sur
# le runner. Ces tests verrouillent la PROPRIETE que le defaut violait : la
# source se DIT relative si elle vit dans le depot, absolue sinon, et un gate
# ne tombe jamais sur la facon de nommer un chemin.

def test_registre_HORS_du_depot_est_LU_et_sa_source_est_DITE(monkeypatch, tmp_path):
    gardes = _registre(monkeypatch, tmp_path, _env(jours=0))
    assert gardes, "hors depot = LU, pas une exception"
    assert ci._VITALITE_ETAT == "LU"
    assert ci._VITALITE_SOURCE and ci._VITALITE_SOURCE.endswith("vitalite.json")
    assert Path(ci._VITALITE_SOURCE).is_absolute(), "hors depot : chemin absolu, dit tel quel"


def test_registre_DANS_le_depot_se_dit_en_RELATIF(monkeypatch, tmp_path):
    _registre(monkeypatch, tmp_path, _env(jours=0))
    monkeypatch.setattr(ci, "ROOT", tmp_path)  # meme fichier, ROOT le contient
    ci._charger_vitalite()
    assert ci._VITALITE_ETAT == "LU"
    assert ci._VITALITE_SOURCE == "vitalite.json"


def test_l_inscription_HORS_du_depot_rend_0_et_n_explose_pas(monkeypatch, tmp_path, capsys):
    _monter(monkeypatch, tmp_path,
            cible={"gardes": {"bandit": _g("2026-09-01")}},
            depot={"gardes": {"bandit": _g("2026-09-07")}})
    assert vi.main() == 0
    assert "cible.json" in capsys.readouterr().out


def test_l_inscription_conclut_par_RELECTURE() -> None:
    """PROPRIETE 3. Verrou de CONCEPTION : conclure sur l'absence d'erreur est le
    defaut que ce depot combat partout — `write` peut rendre sans lever et laisser un
    contenu different (ACL, disque plein, encodage)."""
    src = (ROOT / "tools" / "forge_vitalite_inscrire.py").read_text(
        encoding="utf-8", errors="replace")
    assert "relu, e_relu = _lire(CIBLE)" in src, "la cible est RELUE apres ecriture"
    assert 'relu.get("gardes") != fusion' in src, "et son contenu est COMPARE"
